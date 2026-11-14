"""Senior reviewer / quality lead services and routes.

Adjudication: requires conflicting reviewer decisions (or an escalated
submission). The final decision creates an immutable adjudication record;
the original reviews are never modified.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.security import AdminPM, CurrentUser, DbSession
from app.models.project import Project
from app.models.submission import Submission, SubmissionAdjudication, SubmissionReview
from app.models.task import Task
from app.models.user import User, UserRole
from app.services import access as acl
from app.services.analytics import fleiss_kappa
from app.services.audit import log_action

router = APIRouter(prefix="/api/quality", tags=["quality"])


def _require_quality_lead(db: DbSession, user: CurrentUser):
    if user.role not in (UserRole.SENIOR_REVIEWER, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Quality monitoring requires a senior reviewer role.")


def _review_decisions(db: DbSession, submission_id: int) -> list[SubmissionReview]:
    return list(db.scalars(
        select(SubmissionReview).where(SubmissionReview.submission_id == submission_id)
        .order_by(SubmissionReview.created_at)
    ).all())


def _conflicting(reviews: list[SubmissionReview]) -> bool:
    return len({r.decision for r in reviews}) > 1


def _submission_brief(db: DbSession, s: Submission, blind: bool = True) -> dict:
    return {
        "id": s.id,
        "task_id": s.task_id,
        "project_id": s.project_id,
        "project_name": s.project.name if s.project else None,
        "task_title": s.task.title if s.task else None,
        "attempt_number": s.attempt_number,
        "status": s.status,
        "label": s.label,
        "explanation": s.explanation,
        "escalated": s.escalated,
        "flagged_suspicious": s.flagged_suspicious,
        "submitted_at": s.submitted_at.isoformat(),
        "tester_name": None if blind else (s.tester.name if s.tester else None),
        "decision_counts": dict(Counter(r.decision for r in s.reviews or [])),
    }


# ------------------------------------------------------------ adjudication

@router.get("/adjudication-queue")
def adjudication_queue(db: DbSession, user: CurrentUser, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200)):
    _require_quality_lead(db, user)
    ids = acl.visible_project_ids(db, user)
    stmt = (
        select(Submission).options(joinedload(Submission.task), joinedload(Submission.project),
                                   joinedload(Submission.reviews))
        .where(Submission.status.in_(["under_review", "submitted"]))
        .order_by(Submission.submitted_at)
    )
    if ids is not None:
        if not ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        stmt = stmt.where(Submission.project_id.in_(ids))
    candidates = db.scalars(stmt).unique().all()

    queue = []
    for s in candidates:
        reviews = s.reviews or []
        if _conflicting(reviews) or s.escalated:
            queue.append(s)
    total = len(queue)
    start = (page - 1) * page_size
    items = queue[start:start + page_size]
    blind = user.role != UserRole.SUPER_ADMIN
    return {"items": [_submission_brief(db, s, blind=blind) for s in items],
            "total": total, "page": page, "page_size": page_size}


@router.post("/submissions/{submission_id}/adjudicate")
def adjudicate(submission_id: int, payload: dict, db: DbSession, user: CurrentUser, request: Request):
    _require_quality_lead(db, user)
    s = db.get(Submission, submission_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    try:
        acl.require_project(db, user, s.project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    final = (payload.get("final_decision") or "").strip()
    if final not in ("approved", "rejected", "revision_requested"):
        raise HTTPException(status_code=422, detail="final_decision must be approved, rejected or revision_requested.")
    rationale = (payload.get("rationale") or "").strip()
    if not rationale:
        raise HTTPException(status_code=422, detail="A written rationale is required for adjudications.")

    reviews = _review_decisions(db, s.id)
    if len(reviews) < 2 and not s.escalated:
        raise HTTPException(status_code=400, detail=(
            "Adjudication requires at least two recorded reviews or an escalated submission."))

    existing = db.scalar(select(SubmissionAdjudication).where(SubmissionAdjudication.submission_id == s.id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="This submission has already been adjudicated.")

    final_status = {"approved": "approved", "rejected": "rejected",
                    "revision_requested": "revision_required"}[final]
    s.status = final_status
    s.decided_at = datetime.now(timezone.utc)
    adj = SubmissionAdjudication(
        submission_id=s.id,
        adjudicator_id=user.id,
        final_decision=final,
        rationale=rationale,
        review_ids=[r.id for r in reviews],
    )
    db.add(adj)
    task = db.get(Task, s.task_id)
    if task is not None:
        from sqlalchemy import update
        db.execute(update(Task).where(Task.id == task.id).values(status=final_status))
    db.commit()
    db.refresh(adj)

    log_action(db, user_id=user.id, action="submission.adjudicate", entity_type="submission", entity_id=s.id,
               details={"final_decision": final, "reviews": adj.review_ids}, request=request)
    from app.services import tasks as task_svc
    task_svc.notify(db, s.tester_id, "adjudication_decided",
                    f"Adjudication decision on your submission: {final.replace('_', ' ')}",
                    rationale, entity_type="submission", entity_id=s.id)
    db.commit()
    return {"id": adj.id, "final_decision": adj.final_decision, "submission_status": final_status}


# ------------------------------------------------------------ monitoring

@router.get("/overview")
def quality_overview(db: DbSession, user: CurrentUser):
    _require_quality_lead(db, user)
    ids = acl.visible_project_ids(db, user)

    def base(sub_filters=None):
        stmt = select(Submission.id)
        if sub_filters is not None:
            stmt = stmt.where(*sub_filters)
        if ids is not None:
            stmt = stmt.where(Submission.project_id.in_(ids or [0]))
        return stmt

    total_submissions = db.scalar(select(func.count()).select_from(base().subquery())) or 0
    escalated = db.scalar(select(func.count()).select_from(
        base([Submission.escalated.is_(True)]).subquery())) or 0
    flagged = db.scalar(select(func.count()).select_from(
        base([Submission.flagged_suspicious.is_(True)]).subquery())) or 0
    ambiguous_reviews = db.scalar(select(func.count()).select_from(
        base().join(SubmissionReview, SubmissionReview.submission_id == Submission.id)
        .where(SubmissionReview.ambiguous.is_(True)).subquery())) or 0

    # disagreements: any submission with 2+ reviews, decided or awaiting adjudication
    all_subs = db.scalars(select(Submission).where(
        *([Submission.project_id.in_(ids)] if ids is not None else []),
    ).options(joinedload(Submission.reviews))).unique().all()
    disagreement_items = 0
    multi_review_items = 0
    for s in all_subs:
        reviews = s.reviews or []
        if len(reviews) >= 2:
            multi_review_items += 1
            if _conflicting(reviews):
                disagreement_items += 1

    return {
        "total_submissions": int(total_submissions),
        "escalated": int(escalated),
        "flagged_suspicious": int(flagged),
        "ambiguous_reviews": int(ambiguous_reviews),
        "multi_review_items": multi_review_items,
        "disagreement_items": disagreement_items,
        "disagreement_rate": round(disagreement_items / multi_review_items, 4) if multi_review_items else None,
        "pending_adjudications": int(db.scalar(select(func.count()).select_from(
            base([Submission.status.in_(["submitted", "under_review"])]).subquery())) or 0),
    }


@router.get("/reviewer-consistency")
def reviewer_consistency(db: DbSession, user: CurrentUser):
    """Per-reviewer decision distribution + accuracy against final outcomes."""
    _require_quality_lead(db, user)
    ids = acl.visible_project_ids(db, user)
    stmt = select(SubmissionReview).options(joinedload(SubmissionReview.reviewer))
    if ids is not None:
        stmt = stmt.join(Submission, SubmissionReview.submission_id == Submission.id).where(
            Submission.project_id.in_(ids or [0]))
    reviews = db.scalars(stmt).all()

    by_reviewer: dict[int, list[SubmissionReview]] = {}
    for r in reviews:
        by_reviewer.setdefault(r.reviewer_id, []).append(r)

    out = []
    for rid, revs in by_reviewer.items():
        reviewer = db.get(User, rid)
        decisions = Counter(r.decision for r in revs)
        # accuracy against adjudicated final decisions when available
        compared = 0
        correct = 0
        for r in revs:
            adj = db.scalar(select(SubmissionAdjudication).where(
                SubmissionAdjudication.submission_id == r.submission_id))
            if adj is not None:
                compared += 1
                final = adj.final_decision
                if r.decision == final or (r.decision == "revision_requested" and final == "revision_requested"):
                    correct += 1
        out.append({
            "reviewer_id": rid,
            "name": reviewer.name if reviewer else f"user {rid}",
            "total_reviews": len(revs),
            "decisions": dict(decisions),
            "escalations": sum(1 for r in revs if r.escalated),
            "ambiguous_flags": sum(1 for r in revs if r.ambiguous),
            "compared_to_adjudication": compared,
            "matches_adjudication": round(correct / compared, 4) if compared else None,
        })
    out.sort(key=lambda x: -x["total_reviews"])
    return {"reviewers": out, "note": ("Accuracy is measured only against submissions that were adjudicated; "
                                       "empty when no adjudications exist yet.")}


@router.get("/tester-quality")
def tester_quality(db: DbSession, user: CurrentUser):
    """Tester error analysis: rejection/revision rates and reviewer comments."""
    _require_quality_lead(db, user)
    ids = acl.visible_project_ids(db, user)
    stmt = select(Submission).options(joinedload(Submission.tester))
    if ids is not None:
        stmt = stmt.where(Submission.project_id.in_(ids or [0]))
    submissions = db.scalars(stmt).all()

    per_tester: dict[int, dict] = {}
    for s in submissions:
        entry = per_tester.setdefault(s.tester_id, {
            "tester_id": s.tester_id,
            "name": s.tester.name if s.tester else f"user {s.tester_id}",
            "submitted": 0, "approved": 0, "rejected": 0, "revision_required": 0,
            "resubmissions": 0, "recent_feedback": [],
        })
        entry["submitted"] += 1
        if s.status in entry and s.status != "submitted":
            entry[s.status] += 1
        if s.attempt_number > 1:
            entry["resubmissions"] += 1
        if s.status in ("rejected", "revision_required"):
            for r in s.reviews or []:
                if r.comments:
                    entry["recent_feedback"].append({
                        "submission_id": s.id, "decision": r.decision, "comments": r.comments[:200],
                    })
    out = []
    for entry in per_tester.values():
        decided = entry["approved"] + entry["rejected"]
        entry["approval_rate"] = round(entry["approved"] / decided, 4) if decided else None
        entry["recent_feedback"] = entry["recent_feedback"][-5:]
        out.append(entry)
    out.sort(key=lambda x: -x["submitted"])
    return {"testers": out}


@router.get("/agreement")
def agreement_analysis(db: DbSession, user: CurrentUser, project_id: int | None = None):
    """Inter-reviewer agreement (raw + Fleiss' kappa) over multi-review submissions."""
    _require_quality_lead(db, user)
    stmt = select(Submission)
    ids = acl.visible_project_ids(db, user)
    if ids is not None:
        stmt = stmt.where(Submission.project_id.in_(ids or {0}))
    if project_id:
        stmt = stmt.where(Submission.project_id == project_id)
    submissions = db.scalars(stmt).all()

    multi = {s.id: s.reviews or [] for s in submissions if len(s.reviews or []) >= 2}
    label_set = sorted({r.decision for revs in multi.values() for r in revs})
    matrix = []
    for revs in multi.values():
        row = [0] * len(label_set)
        for r in revs:
            row[label_set.index(r.decision)] += 1
        matrix.append(row)

    full_agreement = sum(1 for revs in multi.values() if len({r.decision for r in revs}) == 1)
    kappa = fleiss_kappa(matrix) if matrix else None
    return {
        "items_with_multiple_reviews": len(multi),
        "full_agreement_items": full_agreement,
        "raw_agreement_rate": round(full_agreement / len(multi), 4) if multi else None,
        "fleiss_kappa": kappa,
        "decision_labels": label_set,
        "note": ("Fleiss' kappa is undefined for single-rating items or degenerate distributions; "
                 "raw percentage agreement is reported alongside for context."),
    }


@router.get("/sample")
def random_quality_sample(db: DbSession, user: CurrentUser, project_id: int | None = None,
                          n: int = Query(5, ge=1, le=50), status: str = "approved"):
    """Random sample of decided submissions for manual quality audits."""
    _require_quality_lead(db, user)
    stmt = select(Submission).options(joinedload(Submission.task), joinedload(Submission.project))
    ids = acl.visible_project_ids(db, user)
    if ids is not None:
        stmt = stmt.where(Submission.project_id.in_(ids or {0}))
    if project_id:
        stmt = stmt.where(Submission.project_id == project_id)
    stmt = stmt.where(Submission.status == status).order_by(func.random()).limit(n)
    items = db.scalars(stmt).unique().all()
    blind = user.role != UserRole.SUPER_ADMIN
    return {"items": [_submission_brief(db, s, blind=blind) for s in items], "sample_size": len(items)}
