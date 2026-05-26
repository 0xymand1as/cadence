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
    POST  /signup            create account
    GET   /login             login form
    POST  /login             authenticate
    POST  /logout            sign out

    GET   /dashboard         †  queue + accounts overview
    GET   /accounts          †  list connected TikTok accounts
    GET   /connect           †  begin TikTok OAuth
    GET   /callback             OAuth redirect handler
    GET   /schedule          †  schedule-post form
    POST  /schedule          †  enqueue a post
    POST  /cancel/<id>       †  cancel queued post
    POST  /delete-account    †  permanently delete account + data
    GET   /health               render healthcheck
"""
from __future__ import annotations

import os
import io
import secrets
import hashlib
import base64
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import bcrypt
import requests
from flask import (Flask, redirect, request, session, url_for,
                   render_template, flash, abort)
from flask_login import (LoginManager, login_user, logout_user,
                          login_required, current_user)

from models  import db, User, TTAccount, ScheduledPost
from crypto  import encrypt, decrypt
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
app.config["MAX_CONTENT_LENGTH"]             = 600 * 1024 * 1024  # 600 MB upload cap

db.init_app(app)

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


# ── Public marketing pages ────────────────────────────────────────────

@app.route("/health")
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
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw    = request.form.get("password") or ""
        if not email or "@" not in email or len(pw) < 8:
            flash("Email and 8+ char password required.")
            return render_template("signup.html"), 400
        if User.query.filter_by(email=email).first():
            flash("Account already exists. Sign in instead.")
            return render_template("signup.html"), 409
        u = User(
            email         = email,
            password_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode(),
        )
        db.session.add(u)
        db.session.commit()
        login_user(u, remember=True)
        return redirect(url_for("dashboard"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw    = request.form.get("password") or ""
        u = User.query.filter_by(email=email).first()
        if not u or not bcrypt.checkpw(pw.encode(), u.password_hash.encode()):
            flash("Invalid credentials.")
            return render_template("login.html"), 401
        login_user(u, remember=True)
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout", methods=["POST", "GET"])
def logout():
    logout_user()
    return redirect(url_for("index"))


# ── Dashboard ─────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    accts = current_user.tt_accounts
    queue = (
        ScheduledPost.query
        .filter_by(user_id=current_user.id)
        .order_by(ScheduledPost.scheduled_at.desc())
        .limit(50)
        .all()
    )
    return render_template("dashboard.html", accts=accts, queue=queue)


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

    if error:
        return render_template("error.html",
                               message=f"TikTok denied access: {error}"), 400
    if state != session.get("state"):
        return render_template("error.html",
                               message="State mismatch — please try again."), 400

    resp = requests.post(
        TIKTOK_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key":     CLIENT_KEY,
            "client_secret": CLIENT_SECRET,
            "code":           code,
            "grant_type":     "authorization_code",
            "redirect_uri":   REDIRECT_URI,
            "code_verifier":  session.pop("cv", ""),
        },
        timeout=15,
    )
    if not resp.ok:
        return render_template("error.html",
                               message=f"Token exchange failed: {resp.text[:200]}"), 400

    tok = resp.json()
    open_id       = tok.get("open_id", "")
    access_token  = tok.get("access_token", "")
    refresh_token = tok.get("refresh_token", "")
    expires_in    = int(tok.get("expires_in", 3600))

    if not (open_id and access_token):
        return render_template("error.html",
                               message=f"Bad token response: {tok}"), 400

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
    flash(f"Connected @{handle or open_id}.")
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


# ── Schedule a post ───────────────────────────────────────────────────

@app.route("/schedule", methods=["GET", "POST"])
@login_required
def schedule():
    if request.method == "POST":
        tt_id      = int(request.form.get("tt_account_id") or 0)
        caption    = (request.form.get("caption") or "").strip()
        sched_str  = (request.form.get("scheduled_at") or "").strip()
        file       = request.files.get("video")

        acct = TTAccount.query.filter_by(id=tt_id, user_id=current_user.id).first()
        if not acct:
            flash("Pick a connected TikTok account.")
            return redirect(url_for("schedule"))
        if not (file and file.filename):
            flash("Upload a video file (mp4, ≤500 MB).")
            return redirect(url_for("schedule"))

        try:
            sched_dt = datetime.fromisoformat(sched_str).astimezone(timezone.utc)
        except Exception:
            flash("Bad schedule time.")
            return redirect(url_for("schedule"))
        if sched_dt < datetime.now(timezone.utc) - timedelta(minutes=1):
            flash("Schedule time is in the past.")
            return redirect(url_for("schedule"))

        blob = file.read()
        if len(blob) == 0:
            flash("Empty file.")
            return redirect(url_for("schedule"))

        db.session.add(ScheduledPost(
            user_id        = current_user.id,
            tt_account_id  = acct.id,
            video_filename = file.filename[:255],
            video_blob     = blob,
            caption        = caption,
            scheduled_at   = sched_dt,
            status         = "queued",
        ))
        db.session.commit()
        flash(f"Scheduled for {sched_dt.strftime('%Y-%m-%d %H:%M UTC')}.")
        return redirect(url_for("dashboard"))

    return render_template("schedule.html", accts=current_user.tt_accounts)


@app.route("/cancel/<int:post_id>", methods=["POST"])
@login_required
def cancel(post_id: int):
    p = ScheduledPost.query.filter_by(id=post_id, user_id=current_user.id).first_or_404()
    if p.status != "queued":
        flash(f"Cannot cancel — already {p.status}.")
    else:
        db.session.delete(p)
        db.session.commit()
        flash("Cancelled.")
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
