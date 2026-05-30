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
| 2 | Local SEO content | On-demand content | Imported (`/local-seo-writer`) — integration deferred, see Appendix A | Google NLP + competitor SERP + Claude |
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
- **Local SEO content** (#2) is **imported** at `/local-seo-writer` (raw, unmodified). Integration depth is **deferred** — pick A, B, or C from **Appendix A** before adapting it. **Keyword research** (#3) migrates in whenever its repo is provided. The KW tool gains GSC opportunity data once Phase 1 lands.

## 8. Open items (settle at build time, not blocking the plan)

1. **Scheduler mechanism** — pg_cron vs Railway cron vs an asyncio worker loop. CLAUDE.md requires confirming before adding any queue/scheduler-like infra. **Must decide before Phase 1.**
2. **Maps geo-grid density** — points per location; primary driver of DataForSEO cost.
3. **Migration repos** — #2 (Local SEO) is now imported and assessed — **see Appendix A** for its stack, data-model overlap, and the A/B/C integration options (decision deferred). #3 (Keyword research) stack/data-model fit remains unknown until its repo is shared.
4. **Notification channels** — confirm email provider and Slack workspace/webhook details.

## 9. Known doc discrepancies to reconcile

- **Frontend platform:** CLAUDE.md says "Lovable (React + Vite)." The actual repo has a React + Vite app in `/frontend` with `netlify.toml` (deployed to **Netlify**). This roadmap assumes the **`/frontend` + Netlify** reality. CLAUDE.md should be updated.
- **Single-tool framing:** CLAUDE.md's "What this project is" / build order describe only the Blog Writer. After this roadmap is accepted, CLAUDE.md should be updated to point here for suite-level context.

## 10. Next step

On approval of this roadmap: update CLAUDE.md + README to reflect the multi-module suite, then begin **Phase 0**. The scheduler-mechanism decision (Open Item #1) is the first thing to resolve before Phase 1.

---

## Appendix A — Local SEO module (#2): import & integration assessment

**Authored:** 2026-05-29 · **Status:** imported, integration **deferred** (no path chosen yet)

### A.1 What was done

The existing **ShowUP Local** app (`kssabraw/showup-local`) was imported into this repo at **`/local-seo-writer`** as a **raw, unmodified copy** (commit `7f3fe05`). Per decision, git history was **not** preserved (squashed into a single import commit). Excluded from the copy: `.git/`, `node_modules/`, `dist/`, and the app's `.env` / `.env.production` (they held only public `VITE_*` values, to be reconfigured for the suite at integration time). 174 files / ~37.7k lines.

No suite adaptation has been applied. The next diff against this import will cleanly show whatever changes are made to fit AR Tools.

### A.2 What the app is

A **local SEO content generator**: enter a keyword + location → it analyzes top-ranking competitor pages, extracts SEO signals (related keywords, key phrases, Google **NLP** entities), and generates optimized local-SEO pages tied to a Google Business Profile. This is exactly suite module #2.

### A.3 Stack — overlap and divergence vs. the suite

| Layer | AR Tools (suite) | ShowUP Local (imported) | Fit |
|---|---|---|---|
| Frontend base | React + Vite | React + Vite | ✅ same |
| UI system | Plain inline styles | **Tailwind + shadcn/ui** (`components.json`, `tailwind.config.ts`) | ⚠️ different design system |
| Routing | React Router | **React Router** (`react-router-dom` ^6.30) | ✅ same |
| Backend | **FastAPI** (platform-api / pipeline-api on Railway) | **Supabase Edge Functions** (Deno/TS) **+** a Python **FastAPI NLP microservice** (`services/nlp`) | ⚠️ different backend model |
| Database | Supabase (AR-Internal-Tools) | **Separate** Supabase project (29 migrations) | ⚠️ two databases |

**Reusable as-is in any path:** the **NLP microservice** (`services/nlp/main.py`, `url_filter.py`) — a standalone Python/FastAPI service that fits the suite's Railway model directly.

### A.4 Data-model overlap (similar, not matching)

ShowUP has its own `business_profiles`, `keyword_analyses`, `generated_pages`, plus a `User` carrying `password_hash` and `credit_balance`. Mapping onto the suite:

- `business_profiles` ≈ suite **`clients`** (overlapping concept, different columns).
- ShowUP `User` + credits **conflicts** with the suite model (Supabase **Auth** for identity; **no billing**).

### A.5 The core mismatch — it's built as a customer-facing SaaS

The app carries a **billing/credits** model the suite explicitly does not have: edge functions `purchase-credit-pack`, `purchase-press-release-pack`, `purchase-rankability-pack` (all **Stripe**-backed), plus `credit_balance` / credit-transaction logic. AR Tools is **internal-only, no billing** (CLAUDE.md §"What this project is"). **These billing parts should be dropped regardless of which integration path is chosen.**

### A.6 Integration options (decision deferred)

| Path | What it means | Effort | Trade-off |
|---|---|---|---|
| **A — Standalone in monorepo** | Keep ShowUP on its own stack (its Supabase + edge functions + NLP service); house it in `/local-seo-writer` and link from the dashboard as a module tile. | Lowest | Two databases, two client rosters; least integrated. |
| **B — Share data, keep backend** | Point it at the shared `clients` table + shared Supabase Auth; strip billing/credits; keep its edge functions + NLP service. | Medium | One client roster; still a second backend paradigm (edge functions) alongside FastAPI. |
| **C — Full port** | Rebuild its UI in the suite frontend style and move its backend logic into FastAPI (platform-api/pipeline-api). | Highest | Most consistent with the rest of the suite; largest rewrite. |

**Cross-cutting regardless of path:** (1) drop the Stripe/credits billing surface; (2) the NLP microservice can be lifted into the suite's Railway services unchanged; (3) reconcile `business_profiles` → `clients`.

**No path is chosen yet.** The raw import stays as-is until A/B/C is selected.
