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
CREATOR_INFO_URL = f"{API_BASE}/v2/post/publish/creator_info/query/"


class TTPostError(Exception):
    """Raised when any TT API call fails."""


def _h(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json; charset=UTF-8",
    }


def query_creator_info(access_token: str) -> dict:
    """
    Query the creator's posting capabilities. REQUIRED by TikTok's Content
    Posting UX guidelines — the posting UI must source its privacy options,
    interaction-disable flags, nickname, and max duration from this call
    (not hardcoded). Returns the `data` dict, e.g.:
      {
        "creator_username", "creator_nickname", "creator_avatar_url",
        "privacy_level_options": [...],   # populate the audience selector
        "comment_disabled", "duet_disabled", "stitch_disabled",  # bools
        "max_video_post_duration_sec"
      }
    Raises TTPostError on failure (caller should ask the user to reconnect).
    """
    # TikTok requires an explicit (empty) JSON body for this POST; sending none
    # with an application/json content-type is rejected as malformed.
    r = requests.post(CREATOR_INFO_URL, headers=_h(access_token), json={}, timeout=15)
    if not r.ok:
        raise TTPostError(f"creator_info failed [{r.status_code}]: {r.text[:300]}")
    return r.json().get("data", {}) or {}


def publish_video(access_token: str, video_bytes: bytes, caption: str,
                  privacy_level: str = "SELF_ONLY",
                  disable_comment: bool = False,
                  disable_duet: bool = False,
                  disable_stitch: bool = False,
                  brand_content_toggle: bool = False,
                  brand_organic_toggle: bool = False) -> str:
    """
    Synchronously publish a video to the TikTok account associated with
    `access_token`. Returns the TT publish_id once PUBLISH_COMPLETE.
    Raises TTPostError on any failure.

    Interaction + commercial-disclosure flags mirror the creator's choices in
    the posting UI (TikTok Content Posting UX requirements):
      disable_*            — turn off comment/duet/stitch for this post
      brand_organic_toggle — "Your Brand" (Promotional content) disclosure
      brand_content_toggle — "Branded content" (Paid partnership) disclosure
    """
    size = len(video_bytes)
    # TikTok chunk rules: a video <= 64 MB uploads as a SINGLE chunk (even when
    # under the 5 MB per-chunk minimum). Above 64 MB it splits into 10 MB chunks
    # where total_chunk_count is a FLOOR and the final chunk absorbs the
    # remainder — so no trailing chunk falls under the 5 MB minimum. The old
    # `min(size,10MB)` + ceil math produced a tiny final chunk for any 10–64 MB
    # video, which TikTok rejected with invalid_params ("total chunk count").
    if size <= 64_000_000:
        chunk        = size
        total_chunks = 1
    else:
        chunk        = 10_000_000
        total_chunks = size // chunk

    # ── 1. init ───────────────────────────────────────────────────────
    init_body = {
        "post_info": {
            "title":               caption[:2200],
            "privacy_level":       privacy_level,
            "disable_duet":        bool(disable_duet),
            "disable_comment":     bool(disable_comment),
            "disable_stitch":      bool(disable_stitch),
            "brand_content_toggle": bool(brand_content_toggle),
            "brand_organic_toggle": bool(brand_organic_toggle),
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source":            "FILE_UPLOAD",
            "video_size":        size,
            "chunk_size":        chunk,
            "total_chunk_count": total_chunks,
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
    for i in range(total_chunks):
        offset = i * chunk
        # final chunk runs to the end of the file (absorbs any remainder)
        end = (size - 1) if i == total_chunks - 1 else (offset + chunk - 1)
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
