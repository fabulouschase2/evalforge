"""Evaluation runs, per-record results and immutable findings."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), nullable=False, index=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id"), nullable=False)
    rubric_id: Mapped[int] = mapped_column(ForeignKey("rubrics.id"), nullable=False, index=True)
    rubric_version_id: Mapped[int] = mapped_column(ForeignKey("rubric_versions.id"), nullable=False)
    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    borderline_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_review_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dataset = relationship("Dataset")
    dataset_version = relationship("DatasetVersion")
    rubric = relationship("Rubric")
    rubric_version = relationship("RubricVersion")
    results = relationship("EvaluationResult", back_populates="run", cascade="all, delete-orphan")


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        Index("ix_results_run_status", "run_id", "status"),
        Index("ix_results_needs_review", "run_id", "needs_review"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id"), nullable=False)
    dataset_record_id: Mapped[int] = mapped_column(ForeignKey("dataset_records.id"), nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # pass | fail | borderline
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    automated_label: Mapped[str] = mapped_column(String(20), nullable=False)
    gold_label: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    borderline_category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    criterion_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    factuality: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run = relationship("EvaluationRun", back_populates="results")
    record = relationship("DatasetRecord")
    findings = relationship("EvaluationFinding", back_populates="result", cascade="all, delete-orphan")
    assignments = relationship("ReviewAssignment", back_populates="result", cascade="all, delete-orphan")
    reviews = relationship("HumanReview", back_populates="result", cascade="all, delete-orphan")


class EvaluationFinding(Base):
    __tablename__ = "evaluation_findings"
    __table_args__ = (Index("ix_findings_result", "result_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("evaluation_results.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    check_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    criterion_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    passed: Mapped[bool | None] = mapped_column(nullable=True)  # None = inconclusive
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    evaluator_version: Mapped[str] = mapped_column(String(50), nullable=False)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    result = relationship("EvaluationResult", back_populates="findings")
