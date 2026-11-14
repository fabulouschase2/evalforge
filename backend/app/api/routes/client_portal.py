"""Client Portal routes — everything a client organization can do.

Isolation: every query is scoped through the caller's organization membership;
IDs from the request can never cross the tenant boundary. Internal-only notes,
worker identities and internal projects (organization_id IS NULL) are invisible
to client users on every endpoint below.

Staff-side queue endpoints (approve/reject/convert requests, publish
deliverables) require platform administrator roles.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select

from app.core.security import AdminPM, CurrentUser, DbSession, require_roles
from app.models.client import (
    ClientMessage, Deliverable, ProjectRequest,
    REQUEST_CATEGORIES, PROJECT_REQUEST_STATUSES,
)
from app.models.dataset import Dataset
from app.models.organization import OrganizationMember
from app.models.project import Project
from app.models.user import UserRole
from app.schemas import ProjectRequestCreate
from app.services import client_portal as cp
from app.services import datasets as ds
from app.services import file_storage
from app.services import org_access
from app.services.audit import log_action
from app.services.notifications import notify

router = APIRouter(prefix="/api/client", tags=["client-portal"])
admin_router = APIRouter(prefix="/api/admin/project-requests", tags=["client-portal"])

ALLOWED_UPLOAD_EXT = {".csv", ".json", ".jsonl", ".ndjson"}
MAX_REQUEST_ATTACHMENTS_MB = 10


# --------------------------------------------------------------------------
# Client-side helpers
# --------------------------------------------------------------------------

def _require_client(db: DbSession, user: CurrentUser, write: bool = False) -> tuple[int, OrganizationMember]:
    """Resolve the caller's single organization membership (client roles only).

    A client user belongs to exactly one organization in this design; if their
    account is in several, `org_id` selects explicitly per call site.
    """
    if user.role not in UserRole.CLIENT_ROLES:
        raise HTTPException(status_code=403, detail="Client role required.")
    if write and user.role not in UserRole.CLIENT_WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Your client role is read-only.")
    org_ids = org_access.org_ids_for_user(db, user)
    if not org_ids:
        raise HTTPException(status_code=403, detail="You are not part of an organization yet.")
    if len(org_ids) > 1:
        raise HTTPException(status_code=400, detail="Account is in multiple organizations; pass org_id.")
    org_id = next(iter(org_ids))
    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if member is None:  # defensive: membership removed mid-session
        raise HTTPException(status_code=403, detail="Organization membership not found.")
    return org_id, member


def _require_org_project(db: DbSession, org_id: int, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Project not found in your organization.")
    return project


# --------------------------------------------------------------------------
# Client dashboard / projects
# --------------------------------------------------------------------------

@router.get("/dashboard")
def client_dashboard(db: DbSession, user: CurrentUser):
    org_id, _ = _require_client(db, user)
    data = cp.client_dashboard(db, org_id)
    data["recent_activity"] = cp.client_activity(db, org_id)
    return data


@router.get("/projects")
def client_projects(db: DbSession, user: CurrentUser, status: str | None = None):
    org_id, _ = _require_client(db, user)
    stmt = select(Project).where(Project.organization_id == org_id).order_by(Project.created_at.desc())
    if status:
        stmt = stmt.where(Project.status == status)
    return [cp.client_project_summary(db, p) for p in db.scalars(stmt).all()]


@router.get("/projects/{project_id}")
def client_project_detail(project_id: int, db: DbSession, user: CurrentUser):
    org_id, _ = _require_client(db, user)
    project = _require_org_project(db, org_id, project_id)
    summary = cp.client_project_summary(db, project)
    summary["recent_activity"] = [
        e for e in cp.client_activity(db, org_id, limit=30) if e.get("project_id") == project.id
    ]
    return summary


# --------------------------------------------------------------------------
# Client project requests
# --------------------------------------------------------------------------

@router.get("/requests")
def client_requests(db: DbSession, user: CurrentUser, status: str | None = None):
    org_id, _ = _require_client(db, user)
    stmt = select(ProjectRequest).where(ProjectRequest.organization_id == org_id)
    if status:
        stmt = stmt.where(ProjectRequest.status == status)
    rows = db.scalars(stmt.order_by(ProjectRequest.created_at.desc())).all()
    return [_request_out(r) for r in rows]


@router.post("/requests", status_code=201)
def create_request(payload: ProjectRequestCreate, db: DbSession, user: CurrentUser, request: Request):
    org_id, _ = _require_client(db, user, write=True)
    if payload.category not in REQUEST_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Unknown category; allowed: {REQUEST_CATEGORIES}")
    if payload.expected_task_volume is not None and payload.expected_task_volume < 0:
        raise HTTPException(status_code=422, detail="expected_task_volume must be >= 0.")
    req = ProjectRequest(
        organization_id=org_id,
        submitted_by=user.id,
        title=payload.title.strip(),
        description=payload.description,
        category=payload.category,
        evaluation_types=payload.evaluation_types or [],
        expected_task_volume=payload.expected_task_volume,
        required_languages=payload.required_languages or [],
        required_skills=payload.required_skills or [],
        dataset_availability=payload.dataset_availability,
        expected_delivery=payload.expected_delivery,
        quality_requirements=payload.quality_requirements,
        special_instructions=payload.special_instructions,
        attachments=[],
        status="submitted",
        admin_history=[{"by": user.name, "role": "client", "action": "submitted", "at": _now_iso()}],
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    log_action(db, user_id=user.id, action="client.request_create", entity_type="project_request",
               entity_id=req.id, details={"title": req.title, "category": req.category}, request=request)
    cp.notify_staff_of_project_request_queue(db, req)
    return _request_out(req)


@router.post("/requests/{request_id}/attachments")
async def upload_request_attachment(
    request_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    file: UploadFile = File(...),
):
    org_id, _ = _require_client(db, user, write=True)
    req = db.get(ProjectRequest, request_id)
    if req is None or req.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Request not found in your organization.")
    if req.status not in ("draft", "submitted", "more_info_required"):
        raise HTTPException(status_code=409, detail="Attachments can only be added while the request is open.")
    filename = file.filename or "attachment"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(status_code=415, detail=f"Unsupported file type; allowed: {sorted(ALLOWED_UPLOAD_EXT)}")
    content = await file.read()
    if len(content) > MAX_REQUEST_ATTACHMENTS_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_REQUEST_ATTACHMENTS_MB} MB limit.")
    key = file_storage.save_bytes("attachments", content, ext.lstrip("."))
    attachments = list(req.attachments or [])
    attachments.append({"filename": filename, "size": len(content), "path": key})
    req.attachments = attachments
    db.commit()
    log_action(db, user_id=user.id, action="client.request_attachment", entity_type="project_request",
               entity_id=req.id, details={"filename": filename}, request=request)
    return {"attachments": attachments}


def _request_out(r: ProjectRequest) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "description": r.description,
        "category": r.category,
        "evaluation_types": r.evaluation_types or [],
        "expected_task_volume": r.expected_task_volume,
        "required_languages": r.required_languages or [],
        "required_skills": r.required_skills or [],
        "dataset_availability": r.dataset_availability,
        "expected_delivery": r.expected_delivery.isoformat() if r.expected_delivery else None,
        "quality_requirements": r.quality_requirements,
        "special_instructions": r.special_instructions,
        "attachments": [
            {"filename": a.get("filename"), "size": a.get("size")} for a in (r.attachments or [])
        ],
        "status": r.status,
        "admin_response": r.admin_response,
        "admin_history": r.admin_history or [],
        "converted_project_id": r.converted_project_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Client dataset uploads (org-scoped, validated, reported)
# --------------------------------------------------------------------------

@router.post("/projects/{project_id}/datasets", status_code=201)
async def client_upload_dataset(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    file: UploadFile = File(...),
    dataset_name: str | None = Form(None),
    notes: str | None = Form(None),
):
    org_id, _ = _require_client(db, user, write=True)
    project = _require_org_project(db, org_id, project_id)
    if project.status not in ("draft", "active"):
        raise HTTPException(status_code=409, detail="This project is not accepting uploads.")

    filename = file.filename or "upload"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(status_code=415, detail=f"Unsupported file type; allowed: {sorted(ALLOWED_UPLOAD_EXT)}")
    from app.core.config import settings
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {settings.max_upload_mb} MB limit.")

    fmt = ds.detect_format(filename, content)
    try:
        rows = ds.parse_file(content, fmt)
    except ds.DatasetImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    dataset = Dataset(
        name=(dataset_name or filename.rsplit(".", 1)[0])[:255],
        description=notes,
        project_id=project.id,
        created_by=user.id,
        format=fmt,
        source_filename=filename,
    )
    db.add(dataset)
    db.flush()
    try:
        version, report = ds.commit_import(
            db, dataset, rows, column_mapping=None,
            record_id_column=None, expected_label_column=None,
            notes=notes or "Client upload", fmt=fmt, source_filename=filename,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))

    log_action(db, user_id=user.id, action="client.dataset_upload", entity_type="dataset",
               entity_id=dataset.id,
               details={"filename": filename, "rows": report["total_rows"],
                        "valid": report["valid_count"], "invalid": report["invalid_count"]},
               request=request)
    cp.notify_staff_of_project(db, project.id, "client.dataset_uploaded",
                               f"Client uploaded a dataset to {project.name}",
                               f"{filename}: {report['valid_count']} valid, {report['invalid_count']} invalid rows.",
                               entity_type="dataset", entity_id=dataset.id)
    return {
        "dataset": {"id": dataset.id, "name": dataset.name, "format": fmt,
                    "version": version.version_number},
        "report": report,
    }


@router.get("/projects/{project_id}/datasets/{dataset_id}/records")
def client_dataset_records(
    project_id: int,
    dataset_id: int,
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    org_id, _ = _require_client(db, user)
    _require_org_project(db, org_id, project_id)
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or dataset.project_id != project_id:
        raise HTTPException(status_code=404, detail="Dataset not found in this project.")
    records, total = ds.list_records(db, dataset_id, None, page, page_size)
    return {
        "items": [
            {
                "id": r.id,
                "record_id": r.record_id,
                "prompt": r.prompt,
                "response": r.response,
                "content_category": r.content_category,
                "language": r.language,
                "collection_status": r.collection_status,
            }
            for r in records
        ],
        "total": total, "page": page, "page_size": page_size,
    }


# --------------------------------------------------------------------------
# Client messaging
# --------------------------------------------------------------------------

@router.get("/projects/{project_id}/messages")
def client_messages(project_id: int, db: DbSession, user: CurrentUser):
    org_id, _ = _require_client(db, user)
    _require_org_project(db, org_id, project_id)
    rows = db.scalars(
        select(ClientMessage).where(
            ClientMessage.project_id == project_id,
            ClientMessage.is_internal.is_(False),  # internal staff notes never leave
        ).order_by(ClientMessage.created_at.asc())
    ).all()
    out = []
    for m in rows:
        out.append(_message_out(m))
        if m.sender_side == "staff" and not m.read_by_client:
            m.read_by_client = True
    db.commit()
    return out


def _message_out(m: ClientMessage) -> dict:
    return {
        "id": m.id,
        "sender_side": m.sender_side,
        "sender_name": ("Project team" if m.sender_side == "staff" else
                        (m.sender.name if m.sender else "Client")),
        "body": m.body,
        "attachment": ({"name": m.attachment_name} if m.attachment_name else None),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.post("/projects/{project_id}/messages", status_code=201)
def client_send_message(
    project_id: int,
    payload: dict,
    db: DbSession,
    user: CurrentUser,
    request: Request,
):
    org_id, _ = _require_client(db, user, write=True)
    project = _require_org_project(db, org_id, project_id)
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=422, detail="Message body is required.")
    msg = ClientMessage(
        project_id=project.id,
        organization_id=org_id,
        sender_id=user.id,
        sender_side="client",
        body=body,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    log_action(db, user_id=user.id, action="client.message_send", entity_type="project",
               entity_id=project.id, request=request)
    cp.notify_staff_of_project(db, project.id, "client.message",
                               f"New client message on {project.name}",
                               body[:200], entity_type="project", entity_id=project.id)
    return _message_out(msg)


# --------------------------------------------------------------------------
# Client deliverables
# --------------------------------------------------------------------------

@router.get("/deliverables")
def client_deliverables(db: DbSession, user: CurrentUser, project_id: int | None = None):
    org_id, _ = _require_client(db, user)
    stmt = select(Deliverable).where(Deliverable.organization_id == org_id)
    if project_id:
        stmt = stmt.where(Deliverable.project_id == project_id)
    rows = db.scalars(stmt.order_by(Deliverable.published_at.desc())).all()
    return [_deliverable_out(db, d) for d in rows]


def _deliverable_out(db: DbSession, d: Deliverable) -> dict:
    project = db.get(Project, d.project_id)
    return {
        "id": d.id,
        "project_id": d.project_id,
        "project_name": project.name if project else None,
        "label": d.label,
        "description": d.description,
        "export_format": d.export_format,
        "record_count": d.record_count,
        "file_size": d.file_size,
        "checksum_sha256": d.checksum_sha256,
        "download_count": d.download_count,
        "published_at": d.published_at.isoformat() if d.published_at else None,
    }


@router.get("/deliverables/{deliverable_id}/download")
def client_download_deliverable(
    deliverable_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
):
    org_id, _ = _require_client(db, user)
    d = db.get(Deliverable, deliverable_id)
    if d is None or d.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Deliverable not found in your organization.")
    # streamed to avoid loading large files fully into memory
    from fastapi.responses import StreamingResponse
    d.download_count = (d.download_count or 0) + 1
    db.commit()
    log_action(db, user_id=user.id, action="deliverable.download", entity_type="deliverable",
               entity_id=d.id,
               details={"project_id": d.project_id, "label": d.label, "format": d.export_format},
               request=request)
    filename = f"{(d.label or 'deliverable').replace(' ', '_')}.{d.export_format}"
    return StreamingResponse(
        file_storage.open_key_streamed(d.file_path),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==========================================================================
# Staff-side: request approval queue + deliverable publishing
# ==========================================================================

@router.get("/admin/requests", deprecated=True, include_in_schema=False)
def _legacy_alias():  # keeps /api/client/admin/* from colliding
    raise HTTPException(status_code=404)


@admin_router.get("")
def admin_list_requests(
    db: DbSession,
    user: AdminPM,
    status: str | None = None,
):
    stmt = select(ProjectRequest)
    if status:
        stmt = stmt.where(ProjectRequest.status == status)
    rows = db.scalars(stmt.order_by(ProjectRequest.created_at.desc())).all()
    out = []
    for r in rows:
        item = _request_out(r)
        item["organization_name"] = cp.org_display_name(db, r.organization_id)
        item["submitted_by_name"] = r.submitter.name if r.submitter else None
        out.append(item)
    return out


@admin_router.get("/{request_id}")
def admin_get_request(request_id: int, db: DbSession, user: AdminPM):
    r = db.get(ProjectRequest, request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Request not found.")
    item = _request_out(r)
    item["organization_name"] = cp.org_display_name(db, r.organization_id)
    item["submitted_by_name"] = r.submitter.name if r.submitter else None
    return item


@admin_router.post("/{request_id}/review")
def admin_review_request(
    request_id: int,
    payload: dict,
    db: DbSession,
    user: AdminPM,
    request: Request,
):
    """Approve / reject / request-more-information with an explanation."""
    r = db.get(ProjectRequest, request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Request not found.")
    action = (payload.get("action") or "").strip()
    note = (payload.get("note") or "").strip()
    mapping = {
        "approve": "approved",
        "reject": "rejected",
        "more_info": "more_info_required",
        "under_review": "under_review",
    }
    if action not in mapping:
        raise HTTPException(status_code=422, detail=f"action must be one of {sorted(mapping)}")
    if action in ("reject", "more_info") and not note:
        raise HTTPException(status_code=422, detail="An explanation is required to reject or request information.")
    if r.status == "converted":
        raise HTTPException(status_code=409, detail="This request was already converted to a project.")
    r.status = mapping[action]
    r.admin_response = note or None
    r.reviewed_by = user.id
    r.reviewed_at = datetime.now(timezone.utc)
    history = list(r.admin_history or [])
    history.append({"by": user.name, "role": "staff", "action": action, "note": note, "at": _now_iso()})
    r.admin_history = history
    db.commit()
    log_action(db, user_id=user.id, action="client.request_review", entity_type="project_request",
               entity_id=r.id, details={"action": action}, request=request)
    status_text = {
        "approve": "approved", "reject": "rejected",
        "more_info": "marked as 'more information required'", "under_review": "moved to review",
    }[action]
    cp.notify_org_members(db, r.organization_id, "client.request_update",
                          f"Your project request was {status_text}",
                          f"Request '{r.title}' — {note}" if note else f"Request '{r.title}'.",
                          entity_type="project_request", entity_id=r.id)
    return _request_out(r)


@admin_router.post("/{request_id}/convert")
def admin_convert_request(request_id: int, db: DbSession, user: AdminPM, request: Request):
    """Convert an approved request into a real project (no information lost)."""
    r = db.get(ProjectRequest, request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Request not found.")
    if r.status == "converted":
        raise HTTPException(status_code=409, detail="Already converted.")
    if r.status not in ("approved", "under_review", "more_info_required"):
        raise HTTPException(status_code=409, detail="Approve the request before converting it.")

    project = Project(
        name=r.title,
        description=r.description,
        owner_id=user.id,
        organization_id=r.organization_id,
        client=cp.org_display_name(db, r.organization_id),
        project_type=r.category if r.category in (
            "ai_response_evaluation", "data_annotation", "text_classification",
            "factuality_verification", "instruction_following_evaluation",
            "coding_evaluation", "image_annotation", "video_annotation",
        ) else "custom_evaluation",
        instructions=r.special_instructions,
        required_skills=r.required_skills or [],
        supported_languages=r.required_languages or [],
        status="active",
        quality_requirements=r.quality_requirements,
        target_task_volume=r.expected_task_volume,
        blind_review=True,
    )
    db.add(project)
    db.flush()
    from app.models.project import ProjectMember
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="admin", added_by=user.id))
    r.status = "converted"
    r.converted_project_id = project.id
    history = list(r.admin_history or [])
    history.append({"by": user.name, "role": "staff", "action": "converted",
                    "note": f"Project #{project.id}", "at": _now_iso()})
    r.admin_history = history
    db.commit()
    db.refresh(project)
    log_action(db, user_id=user.id, action="client.request_convert", entity_type="project_request",
               entity_id=r.id, details={"project_id": project.id}, request=request)
    cp.notify_org_members(db, r.organization_id, "client.request_update",
                          f"Your request became project '{project.name}'",
                          "Track progress in My Projects.",
                          entity_type="project", entity_id=project.id)
    return {"project_id": project.id, "request": _request_out(r)}


# --- Staff: publish deliverables -------------------------------------------

publish_router = APIRouter(prefix="/api/admin/projects", tags=["client-portal"])


@publish_router.get("/{project_id}/deliverables")
def admin_list_deliverables(project_id: int, db: DbSession, user: AdminPM):
    _require_admin_project(db, user, project_id)
    rows = db.scalars(
        select(Deliverable).where(Deliverable.project_id == project_id)
        .order_by(Deliverable.published_at.desc())
    ).all()
    return [_deliverable_out(db, d) for d in rows]


@publish_router.post("/{project_id}/deliverables", status_code=201)
def admin_publish_deliverable(
    project_id: int,
    payload: dict,
    db: DbSession,
    user: AdminPM,
    request: Request,
):
    """Package the project's approved results and publish to the client org."""
    project = _require_admin_project(db, user, project_id)
    if project.organization_id is None:
        raise HTTPException(status_code=422, detail="This project has no client organization.")
    fmt = (payload.get("format") or "json").lower()
    if fmt not in ("json", "csv", "jsonl"):
        raise HTTPException(status_code=422, detail="format must be json, csv or jsonl.")
    key, size, count, digest = cp.build_deliverable_file(db, project, fmt)
    d = Deliverable(
        project_id=project.id,
        organization_id=project.organization_id,
        label=(payload.get("label") or f"{project.name} approved results").strip()[:255],
        description=payload.get("description"),
        export_format=fmt,
        dataset_version_id=payload.get("dataset_version_id"),
        file_path=key,
        file_size=size,
        record_count=count,
        checksum_sha256=digest,
        published_by=user.id,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    log_action(db, user_id=user.id, action="deliverable.publish", entity_type="deliverable",
               entity_id=d.id,
               details={"project_id": project.id, "format": fmt, "records": count},
               request=request)
    cp.notify_org_members(db, project.organization_id, "client.deliverable_published",
                          f"New deliverable published: {d.label}",
                          f"{count} approved results ({fmt}) are ready to download.",
                          entity_type="deliverable", entity_id=d.id)
    return _deliverable_out(db, d)


def _require_admin_project(db: DbSession, user, project_id: int) -> Project:
    from app.services import access as acl
    try:
        return acl.require_project(db, user, project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# --- Staff: project message thread (replies + internal notes) ----------------


@publish_router.get("/{project_id}/messages")
def admin_list_messages(project_id: int, db: DbSession, user: AdminPM):
    """Staff view of the client thread — includes internal notes."""
    project = _require_admin_project(db, user, project_id)
    rows = db.scalars(
        select(ClientMessage).where(ClientMessage.project_id == project.id)
        .order_by(ClientMessage.created_at.asc())
    ).all()
    out = []
    for m in rows:
        out.append(_message_out(m) | {
            "is_internal": m.is_internal,
            "read_by_staff": m.read_by_staff,
        })
        if m.sender_side == "client" and not m.read_by_staff:
            m.read_by_staff = True
    db.commit()
    return out


@publish_router.post("/{project_id}/messages", status_code=201)
def admin_send_message(project_id: int, payload: dict, db: DbSession, user: AdminPM, request: Request):
    """Staff reply to the client, or an internal note (is_internal=true)."""
    project = _require_admin_project(db, user, project_id)
    if project.organization_id is None:
        raise HTTPException(status_code=422, detail="This project has no client organization.")
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=422, detail="Message body is required.")
    is_internal = bool(payload.get("is_internal"))
    msg = ClientMessage(
        project_id=project.id,
        organization_id=project.organization_id,
        sender_id=user.id,
        sender_side="staff",
        body=body,
        is_internal=is_internal,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    log_action(db, user_id=user.id, action="staff.message_send", entity_type="project",
               entity_id=project.id, details={"is_internal": is_internal}, request=request)
    if not is_internal:
        cp.notify_org_members(db, project.organization_id, "client.message",
                              f"New message on {project.name}", body[:200],
                              entity_type="project", entity_id=project.id)
    return _message_out(msg) | {"is_internal": is_internal}
