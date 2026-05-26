"""
Cadence — background scheduler that fires queued posts at scheduled_at.

Run loop polls every 30s for posts where:
  - status == "queued"
  - scheduled_at <= now()

For each match: mark publishing → call poster.publish_video → mark posted
or failed with error. Refreshes expired tokens on the way.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from models import db, ScheduledPost, TTAccount
from crypto import decrypt, encrypt
from poster import publish_video, refresh_access_token, TTPostError

log = logging.getLogger("cadence.scheduler")


def _fire_due_posts(app):
    """Find every due queued post + publish it."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        due = (
            ScheduledPost.query
            .filter(ScheduledPost.status == "queued")
            .filter(ScheduledPost.scheduled_at <= now)
            .order_by(ScheduledPost.scheduled_at.asc())
            .limit(20)
            .all()
        )

        if not due:
            return

        for post in due:
            post.status = "publishing"
            db.session.commit()
            try:
                acct = post.tt_account
                access_token = _ensure_fresh_token(acct, app)
                publish_id = publish_video(
                    access_token, post.video_blob, post.caption or ""
                )
                post.status        = "posted"
                post.tt_publish_id = publish_id
                post.posted_at     = datetime.now(timezone.utc)
                # free the blob — keep DB lean post-publish
                post.video_blob    = b""
                db.session.commit()
                log.info(f"posted {post.id} → publish_id={publish_id}")
            except Exception as e:
                post.status = "failed"
                post.error  = str(e)[:1000]
                db.session.commit()
                log.exception(f"failed to post {post.id}: {e}")


def _ensure_fresh_token(acct: TTAccount, app) -> str:
    """Decrypt access token; refresh if expiring within 5 min."""
    if acct.expires_at - datetime.now(timezone.utc) > timedelta(minutes=5):
        return decrypt(acct.access_token_e)

    # refresh
    new = refresh_access_token(
        client_key    = os.environ["TIKTOK_CLIENT_KEY"],
        client_secret = os.environ["TIKTOK_CLIENT_SECRET"],
        refresh_token = decrypt(acct.refresh_token_e),
    )
    acct.access_token_e  = encrypt(new["access_token"])
    if new.get("refresh_token"):
        acct.refresh_token_e = encrypt(new["refresh_token"])
    expires_in = int(new.get("expires_in", 3600))
    acct.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    db.session.commit()
    return new["access_token"]


def start_scheduler(app):
    sched = BackgroundScheduler(daemon=True, timezone="UTC")
    sched.add_job(
        _fire_due_posts,
        trigger="interval",
        seconds=30,
        args=[app],
        id="cadence_fire_due",
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    log.info("Cadence scheduler started (30s tick)")
    return sched
