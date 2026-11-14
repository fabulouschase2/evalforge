"""Projects, project membership and per-project access control."""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow, UserRole

PROJECT_TYPES = [
    "ai_response_evaluation", "data_annotation", "text_classification",
    "factuality_verification", "instruction_following_evaluation",
    "coding_evaluation", "image_annotation", "video_annotation",
    "audio_evaluation", "safety_evaluation", "custom_evaluation",
]
PROJECT_STATUSES = ["draft", "active", "paused", "completed", "archived"]

# Platform roles allowed to *work on* a project as members
MEMBER_ROLES = {
    "admin": UserRole.STAFF,          # manage project: tasks, membership, datasets
    "tester": [UserRole.TESTER],      # claim and complete tasks
    "reviewer": [UserRole.REVIEWER, UserRole.SENIOR_REVIEWER],  # review submissions
}


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # --- v2 extension (all nullable to stay backward compatible) ---
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    client: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_type: Mapped[str] = mapped_column(String(50), default="ai_response_evaluation", index=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    supported_languages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    quality_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_task_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blind_review: Mapped[bool] = mapped_column(Boolean, default=True)
    # v3 golden task queue configuration (percentage/fixed/spacing/thresholds)
    golden_task_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # v3 worker eligibility requirements (assessments min scores, verified skills)
    eligibility_requirements: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_demo: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    owner = relationship("User", foreign_keys=[owner_id])
    organization = relationship("Organization", foreign_keys=[organization_id])
    members = relationship(
        "ProjectMember", back_populates="project", cascade="all, delete-orphan"
    )

    def is_admin_of(self, user_id: int) -> bool:
        """Owner or explicit admin member."""
        if self.owner_id == user_id:
            return True
        return any(
            m.user_id == user_id and m.role == "admin" for m in (self.members or [])
        )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        Index("ix_project_members_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # admin | tester | reviewer
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
