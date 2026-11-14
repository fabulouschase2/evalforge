"""Submission lifecycle: drafts, validation against rubric forms, submission, resubmission.

Guarantees:
- a task can hold exactly one open submission per attempt (unique task+attempt)
- submission requires task status in_progress (or revision_required for a new
  attempt when attempts remain); the transition is an atomic conditional UPDATE
- payloads are validated against the rubric version's evaluation form,
  including conditional-question logic
"""
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.rubric import RubricVersion
from app.models.submission import Submission, SubmissionReview, SubmissionAdjudication
from app.models.task import Task
from app.models.user import User

FORM_FIELD_TYPES = {"yes_no", "single_select", "multi_select", "numeric", "likert", "text", "evidence"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_form_fields(rubric_version: RubricVersion | None) -> list[dict]:
    if rubric_version is None:
        return []
    form = (rubric_version.definition or {}).get("form") or {}
    fields = form.get("fields") or []
    return [f for f in fields if isinstance(f, dict) and f.get("id")]


def _condition_met(payload: dict, conditional_on: dict) -> bool:
    parent_value = payload.get(conditional_on["field_id"])
    return parent_value in (conditional_on.get("values") or [])


def validate_payload_against_form(fields: list[dict], payload: dict) -> tuple[dict, list[str]]:
    """Validate a tester payload against the form; returns (clean_payload, errors).

    Conditional questions are only enforced when their trigger condition is met
    by the current payload; values from hidden branches are stripped.
    """
    errors: list[str] = []
    clean: dict = {}
    for f in fields:
        fid, ftype = f["id"], f.get("type")
        cond = f.get("conditional_on")
        if cond and not _condition_met(payload, cond):
            continue  # hidden branch: ignore entirely
        value = payload.get(fid)
        missing = value is None or value == "" or value == [] 
        if missing:
            if f.get("required"):
                errors.append(f"'{f.get('label', fid)}' is required.")
            continue
        if ftype == "yes_no":
            if value not in ("yes", "no"):
                errors.append(f"'{f.get('label', fid)}' must be 'yes' or 'no'.")
        elif ftype == "single_select":
            if value not in (f.get("options") or []):
                errors.append(f"'{f.get('label', fid)}' must be one of {f.get('options')}.")
        elif ftype == "multi_select":
            if not isinstance(value, list):
                errors.append(f"'{f.get('label', fid)}' must be a list of selections.")
            else:
                bad = [v for v in value if v not in (f.get("options") or [])]
                if bad:
                    errors.append(f"'{f.get('label', fid)}' contains invalid options: {bad}.")
        elif ftype in ("numeric", "likert"):
            scale = f.get("scale") or {}
            try:
                num = float(value)
            except (TypeError, ValueError):
                errors.append(f"'{f.get('label', fid)}' must be a number.")
                continue
            if isinstance(scale.get("min"), (int, float)) and num < scale["min"]:
                errors.append(f"'{f.get('label', fid)}' must be >= {scale['min']}.")
            if isinstance(scale.get("max"), (int, float)) and num > scale["max"]:
                errors.append(f"'{f.get('label', fid)}' must be <= {scale['max']}.")
            clean[fid] = num
            continue
        elif ftype == "text":
            if not isinstance(value, str) or not value.strip():
                errors.append(f"'{f.get('label', fid)}' must be non-empty text.")
        elif ftype == "evidence":
            if not isinstance(value, list) or not all(isinstance(e, dict) for e in value):
                errors.append(f"'{f.get('label', fid)}' must be a list of evidence objects.")
        clean[fid] = value
    # reject unknown payload keys (strict forms)
    known = {f["id"] for f in fields}
    extra = [k for k in payload.keys() if k not in known and not k.startswith("_")]
    if extra:
        errors.append(f"Unknown form fields submitted: {extra}.")
    return clean, errors


def save_draft(db: Session, task: Task, tester: User, payload: dict) -> None:
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.assigned_tester_id == tester.id,
               Task.status.in_(["assigned", "in_progress", "revision_required"]))
        .values(draft_payload=payload, draft_updated_at=_now())
    )
    db.commit()
    if result.rowcount == 0:
        raise PermissionError("Draft can only be saved by the assigned tester while working.")


def submit_task(db: Session, task: Task, tester: User, payload: dict,
                explanation: str | None, evidence: list | None,
                time_spent_seconds: int | None) -> tuple[Submission | None, list[str]]:
    """Validate and create a submission; atomically transitions the task status.

    Allowed from in_progress (first attempt) or revision_required (resubmission
    when attempts remain). Duplicate submissions are impossible: the status
    guard fails for tasks already submitted/under_review.
    """
    if task.assigned_tester_id != tester.id:
        return None, ["Task is not assigned to you."]
    if task.status not in ("in_progress", "revision_required"):
        return None, [f"Task cannot be submitted from status '{task.status}'. Actual open submission "
                      "flows require in_progress or an authorized revision_required task."]
    attempt_count = (db.scalar(select(func.count()).select_from(Submission).where(Submission.task_id == task.id)) or 0)
    if attempt_count >= task.max_attempts:
        return None, [f"Attempt limit reached ({task.max_attempts}). Ask a project admin to raise max attempts."]
    attempt_number = attempt_count + 1

    fields = get_form_fields(task.rubric_version)
    if fields:
        clean_payload, errors = validate_payload_against_form(fields, payload or {})
    else:
        # free-form tasks: at least a label or explanation is required
        clean_payload = payload or {}
        errors = []
        if not (clean_payload or explanation):
            errors.append("Provide evaluation answers or a written explanation.")
    if errors:
        return None, errors

    now = _now()
    # Atomic transition to 'submitted'
    result = db.execute(
        update(Task)
        .where(Task.id == task.id,
               Task.assigned_tester_id == tester.id,
               Task.status.in_(["in_progress", "revision_required"]))
        .values(status="submitted", draft_payload=None, draft_updated_at=None)
    )
    if result.rowcount == 0:
        db.rollback()
        return None, ["Task state changed concurrently; submission refused. Refresh and retry."]

    label = None
    for f in fields:
        if f.get("type") == "yes_no":
            label = "pass" if clean_payload.get(f["id"]) == "yes" else "fail"
            break
    if label is None and isinstance(clean_payload.get("label"), str):
        label = clean_payload["label"]

    submission = Submission(
        task_id=task.id,
        project_id=task.project_id,
        tester_id=tester.id,
        attempt_number=attempt_number,
        status="submitted",
        payload=clean_payload,
        label=label,
        explanation=explanation,
        evidence=evidence or [],
        rubric_version_id=task.rubric_version_id,
        time_spent_seconds=time_spent_seconds,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    # v3 golden-task quality control: score immediately when this task is a probe
    try:
        from app.services.golden import score_submission_if_golden
        score_submission_if_golden(db, submission)
    except Exception:  # quality scoring must never break the submission flow
        import logging
        logging.getLogger("evalforge.golden").exception("golden scoring failed for submission %s", submission.id)
    return submission, []


def reviewer_ids_for_submission(db: Session, submission: Submission) -> list[int]:
    from app.services.access import project_reviewer_ids
    return project_reviewer_ids(db, submission.project_id)


def submission_review_history(db: Session, submission: Submission) -> list[SubmissionReview]:
    return list(db.scalars(
        select(SubmissionReview).where(SubmissionReview.submission_id == submission.id)
        .order_by(SubmissionReview.created_at)
    ).all())
