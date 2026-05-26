# TikTok App Resubmission Checklist

Goal: get Content Posting API approved by framing this as a public SaaS
tool for music creators (which it is — just underutilized externally right now).

---

## Step 1 — Deploy the landing page (15 min)

1. Go to render.com → New → Web Service
2. Connect this GitHub repo (or push `tiktok_app/` to a new repo)
3. Set **Root Directory** to `tiktok_app`
4. Under **Environment Variables**, add:
   - `TIKTOK_CLIENT_KEY` — from your .env file
   - `TIKTOK_CLIENT_SECRET` — from your .env file
5. Deploy. Your public URL will be: `https://wywh-automation.onrender.com`
6. Visit it and confirm the landing page loads

---

## Step 2 — Update TikTok developer app (10 min)

Go to developers.tiktok.com → your app → Edit

**App description** (paste this exactly):
> WYWH Automation is a content scheduling and publishing tool for independent music artists, live-event brands, and entertainment creators. It enables creators to automate TikTok video uploads, manage captions and hashtags, A/B test content performance, and track engagement metrics across platforms. Creators connect their TikTok account once via OAuth and the tool handles scheduled posting from their approved content library.

**Category:** Social Media Management

**Website URL:** `https://wywh-automation.onrender.com`

**Privacy Policy URL:** `https://wywh-automation.onrender.com/privacy`

**Terms of Service URL:** `https://wywh-automation.onrender.com/terms`

---

## Step 3 — Register redirect URI

In your TikTok app settings → Login Kit → Redirect URIs:

Add: `https://wywh-automation.onrender.com/callback`

(Keep `http://localhost:8723/callback` too — needed for local setup_tiktok_auth.py)

---

## Step 4 — Record demo video (10 min)

TikTok requires a demo video showing your app in use. Record a 2-3 min screen
recording showing:
1. The landing page at wywh-automation.onrender.com
2. Clicking "Connect your TikTok" and going through the OAuth flow
3. The success screen after connecting
4. (Optional) Show the Studio app queuing a scheduled post

Upload to YouTube as unlisted and paste the link in the TikTok app submission.

---

## Step 5 — Resubmit

Submit for review. Expected review time: 5-10 business days.

When approved:
1. Change `tt_mode: inbox` → `tt_mode: direct` in brands.yaml for each brand
2. Run `python3 setup/setup_tiktok_auth.py --brand wywh` (re-auth with new scopes)
3. Run `python3 setup/setup_tiktok_auth.py --brand otj`
4. Relaunch the engine

---

## While waiting (bridge mode is already live)

The inbox bridge is running now. The engine uploads TikTok videos to your draft
queue automatically. When a draft is ready:
- Mac notification fires: "TikTok Draft Ready — open TikTok → inbox → publish"
- Caption is shown in the notification (copy-paste it in the app)
- Draft log: `~/.wywh/<brand>/tt_pending_drafts.jsonl`

First, run auth for each brand to create the token files:
```
cd /Users/jakedouglas/Desktop/WYWHAutomation
python3 setup/setup_tiktok_auth.py --brand wywh
python3 setup/setup_tiktok_auth.py --brand otj
```
Then restart the engine: relaunch WYWH Studio.app
