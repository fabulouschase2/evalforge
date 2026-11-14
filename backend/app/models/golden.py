"""Golden tasks: known-answer quality probes hidden inside worker queues.

Rules enforced by services (never in the client):
- the reference answer is immutable per version; edits create a new version;
- `is_golden` and all reference fields are NEVER serialized to tester-facing
  payloads — a tester cannot identify a golden task;
- every scored attempt appends a golden_task_results row (history preserved).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Float, Integer, JSON, String, Text, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow

SCORING_METHODS = [
    "exact",              # case/whitespace-normalized exact match
    "variations",         # exact match against accepted_variations list
    "numeric_tolerance",  # numeric compare with config.tolerance
    "single_label",       # label against config.labels (case-insensitive)
    "multi_label",        # set match with optional config.allow_partial
    "contains_keywords",  # all config.keywords present (order-insensitive)
]
DIFFICULTIES = ["easy", "medium", "hard", "expert"]

ALERT_TYPES = [
    "low_accuracy",           # worker accuracy below threshold over window
    "repeated_failures",      # N consecutive failed golden tasks
    "sudden_decline",         # accuracy drop vs prior window
    "repeated_identical",     # identical responses across distinct tasks
    "excessive_speed",        # completions faster than plausible threshold
]


class GoldenTask(Base):
    __tablename__ = "golden_tasks"
    __table_args__ = (
        Index("ix_golden_tasks_project", "project_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_records.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reference_answer: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # accepted_variations: list of alternative answers (strings or label lists)
    accepted_variations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scoring_method: Mapped[str] = mapped_column(String(30), nullable=False, default="exact")
    scoring_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions = relationship(
        "GoldenTaskVersion", back_populates="golden_task",
        cascade="all, delete-orphan", order_by="GoldenTaskVersion.version",
    )


class GoldenTaskVersion(Base):
    """Append-only reference-answer history (the current value lives on the task)."""
    __tablename__ = "golden_task_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    golden_task_id: Mapped[int] = mapped_column(
        ForeignKey("golden_tasks.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_answer: Mapped[dict] = mapped_column(JSON, nullable=False)
    accepted_variations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scoring_method: Mapped[str] = mapped_column(String(30), nullable=False)
    scoring_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    golden_task = relationship("GoldenTask", back_populates="versions")


class GoldenTaskResult(Base):
    """One row per scored attempt — immutable, append-only."""
    __tablename__ = "golden_task_results"
    __table_args__ = (
        Index("ix_golden_results_worker", "worker_id", "scored_at"),
        Index("ix_golden_results_project", "project_id", "scored_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    golden_task_id: Mapped[int] = mapped_column(ForeignKey("golden_tasks.id"), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False, index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    golden_task_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scoring_method: Mapped[str] = mapped_column(String(30), nullable=False)
    scored_answer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualityAlert(Base):
    """Configurable-threshold alert. Indicators only — never auto-suspensions."""
    __tablename__ = "quality_alerts"
    __table_args__ = (
        Index("ix_quality_alerts_open", "project_id", "resolved"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="warning", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
