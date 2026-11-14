"""Submissions (tester work) and their review/adjudication history.

Rules enforced by services, guaranteed by schema:
- one row per (task, attempt); attempt increments only via authorized reopens
- review decisions are append-only: a new decision inserts a new row
- adjudications reference the exact review ids they considered
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow

SUBMISSION_STATUSES = [
    "submitted", "under_review", "approved", "rejected", "revision_required",
]
REVIEW_DECISIONS = ["approved", "rejected", "revision_requested"]


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_submission_task_attempt"),
        Index("ix_submissions_project_status", "project_id", "status"),
        Index("ix_submissions_tester", "tester_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    tester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False, index=True)
    # validated rubric-form answers
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # list of {kind: url|text, value: str, note: str|null}
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # traceability pins
    rubric_version_id: Mapped[int | None] = mapped_column(ForeignKey("rubric_versions.id"), nullable=True)
    dataset_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_versions.id"), nullable=True
    )
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flagged_suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task = relationship("Task", back_populates="submissions")
    project = relationship("Project")
    tester = relationship("User", foreign_keys=[tester_id])
    rubric_version = relationship("RubricVersion")
    reviews = relationship(
        "SubmissionReview", back_populates="submission", cascade="all, delete-orphan",
        order_by="SubmissionReview.created_at",
    )
    adjudication = relationship(
        "SubmissionAdjudication", back_populates="submission",
        uselist=False, cascade="all, delete-orphan",
    )


class SubmissionReview(Base):
    """Append-only reviewer decision. Never updated after creation."""
    __tablename__ = "submission_reviews"
    __table_args__ = (Index("ix_submission_reviews_submission", "submission_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_labels: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    flagged_suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    blind: Mapped[bool] = mapped_column(Boolean, default=True)
    rubric_version_id: Mapped[int | None] = mapped_column(ForeignKey("rubric_versions.id"), nullable=True)
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    submission = relationship("Submission", back_populates="reviews")
    reviewer = relationship("User", foreign_keys=[reviewer_id])


class SubmissionAdjudication(Base):
    __tablename__ = "submission_adjudications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False, index=True)
    adjudicator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    final_decision: Mapped[str] = mapped_column(String(30), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    review_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    submission = relationship("Submission", back_populates="adjudication")
    adjudicator = relationship("User", foreign_keys=[adjudicator_id])
