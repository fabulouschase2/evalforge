"""Simple in-memory sliding-window rate limiting for sensitive endpoints.

Per (ip, bucket) counters; suitable for single-process deployments and a
sane baseline for brute-force protection on authentication. In multi-worker
production deployments, swap the storage for Redis (interface unchanged).
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.services.audit import client_ip

_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_LOCK = threading.Lock()


def rate_limit(request: Request, bucket: str, max_events: int, window_seconds: int) -> None:
    """Raise 429 when the caller exceeds max_events within window_seconds."""
    key = f"{bucket}:{client_ip(request) or 'unknown'}"
    now = time.monotonic()
    with _LOCK:
        q = _BUCKETS[key]
        while q and q[0] <= now - window_seconds:
            q.popleft()
        if len(q) >= max_events:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait a moment and try again.",
            )
        q.append(now)


def reset_rate_limits() -> None:
    """Clear all buckets (used by the test suite to isolate tests)."""
    with _LOCK:
        _BUCKETS.clear()
