"""Projects: full lifecycle management with membership and isolation.

Isolation model (enforced here, not in the client):
- super_admin: all projects
- project_admin / project_manager: owned or 'admin' membership
- tester: 'tester' membership, active projects only
- reviewer / senior_reviewer: 'reviewer' membership
"""
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.security import AdminPM, CurrentUser, DbSession
from app.models.dataset import Dataset
from app.models.organization import Organization
from app.models.project import (
    Project, ProjectMember, PROJECT_STATUSES, PROJECT_TYPES,
)
from app.models.task import Task
from app.models.user import User, UserRole
from app.schemas import ProjectCreate, ProjectOut
from app.services import access as acl
from app.services.audit import log_action

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _project_out(db: DbSession, p: Project, user: User) -> dict:
    base = ProjectOut.model_validate(p).model_dump(mode="json")
    base.update({
        "organization_id": p.organization_id,
        "organization_name": p.organization.name if p.organization else (p.client or None),
        "client": p.client,
        "project_type": p.project_type,
        "status": p.status,
        "deadline": p.deadline.isoformat() if p.deadline else None,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "instructions": p.instructions,
        "required_skills": p.required_skills or [],
        "supported_languages": p.supported_languages or [],
        "quality_requirements": p.quality_requirements,
        "target_task_volume": p.target_task_volume,
        "blind_review": p.blind_review,
        "is_admin": p.is_admin_of(user.id) or user.role == UserRole.SUPER_ADMIN,
        "member_count": len(p.members or []),
        "dataset_count": db.scalar(select(func.count()).select_from(Dataset).where(Dataset.project_id == p.id)) or 0,
        "task_count": db.scalar(select(func.count()).select_from(Task).where(Task.project_id == p.id)) or 0,
        "is_demo": p.is_demo,
    })
    return base


@router.post("", status_code=201)
def create_project(payload: ProjectCreate, db: DbSession, user: AdminPM, request: Request):
    if payload.project_type and payload.project_type not in PROJECT_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown project type; allowed: {PROJECT_TYPES}")
    if payload.status and payload.status not in PROJECT_STATUSES:
        raise HTTPException(status_code=422, detail=f"Unknown project status; allowed: {PROJECT_STATUSES}")
    if payload.organization_id is not None and db.get(Organization, payload.organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found.")

    project = Project(
        name=payload.name.strip(),
        description=payload.description,
        owner_id=user.id,
        organization_id=payload.organization_id,
        client=payload.client,
        project_type=payload.project_type or "ai_response_evaluation",
        instructions=payload.instructions,
        required_skills=payload.required_skills,
        supported_languages=payload.supported_languages,
        start_date=payload.start_date,
        deadline=payload.deadline,
        status=payload.status or "active",
        quality_requirements=payload.quality_requirements,
        target_task_volume=payload.target_task_volume,
        blind_review=payload.blind_review if payload.blind_review is not None else True,
    )
    db.add(project)
    db.flush()
    # creator is recorded as an admin member as well as owner
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="admin", added_by=user.id))
    db.commit()
    db.refresh(project)
    log_action(db, user_id=user.id, action="project.create", entity_type="project", entity_id=project.id,
               details={"name": project.name, "type": project.project_type}, request=request)
    return _project_out(db, project, user)


@router.get("")
def list_projects(db: DbSession, user: CurrentUser, status: str | None = None, project_type: str | None = None):
    ids = acl.visible_project_ids(db, user)
    stmt = (
        select(Project)
        .options(joinedload(Project.members), joinedload(Project.organization))
        .order_by(Project.created_at.desc())
    )
    if ids is not None:
        if not ids:
            return []
        stmt = stmt.where(Project.id.in_(ids))
    if status:
        stmt = stmt.where(Project.status == status)
    if project_type:
        stmt = stmt.where(Project.project_type == project_type)
    return [_project_out(db, p, user) for p in db.scalars(stmt).unique().all()]


@router.get("/types")
def list_project_types(user: CurrentUser):
    return {"types": PROJECT_TYPES, "statuses": PROJECT_STATUSES}


@router.get("/{project_id}")
def get_project(project_id: int, db: DbSession, user: CurrentUser):
    try:
        project = acl.require_project(db, user, project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _project_out(db, project, user)


@router.put("/{project_id}")
def update_project(project_id: int, payload: ProjectCreate, db: DbSession, user: AdminPM, request: Request):
    try:
        project = acl.require_project(db, user, project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    changes = {}
    for field in ("name", "description", "project_type", "instructions", "status",
                  "quality_requirements", "required_skills", "supported_languages",
                  "start_date", "deadline", "target_task_volume", "client",
                  "organization_id", "blind_review"):
        val = getattr(payload, field, None)
        if val is not None and getattr(project, field, None) != val:
            changes[field] = val
            setattr(project, field, val)
    if "project_type" in changes and changes["project_type"] not in PROJECT_TYPES:
        raise HTTPException(status_code=422, detail="Unknown project type.")
    if "status" in changes and changes["status"] not in PROJECT_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown project status.")
    db.commit()
    log_action(db, user_id=user.id, action="project.update", entity_type="project", entity_id=project.id,
               details={"changes": list(changes.keys())}, request=request)
    return _project_out(db, project, user)


@router.post("/{project_id}/archive", status_code=204)
def archive_project(project_id: int, db: DbSession, user: AdminPM, request: Request):
    try:
        project = acl.require_project(db, user, project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    project.status = "archived"
    db.commit()
    log_action(db, user_id=user.id, action="project.archive", entity_type="project", entity_id=project.id,
               request=request)
    return None


# ---------------------------------------------------------------- membership

@router.get("/{project_id}/members")
def list_members(project_id: int, db: DbSession, user: CurrentUser):
    try:
        acl.require_project(db, user, project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    members = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)).all()
    out = []
    for m in members:
        u = db.get(User, m.user_id)
        out.append({
            "id": m.id, "user_id": m.user_id, "role": m.role,
            "name": u.name if u else "?", "email": u.email if u else "?",
            "platform_role": u.role if u else None,
            "added_at": m.created_at.isoformat(),
        })
    return out


@router.post("/{project_id}/members", status_code=201)
def add_member(project_id: int, payload: dict, db: DbSession, user: AdminPM, request: Request):
    try:
        project = acl.require_project(db, user, project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    role = (payload.get("role") or "").strip()
    if role not in ("admin", "tester", "reviewer"):
        raise HTTPException(status_code=422, detail="Membership role must be admin, tester or reviewer.")
    target = None
    if payload.get("user_id"):
        target = db.get(User, int(payload["user_id"]))
    elif payload.get("email"):
        target = db.scalar(select(User).where(User.email == str(payload["email"]).lower()))
    if target is None:
        raise HTTPException(status_code=404, detail="User not found (match by user_id or email).")
    if not target.is_active:
        raise HTTPException(status_code=400, detail="Cannot add a suspended account to a project.")
    if target.role == UserRole.TESTER and role != "tester":
        raise HTTPException(status_code=422, detail="A tester platform role can only join as a tester.")
    if target.role in (UserRole.REVIEWER, UserRole.SENIOR_REVIEWER) and role != "reviewer":
        raise HTTPException(status_code=422, detail="A reviewer platform role can only join as a reviewer.")
    if target.role in UserRole.STAFF and role != "admin":
        raise HTTPException(status_code=422, detail="Staff users join projects as admins.")

    existing = db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == target.id))
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member of this project.")
    db.add(ProjectMember(project_id=project_id, user_id=target.id, role=role, added_by=user.id))
    db.commit()
    log_action(db, user_id=user.id, action="project.member_add", entity_type="project", entity_id=project_id,
               details={"user_id": target.id, "role": role}, request=request)
    return {"user_id": target.id, "role": role}


@router.delete("/{project_id}/members/{member_id}", status_code=204)
def remove_member(project_id: int, member_id: int, db: DbSession, user: AdminPM, request: Request):
    try:
        project = acl.require_project(db, user, project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=404, detail="Member not found.")
    if member.role == "admin" and project.owner_id == member.user_id:
        raise HTTPException(status_code=400, detail="The project owner cannot be removed.")
    db.delete(member)
    db.commit()
    log_action(db, user_id=user.id, action="project.member_remove", entity_type="project", entity_id=project_id,
               details={"user_id": member.user_id, "role": member.role}, request=request)
    return None

# ------------------------------------------------------------- organizations
# V3: organization management moved to app/api/routes/organizations.py
# (multi-tenant aware). The legacy org_router below remains as an empty alias
# for backward compatibility of the module import.
org_router = APIRouter(prefix="/api/organizations", tags=["organizations"])
