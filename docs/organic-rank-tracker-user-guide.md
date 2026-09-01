# Organic Rank Tracker — User Guide

A step-by-step tutorial for the Organic Rank Tracker inside AR Tools. No code, no terminal —
everything here happens in the dashboard.

> **What this tool is.** It tracks a client's **Google organic (blue-link) search** positions,
> clicks, and impressions — sourced from Google Search Console (GSC) and/or a DataForSEO live
> SERP check. It does **not** track Google Maps / local-pack rankings (that's the separate **Maps
> Ranker** module) and it isn't the place to research new keywords or mass-generate content (see
> the Keyword Research and Content tool guides). Connecting Search Console is covered in the
> onboarding tutorial (`docs/new-hire-onboarding-tutorial-v1_0.md` §5) — this guide is about using
> the tracker day to day once it's set up.

---

## Before you start

- **The tool works with or without Search Console connected** — but it's a materially different
  tool either way. A colored pill next to the page title reads **"Search Console"** (green) when a
  verified GSC property exists, or **"DataForSEO"** (blue) when it doesn't.
  - **Without GSC:** the Overview, Pages, and Brand search tabs are hidden entirely, and you land
    on Keywords by default. The Keywords table loses its 7d/30d/60d/90d position, Clicks,
    Impressions, and CTR columns, and each keyword's rank comes from a weekly DataForSEO live
    check instead of a real Search Console average.
  - **With GSC:** all of that unlocks, plus real click/impression numbers throughout.
- **No role gate.** Any logged-in team member can add/remove/refresh keywords — this isn't
  staff/admin-restricted.
- **Not freeze-gated.** Unlike content-generation tools, the tracker keeps working during a client
  freeze — a freeze pauses content/link *output*, not tracking/observation.
- **GSC Research and Keyword Research are separate tools**, not tabs inside this tracker — they
  each have their own workspace card.

---

## The big picture

1. Track the keywords that matter (**Keywords** tab).
2. If GSC is connected, start on **Overview** for a plain-English read of how the campaign is
   doing and what needs attention.
3. Drill into **Rankability** for realistic quick wins, **SERP Trends** for what's shifting in the
   competitive landscape, and per-keyword **SERP Snapshots** / **Organic Rank Analysis** reports
   for the deep dives.
4. Watch **Alerts** for drops, confirm deindexing when it's flagged.
5. Generate or schedule client-facing **Reports**.
6. Everything here also feeds the client's **Action Plan** — a drop or a quick win surfaces there
   automatically, deep-linked back to this tool.

---

## Step 1 — Track keywords

Open the client → **Organic Rank Tracker** → **Keywords** tab (the default tab without GSC; one
of several tabs with GSC connected).

- **Track keywords** button opens a textarea — one keyword per line (or comma-separated) — then
  **Add keywords**.
- **Import CSV** — upload a `.csv` and it reads the first column as keywords.
- **Refresh live ranks** — enqueues a background DataForSEO pull for keywords GSC doesn't cover;
  runs in the background and survives navigating away.
- **Export CSV** — the full table, including status, source, ranks at every horizon, CPC/volume,
  GSC averages, canonical URL, and index status.
- After adding your first keywords, a banner offers to **Run rankability** (captures a SERP
  snapshot per new keyword) right away, or **Not now**.

---

## Step 2 — Read the Overview (GSC-connected clients only)

- A plain-English **headline + narrative** summarizing the tracker's current state.
- KPI cards: Keywords, At risk, plus (with GSC) Avg position / Clicks / Impressions over 30 days,
  or (DataForSEO-only) Ranking count / Avg live rank.
- Status-rollup chips: Climbing / Stable / Volatile / Dropping / At risk / Not in top 100 / No
  data yet.
- **Striking distance** — untracked GSC queries already ranking positions 8–20 that you're not yet
  tracking, each with a one-click **Track** button.
- **Needs attention** — the top 8 keywords sorted by how urgently they need a look, each with a
  sparkline and status chip.

---

## Step 3 — Work a keyword row (Keywords tab)

Filter chips at the top of the table (**All**, then each status present) narrow the list. Click
any row to expand it: a position chart, point-in-time ranks (campaign start / 90d / 30d / 7d /
now), and — if the keyword ranks on more than one page — a **landing-page breakdown** with a
**Pin** button to lock the canonical URL.

Per-row icon buttons:

- **Camera** — capture a **Competitive SERP Snapshot** (AI Overview text + cited sources, intent
  signals, the full top-10 organic table with RD/UR/DR, per-domain authority, and how many of the
  top results are actually written for this keyword).
- **Bar chart** — generate the per-keyword **Organic Rank Analysis report** (needs a snapshot
  first — if there isn't one, you'll be told to capture one). Once generated: at-a-glance stats
  (Position, Projected 90d, Winnability, Priority), a written narrative, and a ranked **work
  order** of recommended next steps (each pointing at the right tool — build links, create a page,
  reoptimize, or consolidate via GSC Research).
- **Gauge** — the domain **Authority report** (DR/UR/RD).
- **Trash** — stop tracking (delete) the keyword.

A keyword flagged as possible deindexing shows a colored banner (confirmed not-indexed / confirmed
still indexed — just a rank drop / uncertain) with a **Check index** button that runs a live
Google URL Inspection.

---

## Step 4 — Rankability and SERP Trends

**Rankability** tab — a 0–100 score per keyword for how realistically winnable it is (from
incumbent backlink authority, how competitive the SERP is, the client's own authority, and SERP
crowding), banded Easy/Moderate/Hard/Very hard. Sort by **Quick wins** (default), **Rankability**,
or **Potential value**. A keyword with no SERP snapshot yet shows in a separate "Not scored yet"
section — capture one from the Keywords tab's camera button (or wait for the weekly auto-capture).

**SERP Trends** tab — three panels: signal/enhancement prevalence over time (a 12-week trend per
SERP feature), a "what changed since last capture" digest, and a per-keyword timeline you can
scrub through.

---

## Step 5 — Alerts

Four triggers, explained right on the tab: a 6+ spot weekly drop from a top-15 position, falling
off page 1, a 6+ spot 30-day drop from ~top 20, or a gradual multi-week slide — plus deindexing.
Each row shows the type, source (Search Console or DataForSEO), and whether it's since recovered.
**Mark all read** clears the unread badge; individual rows can be marked **Read** or dismissed.
Alerts clear automatically once the keyword recovers.

---

## Step 6 — Reports (GSC-connected clients only)

- **Schedule**: As needed / Weekly (pick a day) / Monthly (pick a day of month) / Every N days,
  plus an optional **"Also deliver each report as a Google Doc"** checkbox (needs a Drive folder
  set on the client).
- **Generate now** for an on-demand report; each past report is a row with a link, a timestamp,
  and a **To Doc** button (or a live Doc link once published).

---

## Step 7 — Settings

Recap (full setup is in the onboarding tutorial): **Tracking location** for DataForSEO live ranks
(auto-set from GBP, overridable), the **rank-data refresh schedule**, the service-account email to
grant GSC access, and each connected **Property**'s status with **Sync now** / **Backfill
history**.

---

## Quick reference

| I want to… | Where |
|---|---|
| Start tracking a new keyword | Keywords tab → **Track keywords** (or **Import CSV**) |
| See what needs attention right now | Overview → "Needs attention," or the status filter chips on Keywords |
| Find out why a keyword dropped | Expand its row → camera icon for a SERP Snapshot, or the bar-chart icon for an Organic Rank Analysis report |
| Confirm actual deindexing | Expand an "at risk" keyword → **Check index** |
| Find untracked page-2 opportunities | Overview → "Striking distance" → **Track** |
| Find realistic quick wins | Rankability tab → sort by **Quick wins** |
| Send/print a rankings report | Reports tab → **Generate now**, or set a schedule |
| Diagnose cannibalization or hidden page-2 wins | The separate **GSC Research** workspace card |
| Connect GSC / change tracking location | Settings tab |

---

## FAQ

**Why don't I see an Overview / Pages / Brand search tab for this client?**
They only appear once a Search Console property shows `Connected`. Without one, the tool runs in
DataForSEO-only mode and defaults to Keywords.

**A Rankability "Quick win" pointed at Local SEO instead of staying in this tracker.**
That's intentional — Rankability only diagnoses; actually fixing a page is a Local SEO Writer
action, so its Action Plan link goes there.

**A SERP snapshot / rank-analysis report says "still processing" for a while.**
These run real background jobs (a snapshot alone is ~24 DataForSEO calls) — the page gives up
polling after a few minutes but the job keeps running; check back later.

**A keyword we already rank #1 for isn't showing as a Rankability quick win.**
Deliberate — a keyword already in the top 3 is excluded from quick wins since there's no upside
left to capture.

**Where do I go to research brand-new keywords, not track existing ones?**
The separate **Keyword Research** workspace card — this tracker only manages keywords you've
already decided to track.
