"""
Cadence — public-facing SaaS landing + TikTok OAuth handler.

Purpose: satisfies TikTok's requirement that apps be public-facing SaaS
products (not internal tools). Deploys to Render.com free tier.

Routes:
    GET  /            — landing page
    GET  /features    — features deep-dive
    GET  /pricing     — pricing tiers
    GET  /about       — about / BD parent
    GET  /privacy     — privacy policy (TT review)
    GET  /terms       — terms of service (TT review)
    GET  /signup      — signup form (stub, visual)
    POST /signup      — signup handler (stub)
    GET  /login       — login form (stub)
    POST /login       — login handler (stub)
    GET  /dashboard   — dashboard preview (visual)
    GET  /connect     — starts TikTok OAuth flow
    GET  /callback    — OAuth redirect handler
    GET  /success     — post-auth success page
    GET  /health      — Render healthcheck
"""
from __future__ import annotations

import os
import secrets
import hashlib
import base64
from datetime import datetime
from urllib.parse import urlencode

import requests
from flask import Flask, redirect, request, session, url_for, render_template

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", secrets.token_hex(32))

CLIENT_KEY    = os.environ.get("TIKTOK_CLIENT_KEY", "")
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
REDIRECT_URI  = os.environ.get(
    "TIKTOK_REDIRECT_URI",
    "https://cadence.biggerdreamsco.com/callback",
)

TIKTOK_AUTH_URL  = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPE            = "user.info.basic,video.upload,video.publish"


# ── Public marketing pages ───────────────────────────────────────────

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


# ── Signup / login (visual stubs for review) ─────────────────────────

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        # Stub — full multi-tenant auth lands in Phase 3.
        # For TT-review demo: accept signup, redirect to dashboard.
        session["user_email"] = request.form.get("email", "")
        return redirect(url_for("dashboard"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        session["user_email"] = request.form.get("email", "")
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


# ── TikTok OAuth flow ────────────────────────────────────────────────

@app.route("/connect")
def connect():
    if not CLIENT_KEY:
        return render_template("error.html", message="TikTok client key not configured. Set TIKTOK_CLIENT_KEY in environment."), 500

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
def callback():
    code  = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return render_template("error.html", message=f"TikTok auth denied: {error}"), 400
    if state != session.get("state"):
        return render_template("error.html", message="State mismatch — please try again."), 400

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
        return render_template("error.html", message=f"Token exchange failed: {resp.text[:200]}"), 400

    token = resp.json()
    if "access_token" not in token:
        return render_template("error.html", message=f"No access_token in response: {token}"), 400

    # Phase 3 will persist this per user. For review demo we just show success.
    session["connected_open_id"] = token.get("open_id", "")
    return redirect(url_for("success"))


@app.route("/success")
def success():
    return render_template("success.html", open_id=session.get("connected_open_id", ""))


if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5050)))
