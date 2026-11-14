"""Organization (client tenant) management — Phase 1 multi-tenant foundations.

Route permissions:
- create / list-all / administer: super_admin + project_admin (staff)
- client users see only organizations they belong to, per their org role
- memberships and invitations are managed by client_owner or staff
"""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from app.core.security import CurrentUser, DbSession, OrgAdmin, require_roles
from app.models.organization import (
    CLIENT_ROLES, Organization, OrganizationInvitation, OrganizationMember,
    ORG_STATUSES,
)
from app.models.user import User, UserRole
from app.schemas import OrganizationCreate, OrganizationUpdate
from app.services import org_access
from app.services.audit import log_action
from app.services.notifications import notify

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; normalize for comparisons."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:90] or "org"


@router.post("", status_code=201)
def create_organization(
    payload: OrganizationCreate,
    db: DbSession,
    user: OrgAdmin,
    request: Request,
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Organization name is required.")
    slug = _slugify(name)
    if db.scalar(select(Organization).where(Organization.slug == slug)):
        slug = f"{slug}-{db.scalar(select(func.count()).select_from(Organization)) + 1}"
    org = Organization(
        name=name,
        description=payload.description,
        slug=slug,
        status="active",
        contact_email=payload.contact_email,
        settings=payload.settings or {},
    )
    db.add(org)
    db.flush()
    # Optionally attach the first owner member right away.
    if payload.owner_email:
        owner = db.scalar(select(User).where(User.email == payload.owner_email.lower()))
        if owner is None:
            raise HTTPException(status_code=404, detail="Owner user not found for owner_email.")
        db.add(OrganizationMember(
            organization_id=org.id, user_id=owner.id,
            role=UserRole.CLIENT_OWNER, added_by=user.id,
        ))
    db.commit()
    db.refresh(org)
    log_action(db, user_id=user.id, action="organization.create",
               entity_type="organization", entity_id=org.id,
               details={"name": org.name}, request=request)
    return org_access.org_out(db, org, include_members=True)


@router.get("")
def list_organizations(db: DbSession, user: CurrentUser):
    """Staff see all organizations; client users see only their own."""
    visible = org_access.visible_org_ids(db, user)
    stmt = select(Organization).order_by(Organization.created_at.desc())
    if visible is not None:
        if not visible:
            return []
        stmt = stmt.where(Organization.id.in_(visible))
    orgs = db.scalars(stmt).all()
    out = []
    for org in orgs:
        item = org_access.org_out(db, org)
        member_count = db.scalar(
            select(func.count()).select_from(OrganizationMember)
            .where(OrganizationMember.organization_id == org.id)
        ) or 0
        item["member_count"] = member_count
        item["my_role"] = org_access.org_role(db, user, org.id)
        out.append(item)
    return out


@router.get("/mine")
def my_organizations(db: DbSession, user: CurrentUser):
    """Organizations the current user belongs to (client portal bootstrap)."""
    from sqlalchemy.orm import joinedload

    memberships = db.scalars(
        select(OrganizationMember)
        .options(joinedload(OrganizationMember.organization))
        .where(OrganizationMember.user_id == user.id)
    ).unique().all()
    return [
        {
            "id": m.organization.id,
            "name": m.organization.name,
            "slug": m.organization.slug,
            "status": m.organization.status,
            "role": m.role,
        }
        for m in memberships
    ]


@router.get("/{org_id}")
def get_organization(org_id: int, db: DbSession, user: CurrentUser):
    _require_org_visible(db, user, org_id)
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return org_access.org_out(db, org, include_members=True)


@router.put("/{org_id}")
def update_organization(
    org_id: int,
    payload: OrganizationUpdate,
    db: DbSession,
    user: CurrentUser,
    request: Request,
):
    _require_org_visible(db, user, org_id)
    if not org_access.can_write_org(db, user, org_id) and user.role not in UserRole.ADMINISTRATORS:
        raise HTTPException(status_code=403, detail="Only the organization owner or an administrator can update it.")
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    changes = {}
    for field in ("name", "description", "contact_email", "settings"):
        val = getattr(payload, field, None)
        if val is not None:
            changes[field] = val
            setattr(org, field, val)
    if payload.status is not None:
        if payload.status not in ORG_STATUSES:
            raise HTTPException(status_code=422, detail=f"Unknown status; allowed: {ORG_STATUSES}")
        if user.role not in UserRole.ADMINISTRATORS and user.role != UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Only administrators can change organization status.")
        changes["status"] = payload.status
        org.status = payload.status
    db.commit()
    log_action(db, user_id=user.id, action="organization.update",
               entity_type="organization", entity_id=org.id,
               details={"changes": list(changes.keys())}, request=request)
    return org_access.org_out(db, org, include_members=True)


def _require_org_visible(db: DbSession, user: User, org_id: int) -> None:
    visible = org_access.visible_org_ids(db, user)
    if visible is not None and org_id not in visible:
        raise HTTPException(status_code=403, detail="You do not have access to this organization.")


# --- Members -----------------------------------------------------------------


@router.get("/{org_id}/members")
def list_members(org_id: int, db: DbSession, user: CurrentUser):
    _require_org_visible(db, user, org_id)
    members = db.scalars(
        select(OrganizationMember)
        .options(*_member_loads())
        .where(OrganizationMember.organization_id == org_id)
    ).unique().all()
    return [
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


def _member_loads():
    from sqlalchemy.orm import joinedload
    return [joinedload(OrganizationMember.user)]


@router.post("/{org_id}/members", status_code=201)
def add_member(
    org_id: int,
    payload: dict,
    db: DbSession,
    user: CurrentUser,
    request: Request,
):
    _require_org_admin_access(db, user, org_id)
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    email = (payload.get("email") or "").strip().lower()
    role = (payload.get("role") or "client_viewer").strip()
    if not email:
        raise HTTPException(status_code=422, detail="email is required.")
    if role not in CLIENT_ROLES:
        raise HTTPException(status_code=422, detail=f"Unknown client role; allowed: {CLIENT_ROLES}")
    target = db.scalar(select(User).where(User.email == email))
    if target is None:
        raise HTTPException(status_code=404, detail="No account with this email. Send an invitation instead.")
    existing = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == target.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This user is already a member.")
    member = OrganizationMember(
        organization_id=org_id, user_id=target.id, role=role, added_by=user.id
    )
    db.add(member)
    # give bare tester accounts their client platform role so /me reflects it
    if target.role == UserRole.TESTER:
        target.role = role
    db.commit()
    db.refresh(member)
    log_action(db, user_id=user.id, action="organization.member_add",
               entity_type="organization", entity_id=org_id,
               details={"user_id": target.id, "role": role}, request=request)
    notify(db, user_id=target.id, type="org.member_added",
           title=f"You were added to {org.name}",
           body=f"Your organization role: {role}.",
           entity_type="organization", entity_id=org_id)
    return {"id": member.id, "user_id": member.user_id, "role": member.role}


@router.delete("/{org_id}/members/{member_id}")
def remove_member(
    org_id: int,
    member_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
):
    _require_org_admin_access(db, user, org_id)
    member = db.get(OrganizationMember, member_id)
    if member is None or member.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Member not found.")
    owners = db.scalar(
        select(func.count()).select_from(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.role == UserRole.CLIENT_OWNER,
        )
    ) or 0
    if member.role == UserRole.CLIENT_OWNER and owners <= 1:
        raise HTTPException(status_code=400, detail="An organization must keep at least one owner.")
    db.delete(member)
    db.commit()
    log_action(db, user_id=user.id, action="organization.member_remove",
               entity_type="organization", entity_id=org_id,
               details={"member_user_id": member.user_id}, request=request)
    return {"ok": True}


@router.put("/{org_id}/members/{member_id}")
def update_member_role(
    org_id: int,
    member_id: int,
    payload: dict,
    db: DbSession,
    user: CurrentUser,
    request: Request,
):
    _require_org_admin_access(db, user, org_id)
    role = (payload.get("role") or "").strip()
    if role not in CLIENT_ROLES:
        raise HTTPException(status_code=422, detail=f"Unknown client role; allowed: {CLIENT_ROLES}")
    member = db.get(OrganizationMember, member_id)
    if member is None or member.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Member not found.")
    if member.role == UserRole.CLIENT_OWNER and role != UserRole.CLIENT_OWNER:
        owners = db.scalar(
            select(func.count()).select_from(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.role == UserRole.CLIENT_OWNER,
            )
        ) or 0
        if owners <= 1:
            raise HTTPException(status_code=400, detail="An organization must keep at least one owner.")
    old = member.role
    member.role = role
    target = db.get(User, member.user_id)
    if target is not None and target.role in UserRole.CLIENT_ROLES:
        target.role = role
    db.commit()
    log_action(db, user_id=user.id, action="organization.member_role_change",
               entity_type="organization", entity_id=org_id,
               details={"member_user_id": member.user_id, "from": old, "to": role},
               request=request)
    return {"id": member.id, "role": member.role}


def _require_org_admin_access(db: DbSession, user: User, org_id: int) -> None:
    """client_owner of this org, or platform administrator."""
    if user.role in UserRole.ADMINISTRATORS:
        return
    if user.role == UserRole.SUPER_ADMIN:
        return
    if user.role == UserRole.CLIENT_OWNER and org_access.can_write_org(db, user, org_id):
        return
    raise HTTPException(status_code=403, detail="Organization owner or administrator access required.")


# --- Invitations ---------------------------------------------------------------


@router.get("/{org_id}/invitations")
def list_invitations(org_id: int, db: DbSession, user: CurrentUser):
    _require_org_admin_access(db, user, org_id)
    invitations = db.scalars(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == org_id)
        .order_by(OrganizationInvitation.created_at.desc())
    ).all()
    return [
        {
            "id": i.id,
            "email": i.email,
            "role": i.role,
            "status": i.status,
            "expires_at": i.expires_at.isoformat() if i.expires_at else None,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in invitations
    ]


@router.post("/{org_id}/invitations", status_code=201)
def create_invitation(
    org_id: int,
    payload: dict,
    db: DbSession,
    user: CurrentUser,
    request: Request,
):
    _require_org_admin_access(db, user, org_id)
    email = (payload.get("email") or "").strip().lower()
    role = (payload.get("role") or "client_viewer").strip()
    if not email:
        raise HTTPException(status_code=422, detail="email is required.")
    if role not in CLIENT_ROLES:
        raise HTTPException(status_code=422, detail=f"Unknown client role; allowed: {CLIENT_ROLES}")
    existing_user = db.scalar(select(User).where(User.email == email))
    if existing_user is not None:
        existing_member = db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == existing_user.id,
            )
        )
        if existing_member is not None:
            raise HTTPException(status_code=409, detail="This user is already a member.")
    invitation, raw_token = org_access.create_invitation(
        db, org_id=org_id, email=email, role=role, invited_by=user.id
    )
    log_action(db, user_id=user.id, action="organization.invite",
               entity_type="organization", entity_id=org_id,
               details={"email": email, "role": role}, request=request)
    # The raw token is returned exactly once; only its hash is stored.
    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "token": raw_token,
        "expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
    }


@router.post("/invitations/accept")
def accept_invitation(payload: dict, db: DbSession, user: CurrentUser, request: Request):
    raw_token = (payload.get("token") or "").strip()
    if not raw_token:
        raise HTTPException(status_code=422, detail="token is required.")
    try:
        member = org_access.accept_invitation(db, raw_token=raw_token, user=user)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    org = db.get(Organization, member.organization_id)
    log_action(db, user_id=user.id, action="organization.invite_accept",
               entity_type="organization", entity_id=member.organization_id,
               details={"role": member.role}, request=request)
    return {
        "organization": {"id": org.id, "name": org.name, "slug": org.slug},
        "role": member.role,
    }
