# Maps Geo-Grid (Local Dominator) — User Guide

A step-by-step tutorial for the Maps Ranker inside AR Tools. No code, no terminal — everything
here happens in the dashboard.

> **What this tool is.** It tracks a client's **Google Maps / local-pack** rank across a grid of
> simulated searches around the business — never the organic (blue-link) SERP, which is the
> separate **Organic Rank Tracker**. Initial setup (Place ID, radius, surface, schedule) is
> covered in the onboarding tutorial (`docs/new-hire-onboarding-tutorial-v1_0.md` §9) — this guide
> is about running scans, reading results, and the reports day to day.

---

## Before you start

- **Setup must be complete before any scan can run**: a Place ID and center lat/lng, at minimum.
  The Setup tab shows an explicit warning banner if it's missing.
- **Weekly scanning with zero active keywords silently skips that client.** The Setup tab warns
  when this is the case — check it if a client's heatmap looks stale.
- **A geo-grid is billed per keyword × pin** — scanning a subset of keywords (One-offs, or the
  keyword-scope picker) is the cheap way to spot-check without re-running the whole grid.

---

## The big picture

```
Heatmap · What changed · Setup · History · One-offs
```

1. **Heatmap** shows the latest completed scan (any trigger).
2. **One-offs** are manual spot-checks — excluded from trends, alerts, and client reports.
3. **What changed** compares two scans and surfaces declines as alerts.
4. **Setup** holds the grid/keyword/schedule configuration.
5. **History** is the client's real record — **scheduled scans only** — and everything reporting-
   facing (trends, client reports, alerts) is built from it.

---

## Step 1 — Run a scan

**Run scan now** (Heatmap or One-offs tab) — button label shows the count when you've picked a
subset (**"Run scan (N keywords)"**). A **keyword-scope picker** lets you scan all keywords or
just some, worth using to keep cost down when you just want to re-check one term.

While a scan runs, a **Stop scan** button appears (drops any queued scan and halts the in-flight
one); per-row **Stop**/**Cancel** icons exist on History/One-offs rows too. A **Weekly: On/Off**
toggle on the Heatmap tab flips scheduling without going into Setup.

---

## Step 2 — Read the Heatmap

Once a scan completes: a header line (scan time, radius, grid size, surface), and per keyword —

- **At a glance**: Average rank, Top-3 coverage, Top-10 coverage, Found (pins where the business
  showed up at all), Strongest/Weakest directions, Top competitor.
- The **geo-grid map** itself, plus **"Open interactive map"** and **"Saved map image"** links, and
  an expandable **"Show full grid"** numeric table.
- A **legend** at the bottom mapping rank bands to colors (1–3 / 4–7 / 8–10 / 11–15 / 16–20 / Not
  ranked).

A **one-off scan** carries an indigo **"One-off · not in reporting"** pill so it's never mistaken
for the client's scheduled record.

---

## Step 3 — One-offs (spot checks)

A separate tab for manual, ad-hoc runs — explicitly excluded from trends, client reports, and
geo-grid alerts, and they don't auto-generate a Local Rank Analysis doc (use **Generate report**
on the row if you want one anyway). Use the keyword-scope picker to keep the cost down.

---

## Step 4 — What changed (scan-over-scan)

Compares two scans: **Performance over time** (7/30/90-day + since-start deltas, overall or
per-keyword), **Coverage by area, over time** (per-octant Top-3% trend), **Alerts** (declines
between scans, with Mark all read / Read / Dismiss), and a **Week-over-week** picker (any past
scan vs. Latest). If the compared scans used different grid radii, a banner tells you the
comparison was normalized to the shared area — this is deliberate, not a bug (see the FAQ).

---

## Step 5 — History (the reporting record)

Lists **scheduled scans only**, plus the trend chart, Share of Local Voice, local relevance
scorecard, competitor momentum/intelligence, review analytics, backlink authority, content vs.
competitors, and GBP profile audit. Everything client-facing is built from this list.

**Run management, both History and One-offs**: a **trash icon** per row deletes that scan (blocked
while a scan is in-flight); **Clear all** wipes a whole list — scoped separately, so clearing
History never touches One-offs and vice versa.

---

## Step 6 — The Local Rank Analysis report

Auto-generated after every **scheduled** scan (one-offs are deliberately skipped — no LLM spend,
no Drive doc, for a scan that isn't part of the client's record). You can always (re)generate it
by hand: **Generate report** on a scan row, or **Regenerate report** inside the accordion on
Heatmap.

Contents: deterministic ring/octant analytics, a written narrative, a saved map image, **weak
coverage areas** (nearby real cities, ranked by severity × proximity × beatability), and
**suggested hyper-local page targets** (octant, nearby city, ring distance, a Google Maps deep
link). View it via the accordion on each keyword's Heatmap card, or **Printable report** on
History (browser print → Save as PDF — there's no server-generated PDF file). If the client has a
Drive folder configured, it also auto-publishes as a Google Doc.

---

## Quick reference

| I want to… | Where |
|---|---|
| Run a full scan | Heatmap or One-offs → **Run scan now** |
| Run a cheaper partial scan | Keyword-scope picker → **Run scan (N keywords)** |
| Stop a running scan | **Stop scan**, or the per-row **Stop** icon |
| Delete one scan | Trash icon on its row (blocked while in-flight) |
| Wipe scan history | **Clear all** (scoped separately per tab) |
| Toggle weekly auto-scan | **Weekly: On/Off** on Heatmap, or Setup → Schedule |
| See what declined since last week | **What changed** tab |
| Read/regenerate the client-ready report | The Local Rank Analysis accordion on Heatmap |
| Get a printable/downloadable PDF | History → **Printable report**, or a keyword's **Download report** |

---

## FAQ

**I widened the grid and now it looks like rankings crashed.**
They didn't — comparisons auto-crop both scans to their shared area and flag it in a banner, so a
resize never reads as a false decline.

**I ran a scan but it's not on the trend chart / didn't trigger an alert.**
It was a one-off (manual) run — only weekly *scheduled* scans feed trends, alerts, and client
reports. This is deliberate, not a bug.

**Weekly scanning is on but nothing's updating.**
Check for zero active keywords on Setup — the tab warns explicitly when that's the case.

**Where's my Google Doc report?**
It only auto-publishes if the client has a Drive folder configured; otherwise the report still
generates and shows in-app, just with no "View Google Doc" link.

**Can I check just one keyword instead of the whole grid?**
Yes — the keyword-scope picker before Run scan. Cheaper, since a geo-grid bills per keyword × pin.
