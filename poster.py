"""
Cadence — TikTok Content Posting API client.

Implements chunked direct-upload flow:
  1. POST /v2/post/publish/video/init/   → upload_url
  2. PUT chunks of bytes to upload_url
  3. POST /v2/post/publish/status/fetch/ → poll until PUBLISH_COMPLETE
"""
from __future__ import annotations

import time
import requests

API_BASE  = "https://open.tiktokapis.com"
INIT_URL  = f"{API_BASE}/v2/post/publish/video/init/"
STATUS_URL= f"{API_BASE}/v2/post/publish/status/fetch/"


class TTPostError(Exception):
    """Raised when any TT API call fails."""


def _h(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json; charset=UTF-8",
    }


def publish_video(access_token: str, video_bytes: bytes, caption: str) -> str:
    """
    Synchronously publish a video to the TikTok account associated with
    `access_token`. Returns the TT publish_id once PUBLISH_COMPLETE.
    Raises TTPostError on any failure.
    """
    size  = len(video_bytes)
    chunk = min(size, 10_000_000)  # 10 MB max per chunk per TT spec

    # ── 1. init ───────────────────────────────────────────────────────
    init_body = {
        "post_info": {
            "title":               caption[:2200],
            "privacy_level":       "PUBLIC_TO_EVERYONE",
            "disable_duet":        False,
            "disable_comment":     False,
            "disable_stitch":      False,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source":            "FILE_UPLOAD",
            "video_size":        size,
            "chunk_size":        chunk,
            "total_chunk_count": max(1, (size + chunk - 1) // chunk),
        },
    }
    r = requests.post(INIT_URL, headers=_h(access_token), json=init_body, timeout=30)
    if not r.ok:
        raise TTPostError(f"init failed [{r.status_code}]: {r.text[:400]}")
    body = r.json().get("data", {})
    publish_id = body.get("publish_id")
    upload_url = body.get("upload_url")
    if not (publish_id and upload_url):
        raise TTPostError(f"init missing publish_id or upload_url: {body}")

    # ── 2. chunked upload ─────────────────────────────────────────────
    offset = 0
    while offset < size:
        end = min(offset + chunk, size) - 1
        seg = video_bytes[offset:end + 1]
        put = requests.put(
            upload_url,
            headers={
                "Content-Range": f"bytes {offset}-{end}/{size}",
                "Content-Type":  "video/mp4",
            },
            data=seg,
            timeout=300,
        )
        if put.status_code not in (200, 201, 206):
            raise TTPostError(f"chunk PUT [{offset}-{end}] failed [{put.status_code}]: {put.text[:200]}")
        offset = end + 1

    # ── 3. poll status ────────────────────────────────────────────────
    deadline = time.time() + 600  # 10 min cap
    while time.time() < deadline:
        time.sleep(4)
        s = requests.post(STATUS_URL, headers=_h(access_token),
                          json={"publish_id": publish_id}, timeout=30)
        if not s.ok:
            raise TTPostError(f"status fetch failed [{s.status_code}]: {s.text[:200]}")
        st = s.json().get("data", {})
        status = st.get("status")
        if status == "PUBLISH_COMPLETE":
            return publish_id
        if status in ("FAILED", "PUBLISH_FAILED"):
            raise TTPostError(f"publish failed: {st}")

    raise TTPostError("publish polling timed out after 10 min")


def refresh_access_token(client_key: str, client_secret: str, refresh_token: str) -> dict:
    """Refresh an expired access token. Returns the new token dict."""
    r = requests.post(
        f"{API_BASE}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key":    client_key,
            "client_secret": client_secret,
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    if not r.ok:
        raise TTPostError(f"refresh failed [{r.status_code}]: {r.text[:200]}")
    return r.json()
