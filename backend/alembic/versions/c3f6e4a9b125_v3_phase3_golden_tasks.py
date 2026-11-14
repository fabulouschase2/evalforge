"""v3 phase3: golden tasks + quality alerts + project golden config

Revision ID: c3f6e4a9b125
Revises: b2e5d3f8a014
Create Date: 2026-11-14

Additive: four new tables + nullable/defaulted columns on tasks and projects.
Idempotent (safe on create_all-based dev databases).
"""
import sqlalchemy as sa
from alembic import op

revision = "c3f6e4a9b125"
down_revision = "b2e5d3f8a014"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    return column in [c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)]


def _has_index(table: str, index: str) -> bool:
    return index in [i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)]


def upgrade() -> None:
    # --- tasks: golden columns ---
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        if not _has_column("tasks", "is_golden"):
            batch_op.add_column(sa.Column("is_golden", sa.Boolean(), nullable=False,
                                          server_default=sa.false()))
        if not _has_column("tasks", "golden_task_id"):
            batch_op.add_column(sa.Column("golden_task_id", sa.Integer(), nullable=True))
    if not _has_index("tasks", "ix_tasks_is_golden"):
        op.create_index("ix_tasks_is_golden", "tasks", ["is_golden"], unique=False)

    # --- projects: golden config + eligibility ---
    with op.batch_alter_table("projects", schema=None) as batch_op:
        if not _has_column("projects", "golden_task_config"):
            batch_op.add_column(sa.Column("golden_task_config", sa.JSON(), nullable=True))
        if not _has_column("projects", "eligibility_requirements"):
            batch_op.add_column(sa.Column("eligibility_requirements", sa.JSON(), nullable=True))

    # --- golden_tasks ---
    if not _has_table("golden_tasks"):
        op.create_table(
            "golden_tasks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("source_record_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("instructions", sa.Text(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("reference_answer", sa.JSON(), nullable=False),
            sa.Column("accepted_variations", sa.JSON(), nullable=True),
            sa.Column("scoring_method", sa.String(length=30), nullable=False, server_default="exact"),
            sa.Column("scoring_config", sa.JSON(), nullable=True),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.Column("difficulty", sa.String(length=20), nullable=False, server_default="medium"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["source_record_id"], ["dataset_records.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("golden_tasks", schema=None) as batch_op:
            batch_op.create_index("ix_golden_tasks_project_id", ["project_id"], unique=False)
            batch_op.create_index("ix_golden_tasks_difficulty", ["difficulty"], unique=False)
            batch_op.create_index("ix_golden_tasks_project", ["project_id", "is_active"], unique=False)

    # --- golden_task_versions ---
    if not _has_table("golden_task_versions"):
        op.create_table(
            "golden_task_versions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("golden_task_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("reference_answer", sa.JSON(), nullable=False),
            sa.Column("accepted_variations", sa.JSON(), nullable=True),
            sa.Column("scoring_method", sa.String(length=30), nullable=False),
            sa.Column("scoring_config", sa.JSON(), nullable=True),
            sa.Column("changed_by", sa.Integer(), nullable=True),
            sa.Column("change_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["golden_task_id"], ["golden_tasks.id"]),
            sa.ForeignKeyConstraint(["changed_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("golden_task_versions", schema=None) as batch_op:
            batch_op.create_index("ix_golden_task_versions_golden_task_id", ["golden_task_id"], unique=False)

    # --- golden_task_results ---
    if not _has_table("golden_task_results"):
        op.create_table(
            "golden_task_results",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("golden_task_id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("submission_id", sa.Integer(), nullable=False),
            sa.Column("worker_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("golden_task_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("scoring_method", sa.String(length=30), nullable=False),
            sa.Column("scored_answer", sa.JSON(), nullable=True),
            sa.Column("score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("failure_reasons", sa.JSON(), nullable=True),
            sa.Column("time_spent_seconds", sa.Integer(), nullable=True),
            sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["golden_task_id"], ["golden_tasks.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"]),
            sa.ForeignKeyConstraint(["worker_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("golden_task_results", schema=None) as batch_op:
            batch_op.create_index("ix_golden_task_results_task_id", ["task_id"], unique=False)
            batch_op.create_index("ix_golden_task_results_submission_id", ["submission_id"], unique=False)
            batch_op.create_index("ix_golden_results_worker", ["worker_id", "scored_at"], unique=False)
            batch_op.create_index("ix_golden_results_project", ["project_id", "scored_at"], unique=False)

    # --- quality_alerts ---
    if not _has_table("quality_alerts"):
        op.create_table(
            "quality_alerts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("worker_id", sa.Integer(), nullable=True),
            sa.Column("alert_type", sa.String(length=40), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False, server_default="warning"),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=True),
            sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("resolved_by", sa.Integer(), nullable=True),
            sa.Column("resolution_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["worker_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("quality_alerts", schema=None) as batch_op:
            batch_op.create_index("ix_quality_alerts_project_id", ["project_id"], unique=False)
            batch_op.create_index("ix_quality_alerts_worker_id", ["worker_id"], unique=False)
            batch_op.create_index("ix_quality_alerts_open", ["project_id", "resolved"], unique=False)


def downgrade() -> None:
    if _has_table("quality_alerts"):
        op.drop_table("quality_alerts")
    if _has_table("golden_task_results"):
        op.drop_table("golden_task_results")
    if _has_table("golden_task_versions"):
        op.drop_table("golden_task_versions")
    if _has_table("golden_tasks"):
        op.drop_table("golden_tasks")
    with op.batch_alter_table("projects", schema=None) as batch_op:
        if _has_column("projects", "eligibility_requirements"):
            batch_op.drop_column("eligibility_requirements")
        if _has_column("projects", "golden_task_config"):
            batch_op.drop_column("golden_task_config")
    if _has_index("tasks", "ix_tasks_is_golden"):
        op.drop_index("ix_tasks_is_golden", table_name="tasks")
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        if _has_column("tasks", "golden_task_id"):
            batch_op.drop_column("golden_task_id")
        if _has_column("tasks", "is_golden"):
            batch_op.drop_column("is_golden")
