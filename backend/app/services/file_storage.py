"""Local file storage for deliverables, attachments and (Phase 5+) media.

Design:
- Everything lives under a single root directory (env-configurable) with
  per-domain subdirectories (`deliverables/`, `attachments/`, `media/`).
- Keys are opaque (`<domain>/<uuid>.<ext>`); callers never embed user input in
  paths — traversal-safe by construction.
- Files are served exclusively through authenticated endpoints, never static
  mounts. `MEDIA_STORAGE_URL` env switch documented for S3 in production; the
  S3 driver is intentionally NOT stubbed as working here.
"""
import hashlib
import os
import uuid
from pathlib import Path

from fastapi import HTTPException

# Storage root: EVALFORGE_STORAGE_ROOT overrides; default `storage/` relative
# to the backend working directory (next to evalforge.db in dev).
_ROOT = Path(os.environ.get("EVALFORGE_STORAGE_ROOT") or "storage").resolve()

DOMAINS = {"deliverables", "attachments", "media"}


def _domain_dir(domain: str) -> Path:
    if domain not in DOMAINS:
        raise ValueError(f"Unknown storage domain {domain!r}")
    d = _ROOT / domain
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_bytes(domain: str, data: bytes, ext: str) -> str:
    """Store bytes and return the storage key."""
    ext = (ext or ".bin").lower().lstrip(".")
    if not ext or len(ext) > 10 or not ext.isalnum():
        ext = "bin"
    key = f"{domain}/{uuid.uuid4().hex}.{ext}"
    path = _domain_dir(domain) / f"{uuid.uuid4().hex}.{ext}"
    path.write_bytes(data)
    # align returned key with the real written filename
    return f"{domain}/{path.name}" if key.rsplit("/", 1)[-1] != path.name else key


def open_key(key: str) -> bytes:
    """Read a stored object by key. Raises HTTPException(404) when missing."""
    domain, _, name = key.partition("/")
    if domain not in DOMAINS or not name or "/" in name or ".." in name or "\\" in name:
        raise HTTPException(status_code=404, detail="File not found.")
    path = (_ROOT / domain / name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return path.read_bytes()


def open_key_streamed(key: str, chunk_size: int = 1024 * 256):
    """Stream a stored object in chunks (for large deliverables/media)."""
    domain, _, name = key.partition("/")
    if domain not in DOMAINS or not name or "/" in name or ".." in name or "\\" in name:
        raise HTTPException(status_code=404, detail="File not found.")
    path = (_ROOT / domain / name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            yield chunk


def key_size(key: str) -> int:
    domain, _, name = key.partition("/")
    if domain not in DOMAINS or not name:
        return 0
    path = (_ROOT / domain / name)
    return path.stat().st_size if path.is_file() else 0


def sha256_of(key: str) -> str:
    h = hashlib.sha256()
    for chunk in open_key_streamed(key):
        h.update(chunk)
    return h.hexdigest()
