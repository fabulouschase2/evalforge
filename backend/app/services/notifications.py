"""Notification service — in-app notifications for all platform events.

V3: single home for notification creation so every new feature routes through
here. Email delivery is intentionally NOT simulated: when SMTP is not
configured (env), `_send_email` is a no-op and the notification stays in-app.
"""
import logging
import os
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.models.notification import Notification

logger = logging.getLogger("evalforge.notifications")


def email_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def notify(db: Session, user_id: int, type: str, title: str, body: str | None = None,
           entity_type: str | None = None, entity_id: int | str | None = None,
           email_to: str | None = None) -> Notification:
    """Create an in-app notification (and send email only when configured)."""
    row = Notification(user_id=user_id, type=type, title=title, body=body,
                       entity_type=entity_type,
                       entity_id=str(entity_id) if entity_id is not None else None)
    db.add(row)
    if email_to and email_configured():
        _send_email(email_to, title, body or "")
    return row


def _send_email(to: str, subject: str, body: str) -> None:
    """Best-effort SMTP delivery; never raises into request handling.

    Requires SMTP_HOST (plus optional SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM, SMTP_TLS). Without configuration no email is sent and the
    attempt is logged — notifications remain in-app only.
    """
    host = os.environ.get("SMTP_HOST")
    if not host:
        logger.info("email skipped (SMTP not configured) to=%s subject=%r", to, subject)
        return
    try:
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg["From"] = os.environ.get("SMTP_FROM", "evalforge@localhost")
        msg.set_content(body)
        port = int(os.environ.get("SMTP_PORT", "587"))
        use_tls = os.environ.get("SMTP_TLS", "1") not in ("0", "false", "False")
        if use_tls:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.starttls()
                user = os.environ.get("SMTP_USER")
                if user:
                    server.login(user, os.environ.get("SMTP_PASSWORD", ""))
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.send_message(msg)
    except Exception:
        logger.exception("email delivery failed to=%s", to)
