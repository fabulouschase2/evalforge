"""Worker qualification assessments, attempts and skill profiles.

Statuses (attempt): not_started | in_progress | submitted | passed | failed
                    | under_review | expired
Auto-grading covers mcq / multi_select / numeric; text and code answers route
to the manual grading queue (under_review) for a quality lead / staff grade.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Float, Integer, JSON, String, Text, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow

ASSESSMENT_TYPES = [
    "mcq", "text_grading", "coding", "annotation_exercise", "factuality",
    "instruction_following", "custom_rubric",
]
QUESTION_TYPES = ["mcq", "multi_select", "numeric", "text", "code"]
ATTEMPT_STATUSES = [
    "in_progress", "submitted", "passed", "failed", "under_review", "expired",
]
SKILL_SOURCES = ["self_reported", "verified"]

SKILL_CATALOG = [
    "AI response evaluation", "Factuality verification", "Software engineering",
    "Python", "JavaScript", "Coding evaluation", "Data annotation",
    "Text classification", "Image annotation", "Video annotation",
    "Audio annotation", "Data classification", "Language evaluation",
    "Safety evaluation", "Instruction-following evaluation",
]


class QualificationAssessment(Base):
    __tablename__ = "qualification_assessments"
    __table_args__ = (Index("ix_qual_assessments_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment_type: Mapped[str] = mapped_column(String(40), default="mcq", nullable=False)
    skill_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    passing_score: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    randomize_questions: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # null project_id = platform-wide qualification
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    questions = relationship(
        "QualificationQuestion", back_populates="assessment",
        cascade="all, delete-orphan", order_by="QualificationQuestion.order",
    )


class QualificationQuestion(Base):
    __tablename__ = "qualification_questions"
    __table_args__ = (Index("ix_qual_questions_assessment", "assessment_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("qualification_assessments.id"), nullable=False
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_type: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # correct_answer: {value: ...} — never serialized to workers
    correct_answer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    points: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment = relationship("QualificationAssessment", back_populates="questions")


class QualificationAttempt(Base):
    __tablename__ = "qualification_attempts"
    __table_args__ = (
        Index("ix_qual_attempts_worker", "worker_id", "status"),
        Index("ix_qual_attempts_assessment", "assessment_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("qualification_assessments.id"), nullable=False
    )
    worker_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # {question_id: answer}
    answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    auto_graded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    graded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assessment = relationship("QualificationAssessment")


class WorkerSkill(Base):
    """Self-reported skills are distinguished from verified ones forever."""
    __tablename__ = "worker_skills"
    __table_args__ = (
        Index("ix_worker_skills_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    skill: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="self_reported", nullable=False)
    level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evidence_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("qualification_assessments.id"), nullable=True
    )
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectEligibilityOverride(Base):
    """Admin-granted exceptions to project eligibility, with recorded reason."""
    __tablename__ = "project_eligibility_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    granted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
