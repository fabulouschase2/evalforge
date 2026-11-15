"""Rubric routes: CRUD, versioning, validation, JSON import/export.

V3.1: reads are scoped through the rubric's project visibility (projectless
rubrics are staff-only); writes on project-linked rubrics require project
administration rights.
"""
from fastapi import APIRouter, HTTPException, Request

from app.core.security import AdminPM, AdminPMEvaluator, CurrentUser, DbSession
from app.models.rubric import Rubric, RubricVersion
from app.models.user import UserRole
from app.schemas import (
    RubricCreate,
    RubricOut,
    RubricUpdate,
    RubricValidationResponse,
    RubricVersionOut,
)
from app.services import access as acl
from app.services import rubrics as rs
from app.services.audit import log_action

router = APIRouter(prefix="/api/rubrics", tags=["rubrics"])


def _rubric_visible(db: DbSession, user, rubric: Rubric) -> bool:
    if rubric.project_id is None:
        return user.role in UserRole.STAFF or user.role in UserRole.PLATFORM_WIDE
    try:
        acl.require_project(db, user, rubric.project_id)
        return True
    except (PermissionError, LookupError):
        return False


def _load_rubric_scoped(db: DbSession, user, rubric_id: int) -> Rubric:
    rubric = db.get(Rubric, rubric_id)
    if rubric is None or not _rubric_visible(db, user, rubric):
        # 404 so rubric ids of other tenants are not enumerable
        raise HTTPException(status_code=404, detail="Rubric not found.")
    return rubric


def _require_rubric_admin(db: DbSession, user, rubric: Rubric) -> None:
    if rubric.project_id is None:
        if user.role != UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Projectless rubrics are managed by super admins.")
        return
    try:
        project = acl.require_project(db, user, rubric.project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/validate", response_model=RubricValidationResponse)
def validate_definition(payload: dict, user: CurrentUser):
    result = rs.validate_rubric_definition(payload.get("definition", payload if "criteria" in (payload or {}) else {}))
    return RubricValidationResponse(valid=result["valid"], errors=result["errors"], warnings=result["warnings"])


@router.post("", response_model=RubricOut, status_code=201)
def create_rubric(payload: RubricCreate, db: DbSession, user: AdminPMEvaluator, request: Request):
    validation = rs.validate_rubric_definition(payload.definition)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail={"message": "Rubric definition has validation errors.", "errors": validation["errors"]})
    if payload.project_id is not None:
        try:
            project = acl.require_project(db, user, payload.project_id)
            acl.require_project_admin(db, user, project)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    normalized = rs.normalize_definition(payload.definition)
    rubric = Rubric(
        name=payload.name.strip(),
        description=payload.description,
        project_id=payload.project_id,
        created_by=user.id,
        current_version=1,
    )
    db.add(rubric)
    db.flush()
    version = RubricVersion(rubric_id=rubric.id, version_number=1, definition=normalized, created_by=user.id)
    db.add(version)
    db.commit()
    db.refresh(rubric)
    log_action(db, user_id=user.id, action="rubric.create", entity_type="rubric", entity_id=rubric.id,
               details={"name": rubric.name, "version": 1}, request=request)
    return rubric


@router.get("", response_model=list[RubricOut])
def list_rubrics(db: DbSession, user: CurrentUser):
    rubrics = list(db.query(Rubric).order_by(Rubric.created_at.desc()).all())
    return [r for r in rubrics if _rubric_visible(db, user, r)]


@router.get("/{rubric_id}", response_model=RubricOut)
def get_rubric(rubric_id: int, db: DbSession, user: CurrentUser):
    return _load_rubric_scoped(db, user, rubric_id)


@router.get("/{rubric_id}/versions", response_model=list[RubricVersionOut])
def list_versions(rubric_id: int, db: DbSession, user: CurrentUser):
    rubric = _load_rubric_scoped(db, user, rubric_id)
    return list(db.query(RubricVersion).filter(RubricVersion.rubric_id == rubric.id).order_by(RubricVersion.version_number.desc()).all())


@router.get("/{rubric_id}/versions/{version_number}", response_model=RubricVersionOut)
def get_version(rubric_id: int, version_number: int, db: DbSession, user: CurrentUser):
    _load_rubric_scoped(db, user, rubric_id)
    version = db.query(RubricVersion).filter(
        RubricVersion.rubric_id == rubric_id, RubricVersion.version_number == version_number
    ).first()
    if version is None:
        raise HTTPException(status_code=404, detail="Rubric version not found.")
    return version


@router.put("/{rubric_id}", response_model=RubricOut)
def update_rubric(rubric_id: int, payload: RubricUpdate, db: DbSession, user: AdminPMEvaluator, request: Request):
    """Update rubric metadata and/or definition.

    Definitions are never mutated in place: a new immutable version is created
    so historical evaluations always reference the exact definition they used.
    """
    rubric = _load_rubric_scoped(db, user, rubric_id)
    _require_rubric_admin(db, user, rubric)

    if payload.definition is not None:
        validation = rs.validate_rubric_definition(payload.definition)
        if not validation["valid"]:
            raise HTTPException(status_code=422, detail={"message": "Rubric definition has validation errors.", "errors": validation["errors"]})
        normalized = rs.normalize_definition(payload.definition)
        latest = db.query(RubricVersion).filter(RubricVersion.rubric_id == rubric.id).order_by(RubricVersion.version_number.desc()).first()
        next_number = (latest.version_number if latest else 0) + 1
        # Only bump a version when the definition actually changed
        if latest is None or latest.definition != normalized:
            db.add(RubricVersion(rubric_id=rubric.id, version_number=next_number, definition=normalized, created_by=user.id))
            rubric.current_version = next_number

    if payload.name is not None:
        rubric.name = payload.name.strip()
    if payload.description is not None:
        rubric.description = payload.description
    db.commit()
    db.refresh(rubric)
    log_action(db, user_id=user.id, action="rubric.update", entity_type="rubric", entity_id=rubric.id,
               details={"name": rubric.name, "current_version": rubric.current_version,
                        "definition_changed": payload.definition is not None}, request=request)
    return rubric


@router.delete("/{rubric_id}", status_code=204)
def delete_rubric(rubric_id: int, db: DbSession, user: AdminPM, request: Request):
    rubric = _load_rubric_scoped(db, user, rubric_id)
    _require_rubric_admin(db, user, rubric)
    from app.models.evaluation import EvaluationRun
    used = db.query(EvaluationRun).filter(EvaluationRun.rubric_id == rubric_id).count()
    if used:
        raise HTTPException(status_code=409, detail=(
            "Rubric is referenced by existing evaluation runs and cannot be deleted."
        ))
    name = rubric.name
    db.delete(rubric)
    db.commit()
    log_action(db, user_id=user.id, action="rubric.delete", entity_type="rubric", entity_id=rubric_id, details={"name": name}, request=request)
    return None
