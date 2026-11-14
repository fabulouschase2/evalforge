"""Task lifecycle services with concurrency-safe state transitions.

Claiming and assignment use atomic conditional UPDATEs
(`UPDATE ... WHERE status='available'` + rowcount check), which is correct
under both SQLite (serialized writes) and PostgreSQL (row locks re-check the
predicate after acquiring the lock). Two workers can never both claim a task.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.dataset import Dataset, DatasetRecord
from app.models.notification import Notification
from app.models.rubric import Rubric, RubricVersion
from app.models.task import Task, TaskAssignment, CLAIMABLE_STATUSES, ACTIVE_WORK_STATUSES
from app.models.user import User

DEFAULT_ASSIGNMENT_TTL_HOURS = 24
MAX_BULK_TASKS = 5000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def notify(db: Session, user_id: int, ntype: str, title: str, body: str | None = None,
           entity_type: str | None = None, entity_id: int | str | None = None) -> None:
    db.add(Notification(user_id=user_id, type=ntype, title=title, body=body,
                        entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None))


def _ttl_hours(db: Session) -> int:
    from app.models.audit import Setting
    row = db.get(Setting, "app")
    if row and isinstance(row.value, dict):
        try:
            return max(1, int(row.value.get("assignment_ttl_hours", DEFAULT_ASSIGNMENT_TTL_HOURS)))
        except (TypeError, ValueError):
            return DEFAULT_ASSIGNMENT_TTL_HOURS
    return DEFAULT_ASSIGNMENT_TTL_HOURS


def generate_tasks_from_dataset(
    db: Session,
    *,
    project_id: int,
    dataset: Dataset,
    rubric: Rubric,
    rubric_version: RubricVersion | None,
    created_by: int,
    task_type: str | None = None,
    priority: str = "normal",
    difficulty: str = "medium",
    estimated_minutes: int | None = None,
    deadline: datetime | None = None,
    max_attempts: int = 2,
    instructions: str | None = None,
    limit: int | None = None,
    skip_records_with_tasks: bool = True,
) -> dict:
    """Create one 'available' task per dataset record (latest or pinned version)."""
    version_id = None
    if dataset.versions:
        version_id = max(v.id for v in dataset.versions)
    stmt = select(DatasetRecord).where(DatasetRecord.dataset_id == dataset.id)
    if version_id:
        stmt = stmt.where(DatasetRecord.dataset_version_id == version_id)
    records = db.scalars(stmt.order_by(DatasetRecord.id)).all()

    existing_record_ids = set()
    if skip_records_with_tasks:
        existing_record_ids = set(db.scalars(
            select(Task.dataset_record_id).where(
                Task.project_id == project_id, Task.dataset_record_id.is_not(None))
        ).all())

    created = 0
    skipped_existing = 0
    created_tasks: list[Task] = []
    for record in records:
        if limit is not None and created >= limit:
            break
        if skip_records_with_tasks and record.id in existing_record_ids:
            skipped_existing += 1
            continue
        if created >= MAX_BULK_TASKS:
            break
        title = f"{record.record_id}: {(record.prompt or '')[:80]}"
        task = Task(
            project_id=project_id,
            dataset_record_id=record.id,
            title=title,
            task_type=task_type or "ai_response_evaluation",
            instructions=instructions or record.instructions,
            status="available",
            priority=priority,
            difficulty=difficulty or record.difficulty_level or "medium",
            estimated_minutes=estimated_minutes,
            deadline=deadline,
            max_attempts=max_attempts,
            rubric_id=rubric.id,
            rubric_version_id=rubric_version.id if rubric_version else None,
            created_by=created_by,
        )
        db.add(task)
        created_tasks.append(task)
        created += 1
    db.commit()

    # v3: weave golden quality probes into the freshly generated queue
    golden_inserted = 0
    try:
        from app.services.golden import weave_golden_tasks
        from app.models.project import Project
        project = db.get(Project, project_id)
        if project is not None:
            golden_inserted = weave_golden_tasks(db, project, created_tasks, created_by)
    except Exception:
        import logging
        logging.getLogger("evalforge.golden").exception(
            "golden weaving failed for project %s", project_id)

    return {"created": created, "skipped_existing": skipped_existing,
            "records": len(records), "golden_inserted": golden_inserted}


def assign_task(db: Session, task: Task, tester: User, assigned_by: int) -> tuple[Task | None, str]:
    """Direct assignment from draft/available. Returns (task, message)."""
    if tester.role != "tester" or not tester.is_active:
        return None, "Only active tester accounts can be assigned tasks."
    now = _now()
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status.in_(["draft", "available"]))
        .values(status="assigned", assigned_tester_id=tester.id, claimed_at=now,
                attempt_count=Task.attempt_count + 1,
                assignment_expires_at=now + timedelta(hours=_ttl_hours(db)))
    )
    if result.rowcount == 0:
        return None, "Task is no longer available for assignment."
    db.add(TaskAssignment(task_id=task.id, user_id=tester.id, assigned_by=assigned_by, action="assigned"))
    db.commit()
    db.refresh(task)
    notify(db, tester.id, "task_assigned", f"New task assigned: {task.title}",
           "You have been assigned a task. Open My Tasks to start working.",
           entity_type="task", entity_id=task.id)
    db.commit()
    return task, "assigned"


def claim_task(db: Session, task_id: int, tester: User) -> tuple[Task | None, str]:
    """Atomic exclusive claim of an available task by an eligible tester."""
    now = _now()
    result = db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == "available")
        .values(status="assigned", assigned_tester_id=tester.id, claimed_at=now,
                attempt_count=Task.attempt_count + 1,
                assignment_expires_at=now + timedelta(hours=_ttl_hours(db)))
    )
    db.commit()
    if result.rowcount == 0:
        return None, "Task was already claimed by someone else."
    task = db.get(Task, task_id)
    db.add(TaskAssignment(task_id=task_id, user_id=tester.id, assigned_by=None, action="self_claimed"))
    db.commit()
    return task, "claimed"


def start_task(db: Session, task: Task, tester_id: int) -> tuple[bool, str]:
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status == "assigned", Task.assigned_tester_id == tester_id)
        .values(status="in_progress")
    )
    db.commit()
    if result.rowcount == 0:
        return False, "Task is not in an assigned state for this tester."
    return True, "in_progress"


def release_task(db: Session, task: Task, released_by: int, action: str = "released") -> None:
    """Return an assigned/in_progress task to the available pool (safe release)."""
    previous = task.assigned_tester_id
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status.in_(ACTIVE_WORK_STATUSES))
        .values(status="available", assigned_tester_id=None, claimed_at=None,
                assignment_expires_at=None, draft_payload=None, draft_updated_at=None)
    )
    if result.rowcount:
        db.add(TaskAssignment(task_id=task.id, user_id=previous or released_by,
                              assigned_by=released_by, action=action, released_at=_now()))
        db.commit()


def reassign_task(db: Session, task: Task, new_tester: User, reassigned_by: int) -> tuple[Task | None, str]:
    if new_tester.role != "tester" or not new_tester.is_active:
        return None, "Only active tester accounts can be assigned tasks."
    previous = task.assigned_tester_id
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status.in_(ACTIVE_WORK_STATUSES))
        .values(status="assigned", assigned_tester_id=new_tester.id, claimed_at=_now(),
                attempt_count=Task.attempt_count + 1,
                assignment_expires_at=_now() + timedelta(hours=_ttl_hours(db)),
                draft_payload=None, draft_updated_at=None)
    )
    db.commit()
    if result.rowcount == 0:
        return None, "Task is not in an assignable state."
    db.add(TaskAssignment(task_id=task.id, user_id=previous, assigned_by=reassigned_by,
                          action="released", released_at=_now()))
    db.add(TaskAssignment(task_id=task.id, user_id=new_tester.id, assigned_by=reassigned_by,
                          action="reassigned"))
    db.commit()
    db.refresh(task)
    notify(db, new_tester.id, "task_assigned", f"Task reassigned to you: {task.title}",
           entity_type="task", entity_id=task.id)
    db.commit()
    return task, "reassigned"


def expire_stale_assignments(db: Session) -> int:
    """Return expired assignments to the available pool."""
    now = _now()
    stale = db.scalars(
        select(Task).where(Task.status.in_(ACTIVE_WORK_STATUSES), Task.assignment_expires_at.is_not(None),
                           Task.assignment_expires_at < now)
    ).all()
    count = 0
    for task in stale:
        release_task(db, task, released_by=task.assigned_tester_id or 0, action="expired")
        count += 1
    return count


def cancel_task(db: Session, task: Task, cancelled_by: int) -> bool:
    if task.status in ("approved", "cancelled"):
        return False
    previous = task.assigned_tester_id
    task.status = "cancelled"
    task.assigned_tester_id = None
    task.assignment_expires_at = None
    db.add(TaskAssignment(task_id=task.id, user_id=previous or cancelled_by,
                          assigned_by=cancelled_by, action="released", released_at=_now()))
    db.commit()
    return True
