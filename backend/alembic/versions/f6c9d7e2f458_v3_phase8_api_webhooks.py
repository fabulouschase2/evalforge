"""v3 phase8: API credentials, request logs, webhooks, idempotency keys

Revision ID: f6c9d7e2f458
Revises: e5b8c6d1e347
Create Date: 2026-11-14

Additive tables only. Idempotent.
"""
import sqlalchemy as sa
from alembic import op

revision = "f6c9d7e2f458"
down_revision = "e5b8c6d1e347"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, index: str) -> bool:
    return index in [i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)]


def upgrade() -> None:
    if not _has_table("api_credentials"):
        op.create_table(
            "api_credentials",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("key_prefix", sa.String(length=12), nullable=False),
            sa.Column("key_hash", sa.String(length=64), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=True),
            sa.Column("project_ids", sa.JSON(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_by", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["revoked_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key_hash"),
        )
        with op.batch_alter_table("api_credentials", schema=None) as batch_op:
            batch_op.create_index("ix_api_credentials_key_prefix", ["key_prefix"], unique=False)
            batch_op.create_index("ix_api_credentials_organization_id", ["organization_id"], unique=False)

    if not _has_table("api_request_logs"):
        op.create_table(
            "api_request_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("credential_id", sa.Integer(), nullable=False),
            sa.Column("method", sa.String(length=10), nullable=False),
            sa.Column("path", sa.String(length=300), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["credential_id"], ["api_credentials.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        if not _has_index("api_request_logs", "ix_api_request_logs_credential"):
            with op.batch_alter_table("api_request_logs", schema=None) as batch_op:
                batch_op.create_index("ix_api_request_logs_credential", ["credential_id", "created_at"], unique=False)

    if not _has_table("webhook_endpoints"):
        op.create_table(
            "webhook_endpoints",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("url", sa.String(length=500), nullable=False),
            sa.Column("secret", sa.String(length=100), nullable=False),
            sa.Column("events", sa.JSON(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("webhook_endpoints", schema=None) as batch_op:
            batch_op.create_index("ix_webhook_endpoints_organization_id", ["organization_id"], unique=False)
            batch_op.create_index("ix_webhook_endpoints_project_id", ["project_id"], unique=False)

    if not _has_table("webhook_deliveries"):
        op.create_table(
            "webhook_deliveries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("endpoint_id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("signature", sa.String(length=200), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("response_code", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["endpoint_id"], ["webhook_endpoints.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("webhook_deliveries", schema=None) as batch_op:
            batch_op.create_index("ix_webhook_deliveries_status", ["status"], unique=False)
            batch_op.create_index("ix_webhook_deliveries_endpoint", ["endpoint_id", "created_at"], unique=False)

    if not _has_table("idempotency_keys"):
        op.create_table(
            "idempotency_keys",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("credential_id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(length=200), nullable=False),
            sa.Column("endpoint", sa.String(length=300), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=True),
            sa.Column("response_status", sa.Integer(), nullable=True),
            sa.Column("response_body", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["credential_id"], ["api_credentials.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        if not _has_index("idempotency_keys", "ix_idempotency_credential"):
            with op.batch_alter_table("idempotency_keys", schema=None) as batch_op:
                batch_op.create_index("ix_idempotency_credential", ["credential_id", "key"], unique=True)


def downgrade() -> None:
    for table in ("idempotency_keys", "webhook_deliveries", "webhook_endpoints",
                  "api_request_logs", "api_credentials"):
        if _has_table(table):
            op.drop_table(table)
