"""v3 phase1: multi-tenant organizations

Revision ID: a1f4c2d7e903
Revises: 4bfc767ebcea
Create Date: 2026-11-13

Extends organizations into real tenants and adds membership + invitation
tables. Entirely additive: existing v2 rows keep working (new organization
columns are nullable/defaulted; no existing column is dropped or renamed).

Idempotent: every step checks whether the object already exists. This makes
the migration safe on dev databases where `Base.metadata.create_all` ran
before Alembic (a documented v2 dev convenience).
"""
import sqlalchemy as sa
from alembic import op

revision = "a1f4c2d7e903"
down_revision = "4bfc767ebcea"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return name in inspector.get_table_names()


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in [c["name"] for c in inspector.get_columns(table)]


def _has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return index in [i["name"] for i in inspector.get_indexes(table)]


def upgrade() -> None:
    # --- organizations: tenant columns (batch mode for SQLite ALTER support) ---
    if _has_table("organizations"):
        with op.batch_alter_table("organizations", schema=None) as batch_op:
            if not _has_column("organizations", "slug"):
                batch_op.add_column(sa.Column("slug", sa.String(length=100), nullable=True))
            if not _has_column("organizations", "status"):
                batch_op.add_column(sa.Column("status", sa.String(length=20),
                                              nullable=False, server_default="active"))
            if not _has_column("organizations", "contact_email"):
                batch_op.add_column(sa.Column("contact_email", sa.String(length=255), nullable=True))
            if not _has_column("organizations", "settings"):
                batch_op.add_column(sa.Column("settings", sa.JSON(), nullable=True))
        if not _has_index("organizations", "ix_organizations_slug"):
            op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
        if not _has_index("organizations", "ix_organizations_status"):
            op.create_index("ix_organizations_status", "organizations", ["status"], unique=False)

    # --- organization_members ---
    if not _has_table("organization_members"):
        op.create_table(
            "organization_members",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=40), nullable=False),
            sa.Column("added_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["added_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        )
    if _has_table("organization_members"):
        with op.batch_alter_table("organization_members", schema=None) as batch_op:
            if not _has_index("organization_members", "ix_organization_members_organization_id"):
                batch_op.create_index("ix_organization_members_organization_id", ["organization_id"], unique=False)
            if not _has_index("organization_members", "ix_org_members_user"):
                batch_op.create_index("ix_org_members_user", ["user_id"], unique=False)

    # --- organization_invitations ---
    if not _has_table("organization_invitations"):
        op.create_table(
            "organization_invitations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("role", sa.String(length=40), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("invited_by", sa.Integer(), nullable=True),
            sa.Column("accepted_user_id", sa.Integer(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["accepted_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if _has_table("organization_invitations"):
        with op.batch_alter_table("organization_invitations", schema=None) as batch_op:
            if not _has_index("organization_invitations", "ix_org_invitations_org"):
                batch_op.create_index("ix_org_invitations_org", ["organization_id"], unique=False)
            if not _has_index("organization_invitations", "ix_organization_invitations_email"):
                batch_op.create_index("ix_organization_invitations_email", ["email"], unique=False)
            if not _has_index("organization_invitations", "ix_organization_invitations_status"):
                batch_op.create_index("ix_organization_invitations_status", ["status"], unique=False)


def downgrade() -> None:
    if _has_table("organization_invitations"):
        op.drop_table("organization_invitations")
    if _has_table("organization_members"):
        op.drop_table("organization_members")
    if _has_table("organizations"):
        with op.batch_alter_table("organizations", schema=None) as batch_op:
            if _has_index("organizations", "ix_organizations_status"):
                batch_op.drop_index("ix_organizations_status")
            if _has_index("organizations", "ix_organizations_slug"):
                batch_op.drop_index("ix_organizations_slug")
            if _has_column("organizations", "settings"):
                batch_op.drop_column("settings")
            if _has_column("organizations", "contact_email"):
                batch_op.drop_column("contact_email")
            if _has_column("organizations", "status"):
                batch_op.drop_column("status")
            if _has_column("organizations", "slug"):
                batch_op.drop_column("slug")
