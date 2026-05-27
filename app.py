"""
Cadence — multi-tenant TikTok scheduling SaaS.

A Bigger Dreams product. Music-industry multi-brand rollout coordinator.

Routes (auth-gated marked w/ †):
    GET   /                  landing
    GET   /features          features
    GET   /pricing           pricing
    GET   /about             about
    GET   /privacy           privacy policy (TT review URL)
    GET   /terms             terms of service (TT review URL)

    GET   /signup            signup form
    POST  /signup            create account (rate-limited)
    GET   /login             login form
    POST  /login             authenticate (rate-limited)
    POST  /logout            sign out

    GET   /dashboard         †  KPIs + queue
    GET   /accounts          †  list + disconnect connected TikTok accounts
    GET   /connect           †  begin TikTok OAuth
    GET   /callback             OAuth redirect handler
    GET   /schedule          †  schedule-post form
    POST  /schedule          †  enqueue a post
    POST  /cancel/<id>       †  cancel queued post
    POST  /disconnect/<id>   †  remove a connected TT account
    POST  /delete-account    †  permanently delete account + data
    GET   /health               render healthcheck
"""
from __future__ import annotations

import os
import secrets
import hashlib
import base64
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import bcrypt
import requests
from flask import (Flask, redirect, request, session, url_for,
                   render_template, flash)
from flask_login import (LoginManager, login_user, logout_user,
                          login_required, current_user)
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from models   import db, User, TTAccount, ScheduledPost
from crypto   import encrypt, decrypt
from scheduler import start_scheduler


# ── Config ────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", secrets.token_hex(32))

# SQLite at /var/data/cadence.db on Render (persistent free-disk),
# fallback to local file for dev.
DEFAULT_DB = "sqlite:////var/data/cadence.db" if os.path.isdir("/var/data") \
             else "sqlite:///cadence.db"
app.config["SQLALCHEMY_DATABASE_URI"]        = os.environ.get("DATABASE_URL", DEFAULT_DB)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"]             = 320 * 1024 * 1024  # 320 MB — slightly over TT's 287 MB cap for headroom
app.config["WTF_CSRF_TIME_LIMIT"]            = None              # session-scoped CSRF
app.config["SESSION_COOKIE_HTTPONLY"]        = True
app.config["SESSION_COOKIE_SAMESITE"]        = "Lax"
# Secure cookie when behind HTTPS (Render proxies it).
app.config["SESSION_COOKIE_SECURE"]          = bool(os.environ.get("RENDER"))
app.config["PERMANENT_SESSION_LIFETIME"]     = timedelta(days=30)

db.init_app(app)

# CSRF — applies to every POST except those decorated w/ @csrf.exempt
csrf = CSRFProtect(app)

# gzip / br responses
Compress(app)

# Per-IP rate limit on auth endpoints
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri="memory://",
    default_limits=[],
)


@app.context_processor
def _inject_csrf():
    """Expose csrf_token() to every template."""
    return {"csrf_token": generate_csrf}


login_mgr = LoginManager(app)
login_mgr.login_view = "login"


@login_mgr.user_loader
def _load_user(uid: str):
    return User.query.get(int(uid))


CLIENT_KEY    = os.environ.get("TIKTOK_CLIENT_KEY",    "")
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
REDIRECT_URI  = os.environ.get(
    "TIKTOK_REDIRECT_URI",
    "https://cadence.biggerdreamsco.com/callback",
)
TIKTOK_AUTH_URL  = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_USERINFO  = "https://open.tiktokapis.com/v2/user/info/"
SCOPE            = "user.info.basic,video.upload,video.publish"

# TikTok content-posting hard limits — surface to UI + enforce server-side
TT_MAX_VIDEO_BYTES = 287 * 1024 * 1024   # 287 MB per TT docs
TT_MAX_CAPTION     = 2200
TT_MIN_SECS        = 3
TT_MAX_SECS        = 60


# ── Public marketing pages ────────────────────────────────────────────

@app.route("/health")
@csrf.exempt
def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}, 200


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/features")
def features():
    return render_template("features.html")


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


# ── Signup / Login / Logout ───────────────────────────────────────────

@app.route("/signup", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw    = request.form.get("password") or ""
        if not email or "@" not in email or len(pw) < 8:
            flash("Email and 8+ character password required.", "error")
            return render_template("signup.html"), 400
        if User.query.filter_by(email=email).first():
            flash("Account already exists — sign in instead.", "error")
            return render_template("signup.html"), 409
        u = User(
            email         = email,
            password_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode(),
            last_login_at = datetime.now(timezone.utc),
        )
        db.session.add(u)
        db.session.commit()
        login_user(u, remember=True)
        flash("Welcome to Cadence. Connect your first TikTok to get started.", "success")
        return redirect(url_for("dashboard"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("20 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw    = request.form.get("password") or ""
        u = User.query.filter_by(email=email).first()
        if not u or not bcrypt.checkpw(pw.encode(), u.password_hash.encode()):
            flash("Invalid credentials.", "error")
            return render_template("login.html"), 401
        u.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        login_user(u, remember=True)
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("index"))


# ── Dashboard ─────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    accts = current_user.tt_accounts
    now   = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    week_end   = now + timedelta(days=7)

    queue = (
        ScheduledPost.query
        .filter_by(user_id=current_user.id)
        .order_by(ScheduledPost.scheduled_at.desc())
        .limit(50)
        .all()
    )

    kpi_scheduled = (
        ScheduledPost.query
        .filter_by(user_id=current_user.id, status="queued")
        .filter(ScheduledPost.scheduled_at >= now)
        .filter(ScheduledPost.scheduled_at <= week_end)
        .count()
    )
    kpi_posted = (
        ScheduledPost.query
        .filter_by(user_id=current_user.id, status="posted")
        .filter(ScheduledPost.posted_at != None)  # noqa: E711
        .filter(ScheduledPost.posted_at >= week_start)
        .count()
    )
    kpi_accounts = len(accts)

    return render_template(
        "dashboard.html",
        accts        = accts,
        queue        = queue,
        kpi_scheduled = kpi_scheduled,
        kpi_posted    = kpi_posted,
        kpi_accounts  = kpi_accounts,
    )


@app.route("/accounts")
@login_required
def accounts():
    return render_template("accounts.html", accts=current_user.tt_accounts)


# ── TikTok OAuth (per-user) ───────────────────────────────────────────

@app.route("/connect")
@login_required
def connect():
    if not CLIENT_KEY:
        return render_template("error.html",
                               message="TikTok client key not configured."), 500

    code_verifier  = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    session["cv"]    = code_verifier
    session["state"] = state

    params = {
        "client_key":             CLIENT_KEY,
        "response_type":          "code",
        "scope":                  SCOPE,
        "redirect_uri":           REDIRECT_URI,
        "state":                  state,
        "code_challenge":         code_challenge,
        "code_challenge_method":  "S256",
    }
    return redirect(f"{TIKTOK_AUTH_URL}?{urlencode(params)}")


@app.route("/callback")
@login_required
def callback():
    code  = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    error_desc = request.args.get("error_description", "")

    if error:
        # User denied / cancelled. Friendly back-to-accounts, no scary error page.
        flash(f"TikTok connection cancelled ({error}). You can try again any time.", "error")
        return redirect(url_for("accounts"))
    if not code:
        flash("TikTok didn't return an authorization code. Please try again.", "error")
        return redirect(url_for("accounts"))
    if state != session.get("state"):
        flash("Security check failed (state mismatch). Please try connecting again.", "error")
        return redirect(url_for("accounts"))

    resp = requests.post(
        TIKTOK_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key":     CLIENT_KEY,
            "client_secret":  CLIENT_SECRET,
            "code":           code,
            "grant_type":     "authorization_code",
            "redirect_uri":   REDIRECT_URI,
            "code_verifier":  session.pop("cv", ""),
        },
        timeout=15,
    )
    if not resp.ok:
        logging.error(f"TT token exchange failed: {resp.status_code} {resp.text[:300]}")
        return render_template("error.html",
                               message="TikTok wouldn't issue a token. Please try connecting again."), 400

    tok = resp.json()
    open_id       = tok.get("open_id", "")
    access_token  = tok.get("access_token", "")
    refresh_token = tok.get("refresh_token", "")
    expires_in    = int(tok.get("expires_in", 3600))

    if not (open_id and access_token):
        logging.error(f"TT token response missing fields: {tok}")
        return render_template("error.html",
                               message="TikTok returned an incomplete token. Please try again."), 400

    handle, avatar = _fetch_handle(access_token)

    existing = TTAccount.query.filter_by(
        user_id=current_user.id, tt_open_id=open_id).first()
    if existing:
        existing.access_token_e  = encrypt(access_token)
        existing.refresh_token_e = encrypt(refresh_token) if refresh_token else existing.refresh_token_e
        existing.expires_at      = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        existing.handle          = handle or existing.handle
        existing.avatar_url      = avatar or existing.avatar_url
    else:
        db.session.add(TTAccount(
            user_id         = current_user.id,
            tt_open_id      = open_id,
            handle          = handle,
            avatar_url      = avatar,
            access_token_e  = encrypt(access_token),
            refresh_token_e = encrypt(refresh_token or ""),
            expires_at      = datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        ))
    db.session.commit()
    flash(f"Connected @{handle or open_id}.", "success")
    return redirect(url_for("dashboard"))


def _fetch_handle(token: str):
    try:
        r = requests.get(
            TIKTOK_USERINFO,
            params={"fields": "open_id,union_id,avatar_url,display_name,username"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.ok:
            d = r.json().get("data", {}).get("user", {})
            return d.get("username") or d.get("display_name") or "", d.get("avatar_url") or ""
    except Exception:
        pass
    return "", ""


@app.route("/disconnect/<int:acct_id>", methods=["POST"])
@login_required
def disconnect(acct_id: int):
    acct = TTAccount.query.filter_by(id=acct_id, user_id=current_user.id).first_or_404()
    # Don't delete queued posts pointed at this acct — cancel them first.
    cancelled = (
        ScheduledPost.query
        .filter_by(tt_account_id=acct.id, user_id=current_user.id, status="queued")
        .update({"status": "cancelled", "error": "TikTok account disconnected"})
    )
    handle = acct.handle or acct.tt_open_id[:8]
    db.session.delete(acct)
    db.session.commit()
    if cancelled:
        flash(f"Disconnected @{handle}. Cancelled {cancelled} queued post(s).", "info")
    else:
        flash(f"Disconnected @{handle}.", "info")
    return redirect(url_for("accounts"))


# ── Schedule a post ───────────────────────────────────────────────────

@app.route("/schedule", methods=["GET", "POST"])
@login_required
def schedule():
    if request.method == "POST":
        tt_id      = int(request.form.get("tt_account_id") or 0)
        caption    = (request.form.get("caption") or "").strip()[:TT_MAX_CAPTION]
        sched_str  = (request.form.get("scheduled_at") or "").strip()
        file       = request.files.get("video")

        acct = TTAccount.query.filter_by(id=tt_id, user_id=current_user.id).first()
        if not acct:
            flash("Pick a connected TikTok account.", "error")
            return redirect(url_for("schedule"))
        if not (file and file.filename):
            flash("Upload a video file.", "error")
            return redirect(url_for("schedule"))

        # Filename + mimetype sanity. TT accepts MP4 (h264) + MOV.
        fn = (file.filename or "").lower()
        if not (fn.endswith(".mp4") or fn.endswith(".mov")):
            flash("Video must be .mp4 or .mov.", "error")
            return redirect(url_for("schedule"))

        try:
            sched_dt = datetime.fromisoformat(sched_str).astimezone(timezone.utc)
        except Exception:
            flash("Pick a valid date and time.", "error")
            return redirect(url_for("schedule"))
        if sched_dt < datetime.now(timezone.utc) - timedelta(minutes=1):
            flash("Scheduled time is in the past.", "error")
            return redirect(url_for("schedule"))
        if sched_dt > datetime.now(timezone.utc) + timedelta(days=10):
            flash("Schedule up to 10 days ahead.", "error")
            return redirect(url_for("schedule"))

        blob = file.read()
        if len(blob) == 0:
            flash("Uploaded file is empty.", "error")
            return redirect(url_for("schedule"))
        if len(blob) > TT_MAX_VIDEO_BYTES:
            flash(f"Video is {len(blob)//(1024*1024)} MB — TikTok caps uploads at 287 MB.", "error")
            return redirect(url_for("schedule"))

        db.session.add(ScheduledPost(
            user_id        = current_user.id,
            tt_account_id  = acct.id,
            video_filename = (file.filename or "video.mp4")[:255],
            video_blob     = blob,
            video_size     = len(blob),
            caption        = caption,
            scheduled_at   = sched_dt,
            status         = "queued",
        ))
        db.session.commit()
        flash(
            f"Scheduled for {sched_dt.strftime('%Y-%m-%d %H:%M UTC')} "
            f"to @{acct.handle or acct.tt_open_id[:8]}.",
            "success",
        )
        return redirect(url_for("dashboard"))

    return render_template(
        "schedule.html",
        accts             = current_user.tt_accounts,
        tt_max_video_mb   = TT_MAX_VIDEO_BYTES // (1024 * 1024),
        tt_max_caption    = TT_MAX_CAPTION,
        tt_min_secs       = TT_MIN_SECS,
        tt_max_secs       = TT_MAX_SECS,
    )


@app.route("/cancel/<int:post_id>", methods=["POST"])
@login_required
def cancel(post_id: int):
    p = ScheduledPost.query.filter_by(id=post_id, user_id=current_user.id).first_or_404()
    if p.status != "queued":
        flash(f"Can't cancel — post is already {p.status}.", "error")
    else:
        # Free the blob immediately + mark cancelled (audit trail).
        p.status     = "cancelled"
        p.video_blob = b""
        db.session.commit()
        flash("Post cancelled.", "info")
    return redirect(url_for("dashboard"))


# ── Delete account (privacy compliance) ───────────────────────────────

@app.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    uid = current_user.id
    User.query.filter_by(id=uid).delete()
    db.session.commit()
    logout_user()
    return render_template("deleted.html")


# ── Error handlers ────────────────────────────────────────────────────

@app.errorhandler(413)
def _too_large(e):
    cap_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return render_template("error.html",
                           message=f"That file is bigger than our {cap_mb} MB upload limit."), 413


@app.errorhandler(404)
def _not_found(e):
    return render_template("error.html",
                           message="Page not found."), 404


# ── Init DB + scheduler on boot ───────────────────────────────────────

def _initialize(app):
    with app.app_context():
        # /var/data is the persistent Render free-disk; only create if writable
        try:
            if os.path.isdir("/var") and os.access("/var", os.W_OK):
                os.makedirs("/var/data", exist_ok=True)
        except PermissionError:
            pass
        db.create_all()


_initialize(app)

# Only start scheduler in real server process (not in `flask shell` etc.)
if os.environ.get("CADENCE_RUN_SCHEDULER", "1") == "1":
    start_scheduler(app)


if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5050)))
