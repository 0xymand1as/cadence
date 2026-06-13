"""
Cadence — video object storage (Supabase Storage via its REST API).

Videos are NOT stored in Postgres (a large bytea write OOMs the small free
DB and crashes it). Instead the bytes live in a Supabase Storage bucket and
the DB keeps only the object key. Uses plain `requests` against the Storage
REST endpoints, so no extra dependency.

Env:
  SUPABASE_URL          e.g. https://abcd.supabase.co
  SUPABASE_SERVICE_KEY  the service_role key (server-side only)
  SUPABASE_BUCKET       bucket name (default: videos)
"""
from __future__ import annotations

import os
import requests

_URL    = os.environ.get("SUPABASE_URL", "").rstrip("/")
_KEY    = os.environ.get("SUPABASE_SERVICE_KEY", "")
_BUCKET = os.environ.get("SUPABASE_BUCKET", "videos")


class StorageError(Exception):
    """Raised when an object-storage operation fails."""


def is_configured() -> bool:
    return bool(_URL and _KEY)


def _obj_url(key: str) -> str:
    return f"{_URL}/storage/v1/object/{_BUCKET}/{key}"


def put_video(key: str, data: bytes) -> None:
    """Upload (upsert) video bytes at `key`."""
    if not is_configured():
        raise StorageError("Object storage is not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY).")
    r = requests.post(
        _obj_url(key),
        headers={
            "Authorization": f"Bearer {_KEY}",
            "Content-Type":  "video/mp4",
            "x-upsert":      "true",
        },
        data=data,
        timeout=180,
    )
    if not r.ok:
        raise StorageError(f"storage upload failed [{r.status_code}]: {r.text[:200]}")


def get_video(key: str) -> bytes:
    """Download video bytes for `key`."""
    if not is_configured():
        raise StorageError("Object storage is not configured.")
    r = requests.get(
        _obj_url(key),
        headers={"Authorization": f"Bearer {_KEY}"},
        timeout=180,
    )
    if not r.ok:
        raise StorageError(f"storage download failed [{r.status_code}]: {r.text[:200]}")
    return r.content


def delete_video(key: str) -> None:
    """Best-effort delete; never raises (cleanup only)."""
    if not (is_configured() and key):
        return
    try:
        requests.delete(
            _obj_url(key),
            headers={"Authorization": f"Bearer {_KEY}"},
            timeout=30,
        )
    except Exception:                                           # noqa: BLE001
        pass
