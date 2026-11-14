"""Qualification lifecycle: attempts, auto-grading, manual grading, eligibility.

Eligibility rule for claiming tasks in a project (checked in the claim path):
1. staff bypass (they don't claim tasks);
2. an explicit override row wins (with recorded reason);
3. every entry in `project.eligibility_requirements` must be satisfied:
   - {"assessment_id": N, "min_score": 0.85} — best passed attempt >= min_score
   - {"skill": "Python", "verified": true}   — a verified WorkerSkill must exist
Workers without requirements are eligible (v2 behavior preserved).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload

from app.models.qualification import (
    QualificationAssessment, QualificationAttempt, QualificationQuestion,
    ProjectEligibilityOverride, WorkerSkill,
)
from app.models.project import Project
from app.models.user import User, utcnow

ATTEMPT_STATUSES = ["in_progress", "submitted", "passed", "failed", "under_review", "expired"]


def _norm(s) -> str:
    return str(s or "").strip().casefold()


# ---------------------------------------------------------------------------
# Attempts
# ---------------------------------------------------------------------------

def assessment_out(a: QualificationAssessment, include_questions: bool = False,
                   include_answers: bool = False) -> dict:
    data = {
        "id": a.id,
        "title": a.title,
        "description": a.description,
        "assessment_type": a.assessment_type,
        "skill_tags": a.skill_tags or [],
        "time_limit_minutes": a.time_limit_minutes,
        "max_attempts": a.max_attempts,
        "passing_score": a.passing_score,
        "randomize_questions": a.randomize_questions,
        "project_id": a.project_id,
        "status": a.status,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "version": a.version,
        "question_count": len(a.questions or []),
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
    if include_questions:
        qs = []
        for q in (a.questions or []):
            item = {
                "id": q.id, "order": q.order, "question_type": q.question_type,
                "prompt": q.prompt, "options": q.options or [], "points": q.points,
            }
            if include_answers:
                item["correct_answer"] = q.correct_answer
                item["explanation"] = q.explanation
            qs.append(item)
        data["questions"] = qs
    return data


def start_attempt(db: Session, assessment: QualificationAssessment, worker: User) -> QualificationAttempt:
    """Begin a new attempt (enforces attempt limits and prior outcomes)."""
    prior = db.scalars(
        select(QualificationAttempt).where(
            QualificationAttempt.assessment_id == assessment.id,
            QualificationAttempt.worker_id == worker.id,
        ).order_by(QualificationAttempt.attempt_number.desc())
    ).all()
    if any(a.status == "passed" for a in prior):
        raise PermissionError("You have already passed this assessment.")
    if any(a.status == "in_progress" for a in prior):
        return prior[0]  # resume the open attempt
    if any(a.status in ("submitted", "under_review") for a in prior):
        raise PermissionError("Your latest attempt is awaiting grading.")
    used = len([a for a in prior if a.status in ("failed", "expired")])
    if used >= assessment.max_attempts:
        raise PermissionError(f"Attempt limit reached ({assessment.max_attempts}).")
    expires = None
    if assessment.time_limit_minutes:
        expires = datetime.now(timezone.utc) + timedelta(minutes=assessment.time_limit_minutes)
    attempt = QualificationAttempt(
        assessment_id=assessment.id,
        worker_id=worker.id,
        attempt_number=used + 1,
        status="in_progress",
        answers={},
        expires_at=expires,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def grade_attempt(db: Session, attempt: QualificationAttempt,
                  grader_id: int | None = None) -> tuple[float, bool, bool]:
    """Grade an attempt. Returns (score 0..1, passed, fully_auto_graded)."""
    questions = db.scalars(
        select(QualificationQuestion).where(
            QualificationQuestion.assessment_id == attempt.assessment_id
        ).order_by(QualificationQuestion.order)
    ).all()
    answers = attempt.answers or {}
    total_points = sum(q.points for q in questions) or 1.0
    earned = 0.0
    auto_gradable = True
    for q in questions:
        answer = answers.get(str(q.id))
        correct = (q.correct_answer or {}).get("value")
        if q.question_type == "mcq":
            if answer is not None and _norm(answer) == _norm(correct):
                earned += q.points
        elif q.question_type == "multi_select":
            got = {_norm(x) for x in (answer if isinstance(answer, list) else [answer]) if x is not None}
            want = {_norm(x) for x in (correct if isinstance(correct, list) else [correct])}
            if got and got == want:
                earned += q.points
        elif q.question_type == "numeric":
            try:
                if answer is not None and abs(float(str(answer).replace(",", "")) - float(correct)) <= 1e-6:
                    earned += q.points
            except (TypeError, ValueError):
                pass
        else:
            # text / code: manual grading required
            auto_gradable = False
    assessment = db.get(QualificationAssessment, attempt.assessment_id)
    score = round(earned / total_points, 4)
    if not auto_gradable:
        attempt.status = "under_review"
        attempt.score = score  # provisional (auto-graded portion)
        attempt.auto_graded = False
        db.commit()
        return score, False, False
    passed = score >= (assessment.passing_score if assessment else 0.7)
    attempt.status = "passed" if passed else "failed"
    attempt.score = score
    attempt.auto_graded = True
    attempt.graded_by = grader_id
    attempt.graded_at = utcnow()
    attempt.submitted_at = attempt.submitted_at or utcnow()
    db.commit()
    if passed:
        _grant_verified_skills(db, attempt)
    return score, passed, True


def _grant_verified_skills(db: Session, attempt: QualificationAttempt) -> None:
    """Passing an assessment verifies its skill tags for the worker."""
    assessment = db.get(QualificationAssessment, attempt.assessment_id)
    if not assessment or not assessment.skill_tags:
        return
    for skill in assessment.skill_tags:
        existing = db.scalar(
            select(WorkerSkill).where(
                WorkerSkill.user_id == attempt.worker_id,
                WorkerSkill.skill == skill,
                WorkerSkill.source == "verified",
            )
        )
        if existing is None:
            db.add(WorkerSkill(
                user_id=attempt.worker_id, skill=skill, source="verified",
                evidence_assessment_id=assessment.id,
                verified_by=attempt.graded_by, verified_at=utcnow(),
            ))
    db.commit()


def submit_answers(db: Session, attempt: QualificationAttempt, answers: dict) -> dict:
    if attempt.status != "in_progress":
        raise PermissionError("This attempt is not open.")
    if attempt.expires_at is not None:
        # SQLite naive datetimes
        exp = attempt.expires_at
        if exp.tzinfo is None:
            from datetime import timezone as _tz
            exp = exp.replace(tzinfo=_tz.utc)
        if exp < datetime.now(timezone.utc):
            attempt.status = "expired"
            db.commit()
            raise PermissionError("The time limit for this attempt has expired.")
    attempt.answers = answers or {}
    attempt.submitted_at = utcnow()
    db.commit()
    score, passed, auto = grade_attempt(db, attempt)
    return {"score": score, "passed": passed, "auto_graded": auto, "status": attempt.status}


# ---------------------------------------------------------------------------
# Worker tiers + performance (computed from evidence, never invented)
# ---------------------------------------------------------------------------

def worker_tier(db: Session, worker_id: int) -> dict:
    """Beginner < Qualified (1 passed qualification) < Advanced (3+) < Specialist (5+ and
    at least one verified expert-ish skill). Evidence-based and recomputed on read."""
    passed = db.scalar(
        select(func.count()).select_from(QualificationAttempt).where(
            QualificationAttempt.worker_id == worker_id,
            QualificationAttempt.status == "passed",
        )
    ) or 0
    verified_skills = db.scalars(
        select(WorkerSkill.skill).where(
            WorkerSkill.user_id == worker_id, WorkerSkill.source == "verified"
        )
    ).all()
    if passed >= 5 and verified_skills:
        tier = "specialist"
    elif passed >= 3:
        tier = "advanced"
    elif passed >= 1:
        tier = "qualified"
    else:
        tier = "beginner"
    return {"tier": tier, "passed_qualifications": passed,
            "verified_skills": list(verified_skills)}


# ---------------------------------------------------------------------------
# Project eligibility (used by the task claim path)
# ---------------------------------------------------------------------------

def eligibility_status(db: Session, user: User, project: Project) -> tuple[bool, list[str]]:
    """Returns (eligible, unmet_reasons)."""
    if user.role in ("super_admin", "project_admin", "project_manager"):
        return True, []
    requirements = project.eligibility_requirements or []
    if not requirements:
        return True, []
    override = db.scalar(
        select(ProjectEligibilityOverride).where(
            ProjectEligibilityOverride.project_id == project.id,
            ProjectEligibilityOverride.user_id == user.id,
        )
    )
    if override is not None:
        return True, []

    unmet: list[str] = []
    for req in requirements:
        if not isinstance(req, dict):
            continue
        if "assessment_id" in req:
            assessment = db.get(QualificationAssessment, int(req["assessment_id"]))
            title = assessment.title if assessment else f"assessment #{req['assessment_id']}"
            min_score = float(req.get("min_score", 0.0))
            best = db.scalar(
                select(func.max(QualificationAttempt.score)).where(
                    QualificationAttempt.assessment_id == int(req["assessment_id"]),
                    QualificationAttempt.worker_id == user.id,
                    QualificationAttempt.status.in_(["passed", "failed", "under_review"]),
                )
            )
            if best is None or float(best) < min_score:
                unmet.append(f"Requires qualification '{title}' with score >= {min_score:.0%}"
                             + (f" (best: {float(best):.0%})" if best is not None else ""))
        elif "skill" in req:
            skill = str(req["skill"])
            if req.get("verified", True):
                ok = db.scalar(
                    select(func.count()).select_from(WorkerSkill).where(
                        WorkerSkill.user_id == user.id,
                        WorkerSkill.skill == skill,
                        WorkerSkill.source == "verified",
                    )
                )
            else:
                ok = db.scalar(
                    select(func.count()).select_from(WorkerSkill).where(
                        WorkerSkill.user_id == user.id, WorkerSkill.skill == skill,
                    )
                )
            if not ok:
                unmet.append(f"Requires {'verified ' if req.get('verified', True) else ''}skill: {skill}")
    return (len(unmet) == 0), unmet
