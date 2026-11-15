"""v3.1: performance indexes

Revision ID: a7b8c9d0e123
Revises: f6c9d7e2f458
Create Date: 2026-11-14

Two composite indexes for the hottest polling/join queries:
- webhook_deliveries (status, next_retry_at): the delivery worker's due scan
- golden_task_results (golden_task_id): report joins from task -> result rows
Idempotent.
"""
import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e123"
down_revision = "f6c9d7e2f458"
branch_labels = None
depends_on = None


def _has_index(table: str, index: str) -> bool:
    return index in [i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)]


def upgrade() -> None:
    if not _has_index("webhook_deliveries", "ix_webhook_deliveries_status_retry"):
        with op.batch_alter_table("webhook_deliveries", schema=None) as batch_op:
            batch_op.create_index("ix_webhook_deliveries_status_retry",
                                  ["status", "next_retry_at"], unique=False)
    if not _has_index("golden_task_results", "ix_golden_task_results_golden_task_id"):
        with op.batch_alter_table("golden_task_results", schema=None) as batch_op:
            batch_op.create_index("ix_golden_task_results_golden_task_id",
                                  ["golden_task_id"], unique=False)


def downgrade() -> None:
    if _has_index("golden_task_results", "ix_golden_task_results_golden_task_id"):
        op.drop_index("ix_golden_task_results_golden_task_id", table_name="golden_task_results")
    if _has_index("webhook_deliveries", "ix_webhook_deliveries_status_retry"):
        op.drop_index("ix_webhook_deliveries_status_retry", table_name="webhook_deliveries")
