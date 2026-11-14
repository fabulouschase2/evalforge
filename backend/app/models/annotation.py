"""Multimodal annotation: media assets and per-modality annotation stores.

All coordinates are stored NORMALIZED (0..1) relative to the original media
dimensions so annotations stay accurate at any display size; export
converters materialize absolute pixels / COCO / YOLO on demand.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Float, Integer, JSON, String, Text, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow

MEDIA_TYPES = ["image", "video", "audio"]
MEDIA_STATUSES = ["ready", "processing", "failed"]

IMAGE_SHAPES = ["bbox", "polygon", "point"]

# allowed upload mime types per media type
ALLOWED_MEDIA = {
    "image": {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"},
    "video": {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"},
    "audio": {"audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/wave": ".wav",
              "audio/x-wav": ".wav", "audio/ogg": ".ogg", "audio/webm": ".webm",
              "audio/mp4": ".m4a"},
}


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (Index("ix_media_assets_project", "project_id", "media_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ready", nullable=False)
    # per-project annotation requirements snapshot (labels, sampling config)
    annotation_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")


class ImageAnnotation(Base):
    """Versioned image annotation. One row per save; latest = current."""
    __tablename__ = "image_annotations"
    __table_args__ = (
        Index("ix_image_annotations_media", "media_asset_id"),
        Index("ix_image_annotations_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_asset_id: Mapped[int] = mapped_column(ForeignKey("media_assets.id"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id"), nullable=True)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # [{type: bbox|polygon|point, label, points: [[x,y],...], width?, height?}] normalized
    shapes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    labels: Mapped[list | None] = mapped_column(JSON, nullable=True)  # classification labels
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoAnnotation(Base):
    __tablename__ = "video_annotations"
    __table_args__ = (
        Index("ix_video_annotations_media", "media_asset_id"),
        Index("ix_video_annotations_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_asset_id: Mapped[int] = mapped_column(ForeignKey("media_assets.id"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id"), nullable=True)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # events: [{label, start_ms, end_ms, frames: [{time_ms, shapes: [...]}]}]
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    frame_labels: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{time_ms, label}]
    sampling_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AudioAnnotation(Base):
    __tablename__ = "audio_annotations"
    __table_args__ = (
        Index("ix_audio_annotations_media", "media_asset_id"),
        Index("ix_audio_annotations_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_asset_id: Mapped[int] = mapped_column(ForeignKey("media_assets.id"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id"), nullable=True)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # segments: [{start_ms, end_ms, transcript, speaker, language, emotion, labels}]
    segments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    global_labels: Mapped[list | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
