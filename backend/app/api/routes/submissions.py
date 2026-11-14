"""Submission routes: drafts, submission, history, tester feedback."""
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.security import AdminPM, CurrentUser, DbSession
from app.models.dataset import DatasetRecord
from app.models.project import Project
from app.models.submission import Submission, SubmissionReview, SubmissionAdjudication
from app.models.task import Task
from app.models.user import UserRole
from app.services import access as acl
from app.services import submissions as sub_svc
from app.services import tasks as task_svc
from app.services.audit import log_action

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


def _submission_out(db: DbSession, s: Submission, include_payload: bool = True, blind: bool = False) -> dict:
    task = s.task
    return {
        "id": s.id,
        "task_id": s.task_id,
        "project_id": s.project_id,
        "attempt_number": s.attempt_number,
        "status": s.status,
        "payload": s.payload if include_payload else {},
        "label": s.label,
        "explanation": s.explanation,
        "evidence": s.evidence or [],
        "rubric_version_id": s.rubric_version_id,
        "time_spent_seconds": s.time_spent_seconds,
        "submitted_at": s.submitted_at.isoformat(),
        "decided_at": s.decided_at.isoformat() if s.decided_at else None,
        "task_title": task.title if task else None,
        "task_instructions": task.instructions if task else None,
        "tester_id": None if blind else s.tester_id,
        "tester_name": None if blind else (s.tester.name if s.tester else None),
        "project_name": s.project.name if s.project else None,
        "blind_review": bool(s.project.blind_review) if s.project else True,
    }


def _load_submission(db: DbSession, user: CurrentUser, submission_id: int) -> Submission:
    s = db.get(Submission, submission_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    try:
        acl.require_project(db, user, s.project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if user.role == UserRole.TESTER and s.tester_id != user.id:
        raise HTTPException(status_code=403, detail="Testers can only access their own submissions.")
    return s


# ------------------------------------------------------------- tester flows

@router.post("/tasks/{task_id}/draft")
def save_draft(task_id: int, payload: dict, db: DbSession, user: CurrentUser, request: Request):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        acl.require_project(db, user, task.project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        sub_svc.save_draft(db, task, user, payload.get("payload", {}))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"saved_at": task.draft_updated_at.isoformat() if task.draft_updated_at else None}


@router.post("/tasks/{task_id}/submit", status_code=201)
def submit(task_id: int, payload: dict, db: DbSession, user: CurrentUser, request: Request):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        acl.require_project(db, user, task.project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    submission, errors = sub_svc.submit_task(
        db, task, user,
        payload.get("payload") or {},
        payload.get("explanation"),
        payload.get("evidence"),
        payload.get("time_spent_seconds"),
    )
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Submission rejected.", "errors": errors})

    log_action(db, user_id=user.id, action="submission.create", entity_type="submission", entity_id=submission.id,
               details={"task_id": task_id, "attempt": submission.attempt_number}, request=request)

    # notify project reviewers
    for rid in sub_svc.reviewer_ids_for_submission(db, submission):
        if rid != user.id:
            task_svc.notify(db, rid, "submission_received", f"New submission to review: {task.title}",
                            f"Attempt {submission.attempt_number} was submitted and awaits review.",
                            entity_type="submission", entity_id=submission.id)
    db.commit()
    return _submission_out(db, submission)


@router.get("/tasks/{task_id}/workspace")
def task_workspace(task_id: int, db: DbSession, user: CurrentUser):
    """Everything the tester's execution UI needs, in one call."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        acl.require_project(db, user, task.project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if user.role == UserRole.TESTER and task.assigned_tester_id != user.id:
        raise HTTPException(status_code=403, detail="This task is not assigned to you.")

    record = task.record
    fields = sub_svc.get_form_fields(task.rubric_version)
    rubric_def = task.rubric_version.definition if task.rubric_version else None

    my_submissions = list(db.scalars(
        select(Submission).where(Submission.task_id == task.id, Submission.tester_id == user.id)
        .order_by(Submission.attempt_number)
    ).all())

    feedback = []
    for s in my_submissions:
        for rv in db.scalars(select(SubmissionReview).where(SubmissionReview.submission_id == s.id)).all():
            feedback.append({
                "submission_id": s.id, "attempt": s.attempt_number,
                "decision": rv.decision, "comments": rv.comments,
                "reviewer_name": None if s.project.blind_review else (rv.reviewer.name if rv.reviewer else None),
                "created_at": rv.created_at.isoformat(),
            })
        adj = db.scalar(select(SubmissionAdjudication).where(SubmissionAdjudication.submission_id == s.id))
        if adj:
            feedback.append({
                "submission_id": s.id, "attempt": s.attempt_number,
                "decision": f"adjudicated: {adj.final_decision}", "comments": adj.rationale,
                "reviewer_name": "Quality lead", "created_at": adj.created_at.isoformat(),
            })

    return {
        "task": {
            "id": task.id, "title": task.title, "task_type": task.task_type,
            "instructions": task.instructions, "status": task.status,
            "priority": task.priority, "difficulty": task.difficulty,
            "estimated_minutes": task.estimated_minutes,
            "deadline": task.deadline.isoformat() if task.deadline else None,
            "attempt_count": task.attempt_count, "max_attempts": task.max_attempts,
            "claimed_at": task.claimed_at.isoformat() if task.claimed_at else None,
            "project_name": task.project.name if task.project else None,
            "blind_review": bool(task.project.blind_review) if task.project else True,
        },
        "record": {
            "record_id": record.record_id, "prompt": record.prompt, "response": record.response,
            # golden tasks must never reveal the expected answer to the worker
            "reference_answer": None if task.is_golden else record.reference_answer,
            "reference_sources": [] if task.is_golden else (record.reference_sources or []),
            "supporting_evidence": record.supporting_evidence,
            "source_url": record.source_url,
            "content_category": record.content_category,
            "language": record.language or "en",
            "custom_fields": record.custom_fields or {},
        } if record else None,
        "form_fields": fields,
        "rubric_definition": rubric_def,
        "draft_payload": task.draft_payload,
        "draft_updated_at": task.draft_updated_at.isoformat() if task.draft_updated_at else None,
        "submissions": [
            {"id": s.id, "attempt_number": s.attempt_number, "status": s.status,
             "submitted_at": s.submitted_at.isoformat(), "payload": s.payload}
            for s in my_submissions
        ],
        "feedback": feedback,
        "can_submit": task.status in ("in_progress", "revision_required"),
    }


# ------------------------------------------------------------- listings

@router.get("/mine")
def my_submissions(db: DbSession, user: CurrentUser, status: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    stmt = (
        select(Submission).options(joinedload(Submission.task), joinedload(Submission.project))
        .where(Submission.tester_id == user.id)
        .order_by(Submission.submitted_at.desc())
    )
    if status:
        stmt = stmt.where(Submission.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all()
    return {"items": [_submission_out(db, s, include_payload=False) for s in items],
            "total": int(total), "page": page, "page_size": page_size}


@router.get("")
def list_submissions(
    db: DbSession, user: CurrentUser,
    project_id: int | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
):
    """Staff/project view of submissions. Testers only ever see their own."""
    ids = acl.visible_project_ids(db, user)
    stmt = (
        select(Submission).options(joinedload(Submission.task), joinedload(Submission.project),
                                   joinedload(Submission.tester))
        .order_by(Submission.submitted_at.desc())
    )
    if user.role == UserRole.TESTER:
        stmt = stmt.where(Submission.tester_id == user.id)
    elif ids is not None:
        if not ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        stmt = stmt.where(Submission.project_id.in_(ids))
    if project_id:
        stmt = stmt.where(Submission.project_id == project_id)
    if status:
        stmt = stmt.where(Submission.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all()
    blind = user.role not in UserRole.PLATFORM_WIDE and user.role not in (UserRole.SENIOR_REVIEWER,)
    return {"items": [_submission_out(db, s, include_payload=True, blind=blind) for s in items],
            "total": int(total), "page": page, "page_size": page_size}


# ------------------------------------------------------------- reviewer decisions

VALID_DECISIONS = ("approved", "rejected", "revision_requested")


@router.get("/review-queue")
def review_queue(db: DbSession, user: CurrentUser, project_id: int | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200)):
    """Submitted work awaiting review in the reviewer's projects (claim-based)."""
    if user.role not in UserRole.REVIEWERS:
        raise HTTPException(status_code=403, detail="Only reviewers can access the review queue.")
    ids = acl.visible_project_ids(db, user)
    stmt = (
        select(Submission).options(joinedload(Submission.task), joinedload(Submission.project))
        .where(Submission.status == "submitted")
        .order_by(Submission.submitted_at)
    )
    if ids is not None:
        if not ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        stmt = stmt.where(Submission.project_id.in_(ids))
    if project_id:
        stmt = stmt.where(Submission.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all()
    blind = user.role not in UserRole.PLATFORM_WIDE
    return {"items": [_submission_out(db, s, include_payload=False, blind=blind) for s in items],
            "total": int(total), "page": page, "page_size": page_size}


@router.post("/{submission_id}/claim-review")
def claim_review(submission_id: int, db: DbSession, user: CurrentUser, request: Request):
    """Exclusive claim: submitted -> under_review by one reviewer at a time."""
    if user.role not in UserRole.REVIEWERS:
        raise HTTPException(status_code=403, detail="Only reviewers can review submissions.")
    s = _load_submission(db, user, submission_id)
    from sqlalchemy import update
    result = db.execute(
        update(Submission)
        .where(Submission.id == s.id, Submission.status == "submitted")
        .values(status="under_review")
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Submission is already under review or decided.")
    db.refresh(s)
    return _submission_out(db, s, blind=user.role not in UserRole.PLATFORM_WIDE)


@router.post("/{submission_id}/review")
def decide_review(submission_id: int, payload: dict, db: DbSession, user: CurrentUser, request: Request):
    """Record an append-only review decision and transition task + submission.

    approved/rejected finalize; revision_requested returns the task to the
    tester as revision_required (resubmission consumes an attempt).
    """
    if user.role not in UserRole.REVIEWERS:
        raise HTTPException(status_code=403, detail="Only reviewers can record decisions.")
    s = _load_submission(db, user, submission_id)
    try:
        project = acl.require_project(db, user, s.project_id)
        if user.role not in (UserRole.SUPER_ADMIN,) and not acl.is_project_reviewer(db, user, s.project_id) \
                and not (user.role in UserRole.STAFF and project.is_admin_of(user.id)):
            raise PermissionError("You are not a reviewer on this project.")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    decision = (payload.get("decision") or "").strip()
    if decision not in VALID_DECISIONS:
        raise HTTPException(status_code=422, detail=f"decision must be one of {VALID_DECISIONS}.")
    if s.status in ("approved", "rejected"):
        raise HTTPException(status_code=409, detail=(
            f"Submission is already {s.status}. Decisions are append-only; use adjudication to override."))

    # guard: the same reviewer cannot decide the same submission twice
    prior = db.scalar(select(SubmissionReview).where(
        SubmissionReview.submission_id == s.id, SubmissionReview.reviewer_id == user.id))
    if prior is not None:
        raise HTTPException(status_code=409, detail="You have already reviewed this submission.")

    review = SubmissionReview(
        submission_id=s.id,
        reviewer_id=user.id,
        decision=decision,
        comments=payload.get("comments"),
        corrected_labels=payload.get("corrected_labels"),
        flagged_suspicious=bool(payload.get("flagged_suspicious", False)),
        ambiguous=bool(payload.get("ambiguous", False)),
        escalated=bool(payload.get("escalated", False)),
        blind=bool(project.blind_review),
        rubric_version_id=s.rubric_version_id,
        time_spent_seconds=payload.get("time_spent_seconds"),
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    # Finalization logic: collect all reviews on this submission
    task = db.get(Task, s.task_id)
    reviews = _reviews_for(db, s.id)
    decisions = {r.decision for r in reviews}
    distinct_reviewers = {r.reviewer_id for r in reviews}
    project_reviewers = acl.project_reviewer_ids(db, s.project_id)
    conflicting = len(decisions) > 1
    all_decided = len(distinct_reviewers) >= max(1, len(project_reviewers))

    new_status = s.status  # default: keep accumulating reviews
    if decision == "revision_requested":
        # A revision request returns work to the tester immediately; other
        # reviewers may still weigh in on the revised attempt's history.
        new_status = "revision_required"
    elif conflicting:
        # reviewers disagree -> under_review, routed to adjudication
        new_status = "under_review"
    elif all_decided:
        # consensus among all assigned reviewers (or single-reviewer setup)
        new_status = review.decision

    from sqlalchemy import update
    if new_status != s.status:
        result = db.execute(
            update(Submission)
            .where(Submission.id == s.id, Submission.status.in_(["submitted", "under_review", "revision_required"]))
            .values(status=new_status, decided_at=_now_utc(),
                    flagged_suspicious=bool(payload.get("flagged_suspicious", False)) or s.flagged_suspicious,
                    escalated=bool(payload.get("escalated", False)) or s.escalated)
        )
        if result.rowcount == 0:
            db.rollback()
            raise HTTPException(status_code=409, detail="Submission state changed concurrently.")
        if task is not None:
            db.execute(
                update(Task)
                .where(Task.id == s.task_id, Task.status.in_(["submitted", "under_review", "revision_required"]))
                .values(status=new_status if new_status != "revision_required" else "revision_required")
            )
    db.commit()

    log_action(db, user_id=user.id, action="review.decision", entity_type="submission", entity_id=s.id,
               details={"decision": decision, "task_id": s.task_id,
                        "flagged": review.flagged_suspicious, "ambiguous": review.ambiguous},
               request=request)
    # v3 webhooks: notify external integrations
    try:
        from app.services import webhooks as _wh
        _wh.dispatch_event(db, "review.completed", {
            "submission_id": s.id, "task_id": s.task_id, "project_id": s.project_id,
            "decision": decision,
        })
        if new_status in ("approved", "rejected"):
            _wh.dispatch_event(db, f"submission.{new_status}", {
                "submission_id": s.id, "task_id": s.task_id, "project_id": s.project_id,
            })
    except Exception:
        pass
    # the tester is always informed of the decision; blind review only hides
    # reviewer identity from the tester, never the decision itself
    task_svc.notify(
        db, s.tester_id,
        "revision_requested" if decision == "revision_requested" else "review_decision",
        f"Your submission was {decision.replace('_', ' ')}: {task.title if task else s.task_id}",
        payload.get("comments"),
        entity_type="submission", entity_id=s.id,
    )
    db.commit()
    return {
        "id": review.id, "decision": review.decision, "submission_status": new_status,
        "comments": review.comments, "created_at": review.created_at.isoformat(),
    }


def _now_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _reviews_for(db: DbSession, submission_id: int) -> list[SubmissionReview]:
    return list(db.scalars(
        select(SubmissionReview).where(SubmissionReview.submission_id == submission_id)
        .order_by(SubmissionReview.created_at)
    ).all())


@router.get("/{submission_id}")
def get_submission(submission_id: int, db: DbSession, user: CurrentUser):
    s = _load_submission(db, user, submission_id)
    # blind review: non-supervisor project reviewers never see the tester identity
    blind = bool(s.project.blind_review) and user.role not in UserRole.PLATFORM_WIDE \
        and user.role != UserRole.SENIOR_REVIEWER
    out = _submission_out(db, s, blind=blind)
    out["reviews"] = []
    out["adjudication"] = None
    out["task_record"] = None
    task = s.task
    if task and task.record:
        r = task.record
        out["task_record"] = {
            "record_id": r.record_id, "prompt": r.prompt, "response": r.response,
            "reference_answer": r.reference_answer, "reference_sources": r.reference_sources or [],
            "supporting_evidence": r.supporting_evidence, "source_url": r.source_url,
        }
    can_see_reviews = user.role != UserRole.TESTER or s.status in ("approved", "rejected", "revision_required")
    if can_see_reviews:
        out["reviews"] = [
            {
                "id": rv.id, "decision": rv.decision, "comments": rv.comments,
                "corrected_labels": rv.corrected_labels,
                "flagged_suspicious": rv.flagged_suspicious, "ambiguous": rv.ambiguous,
                "escalated": rv.escalated,
                "reviewer_id": rv.reviewer_id,
                "reviewer_name": (rv.reviewer.name if rv.reviewer else None)
                if (not s.project.blind_review or user.role != UserRole.TESTER) else None,
                "created_at": rv.created_at.isoformat(),
            }
            for rv in sub_svc.submission_review_history(db, s)
        ]
        adj = db.scalar(select(SubmissionAdjudication).where(SubmissionAdjudication.submission_id == s.id))
        if adj:
            out["adjudication"] = {
                "id": adj.id, "final_decision": adj.final_decision, "rationale": adj.rationale,
                "created_at": adj.created_at.isoformat(),
            }
    out["rubric_definition"] = s.task.rubric_version.definition if s.task and s.task.rubric_version else None
    return out
