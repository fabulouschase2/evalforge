"""Multimodal routes: media upload/streaming, annotation save/submit, exports.

Authorization model:
- media belongs to a project; workers need project membership, staff need
  project visibility; media is streamed with Range support (never fully
  loaded into memory).
- annotations are stored normalized; the submit path creates a Submission so
  the existing reviewer/adjudication flow applies unchanged.
"""
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.core.security import AdminPM, CurrentUser, DbSession
from app.models.annotation import (
    AudioAnnotation, ImageAnnotation, MediaAsset, VideoAnnotation,
    IMAGE_SHAPES, MEDIA_TYPES,
)
from app.models.submission import Submission
from app.models.task import Task
from app.models.user import UserRole
from app.services import access as acl
from app.services import multimodal as mm
from app.services import submissions as sub_svc
from app.services.audit import log_action

router = APIRouter(prefix="/api/media", tags=["multimodal"])
tasks_router = APIRouter(prefix="/api/annotation-tasks", tags=["multimodal"])


def _load_media(db: DbSession, user: CurrentUser, media_id: int) -> MediaAsset:
    media = db.get(MediaAsset, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media asset not found.")
    try:
        acl.require_project(db, user, media.project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return media


# ---------------------------------------------------------------------------
# Media upload + listing + streaming
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/upload", status_code=201)
async def upload_media(
    project_id: int,
    db: DbSession,
    user: AdminPM,
    request: Request,
    file: UploadFile = File(...),
    annotation_config: str | None = Form(None),
):
    try:
        project = acl.require_project(db, user, project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    filename = file.filename or "upload.bin"
    try:
        data = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read the uploaded file.")
    try:
        info = mm.validate_and_store_media(data, filename, file.content_type)
    except HTTPException:
        raise
    import json as _json
    config = None
    if annotation_config:
        try:
            config = _json.loads(annotation_config)
        except ValueError:
            raise HTTPException(status_code=422, detail="annotation_config must be JSON.")
    media = MediaAsset(
        project_id=project.id,
        uploader_id=user.id,
        media_type=info["media_type"],
        filename=filename[:255],
        storage_key=info["key"],
        mime_type=info["mime"],
        size_bytes=info["size"],
        width=info["width"],
        height=info["height"],
        duration_ms=info["duration_ms"],
        checksum_sha256=info["sha256"],
        annotation_config=config,
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    log_action(db, user_id=user.id, action="media.upload", entity_type="media_asset",
               entity_id=media.id,
               details={"filename": filename, "media_type": info["media_type"],
                        "mime": info["mime"], "size": info["size"]}, request=request)
    return {
        "id": media.id, "filename": media.filename, "media_type": media.media_type,
        "mime_type": media.mime_type, "size_bytes": media.size_bytes,
        "width": media.width, "height": media.height, "duration_ms": media.duration_ms,
    }


@router.post("/projects/{project_id}/generate-tasks", status_code=201)
def generate_annotation_tasks(
    project_id: int,
    payload: dict,
    db: DbSession,
    user: AdminPM,
    request: Request,
):
    """Create one annotation task per media asset (deduped per media)."""
    try:
        project = acl.require_project(db, user, project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    media_type = payload.get("media_type")
    if media_type and media_type not in MEDIA_TYPES:
        raise HTTPException(status_code=422, detail=f"media_type must be one of {MEDIA_TYPES}")
    type_for = {"image": "image_annotation", "video": "video_annotation", "audio": "audio_annotation"}
    stmt = select(MediaAsset).where(MediaAsset.project_id == project_id)
    if media_type:
        stmt = stmt.where(MediaAsset.media_type == media_type)
    assets = db.scalars(stmt).all()
    if not assets:
        raise HTTPException(status_code=422, detail="No media assets uploaded for this selection.")
    existing_media_ids = set(db.scalars(
        select(Task.media_asset_id).where(Task.project_id == project_id, Task.media_asset_id.is_not(None))
    ).all())
    created = 0
    for m in assets:
        if m.id in existing_media_ids:
            continue
        db.add(Task(
            project_id=project_id,
            title=f"Annotate {m.media_type}: {m.filename}",
            task_type=type_for[m.media_type],
            instructions=payload.get("instructions") or project.instructions,
            status="available",
            difficulty=payload.get("difficulty") or "medium",
            created_by=user.id,
            media_asset_id=m.id,
        ))
        created += 1
    db.commit()
    log_action(db, user_id=user.id, action="annotation.tasks_generate", entity_type="project",
               entity_id=project_id, details={"created": created}, request=request)
    return {"created": created, "skipped_existing": len(assets) - created}


@router.get("/projects/{project_id}")
def list_media(project_id: int, db: DbSession, user: CurrentUser, media_type: str | None = None):
    try:
        acl.require_project(db, user, project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    stmt = select(MediaAsset).where(MediaAsset.project_id == project_id)
    if media_type:
        if media_type not in MEDIA_TYPES:
            raise HTTPException(status_code=422, detail=f"media_type must be one of {MEDIA_TYPES}")
        stmt = stmt.where(MediaAsset.media_type == media_type)
    rows = db.scalars(stmt.order_by(MediaAsset.created_at.desc())).all()
    return [
        {
            "id": m.id, "filename": m.filename, "media_type": m.media_type,
            "mime_type": m.mime_type, "size_bytes": m.size_bytes,
            "width": m.width, "height": m.height, "duration_ms": m.duration_ms,
            "status": m.status, "annotation_config": m.annotation_config or {},
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


@router.get("/{media_id}")
def media_detail(media_id: int, db: DbSession, user: CurrentUser):
    m = _load_media(db, user, media_id)
    return {
        "id": m.id, "project_id": m.project_id, "filename": m.filename,
        "media_type": m.media_type, "mime_type": m.mime_type, "size_bytes": m.size_bytes,
        "width": m.width, "height": m.height, "duration_ms": m.duration_ms,
        "checksum_sha256": m.checksum_sha256, "status": m.status,
        "annotation_config": m.annotation_config or {},
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/{media_id}/stream")
def stream_media(media_id: int, db: DbSession, user: CurrentUser, request: Request):
    """Range-aware authenticated streaming — never loads whole files in memory."""
    m = _load_media(db, user, media_id)
    from app.services import file_storage
    import os

    domain, _, name = m.storage_key.partition("/")
    path = (file_storage._ROOT / domain / name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media file missing from storage.")
    size = path.stat().st_size
    range_header = request.headers.get("range")
    start, end = 0, size - 1
    status_code = 200
    if range_header and range_header.startswith("bytes="):
        try:
            first, last = range_header[6:].split("-", 1)
            start = int(first) if first else 0
            end = int(last) if last else size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                raise ValueError
            status_code = 206
        except ValueError:
            raise HTTPException(status_code=416, detail="Invalid Range header.")
    length = end - start + 1

    def _iter():
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Type": m.mime_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "private, max-age=3600",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(_iter(), status_code=status_code, headers=headers)


# ---------------------------------------------------------------------------
# Annotation get/save/submit per modality
# ---------------------------------------------------------------------------

def _annotation_model(media_type: str):
    return {"image": ImageAnnotation, "video": VideoAnnotation, "audio": AudioAnnotation}[media_type]


def _annotation_out(row) -> dict:
    data = {
        "id": row.id, "media_asset_id": row.media_asset_id, "task_id": row.task_id,
        "version": row.version, "is_final": row.is_final,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if isinstance(row, ImageAnnotation):
        data["shapes"] = row.shapes or []
        data["labels"] = row.labels or []
    elif isinstance(row, VideoAnnotation):
        data["events"] = row.events or []
        data["frame_labels"] = row.frame_labels or []
        data["duration_ms"] = row.duration_ms
    else:
        data["segments"] = row.segments or []
        data["global_labels"] = row.global_labels or []
        data["duration_ms"] = row.duration_ms
    return data


def _load_annotation_target(db: DbSession, user: CurrentUser, task_id: int) -> tuple[Task, MediaAsset]:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        acl.require_project(db, user, task.project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if task.media_asset_id is None:
        raise HTTPException(status_code=422, detail="This task has no media asset.")
    media = db.get(MediaAsset, task.media_asset_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media asset missing.")
    return task, media


@tasks_router.get("/{task_id}/annotation")
def get_annotation(task_id: int, db: DbSession, user: CurrentUser):
    task, media = _load_annotation_target(db, user, task_id)
    model = _annotation_model(media.media_type)
    row = db.scalar(
        select(model).where(model.task_id == task_id).order_by(model.version.desc())
    )
    return {
        "media": {
            "id": media.id, "filename": media.filename, "media_type": media.media_type,
            "mime_type": media.mime_type, "width": media.width, "height": media.height,
            "duration_ms": media.duration_ms, "annotation_config": media.annotation_config or {},
        },
        "annotation": _annotation_out(row) if row else None,
        "task_status": task.status,
    }


@tasks_router.put("/{task_id}/annotation")
def save_annotation(task_id: int, payload: dict, db: DbSession, user: CurrentUser, request: Request):
    """Save a new annotation version (autosave) — task must be assigned to the caller."""
    task, media = _load_annotation_target(db, user, task_id)
    if task.assigned_tester_id != user.id and user.role not in UserRole.STAFF:
        raise HTTPException(status_code=403, detail="Only the assigned worker can edit this annotation.")
    if task.status not in ("assigned", "in_progress", "draft", "revision_required") and user.role not in UserRole.STAFF:
        raise HTTPException(status_code=409, detail=f"Task is not open for annotation (status {task.status}).")

    model = _annotation_model(media.media_type)
    latest = db.scalar(select(model).where(model.task_id == task_id).order_by(model.version.desc()))
    version = (latest.version + 1) if latest else 1
    try:
        if media.media_type == "image":
            shapes = mm.validate_image_shapes(payload.get("shapes") or [])
            row = model(
                media_asset_id=media.id, task_id=task.id, worker_id=user.id, version=version,
                shapes=shapes, labels=[str(x) for x in (payload.get("labels") or [])],
                image_width=payload.get("image_width") or media.width,
                image_height=payload.get("image_height") or media.height,
            )
        elif media.media_type == "video":
            events = mm.validate_video_events(payload.get("events") or [])
            row = model(
                media_asset_id=media.id, task_id=task.id, worker_id=user.id, version=version,
                events=events,
                frame_labels=payload.get("frame_labels") or [],
                duration_ms=payload.get("duration_ms") or media.duration_ms,
                sampling_config=payload.get("sampling_config"),
            )
        else:
            segments = mm.validate_audio_segments(payload.get("segments") or [])
            row = model(
                media_asset_id=media.id, task_id=task.id, worker_id=user.id, version=version,
                segments=segments,
                global_labels=[str(x) for x in (payload.get("global_labels") or [])],
                duration_ms=payload.get("duration_ms") or media.duration_ms,
            )
    except mm.AnnotationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.add(row)
    db.commit()
    db.refresh(row)
    log_action(db, user_id=user.id, action=f"annotation.save_{media.media_type}",
               entity_type="annotation", entity_id=row.id,
               details={"task_id": task.id, "version": version}, request=request)
    return _annotation_out(row)


@tasks_router.post("/{task_id}/submit")
def submit_annotation(task_id: int, payload: dict, db: DbSession, user: CurrentUser, request: Request):
    """Finalize the annotation: creates a Submission reviewed via the normal flow."""
    task, media = _load_annotation_target(db, user, task_id)
    if task.assigned_tester_id != user.id:
        raise HTTPException(status_code=403, detail="Task is not assigned to you.")
    if task.status not in ("assigned", "in_progress", "revision_required"):
        raise HTTPException(status_code=409, detail=f"Task cannot be submitted from status '{task.status}'.")

    model = _annotation_model(media.media_type)
    latest = db.scalar(select(model).where(model.task_id == task_id).order_by(model.version.desc()))
    if latest is None:
        raise HTTPException(status_code=422, detail="Save the annotation before submitting.")

    # reuse the standard submission lifecycle (attempt bookkeeping + atomic status move)
    submission, errors = sub_svc.submit_task(
        db, task, user,
        payload={"annotation_type": media.media_type, "media_asset_id": media.id,
                 "annotation_version": latest.version},
        explanation=payload.get("explanation"),
        evidence=None,
        time_spent_seconds=payload.get("time_spent_seconds"),
    )
    if submission is None:
        raise HTTPException(status_code=422, detail=errors)
    latest.submission_id = submission.id
    latest.is_final = True
    db.commit()
    # mark in_progress (claim→submit without explicit start)
    log_action(db, user_id=user.id, action="annotation.submit", entity_type="submission",
               entity_id=submission.id,
               details={"media_type": media.media_type, "annotation_version": latest.version},
               request=request)
    from app.services.golden import score_submission_if_golden
    score_submission_if_golden(db, submission)
    return {"submission_id": submission.id, "annotation_version": latest.version}


# ---------------------------------------------------------------------------
# Exports (staff; permission-checked and audited)
# ---------------------------------------------------------------------------

exports_router = APIRouter(prefix="/api/exports/annotations", tags=["multimodal"])


@exports_router.get("")
def export_annotations(
    db: DbSession, user: AdminPM, request: Request,
    project_id: int = Query(...),
    media_type: str = Query("image"),
    format: str = Query("json"),
    approved_only: bool = Query(True),
):
    try:
        project = acl.require_project(db, user, project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    import io
    import csv as _csv
    import json as _json

    if media_type == "image":
        stmt = (
            select(ImageAnnotation, MediaAsset)
            .join(MediaAsset, MediaAsset.id == ImageAnnotation.media_asset_id)
            .where(MediaAsset.project_id == project_id)
        )
        if approved_only:
            stmt = stmt.where(ImageAnnotation.is_final.is_(True),
                              Submission.status == "approved")
            stmt = stmt.outerjoin(Submission, Submission.id == ImageAnnotation.submission_id)
        rows = db.execute(
            stmt.order_by(ImageAnnotation.media_asset_id, ImageAnnotation.version.desc())
        ).all()
        latest_by_media: dict[int, tuple] = {}
        for ann, media in rows:
            if ann.media_asset_id not in latest_by_media:
                latest_by_media[ann.media_asset_id] = (ann, media)
        rows = list(latest_by_media.values())
        media_by_id = {m.id: m for _, m in rows}
        fmt = format.lower()
        if fmt == "coco":
            payload = mm.image_to_coco(rows, media_by_id)
            data = _json.dumps(payload, indent=2).encode("utf-8")
            ext, mime = "json", "application/json"
        elif fmt == "csv":
            buf = io.StringIO()
            w = _csv.writer(buf)
            w.writerow(["media_id", "filename", "shape_type", "label", "points_normalized", "image_width", "image_height"])
            for ann, media in rows:
                for s in ann.shapes or []:
                    w.writerow([media.id, media.filename, s["type"], s["label"],
                                _json.dumps(s["points"]), media.width or ann.image_width,
                                media.height or ann.image_height])
            data = buf.getvalue().encode("utf-8")
            ext, mime = "csv", "text/csv"
        else:
            payload = [
                {
                    "media_id": media.id, "filename": media.filename,
                    "width": media.width, "height": media.height,
                    "annotation_version": ann.version,
                    "shapes": ann.shapes, "labels": ann.labels or [],
                }
                for ann, media in rows
            ]
            data = _json.dumps(payload, indent=2).encode("utf-8")
            ext, mime = "json", "application/json"
    elif media_type == "video":
        rows = db.execute(
            select(VideoAnnotation, MediaAsset)
            .join(MediaAsset, MediaAsset.id == VideoAnnotation.media_asset_id)
            .where(MediaAsset.project_id == project_id)
            .order_by(VideoAnnotation.media_asset_id, VideoAnnotation.version.desc())
        ).all()
        latest: dict[int, tuple] = {}
        for ann, media in rows:
            latest.setdefault(ann.media_asset_id, (ann, media))
        payload = [
            {"media_id": media.id, "filename": media.filename,
             "duration_ms": media.duration_ms or ann.duration_ms,
             "events": ann.events}
            for ann, media in latest.values()
        ]
        data = _json.dumps(payload, indent=2).encode("utf-8")
        ext, mime = "json", "application/json"
    else:
        rows = db.execute(
            select(AudioAnnotation, MediaAsset)
            .join(MediaAsset, MediaAsset.id == AudioAnnotation.media_asset_id)
            .where(MediaAsset.project_id == project_id)
            .order_by(AudioAnnotation.media_asset_id, AudioAnnotation.version.desc())
        ).all()
        latest: dict[int, tuple] = {}
        for ann, media in rows:
            latest.setdefault(ann.media_asset_id, (ann, media))
        if format.lower() == "csv":
            buf = io.StringIO()
            w = _csv.writer(buf)
            w.writerow(["media_id", "filename", "start_ms", "end_ms", "transcript", "speaker", "language", "emotion"])
            for ann, media in latest.values():
                for s in ann.segments or []:
                    w.writerow([media.id, media.filename, s["start_ms"], s["end_ms"],
                                s["transcript"], s.get("speaker"), s.get("language"), s.get("emotion")])
            data = buf.getvalue().encode("utf-8")
            ext, mime = "csv", "text/csv"
        else:
            payload = [
                {"media_id": media.id, "filename": media.filename,
                 "duration_ms": media.duration_ms or ann.duration_ms,
                 "segments": ann.segments, "global_labels": ann.global_labels or []}
                for ann, media in latest.values()
            ]
            data = _json.dumps(payload, indent=2).encode("utf-8")
            ext, mime = "json", "application/json"

    log_action(db, user_id=user.id, action="annotation.export", entity_type="project",
               entity_id=project_id,
               details={"media_type": media_type, "format": format, "project": project.name},
               request=request)
    from fastapi import Response
    filename = f"{project.name.replace(' ', '_')}_{media_type}_annotations.{ext}"
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
