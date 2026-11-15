"""External API surface (/api/ext/v1) — scoped, org-bound, idempotent.

Authorization is credential-based ONLY (never user JWT): scopes + organization
+ project allowlist. Write endpoints honor an Idempotency-Key header: a retried
request with the same key returns the stored response instead of re-processing.
"""
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.api_auth import ApiAuth, get_api_credential
from app.core.security import DbSession
from app.models.api_integration import IdempotencyKey
from app.models.dataset import Dataset, DatasetRecord
from app.models.project import Project
from app.models.submission import Submission
from app.models.task import Task
from app.services import datasets as ds
from app.services import webhooks as wh

router = APIRouter(prefix="/api/ext/v1", tags=["external-api"])


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------

def _visible_projects(db: Session, ctx) -> list[Project]:
    stmt = select(Project)
    if ctx.organization_id is not None:
        stmt = stmt.where(Project.organization_id == ctx.organization_id)
    rows = db.scalars(stmt.order_by(Project.id)).all()
    allow = ctx.credential.project_ids or []
    return [p for p in rows if not allow or p.id in allow]


def _allowed_project(db: Session, ctx, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None or not ctx.project_allowed(project_id, project.organization_id):
        raise HTTPException(status_code=404, detail="Project not found for this credential.")
    return project


def _dataset_allowed(db: Session, ctx, dataset: Dataset | None) -> Dataset:
    if dataset is None or dataset.project_id is None:
        raise HTTPException(status_code=404, detail="Dataset not found for this credential.")
    project = db.get(Project, dataset.project_id)
    if not ctx.project_allowed(dataset.project_id, project.organization_id if project else None):
        raise HTTPException(status_code=404, detail="Dataset not found for this credential.")
    return dataset


def _idempotency_precheck(db: Session, request: Request, ctx, body: dict | None):
    """Returns (replay_response | None, idempotency_row | None).

    Concurrency-safe: a unique index on (credential_id, key) arbitrates races.
    If a concurrent request committed the same key first, the loser re-reads and
    replays the stored response instead of double-processing (V3.1).
    """
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None, None
    request_hash = hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest() if body is not None else None

    def _existing():
        return db.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.credential_id == ctx.id, IdempotencyKey.key == key[:200]
            )
        )

    existing = _existing()
    if existing is not None and existing.response_status is not None:
        if existing.request_hash and request_hash and existing.request_hash != request_hash:
            raise HTTPException(status_code=422,
                                detail="Idempotency-Key reused with a different request body.")
        return JSONResponse(status_code=existing.response_status, content=existing.response_body), None
    row = existing or IdempotencyKey(credential_id=ctx.id, key=key[:200],
                                     endpoint=str(request.url.path),
                                     request_hash=request_hash)
    db.add(row)
    try:
        db.commit()
    except Exception:
        # lost an insert race: the winner is processing (or finished) — replay it
        db.rollback()
        winner = _existing()
        if winner is not None and winner.response_status is not None:
            if winner.request_hash and request_hash and winner.request_hash != request_hash:
                raise HTTPException(status_code=422,
                                    detail="Idempotency-Key reused with a different request body.")
            return JSONResponse(status_code=winner.response_status, content=winner.response_body), None
        if winner is not None:
            # concurrent in-flight request has not stored a response yet
            raise HTTPException(status_code=409,
                                detail="An identical request with this Idempotency-Key is still in progress; retry shortly.")
        raise
    db.refresh(row)
    return None, row


def _store_idempotent(row, db: Session, status_code: int, payload: dict) -> None:
    if row is None:
        return
    row.response_status = status_code
    row.response_body = payload
    db.commit()


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------

@router.get("/projects")
def ext_projects(db: DbSession, request: Request, ctx = ApiAuth):
    ctx.require_scope("projects:read")
    return [
        {"id": p.id, "name": p.name, "status": p.status, "project_type": p.project_type,
         "description": p.description, "target_task_volume": p.target_task_volume,
         "deadline": p.deadline.isoformat() if p.deadline else None}
        for p in _visible_projects(db, ctx)
    ]


# --------------------------------------------------------------------------
# Datasets
# --------------------------------------------------------------------------

@router.get("/datasets/{dataset_id}")
def ext_dataset(dataset_id: int, db: DbSession, request: Request, ctx = ApiAuth):
    ctx.require_scope("datasets:read")
    dataset = _dataset_allowed(db, ctx, db.get(Dataset, dataset_id))
    record_count = db.scalar(select(func.count()).select_from(DatasetRecord)
                             .where(DatasetRecord.dataset_id == dataset.id)) or 0
    return {
        "id": dataset.id, "name": dataset.name, "format": dataset.format,
        "project_id": dataset.project_id, "current_version": dataset.current_version,
        "status": dataset.status, "record_count": record_count,
    }


@router.post("/datasets", status_code=201)
def ext_create_dataset(payload: dict, db: DbSession, request: Request, ctx = ApiAuth):
    ctx.require_scope("datasets:write")
    replay, row = _idempotency_precheck(db, request, ctx, payload)
    if replay is not None:
        return replay
    project = _allowed_project(db, ctx, int(payload.get("project_id", 0)))
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required.")
    dataset = Dataset(name=name, description=payload.get("description"),
                      project_id=project.id, format="json")
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    wh.dispatch_event(db, "dataset.imported", {"dataset_id": dataset.id,
                                               "project_id": project.id, "version": 0})
    body = {"id": dataset.id, "name": dataset.name, "project_id": project.id}
    _store_idempotent(row, db, 201, body)
    return body


@router.post("/datasets/{dataset_id}/records", status_code=201)
def ext_add_records(dataset_id: int, payload: dict, db: DbSession, request: Request, ctx = ApiAuth):
    """Bulk record ingestion: {"records": [{record_id, prompt, response, ...}]}"""
    ctx.require_scope("datasets:write")
    replay, row = _idempotency_precheck(db, request, ctx, payload)
    if replay is not None:
        return replay
    dataset = _dataset_allowed(db, ctx, db.get(Dataset, dataset_id))
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise HTTPException(status_code=422, detail="records list is required.")
    if len(records) > 5000:
        raise HTTPException(status_code=422, detail="Maximum 5000 records per batch.")
    normalized = ds.normalize_rows(records)
    version, report = ds.commit_import(
        db, dataset, normalized, column_mapping=None, record_id_column=None,
        expected_label_column=None,
        notes="API ingestion", fmt="json", source_filename="api",
    )
    wh.dispatch_event(db, "dataset.imported", {
        "dataset_id": dataset.id, "version": version.version_number,
        "valid": report["valid_count"], "invalid": report["invalid_count"],
    })
    body = {"dataset_id": dataset.id, "version": version.version_number, "report": report}
    _store_idempotent(row, db, 201, body)
    return body


# --------------------------------------------------------------------------
# Tasks + results
# --------------------------------------------------------------------------

@router.get("/projects/{project_id}/tasks")
def ext_tasks(project_id: int, db: DbSession, request: Request, ctx = ApiAuth,
              status: str | None = None, page: int = Query(1, ge=1),
              page_size: int = Query(50, ge=1, le=200)):
    ctx.require_scope("tasks:read")
    _allowed_project(db, ctx, project_id)
    stmt = select(Task).where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Task.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "total": int(total), "page": page, "page_size": page_size,
        "items": [
            {"id": t.id, "title": t.title, "status": t.status, "task_type": t.task_type,
             "difficulty": t.difficulty, "created_at": t.created_at.isoformat()}
            for t in rows
        ],
    }


@router.post("/projects/{project_id}/tasks", status_code=201)
def ext_create_task(project_id: int, payload: dict, db: DbSession, request: Request, ctx = ApiAuth):
    ctx.require_scope("tasks:write")
    replay, row = _idempotency_precheck(db, request, ctx, payload)
    if replay is not None:
        return replay
    project = _allowed_project(db, ctx, project_id)
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required.")
    task = Task(
        project_id=project.id, title=title[:255],
        task_type=project.project_type,
        instructions=payload.get("instructions"),
        status="available" if payload.get("publish", True) else "draft",
        priority=payload.get("priority") if payload.get("priority") in ("low", "normal", "high", "urgent") else "normal",
        difficulty=payload.get("difficulty") if payload.get("difficulty") in ("easy", "medium", "hard", "expert") else "medium",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    wh.dispatch_event(db, "task.created", {"task_id": task.id, "project_id": project.id,
                                           "title": task.title})
    body = {"id": task.id, "status": task.status}
    _store_idempotent(row, db, 201, body)
    return body


@router.get("/projects/{project_id}/results")
def ext_results(project_id: int, db: DbSession, request: Request, ctx = ApiAuth,
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    """Approved results only — review internals and worker identities stay hidden."""
    ctx.require_scope("results:read")
    _allowed_project(db, ctx, project_id)
    base = select(Submission).where(Submission.project_id == project_id,
                                    Submission.status == "approved")
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(Submission.id).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    tasks = {t.id: t for t in db.scalars(
        select(Task).where(Task.id.in_([s.task_id for s in rows] or [0]))).all()}
    return {
        "total": int(total), "page": page, "page_size": page_size,
        "items": [
            {"task_id": s.task_id, "task_title": tasks[s.task_id].title if s.task_id in tasks else None,
             "attempt": s.attempt_number, "payload": s.payload, "label": s.label,
             "explanation": s.explanation,
             "approved_at": s.decided_at.isoformat() if s.decided_at else None}
            for s in rows
        ],
    }
