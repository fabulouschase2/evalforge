"""Review routes: queue, assignment, submission, adjudication, blind-review visibility."""
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.core.security import AdminPM, CurrentUser, DbSession
from app.models.dataset import DatasetRecord
from app.models.evaluation import EvaluationFinding, EvaluationResult, EvaluationRun
from app.models.review import Adjudication, HumanReview, ReviewAssignment
from app.models.user import UserRole
from app.schemas import (
    AdjudicateRequest,
    AssignReviewersRequest,
    AssignmentOut,
    ReviewSubmitRequest,
)
from app.services import reviews as rs
from app.services.audit import log_action

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _result_context(db, result: EvaluationResult) -> dict:
    record = db.get(DatasetRecord, result.dataset_record_id)
    run = db.get(EvaluationRun, result.run_id)
    return {
        "result": result,
        "record": record,
        "run": run,
    }


@router.get("/queue")
def review_queue(db: DbSession, user: CurrentUser):
    """Pending assignments for the current user (their own queue)."""
    assignments = db.scalars(
        select(ReviewAssignment)
        .where(ReviewAssignment.reviewer_id == user.id, ReviewAssignment.status == "pending")
        .order_by(ReviewAssignment.created_at)
    ).all()
    items = []
    for a in assignments:
        result = db.get(EvaluationResult, a.result_id)
        if result is None:
            continue
        run = db.get(EvaluationRun, result.run_id)
        record = db.get(DatasetRecord, result.dataset_record_id)
        items.append({
            "assignment": AssignmentOut.model_validate(a).model_dump(mode="json"),
            "result_id": result.id,
            "record_id": result.record_id,
            "run_id": result.run_id,
            "run_name": run.name if run else None,
            "automated_status": result.status,
            "automated_label": result.automated_label,
            "borderline_category": result.borderline_category,
            "prompt_excerpt": (record.prompt[:200] if record and record.prompt else None),
        })
    return {"items": items, "total": len(items)}


@router.get("/assignments")
def my_assignments(db: DbSession, user: CurrentUser):
    assignments = db.scalars(
        select(ReviewAssignment).where(ReviewAssignment.reviewer_id == user.id).order_by(ReviewAssignment.created_at.desc())
    ).all()
    return [AssignmentOut.model_validate(a).model_dump(mode="json") for a in assignments]


@router.post("/assign")
def assign_reviewers(payload: AssignReviewersRequest, db: DbSession, user: AdminPM, request: Request):
    result_ids = payload.result_ids
    if not result_ids:
        # Assign to all results currently flagged needs_review across completed runs
        flagged = db.scalars(select(EvaluationResult).where(EvaluationResult.needs_review.is_(True))).all()
        result_ids = [r.id for r in flagged]
    assignments = rs.create_assignments(db, result_ids, payload.reviewer_ids, assigned_by=user.id)
    log_action(db, user_id=user.id, action="review.assign", entity_type="review", entity_id=None,
               details={"result_ids": result_ids[:50], "reviewers": payload.reviewer_ids, "created": len(assignments)}, request=request)
    return {"created": len(assignments), "assignments": [AssignmentOut.model_validate(a).model_dump(mode="json") for a in assignments]}


@router.get("/{assignment_id}")
def get_assignment(assignment_id: int, db: DbSession, user: CurrentUser):
    assignment = db.get(ReviewAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    is_owner = assignment.reviewer_id == user.id
    is_supervisor = user.role in UserRole.STAFF
    if not (is_owner or is_supervisor):
        raise HTTPException(status_code=403, detail="You do not have access to this review assignment.")

    result = db.get(EvaluationResult, assignment.result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Evaluation result not found.")
    record = db.get(DatasetRecord, result.dataset_record_id)
    run = db.get(EvaluationRun, result.run_id)
    findings = list(db.scalars(
        select(EvaluationFinding)
        .where(EvaluationFinding.result_id == result.id)
        .order_by(EvaluationFinding.id)
    ).all())

    visible_reviews = rs.get_reviews_visible_to(db, result.id, user.id if is_owner else None)
    own_review = db.scalar(select(HumanReview).where(
        HumanReview.result_id == result.id, HumanReview.reviewer_id == user.id))

    return {
        "assignment": AssignmentOut.model_validate(assignment).model_dump(mode="json"),
        "result": {
            "id": result.id,
            "run_id": result.run_id,
            "record_id": result.record_id,
            "status": result.status,
            "automated_label": result.automated_label,
            "score": result.score,
            "confidence": result.confidence,
            "borderline_category": result.borderline_category,
            "criterion_scores": result.criterion_scores,
            "factuality": result.factuality,
            "summary": result.summary,
            "gold_label": result.gold_label if (is_supervisor or (own_review and own_review.id)) else None,
        },
        "record": {
            "record_id": record.record_id,
            "prompt": record.prompt,
            "response": record.response,
            "reference_answer": record.reference_answer,
            "reference_sources": record.reference_sources or [],
            "metadata": record.record_metadata or {},
        } if record else None,
        "run": {"id": run.id, "name": run.name, "rubric_id": run.rubric_id, "rubric_version_id": run.rubric_version_id} if run else None,
        "findings": [
            {
                "id": f.id, "rule_id": f.rule_id, "rule_name": f.rule_name, "check_type": f.check_type,
                "criterion_id": f.criterion_id, "passed": f.passed, "uncertain": f.uncertain,
                "evidence": f.evidence, "explanation": f.explanation, "severity": f.severity,
                "evaluator_version": f.evaluator_version, "rubric_version": f.rubric_version,
            } for f in findings
        ],
        "visible_reviews": [
            {
                "id": rv.id, "reviewer_id": rv.reviewer_id, "label": rv.label,
                "reasoning": rv.reasoning, "criterion_scores": rv.criterion_scores,
                "uncertain": rv.uncertain, "submitted_at": rv.submitted_at.isoformat(),
            } for rv in visible_reviews
        ],
        "own_review_submitted": assignment.status == "submitted",
        "own_review": {
            "id": own_review.id, "label": own_review.label, "reasoning": own_review.reasoning,
            "criterion_scores": own_review.criterion_scores, "uncertain": own_review.uncertain,
        } if (own_review and own_review.reviewer_id == user.id) else None,
        "adjudication": _adjudication_payload(db, result.id),
    }


def _adjudication_payload(db, result_id: int):
    adj = db.scalar(select(Adjudication).where(Adjudication.result_id == result_id))
    if adj is None:
        return None
    return {
        "id": adj.id, "final_label": adj.final_label, "rationale": adj.rationale,
        "final_criterion_scores": adj.final_criterion_scores, "review_ids": adj.review_ids,
        "created_at": adj.created_at.isoformat(),
    }


@router.post("/{assignment_id}/submit")
def submit_review(assignment_id: int, payload: ReviewSubmitRequest, db: DbSession, user: CurrentUser, request: Request):
    assignment = db.get(ReviewAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    if assignment.reviewer_id != user.id:
        raise HTTPException(status_code=403, detail="You can only submit your own review assignment.")

    review = rs.submit_review(db, assignment, payload.model_dump())
    log_action(db, user_id=user.id, action="review.submit", entity_type="review", entity_id=review.id,
               details={"result_id": review.result_id, "label": review.label, "uncertain": review.uncertain}, request=request)

    if rs.needs_adjudication(db, review.result_id):
        log_action(db, user_id=None, action="review.disagreement_detected", entity_type="result",
                   entity_id=review.result_id, details={"note": "Reviewer labels conflict; adjudication required."}, request=request)
    return {"review_id": review.id, "status": assignment.status}


@router.get("/results/{result_id}/reviews")
def result_reviews(result_id: int, db: DbSession, user: CurrentUser):
    """Submitted reviews visible to the caller (blind-review rules applied)."""
    result = db.get(EvaluationResult, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found.")
    supervisor = user.role in UserRole.STAFF
    visible = rs.get_reviews_visible_to(db, result_id, None if supervisor else user.id)
    return [
        {
            "id": rv.id, "reviewer_id": rv.reviewer_id, "label": rv.label, "reasoning": rv.reasoning,
            "criterion_scores": rv.criterion_scores, "uncertain": rv.uncertain,
            "agrees_with_automated": rv.agrees_with_automated,
            "submitted_at": rv.submitted_at.isoformat(),
        } for rv in visible
    ]


@router.post("/results/{result_id}/adjudicate")
def adjudicate(result_id: int, payload: AdjudicateRequest, db: DbSession, user: AdminPM, request: Request):
    result = db.get(EvaluationResult, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found.")
    scores = {cs.criterion_id: {"score": cs.score, "comment": cs.comment} for cs in payload.final_criterion_scores}
    adjudication = rs.create_adjudication(db, result, user.id, payload.final_label, payload.rationale, scores)
    log_action(db, user_id=user.id, action="review.adjudicate", entity_type="result", entity_id=result_id,
               details={"final_label": adjudication.final_label, "review_ids": adjudication.review_ids}, request=request)
    return {"id": adjudication.id, "final_label": adjudication.final_label}
