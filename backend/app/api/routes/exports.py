"""CSV/JSON report exports with permission checks and audit logging."""
import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.security import AdminPM, CurrentUser, DbSession
from app.models.submission import Submission
from app.models.task import Task
from app.services import access as acl
from app.services.audit import log_action

router = APIRouter(prefix="/api/exports", tags=["exports"])


def _csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for r in rows:
        writer.writerow([r.get(c, "") for c in columns])
    return buf.getvalue()


@router.get("/tasks")
def export_tasks(db: DbSession, user: AdminPM, format: str = Query("csv", pattern="^(csv|json)$"),
                 project_id: int | None = None, request: Request = None):
    ids = acl.visible_project_ids(db, user)
    stmt = select(Task).options(joinedload(Task.tester))
    if ids is not None:
        stmt = stmt.where(Task.project_id.in_(ids or [0]))
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    tasks = db.scalars(stmt.order_by(Task.id)).all()
    rows = [
        {
            "task_id": t.id, "project_id": t.project_id, "title": t.title,
            "task_type": t.task_type, "status": t.status, "priority": t.priority,
            "difficulty": t.difficulty, "assigned_tester_id": t.assigned_tester_id or "",
            "claimed_at": t.claimed_at.isoformat() if t.claimed_at else "",
            "created_at": t.created_at.isoformat(),
        }
        for t in tasks
    ]
    log_action(db, user_id=user.id, action="data.export", entity_type="task", entity_id=None,
               details={"format": format, "count": len(rows), "project_id": project_id}, request=request)
    if format == "json":
        return Response(json.dumps(rows, default=str), media_type="application/json")
    csv_content = _csv(rows, ["task_id", "project_id", "title", "task_type", "status", "priority",
                              "difficulty", "assigned_tester_id", "claimed_at", "created_at"])
    return Response(csv_content, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="tasks.csv"'})


@router.get("/submissions")
def export_submissions(db: DbSession, user: AdminPM, format: str = Query("csv", pattern="^(csv|json)$"),
                       project_id: int | None = None, request: Request = None):
    ids = acl.visible_project_ids(db, user)
    stmt = select(Submission).options(joinedload(Submission.tester), joinedload(Submission.task))
    if ids is not None:
        stmt = stmt.where(Submission.project_id.in_(ids or [0]))
    if project_id:
        stmt = stmt.where(Submission.project_id == project_id)
    subs = db.scalars(stmt.order_by(Submission.id)).all()
    rows = [
        {
            "submission_id": s.id, "task_id": s.task_id, "project_id": s.project_id,
            "attempt": s.attempt_number, "status": s.status, "label": s.label or "",
            "explanation": (s.explanation or "")[:300], "time_spent_seconds": s.time_spent_seconds or "",
            "submitted_at": s.submitted_at.isoformat(), "decided_at": s.decided_at.isoformat() if s.decided_at else "",
        }
        for s in subs
    ]
    log_action(db, user_id=user.id, action="data.export", entity_type="submission", entity_id=None,
               details={"format": format, "count": len(rows), "project_id": project_id}, request=request)
    if format == "json":
        return Response(json.dumps(rows, default=str), media_type="application/json")
    csv_content = _csv(rows, ["submission_id", "task_id", "project_id", "attempt", "status", "label",
                              "explanation", "time_spent_seconds", "submitted_at", "decided_at"])
    return Response(csv_content, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="submissions.csv"'})
