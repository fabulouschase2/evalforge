"""Human review workflow: assignment, blind independent reviews, adjudication.

Blind review guarantee: while a reviewer's own assignment is pending, the API
never exposes other reviewers' submissions for the same result to them.
All original assessments are preserved (soft immutability — reviews are never
overwritten; adjudication creates a separate record).
"""
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.review import Adjudication, HumanReview, ReviewAssignment
from app.models.evaluation import EvaluationResult
from app.models.user import User, UserRole


def create_assignments(
    db: Session,
    result_ids: list[int],
    reviewer_ids: list[int],
    assigned_by: int,
    blind: bool = True,
) -> list[ReviewAssignment]:
    reviewers = db.scalars(select(User).where(User.id.in_(reviewer_ids))).all()
    if len(reviewers) != len(set(reviewer_ids)):
        raise HTTPException(status_code=404, detail="One or more reviewers not found.")
    for r in reviewers:
        if r.role not in (UserRole.REVIEWER, UserRole.SENIOR_REVIEWER, UserRole.PROJECT_ADMIN,
                          UserRole.PROJECT_MANAGER, UserRole.SUPER_ADMIN):
            raise HTTPException(status_code=400, detail=f"User {r.email} cannot be assigned reviews.")

    assignments: list[ReviewAssignment] = []
    created = 0
    for result_id in result_ids:
        result = db.get(EvaluationResult, result_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Result {result_id} not found.")
        for reviewer in reviewers:
            if reviewer.id == assigned_by and blind:
                continue  # assigning reviewer excluded from blind review
            existing = db.scalar(
                select(ReviewAssignment).where(
                    ReviewAssignment.result_id == result_id,
                    ReviewAssignment.reviewer_id == reviewer.id,
                )
            )
            if existing:
                continue
            assignment = ReviewAssignment(
                result_id=result_id, reviewer_id=reviewer.id,
                blind=blind, assigned_by=assigned_by, status="pending",
            )
            db.add(assignment)
            assignments.append(assignment)
            created += 1
    db.commit()
    for a in assignments:
        db.refresh(a)
    return assignments


def get_reviews_visible_to(
    db: Session,
    result_id: int,
    reviewer_id: int | None,
) -> list[HumanReview]:
    """Reviews on a result the given reviewer is allowed to see.

    Rule: a reviewer sees other reviews on a result only after their own
    assessment has been submitted (blind review). Reviewers with no assignment
    (adjudicators / admins) see all submitted reviews.
    """
    stmt = select(HumanReview).where(HumanReview.result_id == result_id)
    all_reviews = list(db.scalars(stmt.order_by(HumanReview.submitted_at)).all())
    if reviewer_id is None:
        return all_reviews
    own_assignment = db.scalar(
        select(ReviewAssignment).where(
            ReviewAssignment.result_id == result_id,
            ReviewAssignment.reviewer_id == reviewer_id,
        )
    )
    if own_assignment is None or own_assignment.status == "submitted":
        return all_reviews
    # own review pending: hide everyone else's
    return [r for r in all_reviews if r.reviewer_id == reviewer_id]


def submit_review(
    db: Session,
    assignment: ReviewAssignment,
    payload: dict[str, Any],
) -> HumanReview:
    if assignment.status == "submitted":
        raise HTTPException(status_code=409, detail="Review already submitted. Assessments are immutable.")
    result = db.get(EvaluationResult, assignment.result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Evaluation result not found.")

    criterion_scores = {
        cs["criterion_id"]: {"score": cs["score"], "comment": cs.get("comment")}
        for cs in payload.get("criterion_scores", [])
    }
    label = payload["label"].strip().lower()
    agrees = None
    if result.automated_label in ("pass", "fail") and label in ("pass", "fail"):
        agrees = (label == result.automated_label)

    review = HumanReview(
        assignment_id=assignment.id,
        result_id=assignment.result_id,
        reviewer_id=assignment.reviewer_id,
        criterion_scores=criterion_scores,
        label=label,
        reasoning=payload.get("reasoning"),
        evidence=payload.get("evidence"),
        uncertain=bool(payload.get("uncertain", False)),
        agrees_with_automated=agrees,
    )
    db.add(review)
    assignment.status = "submitted"
    db.commit()
    db.refresh(review)
    return review


def reviews_disagree(reviews: list[HumanReview]) -> bool:
    labels = {r.label for r in reviews}
    return len(labels) > 1


def needs_adjudication(db: Session, result_id: int) -> bool:
    reviews = list(db.scalars(select(HumanReview).where(HumanReview.result_id == result_id)).all())
    existing = db.scalar(select(Adjudication).where(Adjudication.result_id == result_id))
    return existing is None and len(reviews) >= 2 and reviews_disagree(reviews)


def create_adjudication(
    db: Session,
    result: EvaluationResult,
    adjudicator_id: int,
    final_label: str,
    rationale: str,
    final_criterion_scores: dict[str, Any] | None,
) -> Adjudication:
    reviews = list(db.scalars(select(HumanReview).where(HumanReview.result_id == result.id)).all())
    if len(reviews) < 2:
        raise HTTPException(status_code=400, detail="Adjudication requires at least two submitted reviews.")
    adjudication = Adjudication(
        result_id=result.id,
        adjudicator_id=adjudicator_id,
        final_label=final_label.strip().lower(),
        final_criterion_scores=final_criterion_scores or {},
        rationale=rationale,
        review_ids=[r.id for r in reviews],
    )
    db.add(adjudication)
    db.commit()
    db.refresh(adjudication)
    return adjudication
