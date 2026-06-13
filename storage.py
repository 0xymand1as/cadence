"""
Cadence — video object storage (Cloudflare R2 via the S3-compatible API).

Videos are NOT stored in Postgres (a large bytea write OOMs the small free
DB and crashes it). Instead the bytes live in an R2 bucket and the DB keeps
only the object key. R2 is reached over its S3-compatible endpoint with a
bucket-scoped API token, so a Cadence breach exposes ONLY this one bucket —
not any other project's data.

Env:
  R2_ENDPOINT_URL       e.g. https://<accountid>.r2.cloudflarestorage.com
  R2_ACCESS_KEY_ID      R2 API token access key id (scoped to this bucket)
  R2_SECRET_ACCESS_KEY  R2 API token secret
  R2_BUCKET             bucket name (default: videos)
"""
from __future__ import annotations

import os

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

_ENDPOINT = os.environ.get("R2_ENDPOINT_URL", "").rstrip("/")
_KEY_ID   = os.environ.get("R2_ACCESS_KEY_ID", "")
_SECRET   = os.environ.get("R2_SECRET_ACCESS_KEY", "")
_BUCKET   = os.environ.get("R2_BUCKET", "videos")

_client = None


class StorageError(Exception):
    """Raised when an object-storage operation fails."""


def is_configured() -> bool:
    return bool(_ENDPOINT and _KEY_ID and _SECRET)


def _s3():
    """Lazily build (and cache) the S3 client for R2."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=_ENDPOINT,
            aws_access_key_id=_KEY_ID,
            aws_secret_access_key=_SECRET,
            region_name="auto",                       # R2 ignores region; "auto" is the convention
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )
    return _client


def put_video(key: str, data: bytes) -> None:
    """Upload (upsert) video bytes at `key`."""
    if not is_configured():
        raise StorageError("Object storage is not configured (R2_ENDPOINT_URL / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY).")
    try:
        _s3().put_object(Bucket=_BUCKET, Key=key, Body=data, ContentType="video/mp4")
    except (ClientError, BotoCoreError) as e:
        raise StorageError(f"storage upload failed: {e}") from e


def get_video(key: str) -> bytes:
    """Download video bytes for `key`."""
    if not is_configured():
        raise StorageError("Object storage is not configured.")
    try:
        resp = _s3().get_object(Bucket=_BUCKET, Key=key)
        return resp["Body"].read()
    except (ClientError, BotoCoreError) as e:
        raise StorageError(f"storage download failed: {e}") from e


def delete_video(key: str) -> None:
    """Best-effort delete; never raises (cleanup only)."""
    if not (is_configured() and key):
        return
    try:
        _s3().delete_object(Bucket=_BUCKET, Key=key)
    except Exception:                                           # noqa: BLE001
        pass
