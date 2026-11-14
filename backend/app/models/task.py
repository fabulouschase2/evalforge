"""Tasks: units of work generated from dataset records or created manually.

Status lifecycle:
  draft -> available -> assigned -> in_progress -> submitted -> under_review
        -> approved | rejected | revision_required -> (resubmit) under_review ...
  available/assigned/in_progress can be cancelled; assigned tasks expire and
  return to available when assignment_expires_at passes.

Claiming uses an atomic conditional UPDATE so two workers can never claim the
same exclusive task, regardless of backend (SQLite / PostgreSQL).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, Index, CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow

TASK_STATUSES = [
    "draft", "available", "assigned", "in_progress", "submitted", "under_review",
    "revision_required", "approved", "rejected", "cancelled",
]
CLAIMABLE_STATUSES = ["available"]
ACTIVE_WORK_STATUSES = ["assigned", "in_progress"]
REVIEWABLE_STATUSES = ["submitted", "under_review"]
REOPEN_STATUSES = ["revision_required", "rejected"]

TASK_PRIORITIES = ["low", "normal", "high", "urgent"]
TASK_DIFFICULTIES = ["easy", "medium", "hard", "expert"]


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("max_attempts >= 1", name="ck_task_max_attempts"),
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_assignee", "assigned_tester_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    dataset_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_records.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), default="ai_response_evaluation", index=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    # rubric pinned at creation (form + automated criteria)
    rubric_id: Mapped[int | None] = mapped_column(ForeignKey("rubrics.id"), nullable=True)
    rubric_version_id: Mapped[int | None] = mapped_column(ForeignKey("rubric_versions.id"), nullable=True)
    # JSON array of required form-field ids the tester must complete
    required_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # autosave payload for the current attempt
    draft_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # current exclusive assignment
    assigned_tester_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignment_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # --- v3 golden task quality control (hidden from tester serialization) ---
    is_golden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    golden_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("golden_tasks.id"), nullable=True
    )
    # --- v3 multimodal annotation ---
    media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id"), nullable=True, index=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project = relationship("Project")
    record = relationship("DatasetRecord")
    rubric = relationship("Rubric")
    rubric_version = relationship("RubricVersion")
    tester = relationship("User", foreign_keys=[assigned_tester_id])
    assignments = relationship(
        "TaskAssignment", back_populates="task", cascade="all, delete-orphan",
        order_by="TaskAssignment.assigned_at",
    )
    submissions = relationship(
        "Submission", back_populates="task", cascade="all, delete-orphan",
        order_by="Submission.attempt_number",
    )


class TaskAssignment(Base):
    """Immutable history of who worked a task and when (audit + reassignment)."""
    __tablename__ = "task_assignments"
    __table_args__ = (Index("ix_task_assignments_task", "task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # assigned | self_claimed | released | expired | reassigned
    action: Mapped[str] = mapped_column(String(30), default="assigned", nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task = relationship("Task", back_populates="assignments")
    user = relationship("User", foreign_keys=[user_id])
