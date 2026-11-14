"""Task management routes: generation, manual creation, assignment, claiming.

Access model:
- Staff (admin of the project) create, generate, assign, reassign, cancel tasks
- Testers see available tasks in projects they are members of and claim/start them
- Everyone touching a task must pass project-membership checks server-side
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.security import AdminPM, CurrentUser, DbSession
from app.models.dataset import Dataset
from app.models.project import Project
from app.models.rubric import Rubric, RubricVersion
from app.models.task import Task, TASK_STATUSES, TASK_PRIORITIES, TASK_DIFFICULTIES
from app.models.user import User, UserRole
from app.services import access as acl
from app.services import tasks as task_svc
from app.services.audit import log_action

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task_out(db: DbSession, t: Task, include_record: bool = True, blind_tester: bool = False,
              hide_golden_reference: bool = False) -> dict:
    record = t.record
    data = {
        "id": t.id,
        "project_id": t.project_id,
        "project_name": t.project.name if t.project else None,
        "title": t.title,
        "task_type": t.task_type,
        "instructions": t.instructions,
        "status": t.status,
        "priority": t.priority,
        "difficulty": t.difficulty,
        "estimated_minutes": t.estimated_minutes,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "max_attempts": t.max_attempts,
        "attempt_count": t.attempt_count,
        "rubric_id": t.rubric_id,
        "rubric_version_id": t.rubric_version_id,
        "assigned_tester_id": None if blind_tester else t.assigned_tester_id,
        "assigned_tester_name": None if blind_tester else (t.tester.name if t.tester else None),
        "claimed_at": t.claimed_at.isoformat() if t.claimed_at else None,
        "assignment_expires_at": t.assignment_expires_at.isoformat() if t.assignment_expires_at else None,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat(),
        "has_record": record is not None,
    }
    # NOTE: is_golden / golden_task_id are intentionally NEVER serialized here.
    if include_record and record is not None:
        hide_reference = hide_golden_reference and t.is_golden
        data["record"] = {
            "id": record.id,
            "record_id": record.record_id,
            "prompt": record.prompt,
            "response": record.response,
            # golden tasks must not reveal the expected answer to workers
            "reference_answer": None if hide_reference else record.reference_answer,
            "reference_sources": [] if hide_reference else (record.reference_sources or []),
            "supporting_evidence": record.supporting_evidence,
            "source_url": record.source_url,
            "content_category": record.content_category,
            "difficulty_level": record.difficulty_level,
            "language": record.language or "en",
            "custom_fields": record.custom_fields or {},
        }
    elif record is not None:
        data["record_id"] = record.record_id
    return data


def _require_visible_task(db: DbSession, user: CurrentUser, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        acl.require_project(db, user, task.project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return task


def _require_project_admin_task(db: DbSession, user: AdminPM, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        project = acl.require_project(db, user, task.project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return task


def _require_tester_membership(db: DbSession, user: CurrentUser, project_id: int) -> None:
    if user.role != UserRole.TESTER:
        raise HTTPException(status_code=403, detail="Only testers can work on tasks.")
    if not acl.is_project_tester(db, user, project_id):
        raise HTTPException(status_code=403, detail="You are not a tester on this project.")


# ------------------------------------------------------------- creation

@router.post("/generate", status_code=201)
def generate_tasks(payload: dict, db: DbSession, user: AdminPM, request: Request):
    project_id = payload.get("project_id")
    dataset_id = payload.get("dataset_id")
    rubric_id = payload.get("rubric_id")
    try:
        project = acl.require_project(db, user, int(project_id))
        acl.require_project_admin(db, user, project)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="project_id, dataset_id and rubric_id are required.")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    dataset = db.get(Dataset, int(dataset_id))
    if dataset is None or dataset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Dataset not found in this project.")
    if dataset.status == "archived":
        raise HTTPException(status_code=409, detail="Cannot generate tasks from an archived dataset.")
    rubric = db.get(Rubric, int(rubric_id))
    if rubric is None:
        raise HTTPException(status_code=404, detail="Rubric not found.")

    rubric_version = None
    if payload.get("rubric_version_id"):
        rubric_version = db.get(RubricVersion, int(payload["rubric_version_id"]))
        if rubric_version is None or rubric_version.rubric_id != rubric.id:
            raise HTTPException(status_code=422, detail="rubric_version_id does not belong to the rubric.")
    else:
        rubric_version = db.scalars(
            select(RubricVersion).where(RubricVersion.rubric_id == rubric.id)
            .order_by(RubricVersion.version_number.desc())
        ).first()

    priority = payload.get("priority", "normal")
    difficulty = payload.get("difficulty", "medium")
    if priority not in TASK_PRIORITIES or difficulty not in TASK_DIFFICULTIES:
        raise HTTPException(status_code=422, detail="Invalid priority or difficulty.")

    limit = payload.get("limit")
    if limit is not None and (not isinstance(limit, int) or limit < 1 or limit > task_svc.MAX_BULK_TASKS):
        raise HTTPException(status_code=422, detail=f"limit must be 1..{task_svc.MAX_BULK_TASKS}.")

    report = task_svc.generate_tasks_from_dataset(
        db,
        project_id=project.id,
        dataset=dataset,
        rubric=rubric,
        rubric_version=rubric_version,
        created_by=user.id,
        task_type=payload.get("task_type") or project.project_type,
        priority=priority,
        difficulty=difficulty,
        estimated_minutes=payload.get("estimated_minutes"),
        deadline=payload.get("deadline"),
        max_attempts=max(1, int(payload.get("max_attempts", 2))),
        instructions=payload.get("instructions"),
        limit=limit,
        skip_records_with_tasks=bool(payload.get("skip_records_with_tasks", True)),
    )
    log_action(db, user_id=user.id, action="task.generate", entity_type="project", entity_id=project.id,
               details={**report, "dataset_id": dataset.id, "rubric_id": rubric.id}, request=request)
    return report


@router.post("/manual", status_code=201)
def create_manual_task(payload: dict, db: DbSession, user: AdminPM, request: Request):
    project_id = payload.get("project_id")
    try:
        project = acl.require_project(db, user, int(project_id))
        acl.require_project_admin(db, user, project)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="project_id is required.")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="Task title is required.")
    record = None
    if payload.get("dataset_record_id"):
        from app.models.dataset import DatasetRecord
        record = db.get(DatasetRecord, int(payload["dataset_record_id"]))
        if record is None:
            raise HTTPException(status_code=404, detail="Dataset record not found.")

    task = Task(
        project_id=project.id,
        dataset_record_id=record.id if record else None,
        title=title,
        task_type=payload.get("task_type") or project.project_type,
        instructions=payload.get("instructions"),
        status="draft" if payload.get("status") == "draft" else "available",
        priority=payload.get("priority") if payload.get("priority") in TASK_PRIORITIES else "normal",
        difficulty=payload.get("difficulty") if payload.get("difficulty") in TASK_DIFFICULTIES else "medium",
        estimated_minutes=payload.get("estimated_minutes"),
        deadline=payload.get("deadline"),
        max_attempts=max(1, int(payload.get("max_attempts", 2))),
        rubric_id=payload.get("rubric_id"),
        rubric_version_id=payload.get("rubric_version_id"),
        required_fields=payload.get("required_fields"),
        created_by=user.id,
    )
    if task.rubric_id is not None and db.get(Rubric, task.rubric_id) is None:
        raise HTTPException(status_code=404, detail="Rubric not found.")
    db.add(task)
    db.commit()
    db.refresh(task)
    log_action(db, user_id=user.id, action="task.create", entity_type="task", entity_id=task.id,
               details={"title": title, "project_id": project.id}, request=request)
    return _task_out(db, task)


@router.post("/bulk-manual", status_code=201)
def create_bulk_tasks(payload: dict, db: DbSession, user: AdminPM, request: Request):
    project_id = payload.get("project_id")
    rows = payload.get("tasks")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=422, detail="'tasks' must be a non-empty array.")
    if len(rows) > task_svc.MAX_BULK_TASKS:
        raise HTTPException(status_code=413, detail=f"Bulk creation is limited to {task_svc.MAX_BULK_TASKS} tasks per call.")
    try:
        project = acl.require_project(db, user, int(project_id))
        acl.require_project_admin(db, user, project)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="project_id is required.")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    created, rejected = 0, []
    for i, row in enumerate(rows):
        title = (row.get("title") or "").strip()
        if not title:
            rejected.append({"row": i, "errors": ["title is required"]})
            continue
        db.add(Task(
            project_id=project.id, title=title,
            task_type=row.get("task_type") or project.project_type,
            instructions=row.get("instructions"),
            status="available",
            priority=row.get("priority") if row.get("priority") in TASK_PRIORITIES else "normal",
            difficulty=row.get("difficulty") if row.get("difficulty") in TASK_DIFFICULTIES else "medium",
            estimated_minutes=row.get("estimated_minutes"),
            deadline=row.get("deadline"),
            max_attempts=max(1, int(row.get("max_attempts", 2))),
            created_by=user.id,
        ))
        created += 1
    db.commit()
    log_action(db, user_id=user.id, action="task.bulk_create", entity_type="project", entity_id=project.id,
               details={"created": created, "rejected": len(rejected)}, request=request)
    return {"created": created, "rejected": rejected}


# ------------------------------------------------------------- listing

@router.get("")
def list_tasks(
    db: DbSession, user: CurrentUser,
    project_id: int | None = None,
    status: str | None = None,
    priority: str | None = None,
    task_type: str | None = None,
    difficulty: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    ids = acl.visible_project_ids(db, user)
    if ids is not None and project_id and project_id not in ids:
        raise HTTPException(status_code=403, detail="You do not have access to this project.")
    stmt = select(Task).options(joinedload(Task.tester), joinedload(Task.record)).order_by(Task.id.desc())
    if ids is not None:
        if not ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        stmt = stmt.where(Task.project_id.in_(ids))
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == status)
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if task_type:
        stmt = stmt.where(Task.task_type == task_type)
    if difficulty:
        stmt = stmt.where(Task.difficulty == difficulty)
    if search:
        stmt = stmt.where(Task.title.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all()
    blind = user.role not in UserRole.PLATFORM_WIDE
    return {
        "items": [_task_out(db, t, include_record=False, blind_tester=blind) for t in items],
        "total": int(total), "page": page, "page_size": page_size,
    }


@router.get("/available")
def available_tasks(db: DbSession, user: CurrentUser, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)):
    """Task marketplace: available tasks in the tester's projects."""
    _require_tester_membership_any(db, user)
    project_ids = sorted(acl.visible_project_ids(db, user) or set())
    stmt = (
        select(Task).options(joinedload(Task.project))
        .where(Task.status == "available", Task.project_id.in_(project_ids or [0]))
        .order_by(Task.priority.desc(), Task.id)
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all()
    return {
        "items": [_task_out(db, t, hide_golden_reference=True) for t in items],
        "total": int(total), "page": page, "page_size": page_size,
    }


def _require_tester_membership_any(db: DbSession, user: CurrentUser) -> None:
    if user.role != UserRole.TESTER:
        raise HTTPException(status_code=403, detail="Only testers have a task marketplace.")
    if not (acl.visible_project_ids(db, user) or set()):
        # fine — they just have no projects yet; marketplace will be empty
        pass


@router.get("/mine")
def my_tasks(db: DbSession, user: CurrentUser, status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    if user.role != UserRole.TESTER:
        raise HTTPException(status_code=403, detail="Only testers have personal task lists.")
    stmt = (
        select(Task).options(joinedload(Task.project), joinedload(Task.record))
        .where(Task.assigned_tester_id == user.id)
        .order_by(Task.id.desc())
    )
    if status:
        stmt = stmt.where(Task.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all()
    return {"items": [_task_out(db, t, hide_golden_reference=True) for t in items], "total": int(total), "page": page, "page_size": page_size}


@router.get("/meta/constants")
def constants(user: CurrentUser):
    return {"statuses": TASK_STATUSES, "priorities": TASK_PRIORITIES, "difficulties": TASK_DIFFICULTIES}


@router.get("/{task_id}")
def get_task(task_id: int, db: DbSession, user: CurrentUser):
    task = _require_visible_task(db, user, task_id)
    blind = (user.role == UserRole.TESTER and task.assigned_tester_id != user.id)
    out = _task_out(db, task, blind_tester=blind, hide_golden_reference=(user.role == UserRole.TESTER))
    if task.assignments:
        out["assignment_history"] = [
            {
                "user_id": a.user_id, "action": a.action,
                "assigned_at": a.assigned_at.isoformat(),
                "released_at": a.released_at.isoformat() if a.released_at else None,
            }
            for a in task.assignments
        ]
    return out


# ------------------------------------------------------------- transitions

@router.post("/{task_id}/claim")
def claim(task_id: int, db: DbSession, user: CurrentUser, request: Request):
    task = _require_visible_task(db, user, task_id)
    _require_tester_membership(db, user, task.project_id)
    # v3: project qualification requirements gate claiming (admin overrides apply)
    from app.services.qualifications import eligibility_status
    from app.models.project import Project
    project = db.get(Project, task.project_id)
    if project is not None:
        eligible, unmet = eligibility_status(db, user, project)
        if not eligible:
            raise HTTPException(status_code=403, detail={
                "message": "You do not meet this project's qualification requirements.",
                "unmet": unmet,
            })
    if task.status not in task_svc.CLAIMABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Task is not available for claiming (status: {task.status}).")
    claimed, message = task_svc.claim_task(db, task_id, user)
    if claimed is None:
        raise HTTPException(status_code=409, detail=message)
    log_action(db, user_id=user.id, action="task.claim", entity_type="task", entity_id=task_id, request=request)
    return _task_out(db, claimed, hide_golden_reference=True)


@router.post("/{task_id}/start")
def start(task_id: int, db: DbSession, user: CurrentUser, request: Request):
    task = _require_visible_task(db, user, task_id)
    if task.assigned_tester_id != user.id:
        raise HTTPException(status_code=403, detail="Task is not assigned to you.")
    ok, message = task_svc.start_task(db, task, user.id)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    db.refresh(task)
    return _task_out(db, task)


@router.post("/{task_id}/assign")
def assign(task_id: int, payload: dict, db: DbSession, user: AdminPM, request: Request):
    task = _require_project_admin_task(db, user, task_id)
    tester = db.get(User, int(payload.get("tester_id", 0)))
    if tester is None:
        raise HTTPException(status_code=404, detail="Tester not found.")
    assigned, message = task_svc.assign_task(db, task, tester, assigned_by=user.id)
    if assigned is None:
        raise HTTPException(status_code=409, detail=message)
    log_action(db, user_id=user.id, action="task.assign", entity_type="task", entity_id=task_id,
               details={"tester_id": tester.id}, request=request)
    return _task_out(db, assigned)


@router.post("/{task_id}/reassign")
def reassign(task_id: int, payload: dict, db: DbSession, user: AdminPM, request: Request):
    task = _require_project_admin_task(db, user, task_id)
    tester = db.get(User, int(payload.get("tester_id", 0)))
    if tester is None:
        raise HTTPException(status_code=404, detail="Tester not found.")
    result, message = task_svc.reassign_task(db, task, tester, reassigned_by=user.id)
    if result is None:
        raise HTTPException(status_code=409, detail=message)
    log_action(db, user_id=user.id, action="task.reassign", entity_type="task", entity_id=task_id,
               details={"from": task.assigned_tester_id, "to": tester.id}, request=request)
    return _task_out(db, result)


@router.post("/{task_id}/release")
def release(task_id: int, db: DbSession, user: AdminPM, request: Request):
    task = _require_project_admin_task(db, user, task_id)
    task_svc.release_task(db, task, released_by=user.id, action="released")
    db.refresh(task)
    log_action(db, user_id=user.id, action="task.release", entity_type="task", entity_id=task_id, request=request)
    return _task_out(db, task)


@router.post("/{task_id}/pause")
def pause(task_id: int, db: DbSession, user: AdminPM, request: Request):
    task = _require_project_admin_task(db, user, task_id)
    if task.status != "available":
        raise HTTPException(status_code=409, detail="Only available tasks can be paused (drafted).")
    task.status = "draft"
    db.commit()
    log_action(db, user_id=user.id, action="task.pause", entity_type="task", entity_id=task_id, request=request)
    return _task_out(db, task)


@router.post("/{task_id}/unpause")
def unpause(task_id: int, db: DbSession, user: AdminPM, request: Request):
    task = _require_project_admin_task(db, user, task_id)
    if task.status != "draft":
        raise HTTPException(status_code=409, detail="Only drafted (paused) tasks can be published.")
    task.status = "available"
    db.commit()
    log_action(db, user_id=user.id, action="task.unpause", entity_type="task", entity_id=task_id, request=request)
    return _task_out(db, task)


@router.post("/{task_id}/cancel")
def cancel(task_id: int, db: DbSession, user: AdminPM, request: Request):
    task = _require_project_admin_task(db, user, task_id)
    if not task_svc.cancel_task(db, task, cancelled_by=user.id):
        raise HTTPException(status_code=409, detail="Approved or already-cancelled tasks cannot be cancelled.")
    log_action(db, user_id=user.id, action="task.cancel", entity_type="task", entity_id=task_id, request=request)
    db.refresh(task)
    return _task_out(db, task)


@router.post("/maintenance/expire-assignments")
def expire_assignments(db: DbSession, user: AdminPM, request: Request):
    count = task_svc.expire_stale_assignments(db)
    if count:
        log_action(db, user_id=user.id, action="task.expire_assignments", entity_type="task", entity_id=None,
                   details={"expired": count}, request=request)
    return {"expired": count}
