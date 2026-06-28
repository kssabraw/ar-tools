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
- **Phase 4 — Campaign-health & strategy overview:** a Claude (Sonnet) narrative
  synthesizing all sections (health score, wins/risks/next steps), reusing Action
  Plan / alerts / rankability signals.
- **Phase 5 — Delivery + scheduling:** PDF email attachments + recipient routing
  (AM for A, team for B), Drive-folder copy (Apps Script extension), monthly +
  weekly schedules on `gsc_scheduler`, on-demand "Generate now."
- **Phase 6 — Frontend:** per-client report settings (GA4 property, Asana
  projects, recipients/AM, schedule), report history + download/preview, "Generate
  & send now."

## Open scope decisions (for later phases)

- **Report B granularity:** per-client weekly to assigned team members, or one
  portfolio digest to the whole team. (Default: per-client.)
- **Branding:** client white-label (client logo + agency footer) for Report A.
  (Default: client-branded.)
