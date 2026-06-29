# Client Reporting module — PRD / build plan v1.0

Authoritative doc for the **Client Reporting** module: generated, client-facing
**PDF** reports plus internal team reports, assembled across the suite's data and
delivered by email + saved to the client's Google Drive folder.

## Goal — two deliverables

- **Report A — Monthly client report (PDF):** organic rankings, Maps geo-grids,
  Google Analytics (GA4), GBP analytics, Asana tasks completed, and a
  strategy/campaign-health overview → **auto-emailed to the account manager** +
  a **copy saved in the client's Google Drive folder**. The AM reviews, then
  forwards to the client.
- **Report B — Weekly team report:** Asana tasks completed + campaign-health →
  **team members**. Lighter; reuses A's Asana + health pieces.

## Locked decisions

- **PDF engine: WeasyPrint** (HTML/CSS → PDF, pure-Python, server-side). System
  libs (pango/cairo/gdk-pixbuf + fonts) are baked into the platform-api Docker
  image. Charts are inline **SVG** (same dependency-free approach as the frontend).
- **Storage:** generated PDFs go to the private **`reports`** Supabase Storage
  bucket (`storage_path` + a signed `pdf_url`). The **Drive-folder copy** lands in
  Phase 5 and needs a small **Apps Script extension** (today's webhook only
  creates Google Docs, not binary PDFs).
- **Sending:** **Google Workspace SMTP** (recipients are internal — AM + team).
  Switch to a transactional provider only if/when emailing clients directly.
- **No new infra:** runs on the existing `async_jobs` worker + `gsc_scheduler`.
- **Data model:** `client_reports` (one row per generated report) — migration
  `20260628211200_client_reports`.

## Prerequisites (provisioned outside this repo)

1. **GA4:** a Google service account with GA Data API access + each client's GA4
   **property ID**. (Gates Phase 2.)
2. **Asana:** a Personal Access Token + the Asana **project(s)** mapped per
   client. (Gates Phase 3.)
3. **GBP analytics:** the **Business Profile Performance API** (calls/directions/
   searches) — distinct from the GBP *profile + reviews* already captured. Same
   Google service account, API enabled + location id. (Phase 2.)
4. **Drive PDF copy:** an Apps Script webhook extension to save a base64 PDF into
   a folder. (Phase 5.)

## Phases

- **Phase 0 — Foundations (DONE):** `client_reports` table + `reports` storage
  bucket + `client_report` async job type; WeasyPrint added to requirements +
  Dockerfile system libs.
- **Phase 1 — PDF from existing data (DONE):** `services/client_report.py` —
  data gathering (organic rankings via `rank_status`, Maps geo-grids, GBP
  profile/reviews), pure HTML/SVG builders (`build_report_html`, `svg_sparkline`,
  `svg_geogrid`), `render_pdf` (WeasyPrint), store to the bucket, finalize the
  row. API `routers/reports.py` (`POST/GET .../clients/{id}/reports`), async job
  `run_client_report_job`. **PDF render is deploy-verified** (WeasyPrint + its
  system libs live only in the deployed image; pure builders are unit-tested).
- **Phase 2 — Google data:** GA4 connector (sessions/users/conversions/channels,
  MoM) + GBP Performance connector. Add both sections.
- **Phase 3 — Asana:** completed-tasks connector + section; unlocks Report B.
- **Phase 4 — Executive summary + performance comparisons (DONE; client-facing,
  positive):** the report is written **for the business owner** — plain, upbeat,
  jargon-free, wins-focused, **no health label/score**.
  - **Performance highlights** section: 30-day / 90-day / since-start comparisons
    for **impressions, organic clicks, and average ranking** (`build_comparisons`
    over `rank_keyword_metrics`). Clicks ("traffic") auto-populate once GSC clicks
    / GA4 are connected (none today); GA4 sessions replace clicks in Phase 2.
  - **AI search visibility** section (`_gather_ai_visibility`): per-engine
    appearance counts from the latest brand scan — auto-populates once AI
    Visibility scans run (none today).
  - **Executive summary** (`generate_exec_summary`, Claude forced tool-use →
    `{headline, highlights, focus_next}`) over the comparisons + sections + the
    Action Plan (planned next steps). Best-effort (`section_status.exec`); model
    `client_report_health_model` = `claude-sonnet-4-6`.
  - **GBP metric growth** (calls/directions/searches over time) is the one piece
    that genuinely waits for Phase 2 — no GBP time-series is stored yet.
  - **Owner-friendly layer** (built on Phase 4, for a non-SEO business owner who
    "just wants to know the budget is working"): an **at-a-glance KPI strip** of
    hero numbers at the top (`_kpi_strip` — search-visibility change, ranking
    gains, keywords on page 1, content delivered; each card renders only when its
    data exists); a **Work delivered this period** section (`_gather_work_delivered`
    + `_section_work_delivered` — completed pipeline runs blog/service/location +
    new Local SEO pages, head-only count queries, each source degrades
    independently); the organic table trimmed to the **top movers** (`_keyword_change`
    + `_TOP_MOVERS`=5, a Movement column + a "remaining N tracked" line, not all
    40 rows); plain-English **captions** (`.note`) under each section; and a
    **white-labeled** footer ("Prepared by &lt;agency&gt;", `client_report_agency_name`,
    default "Amazing Rankings"). Report order: cover → KPI strip → executive
    summary → performance highlights → work delivered → organic (top movers) →
    Maps coverage → AI search visibility → GBP. **Live-verified** end-to-end (a
    real First Class Roofing report rendered on the deployed worker).
- **Phase 5 — Delivery + scheduling:** PDF email attachments + recipient routing
  (AM for A, team for B), Drive-folder copy (Apps Script extension), monthly +
  weekly schedules on `gsc_scheduler`, on-demand "Generate now."
- **Phase 6 — Frontend (DONE for current scope):** a "Client Reports" workspace
  card + `pages/ClientReports.tsx` (route `clients/:id/reports`) — generate
  on-demand, history list with live status polling, download the PDF (detail
  endpoint re-signs the URL on read). *Report settings (GA4 property, Asana
  projects, recipients/AM, schedule) are deferred with Phases 2/3/5.*

## Open scope decisions (for later phases)

- **Report B granularity:** per-client weekly to assigned team members, or one
  portfolio digest to the whole team. (Default: per-client.)
- **Branding:** client white-label (client logo + agency footer) for Report A.
  (Default: client-branded.) **Partly built:** the footer is agency-white-labeled
  (`client_report_agency_name`); the cover already uses the client logo. A
  per-client/per-agency branding override is the remaining piece.
