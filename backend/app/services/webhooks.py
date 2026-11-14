"""Outbound webhooks: signing, SSRF protection, delivery with retries.

- Payloads are signed `X-EvalForge-Signature: t=<unix>,v1=HMAC_SHA256(secret, t + "." + body)`
  (Stripe-style; secret shown once at endpoint creation, stored hashed).
- SSRF guard: http(s) only, IP-literal private/loopback/link-local/metadata
  ranges blocked, DNS resolved and re-checked at delivery time.
- Deliveries run in a small background worker thread (in-process queue with
  exponential backoff; single-process scale documented for production).
"""
import hashlib
import hmac
import ipaddress
import json
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.api_integration import WebhookDelivery, WebhookEndpoint

MAX_ATTEMPTS = 5
BACKOFF_SECONDS = [30, 120, 600, 3600]  # after attempt 1..4

_blocked_net = threading.local()


def hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_secret() -> str:
    import secrets
    return "whsec_" + secrets.token_urlsafe(32)


def sign_payload(secret_raw: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret_raw.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


class SSRFError(ValueError):
    pass


def _ip_blocked(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
        or addr.is_multicast or addr.is_unspecified
        or str(addr) in ("169.254.169.254",)  # cloud metadata endpoints
    )


def validate_webhook_url(url: str) -> None:
    """SSRF guard — raises SSRFError for non-public http(s) targets."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError("Webhook URL must use http or https.")
    host = parsed.hostname
    if not host:
        raise SSRFError("Webhook URL has no host.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        raise SSRFError(f"Webhook host '{host}' does not resolve.")
    for info in infos:
        ip = info[4][0]
        if _ip_blocked(ip):
            raise SSRFError(f"Webhook host resolves to a forbidden address ({ip}). "
                            "Internal network access is not allowed.")


def dispatch_event(db: Session, event_type: str, payload: dict) -> int:
    """Queue a delivery for every active endpoint subscribed to this event.

    Returns the number of deliveries queued. Delivery itself happens on the
    background worker (test environments can call deliver_due() directly).
    """
    endpoints = db.scalars(
        select(WebhookEndpoint).where(WebhookEndpoint.is_active.is_(True))
    ).all()
    queued = 0
    for ep in endpoints:
        events = ep.events or []
        if events and event_type not in events:
            continue
        body = {"event": event_type, "data": payload, "queued_at": datetime.now(timezone.utc).isoformat()}
        delivery = WebhookDelivery(
            endpoint_id=ep.id, event_type=event_type, payload=body, status="pending",
            next_retry_at=datetime.now(timezone.utc),
        )
        db.add(delivery)
        queued += 1
    if queued:
        db.commit()
    return queued


def deliver_due(db: Session, max_deliveries: int = 20, allow_private: bool = False) -> int:
    """Attempt deliveries whose retry time has arrived. Returns processed count.

    `allow_private=True` exists for integration tests with local receivers;
    production callers never pass it.
    """
    now = datetime.now(timezone.utc)
    due = db.scalars(
        select(WebhookDelivery).where(
            WebhookDelivery.status == "pending",
            WebhookDelivery.next_retry_at <= now,
        ).limit(max_deliveries)
    ).all()
    processed = 0
    for delivery in due:
        endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None or not endpoint.is_active:
            delivery.status = "disabled"
            db.commit()
            continue
        try:
            if not allow_private:
                validate_webhook_url(endpoint.url)
        except SSRFError as exc:
            delivery.error = f"Blocked: {exc}"
            delivery.status = "failed"
            db.commit()
            processed += 1
            continue
        body = json.dumps(delivery.payload, default=str).encode("utf-8")
        ts = int(time.time())
        sig = sign_payload(endpoint.secret, ts, body)
        try:
            resp = httpx.post(
                endpoint.url, content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-EvalForge-Event": delivery.event_type,
                    "X-EvalForge-Signature": sig,
                    "User-Agent": "EvalForge-Webhooks/1.0",
                },
                timeout=10.0,
            )
            delivery.attempts += 1
            delivery.response_code = resp.status_code
            if 200 <= resp.status_code < 300:
                delivery.status = "delivered"
                delivery.delivered_at = datetime.now(timezone.utc)
                delivery.error = None
            else:
                _reschedule(db, delivery)
        except httpx.HTTPError as exc:
            delivery.attempts += 1
            delivery.error = str(exc)[:500]
            _reschedule(db, delivery)
        db.commit()
        processed += 1
    return processed


def _reschedule(db: Session, delivery: WebhookDelivery) -> None:
    if delivery.attempts >= MAX_ATTEMPTS:
        delivery.status = "failed"
        delivery.next_retry_at = None
    else:
        delay = BACKOFF_SECONDS[min(delivery.attempts - 1, len(BACKOFF_SECONDS) - 1)]
        delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)


_worker_thread: threading.Thread | None = None
_worker_stop = threading.Event()


def start_worker(session_factory) -> None:
    """Start the in-process delivery loop (no-op when already running)."""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return

    def _loop() -> None:
        while not _worker_stop.is_set():
            try:
                db = session_factory()
                try:
                    deliver_due(db)
                finally:
                    db.close()
            except Exception:
                pass
            _worker_stop.wait(5.0)

    _worker_stop.clear()
    _worker_thread = threading.Thread(target=_loop, name="evalforge-webhooks", daemon=True)
    _worker_thread.start()


def stop_worker() -> None:
    _worker_stop.set()
