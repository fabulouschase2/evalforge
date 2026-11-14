"""Data collection routes: record CRUD, bulk paste, archive/restore, export.

Every route enforces project-level access through services.access — a tester
or reviewer can only read records of their own projects, and only staff who
administer the project may modify data.
"""
import json

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, select

from app.core.security import AdminPM, AdminPMEvaluator, CurrentUser, DbSession
from app.models.dataset import Dataset, DatasetRecord
from app.models.task import Task
from app.services import access as acl
from app.services import collection as col
from app.services.audit import log_action

router = APIRouter(prefix="/api/datasets", tags=["data-collection"])


def _load_dataset_for_read(db: DbSession, user: CurrentUser, dataset_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    if dataset.project_id:
        try:
            acl.require_project(db, user, dataset.project_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    elif user.role not in ("super_admin", "project_admin", "project_manager"):
        raise HTTPException(status_code=403, detail="Datasets without a project are staff-only.")
    return dataset


def _load_dataset_for_edit(db: DbSession, user: AdminPMEvaluator, dataset_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    if dataset.status == "archived":
        raise HTTPException(status_code=409, detail="Dataset is archived and read-only. Restore it first.")
    if dataset.project_id:
        project = acl.require_project(db, user, dataset.project_id)
        try:
            acl.require_project_admin(db, user, project)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
    elif user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Datasets without a project are managed by super admins only.")
    return dataset


@router.get("/{dataset_id}/records")
def list_records(
    dataset_id: int,
    db: DbSession,
    user: CurrentUser,
    version_id: int | None = None,
    status: str | None = None,
    category: str | None = None,
    language: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    dataset = _load_dataset_for_read(db, user, dataset_id)
    stmt = select(DatasetRecord).where(DatasetRecord.dataset_id == dataset_id)
    if version_id:
        stmt = stmt.where(DatasetRecord.dataset_version_id == version_id)
    if status:
        stmt = stmt.where(DatasetRecord.collection_status == status)
    if category:
        stmt = stmt.where(DatasetRecord.content_category == category)
    if language:
        stmt = stmt.where(DatasetRecord.language == language)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(DatasetRecord.prompt.ilike(like) | DatasetRecord.response.ilike(like))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(DatasetRecord.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [_record_out(r) for r in items],
        "total": int(total), "page": page, "page_size": page_size,
        "dataset_status": dataset.status,
    }


def _record_out(r: DatasetRecord) -> dict:
    return {
        "id": r.id,
        "record_id": r.record_id,
        "prompt": r.prompt,
        "response": r.response,
        "reference_answer": r.reference_answer,
        "reference_sources": r.reference_sources or [],
        "expected_label": r.expected_label,
        "gold_explanation": r.gold_explanation,
        "metadata": r.record_metadata or {},
        "supporting_evidence": r.supporting_evidence,
        "source_url": r.source_url,
        "content_category": r.content_category,
        "difficulty_level": r.difficulty_level,
        "language": r.language or "en",
        "instructions": r.instructions,
        "collection_status": r.collection_status or "collected",
        "custom_fields": r.custom_fields or {},
        "version_id": r.dataset_version_id,
    }


@router.post("/{dataset_id}/records", status_code=201)
def create_record(dataset_id: int, payload: dict, db: DbSession, user: AdminPMEvaluator, request: Request):
    dataset = _load_dataset_for_edit(db, user, dataset_id)
    record, errors = col.create_manual_record(db, dataset, payload, user)
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Record rejected.", "errors": errors})
    log_action(db, user_id=user.id, action="record.create", entity_type="dataset_record", entity_id=record.id,
               details={"dataset_id": dataset_id, "record_id": record.record_id}, request=request)
    return _record_out(record)


@router.post("/{dataset_id}/records/bulk")
def bulk_add_records(dataset_id: int, payload: dict, db: DbSession, user: AdminPMEvaluator, request: Request):
    dataset = _load_dataset_for_edit(db, user, dataset_id)
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=422, detail="'rows' must be a non-empty JSON array of record objects.")
    if len(rows) > 5000:
        raise HTTPException(status_code=413, detail="Bulk paste is limited to 5000 rows per call.")
    report = col.bulk_add_records(db, dataset, rows, user)
    log_action(db, user_id=user.id, action="record.bulk_create", entity_type="dataset", entity_id=dataset_id,
               details={"added": report["added"], "rejected": len(report["rejected"]), "total": report["total"]},
               request=request)
    return report


@router.patch("/{dataset_id}/records/{record_pk}")
def edit_record(dataset_id: int, record_pk: int, payload: dict, db: DbSession, user: AdminPMEvaluator, request: Request):
    dataset = _load_dataset_for_edit(db, user, dataset_id)
    record = db.get(DatasetRecord, record_pk)
    if record is None or record.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="Record not found in this dataset.")
    if not col.record_editable(db, record):
        raise HTTPException(status_code=409, detail=(
            "This record is referenced by existing tasks and is frozen for traceability. "
            "Cancel those tasks or create a new record instead."
        ))
    errors = col.apply_record_edit(record, payload, dataset)
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Update rejected.", "errors": errors})
    db.commit()
    log_action(db, user_id=user.id, action="record.edit", entity_type="dataset_record", entity_id=record.id,
               details={"dataset_id": dataset_id, "fields": list(payload.keys())}, request=request)
    return _record_out(record)


@router.delete("/{dataset_id}/records/{record_pk}", status_code=204)
def delete_record(dataset_id: int, record_pk: int, db: DbSession, user: AdminPM, request: Request):
    dataset = _load_dataset_for_edit(db, user, dataset_id)
    record = db.get(DatasetRecord, record_pk)
    if record is None or record.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="Record not found in this dataset.")
    if not col.record_editable(db, record):
        raise HTTPException(status_code=409, detail="Record is referenced by tasks and cannot be deleted.")
    rid = record.record_id
    db.delete(record)
    db.commit()
    log_action(db, user_id=user.id, action="record.delete", entity_type="dataset", entity_id=dataset_id,
               details={"record_id": rid}, request=request)
    return None


@router.post("/{dataset_id}/archive", status_code=204)
def archive_dataset(dataset_id: int, db: DbSession, user: AdminPM, request: Request):
    dataset = _load_dataset_for_edit(db, user, dataset_id)
    dataset.status = "archived"
    db.commit()
    log_action(db, user_id=user.id, action="dataset.archive", entity_type="dataset", entity_id=dataset_id, request=request)
    return None


@router.post("/{dataset_id}/restore", status_code=204)
def restore_dataset(dataset_id: int, db: DbSession, user: AdminPM, request: Request):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    try:
        acl.require_dataset_edit(db, user, dataset, allow_archived=True)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    dataset.status = "active"
    db.commit()
    log_action(db, user_id=user.id, action="dataset.restore", entity_type="dataset", entity_id=dataset_id, request=request)
    return None


@router.get("/{dataset_id}/export")
def export_dataset(dataset_id: int, db: DbSession, user: AdminPMEvaluator, request: Request, format: str = Query("json", pattern="^(json|csv)$")):
    dataset = _load_dataset_for_read(db, user, dataset_id)
    if dataset.project_id:
        project = acl.require_project(db, user, dataset.project_id)
        try:
            acl.require_project_admin(db, user, project)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Export requires project administration rights.")
    content, media_type, filename = col.export_dataset(db, dataset, format)
    log_action(db, user_id=user.id, action="dataset.export", entity_type="dataset", entity_id=dataset_id,
               details={"format": format}, request=request)
    return Response(
        content=content, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{dataset_id}/custom-fields")
def get_custom_fields(dataset_id: int, db: DbSession, user: CurrentUser):
    dataset = _load_dataset_for_read(db, user, dataset_id)
    return {"definitions": dataset.custom_field_definitions or []}


@router.put("/{dataset_id}/custom-fields")
def set_custom_fields(dataset_id: int, payload: dict, db: DbSession, user: AdminPMEvaluator, request: Request):
    dataset = _load_dataset_for_edit(db, user, dataset_id)
    definitions = payload.get("definitions", [])
    errors = col.validate_custom_field_definitions(definitions)
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Invalid field definitions.", "errors": errors})
    dataset.custom_field_definitions = definitions
    db.commit()
    log_action(db, user_id=user.id, action="dataset.custom_fields_update", entity_type="dataset", entity_id=dataset_id,
               details={"count": len(definitions)}, request=request)
    return {"definitions": definitions}
