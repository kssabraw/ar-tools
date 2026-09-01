# GBP Posts — User Guide

A step-by-step tutorial for the GBP Posts tool inside AR Tools. No code, no terminal — everything
here happens in the dashboard.

> **What this tool is.** It composes and publishes real **Google Business Profile posts**
> (Updates, Offers, Events, Products) to a client's live Google listing, via Google's own API.
> "Publish now" and auto-publish both go **live on the public listing** — this is not a draft
> sandbox. Connecting the agency's Google account and registering a client's specific listing is
> covered in the onboarding tutorial (`docs/new-hire-onboarding-tutorial-v1_0.md` §4) — this guide
> covers composing, scheduling, and managing posts day to day.

---

## Before you start

- **A connection bar at the top tells you the state**: green ("Connected to Google Business
  Profile as {email}") means you're set; blue means someone staff+ needs to click **Connect
  Google Business Profile**; grey means an admin hasn't configured the OAuth app yet.
- **A verified location is required to publish** — Compose shows a warning if the client's
  location doesn't show `ok` yet; drafting still works either way.
- **Freeze pauses publishing, not drafting.** A frozen client blocks `Publish now` and scheduled
  auto-publish, but drafting (manual or AI) and syncing keep working.

---

## The big picture

```
Compose · Posts · Schedule · Trash
```

1. **Compose** a post by hand or with AI.
2. Track everything in **Posts** — drafts, scheduled, and live.
3. Set up a recurring **Schedule** so posts go out on their own.
4. Recover anything you deleted from **Trash**.

---

## Step 1 — Compose

Pick a type: **Update**, **Offer**, **Event**, or **Product** (Product publishes as a normal
Update — Google has no real product-post API, this is just framing). Offer/Event add their own
fields (title, start/end date, and for Offers, a coupon code/redeem URL/terms).

- **Draft with AI** — an optional topic/angle and a source page URL, then generates copy grounded
  in the client's brand voice + ICP, respecting a hard rule set (under 1500 chars, never invents
  prices/dates/offers, never puts a phone number in the body, no raw URLs).
- **"Create posts from a page URL"** — paste a URL and a count (1–99) to draft that many distinct
  posts from one page, each nudged with a different angle so they don't read like paraphrases of
  each other.
- **Image field** — Upload, Generate with AI, From URL, or **Reuse existing** (pulls from the
  client's own prior blog / Local SEO featured images).
- A CTA dropdown (No button / Learn more / Book / Order online / Shop / Sign up / Call) with a URL
  field.
- Bottom bar: **Save draft**, **Publish now**, or pick a datetime and **Schedule**.

---

## Step 2 — Posts

Filter chips: **All / Drafts / Scheduled / Live**, each with a live count. **Sync from Google**
pulls in anything created directly in Google (or reconciles a rejected/live status). Each card
shows a status badge — **Draft** (grey) / **Scheduled** (purple, with the time) / **Publishing…**
(amber) / **Live** (green, with a **View on Google** link) / **Rejected**/**Failed** (red) /
**Deleted**. Live posts get **Remove from Google**; drafts get Edit, image swap, **Regenerate**
(AI re-draft), and a per-row schedule picker; everything gets **Trash**.

---

## Step 3 — Publish

- **Manual**: **Publish now** on Compose or a Posts row — goes live right away.
- **Scheduled**: pick a future time in Compose/a draft row, or set up the recurring Schedule
  (below) with auto-publish on.
- The status badge is the tell for which kind a post is — Scheduled shows the future time; Live
  shows the "View on Google" link once it's actually posted.

---

## Step 4 — Recurring Schedule

Cadence: **Off / Weekly / Every 2 weeks / Monthly**, plus an hour of day, post type, and "Theme /
rotation notes" to guide the AI draft. **Auto-publish** is a separate checkbox — off by default,
so scheduled posts land as drafts for review; turning it on shows an explicit warning: **"⚠ Posts
will publish live with no human review."**

---

## Step 5 — Trash

Lists deleted posts with **Restore** or permanent delete, plus **Empty trash**. A post still live
on Google is deliberately kept out of a bulk empty — "N kept because they're still live on
Google" — remove it from Google first if you actually want it gone.

---

## Quick reference

| I want to… | Where |
|---|---|
| Write a post by hand | Compose → pick a type → fill it in |
| Draft one with AI | Compose → **Draft with AI** |
| Bulk-draft from a page | Compose → **"Create posts from a page URL"** |
| Reuse an existing image | Compose → Image field → **Reuse existing** |
| Publish immediately | **Publish now** (Compose or a Posts row) |
| Schedule a one-off post | Pick a datetime → **Schedule** |
| Set up recurring auto-drafting | Schedule tab |
| Turn on hands-off publishing (risky) | Schedule tab → **Auto-publish** checkbox |
| Pull in posts made directly in Google | Posts tab → **Sync from Google** |
| Recover a deleted post | Trash tab → **Restore** |

---

## FAQ

**My scheduled auto-publish post didn't go out.**
Check whether the client is frozen — the scheduler skips or holds due posts on a frozen client
until the freeze lifts.

**The AI keeps writing generic copy that ignores our brand voice.**
It only pulls brand voice/ICP from the client's saved settings — if those aren't filled in, there's
nothing to steer it with. Set them on the client's Brand Voice/ICP pages.

**I emptied Trash but a post is still on Google.**
Deliberate — Empty Trash skips anything still live on Google. Use **Remove from Google** first.

**My Offer/Event post won't save.**
Both require a title and a start date — check those are filled in.

**My uploaded image got rejected.**
It needs to be JPG or PNG, at least 250×250px, and between 10KB and 25MB.
