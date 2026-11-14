"""Datasets, immutable versions and normalized evaluation records."""
from datetime import datetime

from sqlalchemy import (
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


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # csv | json | jsonl
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="json")
    source_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_demo: Mapped[bool] = mapped_column(default=False, index=True)
    # active | archived — archived datasets are read-only and hidden from task generation
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    # custom collection fields defined per dataset: [{key, label, type, required}]
    custom_field_definitions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions = relationship(
        "DatasetVersion", back_populates="dataset", cascade="all, delete-orphan",
        order_by="DatasetVersion.version_number",
    )
    records = relationship("DatasetRecord", back_populates="dataset", cascade="all, delete-orphan")


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    dataset = relationship("Dataset", back_populates="versions")


class DatasetRecord(Base):
    __tablename__ = "dataset_records"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "record_id", name="uq_version_record_id"),
        Index("ix_dataset_records_dataset_version", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), nullable=False, index=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_versions.id"), nullable=False
    )
    record_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expected_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gold_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    # --- v2 collection extension (all nullable) ---
    supporting_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    difficulty_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True, default="en")
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # collected | verified | flagged
    collection_status: Mapped[str | None] = mapped_column(String(30), default="collected", index=True)
    custom_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    dataset = relationship("Dataset", back_populates="records")
    version = relationship("DatasetVersion")
