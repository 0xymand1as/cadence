# TikTok Content Posting API — Resubmit V2

**App:** WYWH Automation Studio · **App ID:** 7632503230471292935 · **Ownership:** Individual
**Status as of 2026-06-01:** Production = **Not approved** (prior submission rejected). Editable via **Return to Draft** → resubmit. Free, unlimited resubmits.

---

## Why it was rejected (verbatim reviewer note)

> Update the following fields and resubmit: **App description**, **Category**
> *Note from reviewer: App will not be approved for personal or company internal use. TikTok for Developers currently does not support personal or internal company use. Not acceptable: Display posts from the TikTok account(s) you or your team manage on your website.*

**Root cause:** the app reads as a *personal / internal / agency* tool ("post my own / my team's / multiple brands' accounts"). TikTok only approves a genuine **third-party product** where *independent creators connect and post to their own accounts*.

**Truthful reframe that passes:** Cadence is a public scheduling product for *independent* music creators/labels/managers. Each user connects **their own** TikTok and posts **their own** content. Jake + friends + studio members are *users* of that product, each on their own account — NOT a roster Jake's team manages. Keep this true and it's approvable.

---

## 1. App Description (replace the rejected one)

> Cadence is a TikTok scheduling tool built for independent music artists, indie labels, and artist managers. Each creator signs up, securely connects their own TikTok account through TikTok Login Kit, uploads original videos they own the rights to, writes captions, chooses a privacy level, and schedules posts around their release calendar. At each scheduled time, Cadence publishes that creator's approved video to their own TikTok account and surfaces post status so they can track their release-week rollout. Any eligible creator can sign up and use it.

Rules followed: no "my brands," no "accounts you/your team manage," no "multi-brand." Every sentence = each creator → their own account. "Any eligible creator can sign up" signals public/third-party.

## 2. Category

Recommend **Social Media Management** (fallbacks if the dropdown differs: "Content & Publishing" / "Marketing"). **Do NOT** use Productivity / Business Tools / anything that reads internal. Confirm exact dropdown value when editing.

## 3. Submit-for-review text (reviewer-facing — directly rebuts the rejection)

> Cadence (https://cadence.biggerdreamsco.com) is a publicly available, multi-tenant SaaS scheduling product for independent music creators, artists, indie labels, and artist managers. It is NOT a personal or internal-company tool: any eligible creator can create their own account and connect their own TikTok account.
>
> Flow: a creator signs up → connects their own TikTok via Login Kit OAuth → uploads original short-form video they own → writes a caption → selects a privacy level (no default) → schedules a time. At that time, Cadence publishes the creator's own approved video to the creator's own TikTok account.
>
> Scopes requested:
> • user.info.basic — show the connected creator's display name/avatar so they can confirm which of their own accounts a post will publish to.
> • video.upload — transfer the creator's selected video to TikTok via the Content Posting API.
> • video.publish — publish the creator's scheduled video to their own account at their chosen time and selected privacy level.
>
> Each user only ever connects and posts to their own TikTok account(s). Cadence does not repost, mirror, or display content from other platforms or from accounts the operator manages. Posting volume is modest (a few posts per creator per day), within standard rate limits.

## 4. Site copy to fix (reviewer visits the site)

`tiktok_app/templates/base.html` and `index.html` currently use **agency/internal** framing. Change:
- **Title** (`base.html:7`): "Cadence — TikTok scheduling, multi-brand, music industry built" → **"Cadence — TikTok scheduling for independent music creators"**
- **Meta description** (`base.html:8`): "Multi-brand TikTok scheduling for music production companies… running release-week rollouts." → **"TikTok scheduling for independent music artists, labels, and managers. Connect your own account and plan your release-week posts."**
- Scan `index.html`, `features.html`, `pricing.html`, `about.html` for: "multi-brand," "your brands," "accounts you manage," "for your team/roster." Replace with per-creator language.

## 5. New demo video (REQUIRED) — shot list (~2–3 min, ≤50 MB, unlisted)

Record against the LIVE app in sandbox/unaudited mode (posts go SELF_ONLY — fine for the demo).

1. **Landing** — browser on `cadence.biggerdreamsco.com` (URL bar visible; domain MUST match the configured website). Scroll the landing/features so it reads as a real product.
2. **Sign up** — create a NEW creator account (neutral, not WYWH/OTJ-branded) → reads third-party.
3. **Connect TikTok** — click Connect → TikTok OAuth consent screen showing all 3 scopes (user.info.basic, video.upload, video.publish) → authorize → return to dashboard showing the connected account's display name/avatar. *(demonstrates user.info.basic)*
4. **Schedule** — upload a neutral sample video, write a caption, **select a privacy level (selector must show NO default — reviewer checks this)**, pick a time, submit. *(demonstrates video.upload)*
5. **Publish/status** — show the queued→publishing status, and if possible the resulting post on the account. *(demonstrates video.publish)*

Demo compliance (these fail demos): domain matches website URL · privacy selector has no default · creator nickname shown · all selected scopes visibly demonstrated.

## 6. Pre-submit checklist

- [ ] App description → new (§1)
- [ ] Category → fixed (§2)
- [ ] Submit-for-review text → new (§3)
- [ ] Site copy de-"multi-brand"-ed (§4)
- [ ] Redirect URI registered = `https://cadence.biggerdreamsco.com/callback` (confirm in URL properties)
- [ ] URL ownership verification = ✅ already live (`tiktok7ao…txt`)
- [ ] **Cold-start fix** — Render free tier sleeps → reviewer's first hit may time out (15s observed). Add a ~10-min keep-alive ping OR upgrade Render before submitting.
- [ ] New demo video recorded + uploaded unlisted
- [ ] Return to Draft → paste fields → resubmit
