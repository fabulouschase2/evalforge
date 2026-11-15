"""Qualification assessments: staff builder, worker attempts, manual grading,
worker skills/performance, project eligibility config."""
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.security import AdminPM, CurrentUser, DbSession
from app.models.qualification import (
    ASSESSMENT_TYPES, QUESTION_TYPES, ProjectEligibilityOverride,
    QualificationAssessment, QualificationAttempt, QualificationQuestion,
    WorkerSkill, SKILL_CATALOG,
)
from app.models.project import Project
from app.models.user import User, UserRole, utcnow
from app.models.golden import GoldenTaskResult
from app.services import access as acl
from app.services import qualifications as qs
from app.services.audit import log_action
from app.services.notifications import notify

router = APIRouter(prefix="/api/qualifications", tags=["qualifications"])
grading_router = APIRouter(prefix="/api/quality/qualifications", tags=["qualifications"])
worker_router = APIRouter(prefix="/api/workers/me", tags=["qualifications"])


# ---------------------------------------------------------------------------
# Staff: assessment builder
# ---------------------------------------------------------------------------

def _require_admin(db: DbSession, user, project_id: int | None) -> None:
    if project_id is None:
        return  # platform-wide qualification: staff role suffices
    try:
        project = acl.require_project(db, user, project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("")
def list_assessments(db: DbSession, user: CurrentUser, project_id: int | None = None):
    """Staff see assessments for their projects + platform-wide ones."""
    stmt = select(QualificationAssessment)
    if project_id:
        stmt = stmt.where(QualificationAssessment.project_id == project_id)
    if user.role not in UserRole.PLATFORM_WIDE:
        ids = acl.visible_project_ids(db, user)
        if ids is None:
            pass
        else:
            from sqlalchemy import or_
            stmt = stmt.where(or_(
                QualificationAssessment.project_id.is_(None),
                QualificationAssessment.project_id.in_(ids or {0}),
            ))
    rows = db.scalars(stmt.order_by(QualificationAssessment.created_at.desc())).all()
    return [qs.assessment_out(a, include_questions=False) for a in rows]


@router.post("", status_code=201)
def create_assessment(payload: dict, db: DbSession, user: AdminPM, request: Request):
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required.")
    atype = payload.get("assessment_type") or "mcq"
    if atype not in ASSESSMENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown assessment type; allowed: {ASSESSMENT_TYPES}")
    project_id = payload.get("project_id")
    _require_admin(db, user, project_id)
    questions = payload.get("questions") or []
    if not questions:
        raise HTTPException(status_code=422, detail="At least one question is required.")
    assessment = QualificationAssessment(
        title=title,
        description=payload.get("description"),
        assessment_type=atype,
        skill_tags=payload.get("skill_tags") or [],
        time_limit_minutes=payload.get("time_limit_minutes"),
        max_attempts=max(1, int(payload.get("max_attempts", 2))),
        passing_score=float(payload.get("passing_score", 0.7)),
        randomize_questions=bool(payload.get("randomize_questions", False)),
        project_id=project_id,
        expires_at=payload.get("expires_at"),
        created_by=user.id,
    )
    db.add(assessment)
    db.flush()
    for i, q in enumerate(questions):
        qtype = q.get("question_type") or "mcq"
        if qtype not in QUESTION_TYPES:
            raise HTTPException(status_code=422, detail=f"Unknown question type '{qtype}'.")
        db.add(QualificationQuestion(
            assessment_id=assessment.id,
            order=int(q.get("order", i)),
            question_type=qtype,
            prompt=q.get("prompt") or "",
            options=q.get("options") or [],
            correct_answer=q.get("correct_answer") or {},
            points=float(q.get("points", 1.0)),
            explanation=q.get("explanation"),
        ))
    db.commit()
    db.refresh(assessment)
    log_action(db, user_id=user.id, action="qualification.create", entity_type="qualification_assessment",
               entity_id=assessment.id, details={"title": title, "questions": len(questions)}, request=request)
    return qs.assessment_out(assessment, include_questions=True, include_answers=True)


@router.get("/{assessment_id}")
def get_assessment(assessment_id: int, db: DbSession, user: CurrentUser):
    a = db.get(QualificationAssessment, assessment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    # staff/admins see correct answers; workers never do
    is_staff = user.role in UserRole.STAFF or user.role in UserRole.PLATFORM_WIDE
    return qs.assessment_out(a, include_questions=True, include_answers=is_staff)


@router.put("/{assessment_id}")
def update_assessment(assessment_id: int, payload: dict, db: DbSession, user: AdminPM, request: Request):
    a = db.get(QualificationAssessment, assessment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    _require_admin(db, user, a.project_id)
    for field in ("title", "description", "time_limit_minutes", "max_attempts",
                  "passing_score", "randomize_questions", "status", "expires_at", "skill_tags"):
        if field in payload and payload[field] is not None:
            setattr(a, field, payload[field])
    if payload.get("questions") is not None:
        # questions change -> new assessment version (attempt history stays valid)
        a.version += 1
        for q in list(a.questions or []):
            db.delete(q)
        db.flush()
        for i, q in enumerate(payload["questions"]):
            db.add(QualificationQuestion(
                assessment_id=a.id,
                order=int(q.get("order", i)),
                question_type=q.get("question_type") if q.get("question_type") in QUESTION_TYPES else "mcq",
                prompt=q.get("prompt") or "",
                options=q.get("options") or [],
                correct_answer=q.get("correct_answer") or {},
                points=float(q.get("points", 1.0)),
                explanation=q.get("explanation"),
            ))
    db.commit()
    db.refresh(a)
    log_action(db, user_id=user.id, action="qualification.update", entity_type="qualification_assessment",
               entity_id=a.id, request=request)
    return qs.assessment_out(a, include_questions=True, include_answers=True)


# ---------------------------------------------------------------------------
# Workers: take assessments
# ---------------------------------------------------------------------------

@router.get("/{assessment_id}/attempt")
def my_attempt(assessment_id: int, db: DbSession, user: CurrentUser):
    """The caller's attempt state for this assessment (worker view, no answers leaked)."""
    a = db.get(QualificationAssessment, assessment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    attempts = db.scalars(
        select(QualificationAttempt).where(
            QualificationAttempt.assessment_id == assessment_id,
            QualificationAttempt.worker_id == user.id,
        ).order_by(QualificationAttempt.attempt_number)
    ).all()
    open_attempt = next((x for x in attempts if x.status == "in_progress"), None)
    if open_attempt is not None and open_attempt.expires_at is not None:
        exp = open_attempt.expires_at
        if exp.tzinfo is None:
            from datetime import timezone as _tz
            exp = exp.replace(tzinfo=_tz.utc)
        if exp < utcnow():
            open_attempt.status = "expired"
            db.commit()
            open_attempt = None
    return {
        "assessment": qs.assessment_out(a, include_questions=bool(open_attempt)),
        "open_attempt": ({"id": open_attempt.id,
                          "expires_at": (open_attempt.expires_at.isoformat()
                                         if open_attempt.expires_at else None),
                          "attempt_number": open_attempt.attempt_number}
                         if open_attempt else None),
        "history": [
            {"id": x.id, "attempt_number": x.attempt_number, "status": x.status,
             "score": x.score, "submitted_at": x.submitted_at.isoformat() if x.submitted_at else None}
            for x in attempts
        ],
        "attempts_used": len([x for x in attempts if x.status != "in_progress"]),
    }


@router.post("/{assessment_id}/attempts", status_code=201)
def start(assessment_id: int, db: DbSession, user: CurrentUser, request: Request):
    if user.role != UserRole.TESTER:
        raise HTTPException(status_code=403, detail="Only testers take assessments.")
    a = db.get(QualificationAssessment, assessment_id)
    if a is None or a.status != "active":
        raise HTTPException(status_code=404, detail="Assessment not found or inactive.")
    try:
        attempt = qs.start_attempt(db, a, user)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    log_action(db, user_id=user.id, action="qualification.attempt_start",
               entity_type="qualification_attempt", entity_id=attempt.id, request=request)
    return {"attempt_id": attempt.id, "expires_at": attempt.expires_at.isoformat() if attempt.expires_at else None}


@router.post("/attempts/{attempt_id}/submit")
def submit(attempt_id: int, payload: dict, db: DbSession, user: CurrentUser, request: Request):
    attempt = db.get(QualificationAttempt, attempt_id)
    if attempt is None or attempt.worker_id != user.id:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    try:
        result = qs.submit_answers(db, attempt, payload.get("answers") or {})
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    log_action(db, user_id=user.id, action="qualification.attempt_submit",
               entity_type="qualification_attempt", entity_id=attempt.id,
               details={"score": result["score"], "status": result["status"]}, request=request)
    notify(db, user_id=user.id, type="qualification_result",
           title=f"Assessment {'passed' if result['passed'] else 'graded'}",
           body=f"Score: {result['score']:.0%} — status: {result['status']}.",
           entity_type="qualification_attempt", entity_id=attempt.id)
    return result


# ---------------------------------------------------------------------------
# Quality/staff: manual grading queue
# ---------------------------------------------------------------------------

@grading_router.get("")
def grading_queue(db: DbSession, user: CurrentUser, status: str = "under_review"):
    if user.role not in UserRole.PLATFORM_WIDE and user.role not in UserRole.STAFF:
        raise HTTPException(status_code=403, detail="Staff access required.")
    stmt = (
        select(QualificationAttempt)
        .options(joinedload(QualificationAttempt.assessment))
        .where(QualificationAttempt.status == status)
        .order_by(QualificationAttempt.submitted_at.asc())
    )
    rows = db.scalars(stmt).unique().all()
    out = []
    for att in rows:
        worker = db.get(User, att.worker_id)
        out.append({
            "id": att.id,
            "assessment_id": att.assessment_id,
            "assessment_title": att.assessment.title if att.assessment else None,
            "worker_id": att.worker_id,
            "worker_name": worker.name if worker else None,
            "status": att.status,
            "provisional_score": att.score,
            "attempt_number": att.attempt_number,
            "submitted_at": att.submitted_at.isoformat() if att.submitted_at else None,
            "answers": att.answers or {},
            "questions": [
                {"id": q.id, "prompt": q.prompt, "question_type": q.question_type,
                 "options": q.options or [], "correct_answer": q.correct_answer,
                 "points": q.points}
                for q in (att.assessment.questions if att.assessment else [])
            ],
        })
    return out


@grading_router.post("/{attempt_id}/grade")
def manual_grade(attempt_id: int, payload: dict, db: DbSession, user: AdminPM, request: Request):
    """Final grade for a manually-reviewed attempt (score 0..1 supplied by grader)."""
    attempt = db.get(QualificationAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    if attempt.status not in ("under_review", "submitted"):
        raise HTTPException(status_code=409, detail="This attempt is not awaiting grading.")
    score = payload.get("score")
    if not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise HTTPException(status_code=422, detail="score must be between 0 and 1.")
    assessment = db.get(QualificationAssessment, attempt.assessment_id)
    passed = float(score) >= (assessment.passing_score if assessment else 0.7)
    attempt.status = "passed" if passed else "failed"
    attempt.score = float(score)
    attempt.graded_by = user.id
    attempt.graded_at = utcnow()
    db.commit()
    if passed:
        qs._grant_verified_skills(db, attempt)
    log_action(db, user_id=user.id, action="qualification.grade", entity_type="qualification_attempt",
               entity_id=attempt.id, details={"score": score, "passed": passed}, request=request)
    notify(db, user_id=attempt.worker_id, type="qualification_result",
           title=f"Assessment {'passed' if passed else 'failed'}",
           body=f"A reviewer graded your attempt: {float(score):.0%}.",
           entity_type="qualification_attempt", entity_id=attempt.id)
    return {"id": attempt.id, "status": attempt.status, "score": attempt.score}


# ---------------------------------------------------------------------------
# Workers: skills + performance
# ---------------------------------------------------------------------------

@worker_router.get("/skills")
def my_skills(db: DbSession, user: CurrentUser):
    rows = db.scalars(
        select(WorkerSkill).where(WorkerSkill.user_id == user.id).order_by(WorkerSkill.skill)
    ).all()
    return {
        "skills": [
            {"id": s.id, "skill": s.skill, "source": s.source, "level": s.level,
             "verified_at": s.verified_at.isoformat() if s.verified_at else None}
            for s in rows
        ],
        "catalog": SKILL_CATALOG,
    }


@worker_router.post("/skills", status_code=201)
def claim_skill(payload: dict, db: DbSession, user: CurrentUser, request: Request):
    if user.role != UserRole.TESTER:
        raise HTTPException(status_code=403, detail="Only testers manage skills.")
    skill = (payload.get("skill") or "").strip()
    if not skill:
        raise HTTPException(status_code=422, detail="skill is required.")
    existing = db.scalar(
        select(WorkerSkill).where(WorkerSkill.user_id == user.id, WorkerSkill.skill == skill)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Skill already listed.")
    row = WorkerSkill(user_id=user.id, skill=skill, source="self_reported")
    db.add(row)
    db.commit()
    db.refresh(row)
    log_action(db, user_id=user.id, action="worker.skill_claim", entity_type="worker_skill",
               entity_id=row.id, details={"skill": skill}, request=request)
    return {"id": row.id, "skill": row.skill, "source": row.source}


@worker_router.get("/performance")
def my_performance(db: DbSession, user: CurrentUser):
    """Worker-facing own performance from stored evidence only."""
    from app.models.submission import Submission, SubmissionReview
    total = db.scalar(select(func.count()).select_from(Submission).where(
        Submission.tester_id == user.id)) or 0
    approved = db.scalar(select(func.count()).select_from(Submission).where(
        Submission.tester_id == user.id, Submission.status == "approved")) or 0
    rejected = db.scalar(select(func.count()).select_from(Submission).where(
        Submission.tester_id == user.id, Submission.status == "rejected")) or 0
    revisions = db.scalar(select(func.count()).select_from(Submission).where(
        Submission.tester_id == user.id, Submission.status == "revision_required")) or 0
    golden = db.scalar(select(func.count()).select_from(GoldenTaskResult).where(
        GoldenTaskResult.worker_id == user.id)) or 0
    golden_passed = db.scalar(select(func.count()).select_from(GoldenTaskResult).where(
        GoldenTaskResult.worker_id == user.id,
        GoldenTaskResult.passed.is_(True))) or 0
    feedback = [
        {"decision": rv.decision, "comments": rv.comments,
         "created_at": rv.created_at.isoformat()}
        for rv in db.scalars(
            select(SubmissionReview).join(Submission, Submission.id == SubmissionReview.submission_id)
            .where(Submission.tester_id == user.id).order_by(SubmissionReview.created_at.desc()).limit(10)
        ).all()
    ]
    return {
        "submissions": {"total": total, "approved": approved, "rejected": rejected,
                        "revision_requested": revisions},
        "golden_tasks": {"attempts": golden, "passed": golden_passed,
                         "accuracy": round(golden_passed / golden, 4) if golden else None},
        "tier": qs.worker_tier(db, user.id),
        "recent_feedback": feedback,
    }


# ---------------------------------------------------------------------------
# Project eligibility config
# ---------------------------------------------------------------------------

@router.get("/eligibility/{project_id}")
def get_eligibility(project_id: int, db: DbSession, user: AdminPM):
    project = _admin_project(db, user, project_id)
    return {"requirements": project.eligibility_requirements or []}


@router.put("/eligibility/{project_id}")
def set_eligibility(project_id: int, payload: dict, db: DbSession, user: AdminPM, request: Request):
    project = _admin_project(db, user, project_id)
    reqs = payload.get("requirements")
    if reqs is not None and not isinstance(reqs, list):
        raise HTTPException(status_code=422, detail="requirements must be a list.")
    project.eligibility_requirements = reqs or []
    db.commit()
    log_action(db, user_id=user.id, action="project.eligibility_update", entity_type="project",
               entity_id=project_id, details={"requirements": reqs or []}, request=request)
    return {"requirements": project.eligibility_requirements or []}


@router.post("/eligibility/{project_id}/override", status_code=201)
def grant_override(project_id: int, payload: dict, db: DbSession, user: AdminPM, request: Request):
    project = _admin_project(db, user, project_id)
    email = (payload.get("email") or "").strip().lower()
    reason = (payload.get("reason") or "").strip()
    if not email or not reason:
        raise HTTPException(status_code=422, detail="email and reason are required.")
    target = db.scalar(select(User).where(User.email == email))
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    existing = db.scalar(select(ProjectEligibilityOverride).where(
        ProjectEligibilityOverride.project_id == project_id,
        ProjectEligibilityOverride.user_id == target.id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Override already exists for this user.")
    row = ProjectEligibilityOverride(project_id=project_id, user_id=target.id,
                                     granted_by=user.id, reason=reason)
    db.add(row)
    db.commit()
    log_action(db, user_id=user.id, action="project.eligibility_override", entity_type="project",
               entity_id=project_id, details={"user_id": target.id, "reason": reason}, request=request)
    return {"id": row.id, "user_id": target.id, "reason": reason}


def _admin_project(db: DbSession, user, project_id: int) -> Project:
    try:
        project = acl.require_project(db, user, project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return project
