"""Audit log routes and application settings."""
from fastapi import APIRouter, Query, Request

from app.core.security import AdminOnly, AdminPM, CurrentUser, DbSession
from app.db.base import get_db
from app.models.audit import Setting
from app.schemas import AuditLogOut, PaginatedOut, SettingsOut, SettingsUpdate
from app.services import audit as audit_svc
from app.services.audit import log_action

router = APIRouter(tags=["audit", "settings"])


@router.get("/api/audit-logs", response_model=PaginatedOut)
def list_audit_logs(
    db: DbSession,
    user: AdminPM,
    action: str | None = None,
    entity_type: str | None = None,
    user_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    items, total = audit_svc.list_logs(db, action=action, entity_type=entity_type, user_id=user_id, page=page, page_size=page_size)
    return PaginatedOut(
        items=[AuditLogOut.model_validate(i).model_dump(mode="json") for i in items],
        total=total, page=page, page_size=page_size,
    )


DEFAULT_SETTINGS = SettingsOut()

SETTING_KEY = "app"


@router.get("/api/settings", response_model=SettingsOut)
def get_settings(db: DbSession, user: CurrentUser):
    row = db.get(Setting, SETTING_KEY)
    if row is None:
        return DEFAULT_SETTINGS
    stored = row.value or {}
    return SettingsOut(**{**DEFAULT_SETTINGS.model_dump(), **stored})


@router.put("/api/settings", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate, db: DbSession, user: AdminOnly, request: Request):
    row = db.get(Setting, SETTING_KEY)
    current = SettingsOut(**((row.value or {}) if row else {}))
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        return current
    merged = {**current.model_dump(), **changes}
    if row is None:
        row = Setting(key=SETTING_KEY, value=merged)
        db.add(row)
    else:
        row.value = merged
    db.commit()
    log_action(db, user_id=user.id, action="settings.update", entity_type="settings", entity_id=SETTING_KEY,
               details={"changes": changes}, request=request)
    return SettingsOut(**merged)
