"""Organization (tenant) access control — the client-side counterpart of access.py.

Rules (all enforced here, never in the client):
- Internal staff roles (super_admin / project_admin / project_manager) are NOT
  granted client data by this module; staff reach client resources through
  explicit assignment (project membership, admin queues) or super-admin power.
- Client roles (client_owner / client_project_manager / client_viewer) see only
  resources that belong to organizations they are active members of.
- The role inside the organization decides read vs write, checked per call.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.organization import (
    CLIENT_ROLES, Organization, OrganizationInvitation, OrganizationMember,
    ORG_ADMIN_ROLES,
)
from app.models.project import Project
from app.models.user import User, UserRole

INVITATION_TTL_HOURS = 168  # one week


def org_ids_for_user(db: Session, user: User) -> set[int]:
    """Organizations the user is a member of (any client role)."""
    if user.role not in UserRole.CLIENT_ROLES and user.role not in UserRole.STAFF:
        return set()
    rows = db.scalars(
        select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == user.id
        )
    ).all()
    return set(rows)


def is_org_member(db: Session, user: User, org_id: int) -> bool:
    return org_id in org_ids_for_user(db, user)


def org_role(db: Session, user: User, org_id: int) -> str | None:
    """The client-side role the user holds in this organization, or None."""
    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    )
    return member.role if member else None


def require_org_member(db: Session, user: User, org_id: int, roles: list[str] | None = None) -> OrganizationMember:
    """Load membership enforcing role. Raises PermissionError / LookupError."""
    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if member is None:
        raise LookupError("Organization not found.")
    if user.role == UserRole.SUPER_ADMIN:
        return member if member else _virtual_admin_membership(org_id, user.id)
    if roles is not None and member.role not in roles:
        raise PermissionError("Your organization role does not permit this action.")
    return member


def _virtual_admin_membership(org_id: int, user_id: int) -> OrganizationMember:
    # super_admins manage every organization even without a membership row.
    return OrganizationMember(organization_id=org_id, user_id=user_id, role="client_owner")


def visible_org_ids(db: Session, user: User) -> set[int] | None:
    """None means 'all organizations' (super_admin only); empty set = none."""
    if user.role == UserRole.SUPER_ADMIN:
        return None
    return org_ids_for_user(db, user)


def can_write_org(db: Session, user: User, org_id: int) -> bool:
    if user.role == UserRole.SUPER_ADMIN:
        return True
    role = org_role(db, user, org_id)
    return role in ORG_ADMIN_ROLES


def visible_project_ids_for_client(db: Session, user: User) -> set[int]:
    """Projects belonging to the user's organizations (client roles only)."""
    orgs = org_ids_for_user(db, user)
    if not orgs:
        return set()
    rows = db.scalars(
        select(Project.id).where(Project.organization_id.in_(orgs))
    ).all()
    return set(rows)


def generate_invitation_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash). Raw token is shown once."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_invitation(db: Session, *, org_id: int, email: str, role: str,
                      invited_by: int | None) -> tuple[OrganizationInvitation, str]:
    raw, token_hash = generate_invitation_token()
    invitation = OrganizationInvitation(
        organization_id=org_id,
        email=email.lower(),
        role=role if role in CLIENT_ROLES else "client_viewer",
        token_hash=token_hash,
        invited_by=invited_by,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=INVITATION_TTL_HOURS),
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation, raw


def accept_invitation(db: Session, *, raw_token: str, user: User) -> OrganizationMember:
    """Attach the (existing, authenticated) user to the invited organization.

    Concurrency-safe (V3.1): the pending->accepted transition is a single
    conditional UPDATE, so two concurrent acceptances of the same token cannot
    both succeed.
    """
    from sqlalchemy import update as _update

    token_hash = hash_token(raw_token)
    invitation = db.scalar(
        select(OrganizationInvitation).where(OrganizationInvitation.token_hash == token_hash)
    )
    if invitation is None:
        raise LookupError("Invitation not found.")
    if invitation.email.lower() != user.email.lower():
        raise PermissionError("This invitation was issued to a different email address.")

    expires = invitation.expires_at
    if expires is not None:
        # SQLite returns naive datetimes; normalize before comparing.
        from datetime import timezone as _tz
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=_tz.utc)
        if expires < datetime.now(_tz.utc):
            invitation.status = "expired"
            db.commit()
            raise PermissionError("This invitation has expired.")

    result = db.execute(
        _update(OrganizationInvitation)
        .where(
            OrganizationInvitation.id == invitation.id,
            OrganizationInvitation.status == "pending",
        )
        .values(status="accepted", accepted_user_id=user.id,
                accepted_at=datetime.now(timezone.utc))
    )
    if result.rowcount == 0:
        db.rollback()
        # re-read to give the caller an accurate reason
        db.refresh(invitation)
        if invitation.status == "expired":
            raise PermissionError("This invitation has expired.")
        raise PermissionError("This invitation is no longer active.")

    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == invitation.organization_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if member is None:
        member = OrganizationMember(
            organization_id=invitation.organization_id,
            user_id=user.id,
            role=invitation.role,
            added_by=invitation.invited_by,
        )
        db.add(member)
    # upgrade platform role to the client role if the account is a bare tester
    if user.role == UserRole.TESTER:
        user.role = invitation.role
    db.commit()
    db.refresh(member)
    return member


def org_out(db: Session, org: Organization, include_members: bool = False) -> dict:
    data = {
        "id": org.id,
        "name": org.name,
        "description": org.description,
        "slug": org.slug,
        "status": org.status,
        "contact_email": org.contact_email,
        "settings": org.settings or {},
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }
    if include_members:
        members = db.scalars(
            select(OrganizationMember)
            .options(joinedload(OrganizationMember.user))
            .where(OrganizationMember.organization_id == org.id)
        ).unique().all()
        data["members"] = [
            {
                "id": m.id,
                "user_id": m.user_id,
                "name": m.user.name if m.user else None,
                "email": m.user.email if m.user else None,
                "role": m.role,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in members
        ]
    return data
