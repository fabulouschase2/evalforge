"""API credential management (staff) + webhook endpoint management."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from app.core.security import AdminOnly, DbSession
from app.models.api_integration import (
    API_SCOPES, WEBHOOK_EVENTS, ApiCredential, ApiRequestLog,
    WebhookDelivery, WebhookEndpoint,
)
from app.models.user import User
from app.core.api_auth import generate_api_key
from app.services import webhooks as wh
from app.services.audit import log_action

router = APIRouter(prefix="/api/admin/api-keys", tags=["api-integrations"])
webhook_router = APIRouter(prefix="/api/admin/webhooks", tags=["api-integrations"])


def _cred_out(c: ApiCredential) -> dict:
    return {
        "id": c.id, "name": c.name, "key_prefix": c.key_prefix,
        "scopes": c.scopes or [], "organization_id": c.organization_id,
        "project_ids": c.project_ids or [], "is_revoked": c.is_revoked,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("")
def list_keys(db: DbSession, user: AdminOnly):
    rows = db.scalars(select(ApiCredential).order_by(ApiCredential.created_at.desc())).all()
    return [_cred_out(c) for c in rows]


@router.post("", status_code=201)
def create_key(payload: dict, db: DbSession, user: AdminOnly, request: Request):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required.")
    scopes = payload.get("scopes") or []
    bad = [s for s in scopes if s not in API_SCOPES]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown scopes: {bad}; allowed: {API_SCOPES}")
    if not scopes:
        raise HTTPException(status_code=422, detail="At least one scope is required.")
    org_id = payload.get("organization_id")
    project_ids = payload.get("project_ids") or []
    expires_at = payload.get("expires_at")
    raw, prefix, key_hash = generate_api_key()
    cred = ApiCredential(
        name=name, key_prefix=prefix, key_hash=key_hash, scopes=scopes,
        organization_id=org_id, project_ids=project_ids or [],
        expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
        created_by=user.id,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    log_action(db, user_id=user.id, action="api_key.create", entity_type="api_credential",
               entity_id=cred.id, details={"name": name, "scopes": scopes}, request=request)
    # raw key is returned exactly once; only the hash is stored
    return {**_cred_out(cred), "key": raw}


@router.post("/{key_id}/rotate", status_code=201)
def rotate_key(key_id: int, db: DbSession, user: AdminOnly, request: Request):
    """Revoke the old key and issue a replacement with identical scopes."""
    cred = db.get(ApiCredential, key_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="API key not found.")
    if cred.is_revoked:
        raise HTTPException(status_code=409, detail="Revoked keys cannot be rotated.")
    raw, prefix, key_hash = generate_api_key()
    cred.is_revoked = True
    cred.revoked_at = datetime.now(timezone.utc)
    cred.revoked_by = user.id
    new_cred = ApiCredential(
        name=cred.name, key_prefix=prefix, key_hash=key_hash, scopes=cred.scopes,
        organization_id=cred.organization_id, project_ids=cred.project_ids,
        expires_at=cred.expires_at, created_by=user.id,
    )
    db.add(new_cred)
    db.commit()
    db.refresh(new_cred)
    log_action(db, user_id=user.id, action="api_key.rotate", entity_type="api_credential",
               entity_id=cred.id, details={"new_id": new_cred.id}, request=request)
    return {**_cred_out(new_cred), "key": raw}


@router.delete("/{key_id}")
def revoke_key(key_id: int, db: DbSession, user: AdminOnly, request: Request):
    cred = db.get(ApiCredential, key_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="API key not found.")
    cred.is_revoked = True
    cred.revoked_at = datetime.now(timezone.utc)
    cred.revoked_by = user.id
    db.commit()
    log_action(db, user_id=user.id, action="api_key.revoke", entity_type="api_credential",
               entity_id=cred.id, details={"name": cred.name}, request=request)
    return {"ok": True}


@router.get("/{key_id}/activity")
def key_activity(key_id: int, db: DbSession, user: AdminOnly,
                 page: int = 1, page_size: int = 50):
    cred = db.get(ApiCredential, key_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="API key not found.")
    total = db.scalar(select(func.count()).select_from(ApiRequestLog)
                      .where(ApiRequestLog.credential_id == key_id)) or 0
    rows = db.scalars(
        select(ApiRequestLog).where(ApiRequestLog.credential_id == key_id)
        .order_by(ApiRequestLog.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "total": total,
        "items": [
            {"id": r.id, "method": r.method, "path": r.path,
             "status_code": r.status_code,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Webhook endpoints
# ---------------------------------------------------------------------------

def _endpoint_out(e: WebhookEndpoint, with_secret: bool = False) -> dict:
    data = {
        "id": e.id, "url": e.url, "events": e.events or [],
        "organization_id": e.organization_id, "project_id": e.project_id,
        "is_active": e.is_active,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }
    if with_secret:
        data["secret"] = e.secret
    return data


@webhook_router.get("")
def list_webhooks(db: DbSession, user: AdminOnly):
    rows = db.scalars(select(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc())).all()
    return [_endpoint_out(e) for e in rows]


@webhook_router.post("", status_code=201)
def create_webhook(payload: dict, db: DbSession, user: AdminOnly, request: Request):
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="url is required.")
    try:
        wh.validate_webhook_url(url)
    except wh.SSRFError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    events = payload.get("events") or []
    bad = [e for e in events if e not in WEBHOOK_EVENTS]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown events: {bad}; allowed: {WEBHOOK_EVENTS}")
    if not events:
        raise HTTPException(status_code=422, detail="Subscribe to at least one event.")
    secret = wh.generate_secret()
    endpoint = WebhookEndpoint(
        url=url, secret=secret, events=events,
        organization_id=payload.get("organization_id"),
        project_id=payload.get("project_id"),
        created_by=user.id,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    log_action(db, user_id=user.id, action="webhook.create", entity_type="webhook_endpoint",
               entity_id=endpoint.id, details={"url": url, "events": events}, request=request)
    return {**_endpoint_out(endpoint, with_secret=True),
            "note": "Store the signing secret now — it is not retrievable afterwards."}


@webhook_router.put("/{webhook_id}")
def update_webhook(webhook_id: int, payload: dict, db: DbSession, user: AdminOnly, request: Request):
    ep = db.get(WebhookEndpoint, webhook_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    if "url" in payload and payload["url"]:
        try:
            wh.validate_webhook_url(payload["url"])
        except wh.SSRFError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        ep.url = payload["url"]
    if isinstance(payload.get("events"), list):
        bad = [e for e in payload["events"] if e not in WEBHOOK_EVENTS]
        if bad:
            raise HTTPException(status_code=422, detail=f"Unknown events: {bad}")
        ep.events = payload["events"]
    if isinstance(payload.get("is_active"), bool):
        ep.is_active = payload["is_active"]
    db.commit()
    log_action(db, user_id=user.id, action="webhook.update", entity_type="webhook_endpoint",
               entity_id=ep.id, request=request)
    return _endpoint_out(ep)


@webhook_router.get("/{webhook_id}/deliveries")
def webhook_deliveries(webhook_id: int, db: DbSession, user: AdminOnly,
                       page: int = 1, page_size: int = 50):
    ep = db.get(WebhookEndpoint, webhook_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    total = db.scalar(select(func.count()).select_from(WebhookDelivery)
                      .where(WebhookDelivery.endpoint_id == webhook_id)) or 0
    rows = db.scalars(
        select(WebhookDelivery).where(WebhookDelivery.endpoint_id == webhook_id)
        .order_by(WebhookDelivery.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "total": total,
        "items": [
            {"id": d.id, "event_type": d.event_type, "status": d.status,
             "attempts": d.attempts, "response_code": d.response_code,
             "error": d.error, "payload": d.payload,
             "created_at": d.created_at.isoformat() if d.created_at else None,
             "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None}
            for d in rows
        ],
    }


@webhook_router.post("/{webhook_id}/test", status_code=202)
def test_webhook(webhook_id: int, db: DbSession, user: AdminOnly, request: Request):
    ep = db.get(WebhookEndpoint, webhook_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    queued = wh.dispatch_event(db, "webhook.test", {"note": "Manual test delivery.", "by": user.email})
    return {"queued": queued}


@webhook_router.post("/deliveries/{delivery_id}/replay", status_code=202)
def replay_delivery(delivery_id: int, db: DbSession, user: AdminOnly, request: Request):
    delivery = db.get(WebhookDelivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Delivery not found.")
    delivery.status = "pending"
    delivery.attempts = 0
    delivery.next_retry_at = datetime.now(timezone.utc)
    delivery.error = None
    db.commit()
    log_action(db, user_id=user.id, action="webhook.replay", entity_type="webhook_delivery",
               entity_id=delivery.id, request=request)
    return {"ok": True}
