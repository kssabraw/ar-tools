# AR Tools — Suite Architecture & Roadmap (v1.0)

**Status:** Draft for review · **Authored:** 2026-05-29 · **Branch:** `claude/gracious-bell-BbkY5`

> **Read order note.** CLAUDE.md and the `/docs` PRDs were written when this repo was a *single* tool (the Blog Writer). This document supersedes that single-tool framing at the **product/architecture** level: AR Tools is now a **multi-module agency suite** sharing one dashboard, one Supabase database, and one scheduler. The existing engineering spec and module PRDs remain authoritative for the Blog Writer's *internals*. Where this doc and CLAUDE.md disagree on "how many tools is this," this doc wins; for "how is the Blog Writer built," the engineering spec still wins.

---

## 1. Vision

AR Tools is an **internal agency suite**. A team member (or VA) picks a client, then works across a set of SEO modules from one dashboard: generate content, research keywords, track rankings, and get alerted — with recommended fixes — when rankings drop. All modules share a single client roster and database.

Not customer-facing. No billing, no signup. Internal team only. (Unchanged from CLAUDE.md.)

## 2. The modules

| # | Module | Type | Status | Primary data source |
|---|---|---|---|---|
| 1 | Blog Writer | On-demand content | Exists (`/writer`) — re-home as a tab | DataForSEO + Claude |
| 2 | Local SEO content | On-demand content | Migrate from existing repo | (TBD on repo review) |
| 3 | Keyword research | On-demand research | Migrate from existing repo | Existing tool + **GSC** opportunity data |
| 4 | Organic rank tracker | Scheduled time-series | Build on shared spine | **DataForSEO** (rank-of-record) + GSC context |
| 5 | Maps / local-pack ranker | Scheduled time-series + geo | Build on shared spine | **DataForSEO** geo-grid |
| 6 | Ranking-drop agent | Intelligence over #4 + #5 | Build | Position **+ GSC clicks/impressions** |
| 7 | Content scheduler (VA) | Workflow / automation | Build | Orchestrates #1 & #2 |

Plus a cross-cutting **Google Search Console analytics layer** (clicks / impressions / CTR / average position) that feeds modules 3, 4, and 6 and powers a per-client performance view.

### Module groupings (they behave differently)

- **Group A — On-demand tools (1, 2, 3):** user provides input → tool runs → result. Migrations #2 and #3 are independent of the rankings work and can land in parallel any time.
- **Group B — Scheduled trackers (4, 5):** recurring jobs collect time-series data. Depend on the shared scheduler + rankings data model.
- **Group C — Intelligence & automation (6, 7):** ride on top of Groups A/B. The drop agent reasons over tracker data + SOPs; the content scheduler orchestrates Group A on a monthly cadence.

## 3. Decision log (locked)

These were decided with the user during scoping on 2026-05-29. Do not reverse without asking.

| Topic | Decision |
|---|---|
| **Organic rank source** | **Hybrid.** DataForSEO is the authoritative daily organic position (precise; covers target + competitor + not-yet-ranking keywords) and is the **only** source for maps/local-pack. GSC supplies clicks/impressions/CTR/average-position for analytics + keyword discovery, shown as *context* next to the DataForSEO rank. |
| **GSC connection** | **Service account.** A Google Cloud service-account key in env (no interactive OAuth/token refresh). Per-client onboarding step: add the service account's email as a user on that client's Search Console property, and store the property/site URL on the `clients` row. |
| **Rank data provider** | **DataForSEO** for both organic SERP and maps/local-pack (already wired into the Blog Writer). No new SERP vendor. |
| **Ranking-drop agent knowledge** | Build an **SOP store** (Supabase table + in-dashboard Markdown editor) the agent reasons over. SOPs are editable by the team without code changes. |
| **Alerting** | **In-app alerts feed** (badges on client tiles) **+ email/Slack** push on a flagged drop. Adds a small outbound notification service. |
| **Content scheduler trigger** | **Generate + publish, no human approval gate.** On the target date the system generates the content and publishes it automatically. |
| **Publish destination** | **Drive now, CMS-ready later.** "Publish" today = create a Google Doc in the client's Drive folder via the existing Apps Script webhook (`writer/platform-api/routers/publish.py`). Design the publish step so a live-to-CMS target (e.g. WordPress REST) can be added later without rework. **Live-to-site is explicitly out of scope for v1.** |
| **Auth/roles** | Internal only. VAs are `team_member`s. No new auth surface beyond the GSC service account. |

## 4. Data sources

- **DataForSEO** — organic positions, maps/local-pack, geo-grid. (Already integrated.)
- **Google Search Console** (service account) — clicks, impressions, CTR, average position; keyword/opportunity discovery.
- **Anthropic Claude** — content generation (per existing module PRDs) + drop-agent recommendations.
- **OpenAI `text-embedding-3-small`** — SIE only (unchanged).
- **Google Drive / Apps Script** — publish/delivery destination (existing).

## 5. Shared infrastructure to build

The modules are valuable individually but cheap together because they share these:

1. **Dashboard shell** — launcher tiles → per-client workspace with tabs (Blog, Local SEO, Keywords, Rankings, Alerts, Content Calendar). Re-home the existing Blog Writer UI as the first tab. Add `logo_url` to `clients` for tile branding.
2. **One shared scheduler** — the single most-reused piece. Drives: rankings ingestion (#4, #5), GSC pulls, and the monthly content schedule (#7). **Mechanism not yet chosen** — see Open Items.
3. **Rankings / metrics data model** — time-series tables for positions and a `gsc_metrics` table.
4. **GSC integration** — service-account auth + per-client property mapping + scheduled ingestion job.
5. **SOP store** — Supabase table + Markdown editor; consumed by the drop agent.
6. **Notifications service** — in-app alerts feed + email/Slack outbound.

## 6. Proposed data model additions (sketch — finalize at build time)

- `clients`: add `logo_url`, `gsc_property` (site URL), `business_location` (for maps geo-grid).
- `tracked_keywords` — `(client_id, keyword, type: organic|maps, location, active)`.
- `rank_snapshots` — `(tracked_keyword_id, date, position, url, source: dataforseo)`; maps rows carry geo-grid point.
- `gsc_metrics` — `(client_id, date, query, page, clicks, impressions, ctr, position)`.
- `sops` — `(id, title, body_markdown, tags, updated_by, updated_at)`.
- `alerts` — `(client_id, type, severity, summary, detail, status, created_at)`.
- `content_plans` / `content_plan_items` — `(client_id, month)` and `(type: blog|local_seo, topic/keyword, target_date, status, generated_run_id, published_doc_url)`.

All via migrations in `writer/supabase/migrations/` (existing convention), service-role access from the backend (per CLAUDE.md).

## 7. Roadmap (phased)

### Phase 0 — Foundation
- Dashboard shell: launcher tiles → client workspace with tabs.
- Re-home the Blog Writer UI as the first tab.
- `clients.logo_url` + tile branding.

### Phase 1 — Data spine
- Build the **shared scheduler** (mechanism TBD — confirm first).
- Rankings data model + **DataForSEO organic tracker** (#4).
- **GSC ingestion** (service account → `gsc_metrics`) + per-client performance view.
- **Maps ranker** (#5) — adds business location + geo-grid.

### Phase 2 — Intelligence & automation
- **Ranking-drop agent** (#6): SOP store → drop detection over Phase 1 data → Claude recommendations → alerts feed + email/Slack.
- **Content scheduler** (#7): monthly plans → auto-generate (#1/#2) → publish to Drive. CMS-ready seam, no approval gate.

### Parallel track — Migrations (any time)
- **Local SEO content** (#2) and **Keyword research** (#3) migrate in whenever their repos are provided. The KW tool gains GSC opportunity data once Phase 1 lands.

## 8. Open items (settle at build time, not blocking the plan)

1. **Scheduler mechanism** — pg_cron vs Railway cron vs an asyncio worker loop. CLAUDE.md requires confirming before adding any queue/scheduler-like infra. **Must decide before Phase 1.**
2. **Maps geo-grid density** — points per location; primary driver of DataForSEO cost.
3. **Migration repos** — stack/data-model fit for #2 and #3 unknown until the repos are shared; each needs a fit assessment (stack, mapping onto shared `clients`, UI fold-in).
4. **Notification channels** — confirm email provider and Slack workspace/webhook details.

## 9. Known doc discrepancies to reconcile

- **Frontend platform:** CLAUDE.md says "Lovable (React + Vite)." The actual repo has a React + Vite app in `/frontend` with `netlify.toml` (deployed to **Netlify**). This roadmap assumes the **`/frontend` + Netlify** reality. CLAUDE.md should be updated.
- **Single-tool framing:** CLAUDE.md's "What this project is" / build order describe only the Blog Writer. After this roadmap is accepted, CLAUDE.md should be updated to point here for suite-level context.

## 10. Next step

On approval of this roadmap: update CLAUDE.md + README to reflect the multi-module suite, then begin **Phase 0**. The scheduler-mechanism decision (Open Item #1) is the first thing to resolve before Phase 1.
