"""v3 phase2: client portal (project requests, messages, deliverables)

Revision ID: b2e5d3f8a014
Revises: a1f4c2d7e903
Create Date: 2026-11-13

Entirely additive: three new tables, no changes to existing ones.
Idempotent (skips tables that already exist from create_all-based dev setups).
"""
import sqlalchemy as sa
from alembic import op

revision = "b2e5d3f8a014"
down_revision = "a1f4c2d7e903"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("project_requests"):
        op.create_table(
            "project_requests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("submitted_by", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=50), nullable=False, server_default="custom_evaluation"),
            sa.Column("evaluation_types", sa.JSON(), nullable=True),
            sa.Column("expected_task_volume", sa.Integer(), nullable=True),
            sa.Column("required_languages", sa.JSON(), nullable=True),
            sa.Column("required_skills", sa.JSON(), nullable=True),
            sa.Column("dataset_availability", sa.String(length=30), nullable=True),
            sa.Column("expected_delivery", sa.DateTime(timezone=True), nullable=True),
            sa.Column("quality_requirements", sa.Text(), nullable=True),
            sa.Column("special_instructions", sa.Text(), nullable=True),
            sa.Column("attachments", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="submitted"),
            sa.Column("admin_response", sa.Text(), nullable=True),
            sa.Column("admin_history", sa.JSON(), nullable=True),
            sa.Column("reviewed_by", sa.Integer(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("converted_project_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["submitted_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["converted_project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("project_requests", schema=None) as batch_op:
            batch_op.create_index("ix_project_requests_organization_id", ["organization_id"], unique=False)
            batch_op.create_index("ix_project_requests_category", ["category"], unique=False)
            batch_op.create_index("ix_project_requests_status", ["status"], unique=False)
            batch_op.create_index("ix_project_requests_org_status", ["organization_id", "status"], unique=False)

    if not _has_table("client_messages"):
        op.create_table(
            "client_messages",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("sender_id", sa.Integer(), nullable=False),
            sa.Column("sender_side", sa.String(length=10), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("attachment_path", sa.String(length=500), nullable=True),
            sa.Column("attachment_name", sa.String(length=255), nullable=True),
            sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("read_by_client", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("read_by_staff", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("client_messages", schema=None) as batch_op:
            batch_op.create_index("ix_client_messages_project_id", ["project_id"], unique=False)
            batch_op.create_index("ix_client_messages_organization_id", ["organization_id"], unique=False)
            batch_op.create_index("ix_client_messages_project", ["project_id", "created_at"], unique=False)

    if not _has_table("deliverables"):
        op.create_table(
            "deliverables",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("export_format", sa.String(length=20), nullable=False, server_default="json"),
            sa.Column("dataset_version_id", sa.Integer(), nullable=True),
            sa.Column("file_path", sa.String(length=500), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
            sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("published_by", sa.Integer(), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
            sa.ForeignKeyConstraint(["published_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("deliverables", schema=None) as batch_op:
            batch_op.create_index("ix_deliverables_project_id", ["project_id"], unique=False)
            batch_op.create_index("ix_deliverables_organization_id", ["organization_id"], unique=False)


def downgrade() -> None:
    if _has_table("deliverables"):
        op.drop_table("deliverables")
    if _has_table("client_messages"):
        op.drop_table("client_messages")
    if _has_table("project_requests"):
        op.drop_table("project_requests")
