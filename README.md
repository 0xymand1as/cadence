# Cadence

TikTok scheduling purpose-built for music industry multi-brand rollouts.

A [Bigger Dreams](https://biggerdreamsco.com) product.

## What it does

Cadence coordinates TikTok posts across multiple connected accounts during music release windows. Built for production companies, indie labels, and artists running staggered rollouts across show accounts, artist accounts, and label accounts.

- Multi-brand calendar with same-hour collision detection
- Release-cycle scheduling (7/14/30-day rollouts)
- Per-brand caption + hashtag templates
- Direct publish via TikTok's official Content Posting API
- Performance analytics pulled back automatically

## Live

- **Site:** https://cadence.biggerdreamsco.com
- **Privacy:** https://cadence.biggerdreamsco.com/privacy
- **Terms:** https://cadence.biggerdreamsco.com/terms

## Stack

- Flask (Python 3.11+) — backend + Jinja templates
- TikTok Content Posting API (OAuth + PKCE)
- Render.com — hosting
- Bigger Dreams design system v3 — UI

## Local dev

```bash
pip install -r requirements.txt
export TIKTOK_CLIENT_KEY=your_key
export TIKTOK_CLIENT_SECRET=your_secret
export TIKTOK_REDIRECT_URI=http://localhost:5050/callback
python3 app.py
```

App runs at http://localhost:5050.

## Deploy

Push to GitHub → Render auto-deploys via `render.yaml`. Env vars set in Render dashboard.

## Contact

jakedouglas@biggerdreamsco.com
