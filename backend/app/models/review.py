"""Review assignments, independent human reviews and adjudications."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow


class ReviewAssignment(Base):
    __tablename__ = "review_assignments"
    __table_args__ = (
        UniqueConstraint("result_id", "reviewer_id", name="uq_assignment_result_reviewer"),
        Index("ix_assignments_reviewer_status", "reviewer_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("evaluation_results.id"), nullable=False, index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # pending | submitted
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    blind: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    result = relationship("EvaluationResult", back_populates="assignments")
    reviewer = relationship("User", foreign_keys=[reviewer_id])


class HumanReview(Base):
    __tablename__ = "human_reviews"
    __table_args__ = (UniqueConstraint("assignment_id", name="uq_review_assignment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("review_assignments.id"), nullable=False)
    result_id: Mapped[int] = mapped_column(ForeignKey("evaluation_results.id"), nullable=False, index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    criterion_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # pass | fail | partially_correct | ...
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    agrees_with_automated: Mapped[bool | None] = mapped_column(nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assignment = relationship("ReviewAssignment")
    result = relationship("EvaluationResult", back_populates="reviews")
    reviewer = relationship("User", foreign_keys=[reviewer_id])


class Adjudication(Base):
    __tablename__ = "adjudications"
    __table_args__ = (Index("ix_adjudications_result", "result_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("evaluation_results.id"), nullable=False)
    adjudicator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    final_label: Mapped[str] = mapped_column(String(50), nullable=False)
    final_criterion_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    adjudicator = relationship("User", foreign_keys=[adjudicator_id])
