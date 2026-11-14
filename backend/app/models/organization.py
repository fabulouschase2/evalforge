"""Client organizations (tenants), their members and membership invitations.

V3 multi-tenancy: an organization is the tenant boundary for all client-facing
resources. Client users authenticate through the normal `users` table and their
platform role (`client_owner` / `client_project_manager` / `client_viewer`)
grants no internal capabilities; everything client-side is authorized through
`organization_members` rows.

Internal staff (super_admin / project_admin / project_manager) may also hold
organization memberships (e.g. as account liaisons), but their access never
derives from them.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow

ORG_STATUSES = ["active", "suspended"]
# Client-side roles kept separate from internal platform roles.
CLIENT_ROLES = ["client_owner", "client_project_manager", "client_viewer"]
# Who may administer an organization (staff or the owner role inside it).
ORG_ADMIN_ROLES = ["client_owner"]


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # --- v3 multi-tenant extension (all nullable/defaulted for v2 rows) ---
    slug: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # org-scoped preferences (branding, defaults); never contains secrets
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members = relationship(
        "OrganizationMember", back_populates="organization",
        cascade="all, delete-orphan",
    )


class OrganizationMember(Base):
    """Membership of a user in a client organization with a client-side role."""
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        Index("ix_org_members_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # client_owner | client_project_manager | client_viewer
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization = relationship("Organization", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])


class OrganizationInvitation(Base):
    """Pending invitation to join an organization as a client member.

    Token is stored hashed (sha256); the raw token is only shown once at
    creation time. Accepted/revoked invitations keep their history.
    """
    __tablename__ = "organization_invitations"
    __table_args__ = (
        Index("ix_org_invitations_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # pending | accepted | revoked | expired
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    accepted_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
