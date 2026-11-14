"""In-app notifications: history, unread badge, mark-read."""
from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.security import CurrentUser, DbSession
from app.models.notification import Notification
from app.services.audit import log_action

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(db: DbSession, user: CurrentUser, unread_only: bool = False,
                       page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=200)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Notification.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": n.id, "type": n.type, "title": n.title, "body": n.body,
                "entity_type": n.entity_type, "entity_id": n.entity_id, "read": n.read,
                "created_at": n.created_at.isoformat(),
            }
            for n in items
        ],
        "total": int(total), "page": page, "page_size": page_size,
    }


@router.get("/unread-count")
def unread_count(db: DbSession, user: CurrentUser):
    count = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read.is_(False))) or 0
    return {"unread": int(count)}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, db: DbSession, user: CurrentUser):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        return {"ok": False}
    n.read = True
    db.commit()
    return {"ok": True}


@router.post("/read-all")
def mark_all_read(db: DbSession, user: CurrentUser, request: Request):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read.is_(False)) \
        .update({"read": True})  # type: ignore[attr-defined]
    db.commit()
    return {"ok": True}
