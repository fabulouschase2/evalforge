"""Golden task scoring, distribution and quality monitoring.

Scoring supports multiple methods — never plain string equality for every type:
- exact:            normalized string equality (trim + collapse whitespace + casefold)
- variations:       exact match against accepted_variations
- numeric_tolerance: first number in the answer within config.tolerance
- single_label:     case-insensitive label membership in config.labels (or reference labels)
- multi_label:      set comparison; partial credit optional (config.allow_partial)
- contains_keywords: all config.keywords present in the answer text

Distribution: golden tasks are real Tasks (so claiming/review/timing stay
uniform) marked is_golden=1 on the task row. That flag and every reference
field are stripped from tester-visible serialization.
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.golden import (
    GoldenTask, GoldenTaskResult, QualityAlert,
)
from app.models.project import Project
from app.models.submission import Submission
from app.models.task import Task
from app.models.user import User
from app.services.notifications import notify

DEFAULT_CONFIG = {
    "percentage": 10,          # % of queue inserts that are golden
    "fixed_count": None,       # or insert exactly N per generation batch
    "min_spacing": 5,          # min ordinary tasks between two golden inserts
    "difficulty_mix": None,    # e.g. {"easy": 2, "medium": 2, "hard": 1}
    "pass_score": 0.99,        # score >= this counts as passed
    # alert thresholds
    "min_attempts_for_accuracy": 5,
    "accuracy_alert_below": 0.6,
    "consecutive_failures_alert": 3,
    "sudden_decline_drop": 0.3,
    "min_seconds_per_task": 10,
}


def project_golden_config(project: Project) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if project and isinstance(project.golden_task_config, dict):
        cfg.update(project.golden_task_config)
    return cfg


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


def _first_number(s: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", (s or "").replace(",", ""))
    return float(m.group(0)) if m else None


def score_answer(golden: GoldenTask, answer) -> tuple[float, bool, list[str]]:
    """Score a submission answer against the reference. Returns (score, passed, reasons).

    `answer` is whatever the tester submitted for the main field: a string,
    a label, or a list of labels depending on task type.
    """
    cfg = dict(golden.scoring_config or {})
    ref = golden.reference_answer or {}
    method = golden.scoring_method
    reasons: list[str] = []
    pass_score = float(cfg.get("pass_score", 0.99))

    def _pass(score: float) -> tuple[float, bool, list[str]]:
        return score, score >= pass_score, ([] if score >= pass_score else reasons)

    ref_text = ref.get("answer") or ref.get("label") or ""
    variations = list(golden.accepted_variations or [])

    if method == "exact":
        if isinstance(answer, str) and _norm(answer) == _norm(str(ref_text)):
            return _pass(1.0)
        reasons.append("Answer does not match the reference answer exactly.")
        return _pass(0.0)

    if method == "variations":
        candidates = [_norm(str(v)) for v in ([ref_text] + variations) if str(v).strip()]
        if isinstance(answer, str) and _norm(answer) in candidates:
            return _pass(1.0)
        reasons.append("Answer is not among the accepted variations.")
        return _pass(0.0)

    if method == "numeric_tolerance":
        tol = float(cfg.get("tolerance", 0.01))
        ref_num = ref.get("number", _first_number(str(ref_text)))
        got = _first_number(answer) if isinstance(answer, str) else (
            float(answer) if isinstance(answer, (int, float)) else None)
        if got is None or ref_num is None:
            reasons.append("No numeric value found to compare.")
            return _pass(0.0)
        diff = abs(got - float(ref_num))
        if diff <= tol + 1e-9:
            return _pass(1.0)
        reasons.append(f"Numeric difference {diff} exceeds tolerance {tol}.")
        return _pass(0.0)

    if method == "single_label":
        labels = [str(l).casefold() for l in (cfg.get("labels") or [ref_text] + variations)]
        got = str(answer).casefold() if not isinstance(answer, list) else (
            str(answer[0]).casefold() if answer else "")
        if got in labels:
            return _pass(1.0)
        reasons.append("Submitted label is not the expected label.")
        return _pass(0.0)

    if method == "multi_label":
        expected = {str(l).casefold() for l in (
            cfg.get("labels") or
            (ref.get("labels") or ([ref_text] + variations))
        ) if str(l).strip()}
        got_list = answer if isinstance(answer, list) else [answer]
        got = {str(l).casefold() for l in got_list if str(l).strip()}
        if not expected:
            reasons.append("Reference labels are not configured.")
            return _pass(0.0)
        if got == expected:
            return _pass(1.0)
        overlap = len(got & expected)
        allow_partial = bool(cfg.get("allow_partial"))
        if allow_partial and expected:
            score = overlap / len(expected) if got else 0.0
            extra = got - expected
            if extra:
                reasons.append(f"Incorrect labels included: {sorted(extra)}")
            if missing := (expected - got):
                reasons.append(f"Missing labels: {sorted(missing)}")
            return _pass(score)
        if missing := (expected - got):
            reasons.append(f"Missing labels: {sorted(missing)}")
        if extra := (got - expected):
            reasons.append(f"Incorrect labels included: {sorted(extra)}")
        return _pass(0.0)

    if method == "contains_keywords":
        keywords = [str(k) for k in (cfg.get("keywords") or [])]
        text = answer if isinstance(answer, str) else " ".join(str(x) for x in (answer or []))
        hay = _norm(text)
        missing = [k for k in keywords if _norm(k) not in hay]
        if not keywords:
            reasons.append("No keywords configured for scoring.")
            return _pass(0.0)
        if missing:
            reasons.append(f"Missing keywords: {missing}")
            found = len(keywords) - len(missing)
            return _pass(found / len(keywords) if cfg.get("partial_credit") else 0.0)
        return _pass(1.0)

    reasons.append(f"Unknown scoring method '{method}'.")
    return _pass(0.0)


# ---------------------------------------------------------------------------
# Distribution: insert golden tasks into a project's queue
# ---------------------------------------------------------------------------

def _next_spacing_ok(db: Session, project_id: int, min_spacing: int) -> bool:
    """Avoid inserting golden tasks back-to-back: check trailing task ids."""
    if min_spacing <= 0:
        return True
    last_rows = db.scalars(
        select(Task.id).where(Task.project_id == project_id, Task.is_golden.is_(True))
        .order_by(Task.id.desc()).limit(1)
    ).all()
    if not last_rows:
        return True
    last_golden_id = last_rows[0]
    ordinary_since = db.scalar(
        select(func.count()).select_from(Task).where(
            Task.project_id == project_id,
            Task.is_golden.is_(False),
            Task.id > last_golden_id,
        )
    ) or 0
    return ordinary_since >= min_spacing


def pick_golden_for_insert(db: Session, project: Project, batch_size: int,
                           rng: random.Random | None = None) -> list[GoldenTask]:
    """Choose golden tasks to weave into a batch of `batch_size` ordinary tasks."""
    rng = rng or random.Random()
    cfg = project_golden_config(project)
    wanted = 0
    if cfg.get("fixed_count"):
        wanted = int(cfg["fixed_count"])
    elif cfg.get("percentage", 0) > 0:
        wanted = int(round(batch_size * float(cfg["percentage"]) / 100.0))
    if wanted <= 0:
        return []

    actives = db.scalars(
        select(GoldenTask).where(
            GoldenTask.project_id == project.id, GoldenTask.is_active.is_(True)
        )
    ).all()
    if not actives:
        return []

    # difficulty mix filter (best effort)
    mix = cfg.get("difficulty_mix") or {}
    picked: list[GoldenTask] = []
    pool = list(actives)
    rng.shuffle(pool)
    for difficulty, count in mix.items():
        take = [g for g in pool if g.difficulty == difficulty][:int(count)]
        picked.extend(take)
    remaining = wanted - len(picked)
    if remaining > 0:
        already = {g.id for g in picked}
        for g in pool:
            if remaining <= 0:
                break
            if g.id not in already:
                picked.append(g)
                remaining -= 1
    return picked[:wanted]


def weave_golden_tasks(db: Session, project: Project, created_tasks: list[Task],
                       created_by: int) -> int:
    """After generating `created_tasks` for a project, insert golden tasks into
    the queue honoring spacing. Returns the number inserted."""
    if not created_tasks:
        return 0
    cfg = project_golden_config(project)
    min_spacing = int(cfg.get("min_spacing", 5))
    inserted = 0
    for golden in pick_golden_for_insert(db, project, len(created_tasks)):
        if not _next_spacing_ok(db, project.id, min_spacing):
            break
        task = Task(
            project_id=project.id,
            dataset_record_id=golden.source_record_id,
            title=golden.title,
            task_type=project.project_type,
            instructions=golden.instructions or project.instructions,
            status="available",
            difficulty=golden.difficulty,
            created_by=created_by,
            is_golden=True,
            golden_task_id=golden.id,
        )
        db.add(task)
        db.flush()
        inserted += 1
    if inserted:
        db.commit()
    return inserted


# ---------------------------------------------------------------------------
# Scoring hook — called from the submission path
# ---------------------------------------------------------------------------

def score_submission_if_golden(db: Session, submission: Submission) -> GoldenTaskResult | None:
    """Score a submission whose task is a golden task; append a result row."""
    task = submission.task
    if task is None or not task.is_golden or task.golden_task_id is None:
        return None
    golden = db.get(GoldenTask, task.golden_task_id)
    if golden is None:
        return None
    payload = submission.payload or {}
    # the graded field: prefer the rubric form's first field, common keys, else whole payload
    answer = None
    for key in ("answer", "label", "response", "value", "evaluation"):
        if key in payload:
            answer = payload[key]
            break
    if answer is None and payload:
        first = next(iter(payload.values()))
        answer = first
    score, passed, reasons = score_answer(golden, answer)
    result = GoldenTaskResult(
        golden_task_id=golden.id,
        task_id=task.id,
        submission_id=submission.id,
        worker_id=submission.tester_id,
        project_id=submission.project_id,
        golden_task_version=golden.version,
        scoring_method=golden.scoring_method,
        scored_answer={"answer": answer} if not isinstance(answer, dict) else answer,
        score=score,
        passed=passed,
        failure_reasons=reasons,
        time_spent_seconds=submission.time_spent_seconds,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    evaluate_alerts(db, submission.project_id, submission.tester_id)
    return result


# ---------------------------------------------------------------------------
# Alerts — indicators for humans, never automatic suspensions
# ---------------------------------------------------------------------------

def evaluate_alerts(db: Session, project_id: int, worker_id: int) -> list[QualityAlert]:
    project = db.get(Project, project_id)
    cfg = project_golden_config(project) if project else dict(DEFAULT_CONFIG)
    min_attempts = int(cfg.get("min_attempts_for_accuracy", 5))
    acc_below = float(cfg.get("accuracy_alert_below", 0.6))
    consec_alert = int(cfg.get("consecutive_failures_alert", 3))
    decline_drop = float(cfg.get("sudden_decline_drop", 0.3))

    created: list[QualityAlert] = []
    results = db.scalars(
        select(GoldenTaskResult).where(
            GoldenTaskResult.project_id == project_id,
            GoldenTaskResult.worker_id == worker_id,
        ).order_by(GoldenTaskResult.scored_at.asc())
    ).all()
    if not results:
        return created

    def _open_exists(kind: str, window_hours: int = 24) -> bool:
        since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        recent = db.scalar(
            select(func.count()).select_from(QualityAlert).where(
                QualityAlert.project_id == project_id,
                QualityAlert.worker_id == worker_id,
                QualityAlert.alert_type == kind,
                QualityAlert.resolved.is_(False),
                QualityAlert.created_at > since,
            )
        ) or 0
        return recent > 0

    # repeated consecutive failures
    streak = 0
    for r in results:
        streak = streak + 1 if not r.passed else 0
    if streak >= consec_alert and not _open_exists("repeated_failures"):
        alert = QualityAlert(
            project_id=project_id, worker_id=worker_id, alert_type="repeated_failures",
            severity="warning",
            message=f"{streak} consecutive failed golden tasks (threshold {consec_alert}). "
                    "Investigate before assigning advanced work.",
            evidence={"consecutive_failures": streak, "threshold": consec_alert},
        )
        db.add(alert)
        created.append(alert)

    # low accuracy over the window
    if len(results) >= min_attempts:
        acc = sum(1 for r in results if r.passed) / len(results)
        if acc < acc_below and not _open_exists("low_accuracy"):
            alert = QualityAlert(
                project_id=project_id, worker_id=worker_id, alert_type="low_accuracy",
                severity="warning",
                message=f"Golden-task accuracy {acc:.0%} over {len(results)} attempts "
                        f"is below the {acc_below:.0%} threshold.",
                evidence={"accuracy": round(acc, 4), "attempts": len(results),
                          "threshold": acc_below},
            )
            db.add(alert)
            created.append(alert)

        # sudden decline: recent half vs older half
        half = len(results) // 2
        if half >= 3:
            older, recent = results[:half], results[half:]
            older_acc = sum(1 for r in older if r.passed) / len(older)
            recent_acc = sum(1 for r in recent if r.passed) / len(recent)
            if (older_acc - recent_acc) >= decline_drop and not _open_exists("sudden_decline"):
                alert = QualityAlert(
                    project_id=project_id, worker_id=worker_id, alert_type="sudden_decline",
                    severity="warning",
                    message=f"Golden-task accuracy dropped from {older_acc:.0%} to {recent_acc:.0%}.",
                    evidence={"older": round(older_acc, 4), "recent": round(recent_acc, 4)},
                )
                db.add(alert)
                created.append(alert)

    # excessive completion speed on the latest result
    latest = results[-1]
    min_secs = int(cfg.get("min_seconds_per_task", 10))
    if latest.time_spent_seconds is not None and 0 < latest.time_spent_seconds < min_secs \
            and not _open_exists("excessive_speed"):
        alert = QualityAlert(
            project_id=project_id, worker_id=worker_id, alert_type="excessive_speed",
            severity="info",
            message=f"Golden task completed in {latest.time_spent_seconds}s "
                    f"(minimum plausible {min_secs}s).",
            evidence={"seconds": latest.time_spent_seconds, "threshold": min_secs},
        )
        db.add(alert)
        created.append(alert)

    if created:
        db.commit()
        for a in created:
            _notify_staff_alert(db, a)
    return created


def _notify_staff_alert(db: Session, alert: QualityAlert) -> None:
    from app.models.user import UserRole
    admins = db.scalars(
        select(User.id).where(
            User.role.in_([UserRole.SUPER_ADMIN, UserRole.PROJECT_ADMIN,
                           UserRole.SENIOR_REVIEWER]), User.is_active.is_(True)
        )
    ).all()
    for uid in admins:
        notify(db, user_id=uid, type="quality_alert", title=f"Quality alert: {alert.alert_type}",
               body=alert.message, entity_type="quality_alert", entity_id=alert.id)
