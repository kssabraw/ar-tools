# AI Visibility — User Guide

A step-by-step tutorial for the AI Visibility tracker inside AR Tools. No code, no terminal —
everything here happens in the dashboard.

> **What this tool is.** It tracks whether a client's brand actually gets **mentioned** when six
> different AI assistants — ChatGPT, Claude, Gemini, Perplexity, Google AI Overview, Google AI
> Mode — answer the client's tracked keywords. It is not a ranking tool in the organic-SERP sense;
> "visibility" means the share of scanned AI answers that mention the brand, weighted by how
> confident the classifier is. Adding keywords/competitors is covered briefly in the onboarding
> tutorial (`docs/new-hire-onboarding-tutorial-v1_0.md` §10) — this guide covers running scans and
> reading results day to day.

---

## Before you start

- **You need at least one active keyword to scan.** The **Run scan** button is disabled with
  nothing to check.
- **Competitors are optional and free to include** — they're re-classified from the same AI
  answers your brand is checked against, no extra scan needed.
- **All six engines default checked** — this is an internal tool with no per-engine credit limits,
  so there's no cost reason to narrow a scan unless you're deliberately isolating one engine.

---

## The big picture

```
Overview · Keywords · Competitors · Schedule
```

1. **Run a scan** across the engines you care about (usually all six).
2. Read the **mention matrix** — one row per keyword, one column per engine.
3. **Diagnose** a keyword the brand is invisible on.
4. Compare against a **competitor's** visibility from the same scan.
5. Publish a **report**, or set a recurring **Schedule**.

---

## Step 1 — Run a scan

**Overview** tab → **Run scan** opens a dialog: per-engine checkboxes (all six preselected), an
**"Include competitors"** checkbox, and a live summary ("N keywords × M engines = T answers
scanned"). While it runs you'll see a progress bar and "X/Y done · Z failed" — you can close the
dialog and it keeps running server-side; reopening the page re-attaches to it automatically.

---

## Step 2 — Read the Overview dashboard

- **Stats row**: a **Global Health Score** arc gauge (≥70 green "Healthy," ≥40 amber "Partial,"
  below that red "Invisible"), Visibility Share %, Keywords Tracked, Engines Monitored.
- **Trend charts** appear once you have ≥2 scan batches.
- **Competitive visibility card**: side-by-side health-gauge tiles for the brand vs. up to two
  tracked competitors, from the latest scan that included competitors — a brand-only scan in
  between doesn't blank this card.
- **"Show visibility for"** dropdown (once competitors exist) — switch the mention matrix below to
  a specific competitor's re-classification from the same scanned answers.
- **The mention matrix**: one row per keyword, one column per engine (logo icon). A corner badge
  reads ✓ found, ✗ not found, "!" scan failed, a pulsing dot pending, or a slashed circle — Google
  didn't generate an AI answer for that search at all (excluded from the score, not a miss). On
  the two Google columns, a small 🔗 marks an inline link vs. a citation-only mention. Click a
  found/not-found cell to open the detail sheet.
- **"Latest scan — cross-engine insights"**: untracked competitors the AI surfaced (one-click
  **Track**), consensus winners named across engines, and what kinds of sources the AIs trust here.

---

## Step 3 — Diagnose a not-found result

Click a red ✗ cell (or **Diagnose** on a result card) to open the detail sheet: at-a-glance chips,
mention type / sentiment / confidence, a possible-misinformation callout when flagged, and a
**"Why invisible"** section with an AI-generated diagnosis (best-effort — it can be unavailable,
and doesn't auto-retry, so a failure won't silently burn another paid call). Further sections show
who did appear and why, which sources the AI cited (color-coded: green = you, amber = a
competitor, slate = other — with a callout when a competitor is cited but you aren't), how the AI
read the query's intent, and the raw AI response on request.

---

## Step 4 — Keywords and Competitors

**Keywords** tab: add a keyword, or click **Suggest AI queries** (grounded on the client's
profile) for click-to-add chips, or **Import from rank tracker** to pull in the organic tracker's
active keywords. Each keyword can be **Paused**/**Active**, or deleted.

**Competitors** tab: add by name — they ride along on the same scanned answers at no extra cost.

---

## Step 5 — Reports

Two different deliverables:

- **Google Doc** button — publishes a per-engine + matrix + invisible-list + competitor-comparison
  report with a narrative, straight to the client's Drive folder. Runs in the background; a
  banner shows the link once it's ready, or the failure reason.
- **Export report** button — a white-label **HTML** report over a chosen date range (7d/30d/90d/6m
  or custom), with Preview (sandboxed iframe), Download, and Print/Save-as-PDF.
- **Export CSV** — the full raw scan history (every keyword × engine row ever scanned).

---

## Step 6 — Schedule

**Off / Weekly / Monthly**, with a day-of-week or day-of-month picker, an hour (UTC), and an
"Include competitors" checkbox. **Save schedule** shows the next run date once active.

---

## Quick reference

| I want to… | Where |
|---|---|
| Run a scan | Overview → **Run scan** |
| Pick engines / include competitors | The scan dialog's checkboxes |
| See which engines mention the brand per keyword | The mention matrix |
| Understand why a keyword is invisible | Click a red ✗ cell (or **Diagnose**) |
| Compare against a competitor's visibility | **"Show visibility for"** dropdown |
| Add/pause/remove tracked queries | Keywords tab |
| Auto-suggest queries | Keywords tab → **Suggest AI queries** |
| Pull in rank-tracker keywords | Keywords tab → **Import from rank tracker** |
| Publish a client-facing Google Doc | Overview → **Google Doc** |
| Build a printable white-label report | Overview → **Export report** |
| Download the raw scan history | Overview → **Export CSV** |
| Turn on recurring scans | Schedule tab |

---

## FAQ

**Why is a cell greyed out with a slashed circle instead of red or green?**
Google didn't generate an AI Overview/AI Mode answer for that search at all — it's excluded from
the visibility score entirely, not counted as a miss.

**Why can't I click into a competitor's cells for the deep diagnosis?**
Competitor cells are re-classifications of the brand's own scanned answers, not independently
scanned rows — the drill-down (diagnosis, citations) is brand-specific only.

**I ran a scan without competitors — why does the comparison card still show old competitor data?**
Deliberate — it always shows the newest scan batch that *did* include competitors, so a brand-only
scan in between doesn't blank the tiles.

**The diagnosis spun and then errored — did the scan fail?**
No, the scan itself completed fine — "Diagnose" is a separate on-demand call that can fail
independently, and it deliberately won't auto-retry so you don't accidentally spend twice.

**I closed the scan dialog — did my scan stop?**
No, it keeps running server-side; reopening the page reconnects to it automatically.
