"""Dataset routes: create, upload/preview/commit import, versions, records, delete.

V3: every read is project-membership scoped (client roles see only their
organization's datasets; workers only their projects; staff additionally see
projectless datasets they manage).
"""
import json

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from app.core.config import settings
from app.core.security import AdminPM, AdminPMEvaluator, CurrentUser, DbSession
from app.models.dataset import Dataset, DatasetVersion
from app.schemas import (
    DatasetOut,
    DatasetVersionOut,
    ImportPreviewRequest,
    PaginatedOut,
    RecordOut,
)
from app.services import access as acl
from app.services import datasets as ds
from app.services.audit import log_action

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

ALLOWED = {".csv", ".json", ".jsonl", ".ndjson"}


def _load_dataset_scoped(db: DbSession, user: CurrentUser, dataset_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    try:
        acl.require_dataset_read(db, user, dataset)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return dataset


def _load_dataset_for_admin(db: DbSession, user, dataset_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    try:
        acl.require_dataset_edit(db, user, dataset)
    except acl.DatasetArchived as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return dataset


@router.post("", response_model=DatasetOut, status_code=201)
def create_dataset(payload: dict, db: DbSession, user: AdminPMEvaluator, request: Request):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Dataset name is required.")
    dataset = Dataset(
        name=name,
        description=payload.get("description"),
        project_id=payload.get("project_id"),
        created_by=user.id,
        format="json",
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    log_action(db, user_id=user.id, action="dataset.create", entity_type="dataset", entity_id=dataset.id, details={"name": name}, request=request)
    return dataset


@router.get("", response_model=list[DatasetOut])
def list_datasets(db: DbSession, user: CurrentUser, project_id: int | None = None):
    visibility = acl.dataset_visibility(db, user)
    stmt = db.query(Dataset)
    if not visibility.get("all"):
        ids = visibility.get("project_ids") or set()
        conds = []
        if ids:
            conds.append(Dataset.project_id.in_(ids))
        if visibility.get("include_projectless"):
            conds.append(Dataset.project_id.is_(None))
        if not conds:
            return []
        stmt = stmt.filter(*conds)
    stmt = stmt.order_by(Dataset.created_at.desc())
    if project_id:
        stmt = stmt.filter(Dataset.project_id == project_id)
    return list(stmt.all())


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: int, db: DbSession, user: CurrentUser):
    return _load_dataset_scoped(db, user, dataset_id)


@router.get("/{dataset_id}/versions", response_model=list[DatasetVersionOut])
def list_versions(dataset_id: int, db: DbSession, user: CurrentUser):
    _load_dataset_scoped(db, user, dataset_id)
    return list(db.query(DatasetVersion).filter(DatasetVersion.dataset_id == dataset_id).order_by(DatasetVersion.version_number.desc()).all())


@router.post("/{dataset_id}/upload/preview")
async def upload_preview(
    dataset_id: int,
    db: DbSession,
    user: AdminPMEvaluator,
    request: Request,
    file: UploadFile = File(...),
    column_mapping: str | None = Form(None),
    record_id_column: str | None = Form(None),
    expected_label_column: str | None = Form(None),
):
    dataset = _load_dataset_for_admin(db, user, dataset_id)

    filename = file.filename or "upload"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED:
        raise HTTPException(status_code=415, detail=f"Unsupported file type {ext or '(none)'}; allowed: {sorted(ALLOWED)}.")

    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {settings.max_upload_mb} MB limit.")

    fmt = ds.detect_format(filename, content)
    try:
        rows = ds.parse_file(content, fmt)
    except ds.DatasetImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    mapping = json.loads(column_mapping) if column_mapping else None
    report = ds.analyze_import(rows, mapping, record_id_column, expected_label_column)
    report["format"] = fmt
    log_action(db, user_id=user.id, action="dataset.upload_preview", entity_type="dataset", entity_id=dataset_id,
               details={"filename": filename, "rows": report["total_rows"]}, request=request)
    return report


@router.post("/{dataset_id}/upload/commit", response_model=DatasetVersionOut, status_code=201)
async def upload_commit(
    dataset_id: int,
    db: DbSession,
    user: AdminPMEvaluator,
    request: Request,
    file: UploadFile = File(...),
    column_mapping: str | None = Form(None),
    record_id_column: str | None = Form(None),
    expected_label_column: str | None = Form(None),
    notes: str | None = Form(None),
):
    dataset = _load_dataset_for_admin(db, user, dataset_id)

    filename = file.filename or "upload"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED:
        raise HTTPException(status_code=415, detail=f"Unsupported file type; allowed: {sorted(ALLOWED)}.")
    content = await file.read()
    fmt = ds.detect_format(filename, content)
    try:
        rows = ds.parse_file(content, fmt)
    except ds.DatasetImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    mapping = json.loads(column_mapping) if column_mapping else None
    try:
        version, report = ds.commit_import(
            db, dataset, rows,
            column_mapping=mapping,
            record_id_column=record_id_column,
            expected_label_column=expected_label_column,
            notes=notes,
            fmt=fmt,
            source_filename=filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    log_action(db, user_id=user.id, action="dataset.import", entity_type="dataset", entity_id=dataset.id,
               details={
                   "filename": filename,
                   "format": fmt,
                   "version": version.version_number,
                   "valid": report["valid_count"],
                   "invalid": report["invalid_count"],
                   "duplicates": report["duplicate_count"],
               }, request=request)
    return version


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, db: DbSession, user: AdminPM, request: Request):
    dataset = _load_dataset_for_admin(db, user, dataset_id)
    # Guardrail: evaluation runs reference dataset versions; block deletes that would break history.
    if dataset.versions and any(v.id for v in dataset.versions):
        from app.models.evaluation import EvaluationRun
        used = db.query(EvaluationRun).filter(EvaluationRun.dataset_id == dataset_id).count()
        if used:
            raise HTTPException(status_code=409, detail=(
                "Dataset is referenced by existing evaluation runs and cannot be deleted "
                "(historical evaluations must remain reproducible)."
            ))
    name = dataset.name
    db.delete(dataset)
    db.commit()
    log_action(db, user_id=user.id, action="dataset.delete", entity_type="dataset", entity_id=dataset_id, details={"name": name}, request=request)
    return None
