"""Client Portal service — org-scoped dashboards, sanitized monitoring, deliverables.

Privacy rules enforced here (routes trust nothing):
- client project monitoring never exposes tester/reviewer identities, private
  worker performance, or internal notes;
- dashboard stats are computed from real stored records only — no invented
  numbers; when there is no data the value is 0 and progress is None.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.client import ClientMessage, Deliverable, ProjectRequest
from app.models.dataset import Dataset, DatasetRecord
from app.models.project import Project
from app.models.submission import Submission
from app.models.task import Task
from app.models.user import User
from app.services import file_storage


def org_member_ids(db: Session, org_id: int) -> list[int]:
    from sqlalchemy import select as _select
    from app.models.organization import OrganizationMember
    return list(db.scalars(
        _select(OrganizationMember.user_id).where(OrganizationMember.organization_id == org_id)
    ).all())


def org_display_name(db: Session, org_id: int) -> str:
    from app.models.organization import Organization
    org = db.get(Organization, org_id)
    return org.name if org else "Organization"


def project_status_counts(db: Session, org_id: int) -> dict:
    rows = db.execute(
        select(Project.status, func.count()).where(Project.organization_id == org_id).group_by(Project.status)
    ).all()
    counts = {status: n for status, n in rows}
    return {
        "total": sum(counts.values()),
        "active": counts.get("active", 0),
        "completed": counts.get("completed", 0),
        "paused": counts.get("paused", 0),
        "draft": counts.get("draft", 0),
        "archived": counts.get("archived", 0),
    }


def request_status_counts(db: Session, org_id: int) -> dict:
    rows = db.execute(
        select(ProjectRequest.status, func.count())
        .where(ProjectRequest.organization_id == org_id)
        .group_by(ProjectRequest.status)
    ).all()
    counts = {status: n for status, n in rows}
    return {
        "total": sum(counts.values()),
        "pending": sum(counts.get(s, 0) for s in ("draft", "submitted", "under_review", "more_info_required")),
        "approved": counts.get("approved", 0) + counts.get("converted", 0),
        "rejected": counts.get("rejected", 0),
    }


def task_status_counts(db: Session, org_id: int) -> dict:
    """Task pipeline across the org's projects (no worker identities)."""
    rows = db.execute(
        select(Task.status, func.count())
        .join(Project, Project.id == Task.project_id)
        .where(Project.organization_id == org_id)
        .group_by(Task.status)
    ).all()
    counts = {status: n for status, n in rows}
    total = sum(counts.values())
    submitted = sum(counts.get(s, 0) for s in ("submitted", "under_review"))
    approved = counts.get("approved", 0)
    return {
        "total": total,
        "available": counts.get("available", 0) + counts.get("draft", 0),
        "in_progress": counts.get("assigned", 0) + counts.get("in_progress", 0),
        "under_review": submitted,
        "approved": approved,
        "rejected": counts.get("rejected", 0) + counts.get("revision_required", 0),
        "cancelled": counts.get("cancelled", 0),
        # None means "cannot compute yet" — the UI must not invent a value
        "completion_rate": round(approved / total, 4) if total else None,
    }


def client_dashboard(db: Session, org_id: int) -> dict:
    projects = project_status_counts(db, org_id)
    tasks = task_status_counts(db, org_id)
    requests = request_status_counts(db, org_id)
    deliverables = db.scalar(
        select(func.count()).select_from(Deliverable).where(Deliverable.organization_id == org_id)
    ) or 0
    unread_messages = db.scalar(
        select(func.count()).select_from(ClientMessage).where(
            ClientMessage.organization_id == org_id,
            ClientMessage.sender_side == "staff",
            ClientMessage.is_internal.is_(False),
            ClientMessage.read_by_client.is_(False),
        )
    ) or 0
    return {
        "organization": {"id": org_id, "name": org_display_name(db, org_id)},
        "projects": projects,
        "tasks": tasks,
        "requests": requests,
        "deliverables": deliverables,
        "unread_messages": unread_messages,
    }


def client_project_summary(db: Session, project: Project) -> dict:
    """Sanitized per-project monitoring for client users."""
    counts = dict(db.execute(
        select(Task.status, func.count()).where(Task.project_id == project.id).group_by(Task.status)
    ).all())
    total = sum(counts.values())
    approved = counts.get("approved", 0)
    datasets = db.scalars(
        select(Dataset).where(Dataset.project_id == project.id).order_by(Dataset.created_at.desc())
    ).all()
    deliverable_count = db.scalar(
        select(func.count()).select_from(Deliverable).where(Deliverable.project_id == project.id)
    ) or 0
    open_requests = db.scalar(
        select(func.count()).select_from(ProjectRequest).where(
            ProjectRequest.converted_project_id == project.id
        )
    ) or 0
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "project_type": project.project_type,
        "status": project.status,
        "instructions": project.instructions,
        "deadline": project.deadline.isoformat() if project.deadline else None,
        "start_date": project.start_date.isoformat() if project.start_date else None,
        "quality_requirements": project.quality_requirements,
        "target_task_volume": project.target_task_volume,
        "tasks": {
            "total": total,
            "pending": counts.get("draft", 0) + counts.get("available", 0),
            "in_progress": counts.get("assigned", 0) + counts.get("in_progress", 0),
            "under_review": counts.get("submitted", 0) + counts.get("under_review", 0),
            "approved": approved,
            "rejected": counts.get("rejected", 0) + counts.get("revision_required", 0),
            "completion_rate": round(approved / total, 4) if total else None,
        },
        "datasets": [
            {
                "id": d.id,
                "name": d.name,
                "format": d.format,
                "current_version": d.current_version,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in datasets
        ],
        "deliverables": deliverable_count,
        "source_request_id": open_requests or None,
    }


def client_activity(db: Session, org_id: int, limit: int = 12) -> list[dict]:
    """Recent org events for the dashboard (sanitized, no worker identities)."""
    events: list[dict] = []
    since = None  # all history; limited by count
    projects = db.scalars(
        select(Project).where(Project.organization_id == org_id)
        .order_by(Project.updated_at.desc()).limit(limit)
    ).all()
    for p in projects:
        events.append({
            "kind": "project",
            "project_id": p.id,
            "title": p.name,
            "detail": f"Project status: {p.status}",
            "at": (p.updated_at or p.created_at).isoformat() if (p.updated_at or p.created_at) else None,
        })
    reqs = db.scalars(
        select(ProjectRequest).where(ProjectRequest.organization_id == org_id)
        .order_by(ProjectRequest.updated_at.desc()).limit(limit)
    ).all()
    for r in reqs:
        events.append({
            "kind": "request",
            "project_id": r.converted_project_id,
            "title": r.title,
            "detail": f"Request status: {r.status}",
            "at": (r.updated_at or r.created_at).isoformat() if (r.updated_at or r.created_at) else None,
        })
    deliverables = db.scalars(
        select(Deliverable).where(Deliverable.organization_id == org_id)
        .order_by(Deliverable.published_at.desc()).limit(limit)
    ).all()
    for d in deliverables:
        events.append({
            "kind": "deliverable",
            "project_id": d.project_id,
            "title": d.label,
            "detail": f"Deliverable published ({d.export_format})",
            "at": d.published_at.isoformat() if d.published_at else None,
        })
    events.sort(key=lambda e: e.get("at") or "", reverse=True)
    return events[:limit]


def build_deliverable_file(db: Session, project: Project, export_format: str) -> tuple[str, int, int, str]:
    """Generate the approved-results package for a project.

    Returns (storage_key, file_size, record_count, sha256). Only approved
    submissions are included; provenance columns (task id, record id, attempt)
    travel with every row so the client can trace results.
    """
    import io
    import csv as _csv
    import json as _json

    rows = db.execute(
        select(Submission, Task, DatasetRecord)
        .join(Task, Task.id == Submission.task_id)
        .outerjoin(DatasetRecord, DatasetRecord.id == Task.dataset_record_id)
        .where(Submission.project_id == project.id, Submission.status == "approved")
        .order_by(Submission.id)
    ).all()

    def base_row(sub: Submission, task: Task, rec: DatasetRecord | None) -> dict:
        return {
            "task_id": task.id,
            "task_title": task.title,
            "record_id": rec.record_id if rec else None,
            "dataset_record_pk": rec.id if rec else None,
            "attempt": sub.attempt_number,
            "label": sub.label,
            "explanation": sub.explanation,
            "payload": sub.payload,
            "approved_at": sub.decided_at.isoformat() if sub.decided_at else None,
        }

    fmt = export_format if export_format in ("json", "csv", "jsonl") else "json"
    if fmt == "json":
        payload = {
            "project": {"id": project.id, "name": project.name},
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "record_count": len(rows),
            "results": [base_row(s, t, r) for s, t, r in rows],
        }
        data = (_json.dumps(payload, indent=2, default=str)).encode("utf-8")
    elif fmt == "jsonl":
        buf = io.StringIO()
        for s, t, r in rows:
            buf.write(_json.dumps(base_row(s, t, r), default=str) + "\n")
        data = buf.getvalue().encode("utf-8")
    else:  # csv
        buf = io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow(["task_id", "task_title", "record_id", "dataset_record_pk", "attempt", "label", "explanation", "payload_json", "approved_at"])
        for s, t, r in rows:
            row = base_row(s, t, r)
            writer.writerow([
                row["task_id"], row["task_title"], row["record_id"], row["dataset_record_pk"],
                row["attempt"], row["label"], row["explanation"],
                _json.dumps(row["payload"], default=str), row["approved_at"],
            ])
        data = buf.getvalue().encode("utf-8")

    key = file_storage.save_bytes("deliverables", data, fmt)
    size = len(data)
    digest = __import__("hashlib").sha256(data).hexdigest()
    return key, size, len(rows), digest


def notify_org_members(db: Session, org_id: int, type_: str, title: str, body: str,
                       entity_type: str | None = None, entity_id: int | str | None = None) -> None:
    from app.services.notifications import notify
    for uid in org_member_ids(db, org_id):
        notify(db, user_id=uid, type=type_, title=title, body=body,
               entity_type=entity_type, entity_id=entity_id)


def notify_staff_of_project(db: Session, project_id: int, type_: str, title: str, body: str,
                            entity_type: str | None = None, entity_id: int | str | None = None) -> None:
    """Notify staff who administer the project (owner + admin members)."""
    from app.services.notifications import notify
    project = db.get(Project, project_id)
    if project is None:
        return
    seen: set[int] = set()
    if project.owner_id:
        seen.add(project.owner_id)
    for m in project.members or []:
        if m.role == "admin":
            seen.add(m.user_id)
    for uid in seen:
        notify(db, user_id=uid, type=type_, title=title, body=body,
               entity_type=entity_type, entity_id=entity_id)


def notify_staff_of_project_request_queue(db: Session, request: ProjectRequest) -> None:
    """Alert platform administrators that a new client request needs review."""
    from app.services.notifications import notify
    from app.models.user import UserRole as _UR
    admins = db.scalars(
        select(User.id).where(
            User.role.in_([_UR.SUPER_ADMIN, _UR.PROJECT_ADMIN]), User.is_active.is_(True)
        )
    ).all()
    for uid in admins:
        notify(db, user_id=uid, type="client.request_update",
               title=f"New project request: {request.title}",
               body="A client organization submitted a project request for approval.",
               entity_type="project_request", entity_id=request.id)
