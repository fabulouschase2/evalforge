"""External API authentication: X-API-Key -> scoped, org-bound credentials.

A key NEVER inherits interactive user permissions: every external request is
authorized by (scopes, organization, project allowlist) only. Rate limiting is
a per-credential in-memory token bucket (documented: use Redis for multi-
instance production deployments).
"""
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.api_integration import ApiCredential, ApiRequestLog
from app.models.user import utcnow

_db_session_factory = None


def bind_session_factory(factory) -> None:
    """Bind the SessionLocal used by logging (wired in main.lifespan)."""
    global _db_session_factory
    _db_session_factory = factory


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, key_prefix, key_hash). Raw shown once, never stored."""
    raw = "ef_" + secrets.token_urlsafe(32)
    return raw, raw[:10], hash_key(raw)


class ApiContext:
    """Resolved credential context carried through external requests."""

    def __init__(self, credential: ApiCredential):
        self.credential = credential

    @property
    def id(self) -> int:
        return self.credential.id

    @property
    def organization_id(self) -> int | None:
        return self.credential.organization_id

    def has_scope(self, scope: str) -> bool:
        return scope in (self.credential.scopes or [])

    def require_scope(self, scope: str) -> None:
        if not self.has_scope(scope):
            raise HTTPException(status_code=403, detail=f"This credential lacks the '{scope}' scope.")

    def project_allowed(self, project_id: int, project_org: int | None) -> bool:
        cred = self.credential
        if cred.organization_id is not None and project_org != cred.organization_id:
            return False
        allow = cred.project_ids or []
        return not allow or project_id in allow


# --- rate limiting (in-memory token bucket per credential) -------------------

_buckets: dict[int, dict] = {}
_buckets_lock = threading.Lock()
RATE_LIMIT_PER_MINUTE = 120


def check_rate_limit(credential_id: int) -> None:
    now = time.monotonic()
    with _buckets_lock:
        bucket = _buckets.setdefault(credential_id, {"tokens": RATE_LIMIT_PER_MINUTE, "ts": now})
        elapsed = now - bucket["ts"]
        bucket["tokens"] = min(RATE_LIMIT_PER_MINUTE,
                               bucket["tokens"] + elapsed * (RATE_LIMIT_PER_MINUTE / 60.0))
        bucket["ts"] = now
        if bucket["tokens"] < 1:
            raise HTTPException(status_code=429, detail="API rate limit exceeded (120 requests/minute).")
        bucket["tokens"] -= 1


def get_api_credential(request: Request, db=Depends(get_db)) -> ApiContext:
    raw = request.headers.get("X-API-Key") or ""
    if not raw:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    if not hmac.compare_digest(raw[:3], "ef_"):
        raise HTTPException(status_code=401, detail="Invalid API key format.")
    # constant-time-ish lookup via prefix then hash compare
    cred = db.scalar(
        select(ApiCredential).where(ApiCredential.key_prefix == raw[:10])
    )
    if cred is None or not hmac.compare_digest(cred.key_hash, hash_key(raw)):
        raise HTTPException(status_code=401, detail="Invalid API key.")
    if cred.is_revoked or cred.revoked_at is not None:
        raise HTTPException(status_code=401, detail="This API key has been revoked.")
    if cred.expires_at is not None:
        exp = cred.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="This API key has expired.")
    check_rate_limit(cred.id)
    cred.last_used_at = utcnow()
    db.commit()
    # expose the resolved credential for the request-logging middleware
    request.state.api_credential_id = cred.id
    request.state.api_credential_scopes = cred.scopes or []
    return ApiContext(cred)


def log_api_request(credential_id: int, method: str, path: str, status_code: int) -> None:
    if _db_session_factory is None:
        return
    try:
        db = _db_session_factory()
        try:
            db.add(ApiRequestLog(credential_id=credential_id, method=method,
                                 path=path[:300], status_code=status_code))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass  # request logging must never break the API response


ApiAuth = Depends(get_api_credential)
