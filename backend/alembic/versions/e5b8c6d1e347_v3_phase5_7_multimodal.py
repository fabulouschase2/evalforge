"""v3 phase5-7: multimodal media assets + image/video/audio annotations

Revision ID: e5b8c6d1e347
Revises: d4a7f5b0c236
Create Date: 2026-11-14

Additive: media_assets + three annotation tables + tasks.media_asset_id.
Idempotent.
"""
import sqlalchemy as sa
from alembic import op

revision = "e5b8c6d1e347"
down_revision = "d4a7f5b0c236"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    return column in [c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)]


def _has_index(table: str, index: str) -> bool:
    return index in [i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)]


def upgrade() -> None:
    # tasks.media_asset_id first (media table created after)
    if not _has_table("media_assets"):
        op.create_table(
            "media_assets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("uploader_id", sa.Integer(), nullable=True),
            sa.Column("media_type", sa.String(length=20), nullable=False),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("storage_key", sa.String(length=500), nullable=False),
            sa.Column("mime_type", sa.String(length=100), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
            sa.Column("annotation_config", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["uploader_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("media_assets", schema=None) as batch_op:
            batch_op.create_index("ix_media_assets_project_id", ["project_id"], unique=False)
            batch_op.create_index("ix_media_assets_project", ["project_id", "media_type"], unique=False)

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        if not _has_column("tasks", "media_asset_id"):
            batch_op.add_column(sa.Column("media_asset_id", sa.Integer(), nullable=True))
    if not _has_index("tasks", "ix_tasks_media_asset_id"):
        op.create_index("ix_tasks_media_asset_id", "tasks", ["media_asset_id"], unique=False)

    if not _has_table("image_annotations"):
        op.create_table(
            "image_annotations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("media_asset_id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("submission_id", sa.Integer(), nullable=True),
            sa.Column("worker_id", sa.Integer(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("shapes", sa.JSON(), nullable=False),
            sa.Column("labels", sa.JSON(), nullable=True),
            sa.Column("image_width", sa.Integer(), nullable=True),
            sa.Column("image_height", sa.Integer(), nullable=True),
            sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"]),
            sa.ForeignKeyConstraint(["worker_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for idx, cols in (
            ("ix_image_annotations_media_asset_id", ["media_asset_id"]),
            ("ix_image_annotations_media", ["media_asset_id"]),
            ("ix_image_annotations_task_id", ["task_id"]),
            ("ix_image_annotations_task", ["task_id"]),
        ):
            if not _has_index("image_annotations", idx):
                with op.batch_alter_table("image_annotations", schema=None) as batch_op:
                    batch_op.create_index(idx, cols, unique=False)

    if not _has_table("video_annotations"):
        op.create_table(
            "video_annotations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("media_asset_id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("submission_id", sa.Integer(), nullable=True),
            sa.Column("worker_id", sa.Integer(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("events", sa.JSON(), nullable=False),
            sa.Column("frame_labels", sa.JSON(), nullable=True),
            sa.Column("sampling_config", sa.JSON(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"]),
            sa.ForeignKeyConstraint(["worker_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for idx, cols in (
            ("ix_video_annotations_media_asset_id", ["media_asset_id"]),
            ("ix_video_annotations_media", ["media_asset_id"]),
            ("ix_video_annotations_task_id", ["task_id"]),
            ("ix_video_annotations_task", ["task_id"]),
        ):
            if not _has_index("video_annotations", idx):
                with op.batch_alter_table("video_annotations", schema=None) as batch_op:
                    batch_op.create_index(idx, cols, unique=False)

    if not _has_table("audio_annotations"):
        op.create_table(
            "audio_annotations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("media_asset_id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("submission_id", sa.Integer(), nullable=True),
            sa.Column("worker_id", sa.Integer(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("segments", sa.JSON(), nullable=False),
            sa.Column("global_labels", sa.JSON(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"]),
            sa.ForeignKeyConstraint(["worker_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for idx, cols in (
            ("ix_audio_annotations_media_asset_id", ["media_asset_id"]),
            ("ix_audio_annotations_media", ["media_asset_id"]),
            ("ix_audio_annotations_task_id", ["task_id"]),
            ("ix_audio_annotations_task", ["task_id"]),
        ):
            if not _has_index("audio_annotations", idx):
                with op.batch_alter_table("audio_annotations", schema=None) as batch_op:
                    batch_op.create_index(idx, cols, unique=False)


def downgrade() -> None:
    for table in ("audio_annotations", "video_annotations", "image_annotations"):
        if _has_table(table):
            op.drop_table(table)
    if _has_index("tasks", "ix_tasks_media_asset_id"):
        op.drop_index("ix_tasks_media_asset_id", table_name="tasks")
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        if _has_column("tasks", "media_asset_id"):
            batch_op.drop_column("media_asset_id")
    if _has_table("media_assets"):
        op.drop_table("media_assets")
