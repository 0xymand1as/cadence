"""
Cadence — SQLAlchemy models.

Tables:
  users           — email + bcrypt password hash + created_at + last_login_at
  tt_accounts     — per-user connected TikTok account (encrypted tokens)
  scheduled_posts — queue of scheduled videos (status: queued | publishing | posted | failed | cancelled)
"""
from __future__ import annotations

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at    = db.Column(db.DateTime, nullable=False, default=_utcnow)
    last_login_at = db.Column(db.DateTime)

    tt_accounts     = db.relationship("TTAccount",     backref="user", lazy=True,
                                       cascade="all, delete-orphan")
    scheduled_posts = db.relationship("ScheduledPost", backref="user", lazy=True,
                                       cascade="all, delete-orphan")


class TTAccount(db.Model):
    __tablename__ = "tt_accounts"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    tt_open_id      = db.Column(db.String(255), nullable=False)
    handle          = db.Column(db.String(64), default="")
    avatar_url      = db.Column(db.String(512), default="")
    access_token_e  = db.Column(db.Text, nullable=False)   # Fernet-encrypted
    refresh_token_e = db.Column(db.Text, nullable=False)   # Fernet-encrypted
    expires_at      = db.Column(db.DateTime, nullable=False)
    created_at      = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "tt_open_id", name="uq_user_tt"),)


class ScheduledPost(db.Model):
    __tablename__ = "scheduled_posts"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"),       nullable=False, index=True)
    tt_account_id   = db.Column(db.Integer, db.ForeignKey("tt_accounts.id"), nullable=False, index=True)
    video_filename  = db.Column(db.String(255), nullable=False)
    video_blob      = db.Column(db.LargeBinary, nullable=False)  # held in DB; OK for review-stage volume
    video_size      = db.Column(db.Integer, default=0)           # bytes — cheap query w/o LENGTH(blob)
    caption         = db.Column(db.Text, default="")
    scheduled_at    = db.Column(db.DateTime, nullable=False, index=True)
    status          = db.Column(db.String(32), nullable=False, default="queued", index=True)
    tt_publish_id   = db.Column(db.String(255), default="")
    error           = db.Column(db.Text, default="")
    created_at      = db.Column(db.DateTime, nullable=False, default=_utcnow)
    posted_at       = db.Column(db.DateTime)

    tt_account = db.relationship("TTAccount")
