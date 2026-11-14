"""v3 phase4: worker qualifications, skills, eligibility overrides

Revision ID: d4a7f5b0c236
Revises: c3f6e4a9b125
Create Date: 2026-11-14

Additive tables only (projects.eligibility_requirements was added in phase 3).
Idempotent.
"""
import sqlalchemy as sa
from alembic import op

revision = "d4a7f5b0c236"
down_revision = "c3f6e4a9b125"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, index: str) -> bool:
    return index in [i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)]


def upgrade() -> None:
    if not _has_table("qualification_assessments"):
        op.create_table(
            "qualification_assessments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("assessment_type", sa.String(length=40), nullable=False, server_default="mcq"),
            sa.Column("skill_tags", sa.JSON(), nullable=True),
            sa.Column("time_limit_minutes", sa.Integer(), nullable=True),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("passing_score", sa.Float(), nullable=False, server_default="0.7"),
            sa.Column("randomize_questions", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("qualification_assessments", schema=None) as batch_op:
            batch_op.create_index("ix_qualification_assessments_project_id", ["project_id"], unique=False)
            batch_op.create_index("ix_qual_assessments_status", ["status"], unique=False)

    if not _has_table("qualification_questions"):
        op.create_table(
            "qualification_questions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("assessment_id", sa.Integer(), nullable=False),
            sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("question_type", sa.String(length=20), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("options", sa.JSON(), nullable=True),
            sa.Column("correct_answer", sa.JSON(), nullable=True),
            sa.Column("points", sa.Float(), nullable=False, server_default="1"),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["assessment_id"], ["qualification_assessments.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("qualification_questions", schema=None) as batch_op:
            batch_op.create_index("ix_qualification_questions_assessment_id", ["assessment_id"], unique=False)
            batch_op.create_index("ix_qual_questions_assessment", ["assessment_id"], unique=False)

    if not _has_table("qualification_attempts"):
        op.create_table(
            "qualification_attempts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("assessment_id", sa.Integer(), nullable=False),
            sa.Column("worker_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="in_progress"),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("answers", sa.JSON(), nullable=True),
            sa.Column("auto_graded", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("graded_by", sa.Integer(), nullable=True),
            sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["assessment_id"], ["qualification_assessments.id"]),
            sa.ForeignKeyConstraint(["worker_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["graded_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("qualification_attempts", schema=None) as batch_op:
            batch_op.create_index("ix_qualification_attempts_assessment_id", ["assessment_id"], unique=False)
            batch_op.create_index("ix_qual_attempts_worker", ["worker_id", "status"], unique=False)
            batch_op.create_index("ix_qual_attempts_assessment", ["assessment_id", "status"], unique=False)

    if not _has_table("worker_skills"):
        op.create_table(
            "worker_skills",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("skill", sa.String(length=100), nullable=False),
            sa.Column("source", sa.String(length=20), nullable=False, server_default="self_reported"),
            sa.Column("level", sa.String(length=30), nullable=True),
            sa.Column("evidence_assessment_id", sa.Integer(), nullable=True),
            sa.Column("verified_by", sa.Integer(), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["evidence_assessment_id"], ["qualification_assessments.id"]),
            sa.ForeignKeyConstraint(["verified_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("worker_skills", schema=None) as batch_op:
            batch_op.create_index("ix_worker_skills_user_id", ["user_id"], unique=False)
            batch_op.create_index("ix_worker_skills_user", ["user_id"], unique=False)

    if not _has_table("project_eligibility_overrides"):
        op.create_table(
            "project_eligibility_overrides",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("granted_by", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("project_eligibility_overrides", schema=None) as batch_op:
            batch_op.create_index("ix_project_eligibility_overrides_project_id", ["project_id"], unique=False)
            batch_op.create_index("ix_project_eligibility_overrides_user_id", ["user_id"], unique=False)


def downgrade() -> None:
    for table in ("project_eligibility_overrides", "worker_skills", "qualification_attempts",
                  "qualification_questions", "qualification_assessments"):
        if _has_table(table):
            op.drop_table(table)
