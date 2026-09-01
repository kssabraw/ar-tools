# Client Reporting — User Guide

A step-by-step tutorial for the Client Reports tool inside AR Tools. No code, no terminal —
everything here happens in the dashboard.

> **What this tool is.** It generates a **client-facing PDF performance report** — organic
> rankings, local-pack geo-grids, and Google Business Profile, plus AI-visibility and website
> traffic once those are connected — and can deliver it by email and/or a Drive copy on a
> recurring schedule. It's not a live dashboard and doesn't touch Asana. GA4 connection lives on
> this same page, briefly covered in the onboarding tutorial
> (`docs/new-hire-onboarding-tutorial-v1_0.md` §6) — this guide covers generating and scheduling
> reports day to day.

---

## Before you start

- **No hard gate to use the page** — it always renders, and every section degrades independently:
  a missing/failing data source is just omitted from the PDF rather than blocking the whole
  report.
- **Email needs SMTP configured agency-wide; Drive copy needs a Drive folder on the client.**
  Neither failing blocks the report itself — delivery is recorded as "skipped," not "failed."
- **Analytics beyond GA4, Asana, and a campaign-health summary are later phases** — the page's own
  subtitle says so.

---

## The big picture

1. **Generate a report on demand**, or set up a **standing schedule**.
2. Pick which extra deliverables ride the same clock (AI Visibility, Local Rank/Maps).
3. Track everything in the **history** list, and re-download any past report.

---

## Step 1 — Generate a report on demand

- **Report type**: **Monthly SEO report** or **AI Visibility report**. (A third type, Local Rank
  / Maps, exists but is schedule-only — see Step 2.)
- **Period**: Last 30 / 60 / 90 / 120 days, Last year, or Since campaign start.
- Optional checkbox: **"Email & save to Drive when done"** — ticks the on-demand delivery for
  *this* report only (a scheduled run always delivers regardless).
- **Generate report** — the history table polls every 4 seconds while anything is pending.
- **Download** on a completed row re-signs the link fresh each time, so old links never expire.

---

## Step 2 — Set up the standing schedule

The **"Delivery & schedule"** card:

- **Recipients** — comma-separated emails (account manager, typically).
- **Schedule** — **Off / Weekly / Monthly**, with a day (and hour, UTC) picker.
- **"Report covers"** — defaults to **Auto** (7 days for weekly, 30 for monthly), or pick one of
  the same explicit periods as Step 1 if you want the report to look further back than its own
  delivery cadence.
- **Email** and **Drive copy** checkboxes — both required to be ticked for that channel to fire.
- Two opt-in extras, each riding the **same** schedule as the combined report: **"AI Visibility
  report"** and **"Local Rank (Maps) report"** — each only actually generates for a client that
  tracks the matching keywords, so it's safe to leave both on for every client.
- **Save**.

---

## Step 3 — Read the history

Columns: **Generated · Type · Period · Includes · Status · Delivered · PDF**.

- **Includes** lists which sections actually came back with data (Organic / Maps / GBP / AI
  Visibility / Website traffic) — "no data" if none did.
- **Status**: pending/running both show as "Generating…"; a failed row's pill shows the error on
  hover.
- **Delivered**: separate ✓/✗/— marks for email and Drive — hover a ✗ for the stored error.

---

## Quick reference

| I want to… | Where |
|---|---|
| Generate a one-off report | Report type + Period → **Generate report** |
| Email/save this one report right now | Tick **"Email & save to Drive when done"** first |
| Turn on recurring reports | **Delivery & schedule** card → Schedule = Weekly/Monthly |
| Add the AI-visibility deliverable to the schedule | Check **"AI Visibility report"** |
| Add the Maps deliverable to the schedule | Check **"Local Rank (Maps) report"** |
| Re-download an old report | History row → **Download** |
| See why a report didn't email/save | Hover the Delivered ✓✗ marks |

---

## FAQ

**A generated report has a blank or missing section.**
Not a bug — each section gathers independently, and a missing/failed one is simply left out; the
report still completes.

**Email delivery shows a dash instead of a checkmark.**
Either SMTP isn't configured agency-wide yet, or the Recipients field is empty — both cause a
silent "skipped," not a failure.

**I ticked AI Visibility / Maps on the schedule but nothing showed up.**
That deliverable only fires if the client actually has tracked keywords for that module —
deliberate, so an accidental toggle can't ship an empty report.

**The old download link 404s.**
Shouldn't happen — Download always re-fetches a fresh signed URL first.

**Monthly "day of month" only goes up to 28.**
Intentional, so a scheduled monthly report never gets silently skipped in a short month.
