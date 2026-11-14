"""Client Portal entities: project requests, messages, deliverables.

Provenance rules:
- project_requests keep every submitted field and the full admin response
  history; converting a request to a project links `converted_project_id`
  without destroying the request.
- client_messages are append-only; `is_internal` messages are staff-only and
  never serialized to client users.
- deliverables record who published what from which dataset version; every
  download is audited.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow

PROJECT_REQUEST_STATUSES = [
    "draft", "submitted", "under_review", "more_info_required",
    "approved", "rejected", "converted",
]

REQUEST_CATEGORIES = [
    "ai_response_evaluation", "data_annotation", "text_classification",
    "factuality_verification", "instruction_following_evaluation",
    "coding_evaluation", "image_annotation", "video_annotation",
    "audio_annotation", "speech_transcription", "multimodal_evaluation",
    "ai_safety_evaluation", "custom_evaluation",
]

MESSAGE_SIDES = ["client", "staff"]


class ProjectRequest(Base):
    __tablename__ = "project_requests"
    __table_args__ = (
        Index("ix_project_requests_org_status", "organization_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # submitted content (all preserved verbatim for conversion)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False,
                                          default="custom_evaluation", index=True)
    evaluation_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expected_task_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_languages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    required_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    dataset_availability: Mapped[str | None] = mapped_column(String(30), nullable=True)
    expected_delivery: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quality_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    special_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{filename, size, path}]

    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False, index=True)
    admin_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    # admin conversation trail (append-only list of {by, role, action, note, at})
    admin_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    organization = relationship("Organization")
    submitter = relationship("User", foreign_keys=[submitted_by])
    converted_project = relationship("Project", foreign_keys=[converted_project_id])


class ClientMessage(Base):
    """Append-only project thread between client members and staff."""
    __tablename__ = "client_messages"
    __table_args__ = (
        Index("ix_client_messages_project", "project_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    sender_side: Mapped[str] = mapped_column(String(10), nullable=False)  # client | staff
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # internal staff notes are never visible to the client organization
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_by_client: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_by_staff: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sender = relationship("User", foreign_keys=[sender_id])


class Deliverable(Base):
    """A published, downloadable result package for the client organization."""
    __tablename__ = "deliverables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    export_format: Mapped[str] = mapped_column(String(20), nullable=False, default="json")  # json|csv|jsonl
    # provenance: which dataset version (if any) the package was generated from
    dataset_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_versions.id"), nullable=True
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")
