# Organic Rank Tracker — Module PRD (v1.0)

**Authored:** 2026-06-22 · **Status:** plan approved, **no code written yet** · **Module #4 (suite roadmap)**

> Read alongside **`docs/suite-architecture-and-roadmap-v1_0.md`** (the suite-level decision log this module inherits) and **`CLAUDE.md`** (stack, conventions, RLS/service-role rule). This document supersedes the standalone *Organic Rank Tracker — Build Spec v0.2* by adapting it to the AR Tools suite: the spec's product reasoning is kept, but its standalone-SaaS assumptions (Astro/Cloudflare stack, per-tenant RLS, n8n/Telegram alerts, billing) are replaced with the suite's locked decisions. Where this doc and the v0.2 spec disagree on **how it's built in this repo**, this doc wins.

---

## 1. Product summary

A **per-client** Organic Rank Tracker on each client's workspace. It connects to a client's Google Search Console (via a service account), stores the GSC performance history forever (GSC only retains 16 months), and layers DataForSEO live rank + commercial data on top. The team tracks user-defined keywords and sees, per keyword: clicks, impressions, CTR, GSC average position, today's live DataForSEO rank, CPC, the landing page the keyword surfaces for, and a per-keyword rank trendline that surfaces drops, recoveries, and **deindexing**.

It is **Module #4 (Scheduled time-series)** in the suite roadmap — Group B. It depends on the shared scheduler and the GSC integration layer, both of which it is the first module to exercise.

Not customer-facing. Internal agency use only. No billing.

---

## 2. The hybrid thesis (the one decision everything rests on)

GSC only returns queries the site **already appears for**. A keyword the client *wants* to rank for but doesn't yet surface for returns nothing — not a zero, just absence. So a pure-GSC tracker structurally cannot do the one thing "keywords I want to rank for" implies.

**Decision: hybrid** (this matches the suite decision log — "Organic rank source: Hybrid").

- **GSC** supplies real clicks / impressions / CTR / average position and the landing page, for keywords already surfacing.
- **DataForSEO** supplies a live point-in-time SERP rank for aspirational keywords (and a sanity-check live rank for the rest), plus CPC / search volume / competition.

The UI merges both into one keyword row, and **labels the two ranks distinctly everywhere** — GSC average position is an impression-weighted aggregate, not a point-in-time rank, and must never be reconciled as equal to the DataForSEO live position (see §9).

### Automatic GSC → DataForSEO fallback (built)

Keywords are **client-anchored** (the GSC property is optional), and the rank source is selected **automatically, per keyword**:

- **GSC** is used when the client has a verified property **and** the site ranks for the keyword (GSC returned a position within the last `rank_gsc_coverage_days`).
- **DataForSEO** is the fallback when GSC can't cover the keyword: the client has **no accessible GSC property**, *or* the site **doesn't rank** for the term (so GSC has nothing). The fallback fetches a live Google organic SERP position for the client's domain, **refreshed weekly** to bound cost (`dataforseo_rank_weekday`), writing `tracked_rank` only (never reconciled with `gsc_position`). The weekly job **skips** keywords GSC already covers, so spend scales with the gaps, not the whole set.

When a keyword (or the whole client) is on the DataForSEO path, the UI **drops the GSC-only views** — clicks, impressions, CTR, and the average-position chart/columns — and shows the live rank ("Today") + its weekly trendline instead. `KeywordSummary.primary_source` (`gsc`/`dataforseo`/`none`) and `Overview.gsc_connected` drive this.

**Tracking location (built).** The DataForSEO rank + market checks run at a per-client **tracking location** (`clients.rank_tracking_location` / `rank_tracking_location_code`), set in Rankings → Settings via the suite's location typeahead (city / region / country). When unset it falls back to the country auto-detected from the client's website TLD (default US). GSC stays national-aggregate regardless (Google's limitation). True local-pack geo-grid tracking remains Module #5 (Maps ranker).

---

## 3. Suite-conformance: what changed from the v0.2 spec

The v0.2 spec was written as a standalone product. These are the deltas, each settled with the user on 2026-06-22:

| v0.2 spec said | This module does | Why |
|---|---|---|
| Astro + React islands on Cloudflare Pages | **React + Vite in `/frontend`, Netlify** — tabs in the existing suite app | Suite stack is locked (CLAUDE.md). One shared frontend. |
| "Multi-tenant with RLS keyed on client/org" | **RLS on, no client-facing policies; all access via service-role key; authorization is API-layer `client_id` filtering** | The suite is single-tenant internal (one agency). There is **no** per-VA/per-org client scoping, now or planned. Follows the existing `async_jobs` pattern. |
| Sync via "Railway scheduled service **or** n8n" | **Suite shared scheduler** (mechanism is suite Open Item #1, TBD before any ingestion job ships) | CLAUDE.md forbids adding queue/scheduler infra without agreement; the suite picks one mechanism for all trackers. |
| Alerts via email / Slack / **Telegram**, reusing n8n | **Suite notifications service** — in-app alerts feed + email/Slack | n8n/Telegram are not in this repo. Notifications service is the suite's planned channel. |
| `Settings → billing`; OAuth "future self-serve product" | **No billing.** Service account only. | Internal tool, no billing (CLAUDE.md). OAuth stays explicitly out of scope. |

Everything else in the v0.2 spec — the hybrid thesis, the service-account ingest, the materialized null date-axis, the computed status field, deindex detection, and the surface-by-exception UX — is **kept** and detailed below.

---

## 4. GSC ingest: service account (the only path)

This matches the suite decision log ("GSC connection: Service account").

A service account is a Google-managed identity with its own email (`name@project.iam.gserviceaccount.com`). It cannot authorize itself onto a client's property — instead **the client adds that email as a user** on their property (Search Console → Settings → Users and permissions). Once added, the app authenticates as the service account and reads their data. No consent screen, no per-user token, no refresh-token lifecycle.

- The service-account key lives **once at the app level** in env on the backend (never per-client, never in the DB). `Restricted` permission is enough to read performance data; `Full` gives headroom for sitemaps / URL Inspection.
- **OAuth is explicitly out of scope** (it would only be needed for a public self-serve product, which AR Tools is not).

### Canonical request shape (`searchanalytics.query`)

```python
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
creds = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_KEY_JSON, scopes=SCOPES,   # loaded from env, not a file on disk
)
sc = build("searchconsole", "v1", credentials=creds)

resp = sc.searchanalytics().query(
    siteUrl=property.site_url,                  # url-prefix: full URL WITH trailing slash
    body={                                      # domain property: "sc-domain:clientdomain.com"
        "startDate": "2026-06-01", "endDate": "2026-06-03",
        "dimensions": ["query", "page", "date"],
        "rowLimit": 25000, "startRow": 0,       # paginate startRow until a short page returns
    },
).execute()
```

**Gotcha (must design around):** `siteUrl` must match the property type **exactly** — url-prefix needs the trailing slash; domain needs the `sc-domain:` prefix. A mismatch returns a **403 that looks like a permissions error but isn't**. The verify-access step (M1) and the `sync_runs` error surface must distinguish "wrong siteUrl format" from "service account not added."

---

## 5. Data model

All tables via migrations in `writer/supabase/migrations/`. Conventions inherited from the existing schema (`20260430120000_schema.sql`): `uuid` PKs (`gen_random_uuid()`), `timestamptz not null default now()`, `check` constraints for enums, FKs to `clients(id)`.

**Access pattern (locked):** RLS **enabled** on every table below, **no client-facing policies** — written by scheduled backend jobs and read by the API, both with the **service-role key** (the `async_jobs` pattern from `20260430120100_rls.sql`). Authorization is enforced in the API layer by `client_id` / `property_id`, exactly as `runs` works today.

### Final reconciled vocabulary

This reconciles three prior naming sources: the v0.2 spec (§5), the roadmap sketch (§6), and the existing DB.

```
clients(id, name, ...)                         -- exists. Tenancy root for all tracker tables.

gsc_properties(
  id, client_id → clients(id),
  site_url,                                     -- "https://acmehvac.com/" or "sc-domain:acmehvac.com"
  property_type    check in ('url_prefix','domain'),
  access_status    check in ('ok','no_access','pending')  default 'pending',
  last_verified_at,
  created_at, updated_at
)
  -- Per-property mapping. A client may have BOTH a url-prefix and a domain property.
  -- The verify-access button (M1) writes access_status. 403s during sync flip it to 'no_access'.
  -- NOTE: the existing clients.gsc_property column is folded in here and then deprecated/dropped
  -- (see §11 migration note).

tracked_keywords(
  id, property_id → gsc_properties(id),
  keyword,
  source           check in ('gsc','dataforseo','both'),
  canonical_url,                                -- the page we treat as "the" landing page
  canonical_url_locked  boolean default false,  -- pin it; stops the heuristic reassigning it
  status           check in ('climbing','stable','volatile','dropping','deindex_risk','no_data')
                     default 'no_data',          -- COMPUTED nightly, not user-set
  status_updated_at,
  active           boolean default true,
  created_at, updated_at
)

gsc_query_daily(property_id → gsc_properties(id), date, query,
                clicks, impressions, ctr, position)
  -- Raw GSC query×date dump (NO page dimension). Daily pull. Idempotent upsert.
  -- Powers trends + "striking distance" discovery (positions ~8–20 = page-2 opportunities).
  -- PK / unique on (property_id, date, query).

gsc_query_page_daily(property_id → gsc_properties(id), date, query, page,
                     clicks, impressions, ctr, position)
  -- Raw GSC query×page×date grain. WEEKLY refresh. Powers canonical_url resolution,
  -- the Pages view, and the per-keyword page breakdown.
  -- KEPT SEPARATE from gsc_query_daily on purpose: GSC computes + anonymizes each dimension
  -- grouping independently, so query×page totals will NOT reconcile against query×date. Do not
  -- try to derive one from the other. PK / unique on (property_id, date, query, page).

rank_keyword_metrics(keyword_id → tracked_keywords(id), date,
                clicks, impressions, ctr, gsc_position, tracked_rank)
  -- Implemented as `rank_keyword_metrics` (not bare `keyword_metrics`) to avoid overloading
  -- "keyword" across the suite + a ghost keyword_metrics migration in the log. See M3 migration.
  -- THE MATERIALIZED DATE AXIS: exactly ONE row per tracked keyword per day across the tracked
  -- range. gsc_position is NULL on days GSC returned nothing — absence is STORED, not omitted
  -- (see §7). gsc_position = GSC averaged (impression-weighted); tracked_rank = DataForSEO live
  -- integer. The two come from different jobs and are NEVER written together / never reconciled.
  -- PK / unique on (keyword_id, date).

keyword_market(keyword, cpc, search_volume, competition, refreshed_at)
  -- Keyword-level market data, CROSS-PROPERTY (not per-client). Refreshed MONTHLY.
  -- Cache once per keyword and reuse across clients. PK / unique on (keyword).

sync_runs(id, property_id → gsc_properties(id), job_type, run_at,
          rows, status, error)
  -- Per-property ingestion audit log + observability. Distinct from async_jobs (the generic
  -- worker queue). job_type distinguishes the ingest jobs of §6. 403s recorded here surface the
  -- "reconnect needed" state in Settings.

rank_snapshots(...)  -- RESERVED for Module #5 (Maps/local-pack geo-grid). Organic live rank lives
                     -- in keyword_metrics.tracked_rank, NOT here. Documented to prevent a
                     -- duplicate organic snapshot table being added later.
```

### Design notes
- `gsc_position` and `tracked_rank` are **two metrics from two sources** — separate columns, never reconciled as equal (§9, §2).
- `canonical_url_locked`: when a client deliberately targets a specific URL, the "most clicks" heuristic must not silently reassign it to a blog post that spiked one week.
- `status` is a **computed field, not decoration** — calculated during the nightly sync from the trend so the UI can sort/filter on it instantly (§7, §8).

---

## 6. Sync jobs & cadence

All jobs run on the **suite shared scheduler** and write observability rows to `sync_runs`.

> **Scheduler mechanism (decided 2026-06-22, suite Open Item #1):** an in-process **asyncio loop in platform-api** (`services/gsc_scheduler.py`) that, once per day after `gsc_ingest_hour_utc`, enqueues a `gsc_ingest` row into the existing `async_jobs` table for each verified property; the existing `job_worker` executes them. Zero new infrastructure, consistent with the existing `job_worker` pattern, no new deps. A missed run (service down at fire time) self-heals via the ingest's trailing re-pull window. This is the reusable spine for later scheduled trackers (Maps #5, content scheduler #7) — add their enqueue passes there rather than introducing new infra.

| Job | Cadence | Notes |
|---|---|---|
| GSC query×date ingest | Daily | Re-pull last **~3 days** each run (GSC backfills late — §9). Paginate `startRow` (25k rows/request). Idempotent upsert into `gsc_query_daily`. |
| GSC query×page refresh | Weekly | Resolves `canonical_url` into `gsc_query_page_daily`. The page dimension multiplies rows + increases anonymization, so no daily granularity. |
| **Date-axis materialize + status compute** | Daily (after ingest) | Write a `keyword_metrics` row per tracked keyword per day, **NULL** position where GSC returned nothing. Recompute `tracked_keywords.status`. |
| DataForSEO live rank ("Today") | Daily (priority KWs) / Weekly (long tail) | Bills per query per run — this is where spend scales. Writes `keyword_metrics.tracked_rank`. |
| DataForSEO CPC / volume / competition | Monthly | Google Ads data refreshes monthly; daily pulls burn credits for identical numbers. Writes `keyword_market`. |
| URL Inspection | On gap detection only | Confirms deindexing (§7). Respect the separate daily per-property quota — trigger on the signal, never poll everything. |

---

## 7. Per-keyword rank trendline & deindex detection

Goal: distinguish a keyword that is **dropping and recovering** from one that has **disappeared entirely** for a period — the signature of a deindexed page.

**Render absence as a gap.** The trendline must distinguish "ranked at position X" from "no data." In the charts this is `null` data points with `spanGaps: false`, so a missing stretch shows as a visible break, not a line drawn straight across it. A continuous line would connect e.g. position 11 → 18 across a three-week hole and read as a gradual slip instead of a disappearance.

**This forces the materialized date axis (§5).** GSC returns **no row** for a zero-impression day — it does not return a zero. If `keyword_metrics` only stored returned days, the gap wouldn't exist in the data and couldn't be drawn. So the daily materialize job generates a row per keyword per day and leaves `gsc_position` NULL when GSC returned nothing. **Absence becomes a stored fact.**

**Gap is only a signal with context.** A gap means deindex risk only if the keyword had **established presence before it** and the gap is **sustained**. A low-volume keyword flickering in and out is anonymization noise (§9); a keyword that pulled steady impressions for weeks and then flatlines to nothing is the alarm. Rule of thumb: **N+ consecutive NULL days after an established baseline → `deindex_risk`** (N tunable; start conservative).

**Confirm with URL Inspection.** When the gap detector fires, auto-run a URL Inspection on that keyword's `canonical_url`. It returns actual index status, so the client message becomes **"this page is deindexed"** rather than "rankings look low."

### Status taxonomy (computed nightly)
- `climbing` — consistent improvement
- `stable` — holding within a band
- `volatile` — swung past a threshold then returned (drop-and-recover)
- `dropping` — sustained decline, still present
- `deindex_risk` — sustained NULL after an established baseline
- `no_data` — never established presence (tracked / aspirational, awaiting first data)

These are the only legal values of `tracked_keywords.status` and the sort/filter keys for the Overview triage (§8).

---

## 8. UI / UX

Built as tabs inside the per-client workspace in the existing `/frontend` suite app (React + Vite, TanStack Query for server state, Recharts for charts). No new frontend surface.

### 8.1 App IA (tabs within the client's Rankings module)
- **Overview** — account-level health for the selected property: KPI cards, the average-position hero chart, and a **lean** triage keyword list (keyword + sparkline + Today + Δ30d + status).
- **Keywords** — the full wide table: every metric column (clicks, impr, CTR, CPC, Today, 7/30/60/90) + sparkline + status, with per-keyword expansion.
- **Pages** — the same data pivoted by URL instead of keyword. Nearly free given `gsc_query_page_daily`; home of canonical-URL and "+N pages" logic.
- **Alerts** — config for deindex/drop notifications (routes to the suite notifications service).
- **Settings** — property connection (service-account email + verify-access), property list. **No billing.**

### 8.2 Charts
- **Average position (hero):** line with **inverted Y axis** (position 1 at top) so improving rank trends upward. Same convention as GSC.
- **Clicks & impressions:** dual-line, **separate left/right Y axes** (clicks left, impressions right) so impressions don't flatten the clicks line. Clicks solid, impressions dashed (color + dash for accessibility).
- **Per-keyword sparkline:** tiny inverted line in each row; renders gaps (`spanGaps:false`); color double-encodes status. Full trendline in the row expansion.

### 8.3 Designing for scale — surface-by-exception
At 48+ keywords nobody scans 48 charts; the UI does the scanning.
- **Health rollup** at the top turns the set into counts (At risk / Volatile / Climbing / Stable). Each is a filter; "At risk" is styled to pull the eye.
- **Default sort = needs attention**, so deindex risks and drops float to the top automatically (cheap because `status` is precomputed).
- **Sparkline replaces the chart** in the dense view — still shows the gap, color-coded by status, scannable peripherally.
- **Progressive disclosure:** the dense list answers "is anything wrong"; row expansion answers "what and why" (full trendline + metric strip + page breakdown + index-check action); the wide `Keywords` table is there when you want the spreadsheet.
- **Grouping** by landing page or by silo/cluster (maps onto the suite's topic-fanout architecture) collapses dozens of keywords into a handful of expandable groups.

### 8.4 Every metric stays reachable
The triage view relocated columns, it didn't drop them. Clicks, impressions, CTR, CPC, Today, and 7/30/60/90 all live in (a) the `Keywords` wide table and (b) the per-keyword expansion's metric strip. Overview is intentionally lean (scan mode); Keywords is intentionally wide (read mode). A per-user **column-visibility toggle** lets anyone who prefers the everything-visible spreadsheet (with horizontal scroll) have it.

### 8.5 Table columns (full / Keywords tab)
Keyword & landing page (name + source badge + canonical URL + "+N pages" chip) · Clicks · Impr. · CTR · CPC (DataForSEO) · **Today** (DataForSEO live, integer, boxed + live dot) · Avg position **7d / 30d / 60d / 90d** (GSC rolling averages, decimals; arrow on 7d flags net direction vs 90d).

The **integer-vs-decimal** distinction (Today vs windows) is deliberate: it signals at a glance that the two come from different sources and must not be read as the same metric.

---

## 9. GSC behaviors to design around (the highest-value constraints)

- **16-month retention.** GSC discards older data. The core value-add is pulling daily and keeping it **forever** in Supabase. Build the historical store from day one.
- **~2–3 day data lag.** Recent days fill in late — the reason for the 3-day re-pull (§6).
- **Anonymized queries.** Low-volume queries are suppressed for privacy and never appear. Handle "tracked, no data yet" (`no_data`) as a first-class state, and **do not confuse anonymization flicker with deindexing** (§7's "established baseline + sustained" rule exists precisely for this).
- **Average position ≠ rank.** Impression-weighted aggregate across devices/locations/time. Label it distinctly from the DataForSEO live check **everywhere** (§2, §8.5).
- **Query → page is many-to-many.** The page dimension returns one row per query×page, splitting metrics across pages. Totals won't reconcile against the query-level pull (GSC computes + anonymizes each grouping independently). Pick a canonical page (most clicks, else most impressions) for single-line views; keep the breakdown for detail / Pages.
- **No zero rows.** Zero-impression days return nothing, not a zero — the reason the date axis must be materialized (§5, §7).
- **Quotas.** 25k rows/request, `startRow` pagination, per-project QPS/daily limits; **separate** quota on URL Inspection.

---

## 10. Alerting

The reason a client cares about deindexing is that it costs them money **silently between logins** — so the alarm must leave the screen. The dashboard is for when they look; the alert is for when they don't.

### In-app alerting (built — 2026-06-23)

Delivered **in-app** (the channel decision; email stays deferred to the suite notifications service). The daily materialize job (`services/rank_materialize.py`) evaluates each keyword on its **primary source** and opens alerts in `rank_alerts` via `services/rank_alerts.py`. Four rules:

- **weekly_drop** — baseline (a week ago) in spots **1–15** and dropped **≥6 spots**.
- **page_one_exit** — was on **page 1** (≤10) a week ago, now **off it** (>10).
- **thirty_day_drop** — baseline (30 days ago) in **~top 20** and dropped **≥6 spots** (top-20 floor cuts deep-keyword noise).
- **deindexed** — reuses the `deindex_risk` signal (§7); GSC-only.

GSC paths compare **7-day rolling averages** (the position is a noisy decimal aggregate); DataForSEO paths compare weekly **point** ranks. The two sources are never mixed in a comparison (§2). **Episode model:** at most one *open* alert per (keyword, type) — opened on first occurrence, **auto-resolved** when the condition clears, so a flapping keyword doesn't spam. Surfaced in a per-client **Rankings → Alerts** tab with an unread badge (`OverviewResponse.unread_alert_count`); read/dismiss/read-all via `routers/rank.py`. Thresholds are conservative tunables (constants in `rank_alerts.py`).

> Email / Slack delivery remains a future option via the suite notifications service. The v0.2 spec's Telegram + n8n are not used.

---

## 11. Build plan

Phasing mirrors the v0.2 spec's milestones, mapped onto the suite. **M1 and M2 are built** (the scheduler decision that gated M2 is settled — see §6).

| Milestone | Scope | Status |
|---|---|---|
| **M1 — Connection (service account)** | `gsc_properties` table + migration (fold in `clients.gsc_property`, then deprecate it — see note). Settings onboarding screen showing the service-account email to add + a **"verify access"** button that runs a test `searchanalytics.query` and flips `access_status` (`pending`→`ok`/`no_access`). Pre-validates site_url format so a verify-time 403 means "not added" (§4). | **Built** |
| **M2 — Sync + storage** | Daily GSC query×date job → `gsc_query_daily`, `startRow` pagination, idempotent upserts, `sync_runs` observability, 3-day re-pull, the asyncio scheduler (§6), a manual "Sync now" trigger + last-sync status on the connection screen. | **Built** |
| **M3 — Materialize + status + UI** | Date-axis materialization → `rank_keyword_metrics` (NULL where absent), computed `status`, keyword CRUD on `tracked_keywords`, merged metrics read API, hero + dual-axis charts (hand-rolled SVG, no charting dep), sparklines with rendered gaps, the Overview triage list + Keywords wide table, the `no_data` state. | **Built** |
| **M4 — DataForSEO + detection + alerts** | **Built:** live "Today" rank (the fallback, see §2) + CPC/volume/competition (`keyword_market`) + estimated-monthly-value ROI; weekly query×page (`gsc_query_page_daily`) → `canonical_url` resolution + Pages view; striking-distance discovery; deindex gap detection + **URL Inspection confirmation** (`tracked_keywords.index_status`); **in-app rank-drop alerting** (`rank_alerts`, see §10). | **Built** |

### Migration note — `clients.gsc_property`
The existing `clients.gsc_property` column (migration `20260529220918_clients_suite_fields.sql`) is **folded into `gsc_properties`** in M1: the M1 migration backfills a `gsc_properties` row from any non-null `clients.gsc_property` (inferring `property_type` from the `sc-domain:` prefix), then the column is left deprecated (kept temporarily for safety, dropped in a follow-up migration once nothing reads it). A client can have **two** properties (url-prefix + domain), which a single column cannot represent — the table is the source of truth going forward.

---

## 12. Open / next up
- ~~**Shared scheduler mechanism** (suite Open Item #1)~~ — **decided 2026-06-22:** asyncio loop in platform-api enqueuing `async_jobs` (§6).
- **Competitive SERP Snapshot (built).** A diagnostic store captured **weekly**
  alongside the DataForSEO rank refresh (so a pre-drop baseline always exists),
  per tracked keyword: the AI Overview (presence/text/cited sources), the SERP
  feature inventory (local pack/GBP, PAA, forums, featured snippet, …), the query
  intent (DataForSEO Labs), and the top-10 organic results (url/domain/rendered
  title+description/position) each enriched with referring domains + URL Rating
  (DataForSEO Backlinks page rank 0–1000) — including the client's own ranking
  page. **Backend-only** (no viewer UI; retrieved on request via the API to
  diagnose drops). `services/serp_snapshot.py`; `serp_snapshots` +
  `serp_snapshot_results`; routes under `routers/rank.py`. RESERVED-table note in
  §5 (`rank_snapshots`) still stands — that is Module #5's geo-grid table, distinct
  from this `serp_snapshots` diagnostic store.
- **Reports (built).** On-demand + scheduled client reports. On-demand = a printable in-app view (browser Print → PDF). Scheduled = a per-client `rank_report_config` (as_needed / weekly+day / monthly+day / every 7·14·30 days); the shared scheduler enqueues a `rank_report` job when due, which snapshots the report data into a `rank_reports` archive (in-app list, each printable). **Delivery:** an optional **Google Doc** in the client's Drive folder — reuses the Apps Script publish webhook (renders the snapshot to Markdown via `render_report_markdown`); a per-client toggle (`deliver_google_doc`) auto-publishes scheduled/generated reports, and any saved report can be published on demand (`POST /rank-reports/{id}/publish`). Email delivery remains a future option via the notifications service.
- **Initial backfill** — M2 ships the recurring 3-day re-pull; a property's full 16-month history is pulled by calling the manual ingest endpoint with an explicit `start_date`/`end_date`. A one-click "backfill history" affordance is a small follow-up.
- Tunable thresholds: `deindex_risk` N (consecutive NULL days), the `volatile`/`dropping`/`climbing` band sizes — start conservative, expose as config later.
- DataForSEO "Today" tiering: which keywords are daily-priority vs weekly long-tail (cost driver).
- Estimated monthly value column = volume × CTR-at-target-position × CPC (turns the Keywords table into an ROI argument for client reviews) — post-M4 enhancement.
- Per-keyword detail view: full trendline + query×page breakdown (lands with M3/M4).
- Notifications service dependency: M4's alerting assumes the suite notifications service exists; if it isn't built yet, M4 alerting ships behind it.

---

## 13. Inheritance & cross-references
- **Suite decision log** (`docs/suite-architecture-and-roadmap-v1_0.md` §3): organic rank source = hybrid; GSC = service account; rank provider = DataForSEO; alerting = in-app + email/Slack. This module is the concrete realization of those rows.
- **CLAUDE.md:** stack (React+Vite/Netlify, FastAPI/Railway, supabase-py service role), RLS-via-service-role, snake_case/PascalCase conventions, "ask before adding scheduler/queue infra."
- **Source spec:** *Organic Rank Tracker — Build Spec v0.2* (the throwaway-mockup design doc this PRD graduates and supersedes for in-repo build).

---

## 14. Competitive SERP Snapshot (planned — not built)

A **dated, on-demand competitive snapshot** for a tracked keyword: the live SERP landscape plus per-page/per-domain authority signals for the client and the top-10 competitors. Stored so snapshots can be compared over time (same archive pattern as reports, §12). All data via **DataForSEO** — no new vendor; "UR"/"DR" use DataForSEO's 0–1000 `rank` metric as the URL-Rating / Domain-Rating equivalent.

### 14.1 Contents (per snapshot)
- **AI Overview (AIO)** — whether an AI Overview appears for the query + its cited sources.
- **Top 10 organic results** — position, URL, domain, title.
- **Query intent** — informational / commercial / transactional / navigational.
- **Per ranking page** (each top-10 competitor page **and** the client's ranking/canonical page): **referring domains** (page-level count) + **UR** (URL Rating).
- **Per domain** (each competitor domain **and** the client's domain): **Domain Rating (DR)** for the whole domain.

The client's ranking URL comes from the tracker's already-resolved `tracked_keywords.canonical_url` (or the client domain's position in the fetched SERP).

### 14.2 Data sources (DataForSEO — decisions locked)
| Field | Endpoint |
|---|---|
| AIO + top 10 | `serp/google/organic/live/advanced` (`ai_overview` + `organic` items) — reuse `services/dataforseo_rank.py` auth/SERP pattern |
| Query intent | DataForSEO Labs search-intent |
| Page **referring domains** + **UR** | `backlinks/summary/live`, **target = URL** → `referring_domains` + `rank` (UR) |
| Domain **DR** (+ domain referring domains) | `backlinks/summary/live`, **target = domain** → `rank` (DR) |

**Cost:** the Backlinks API bills **per target**. One snapshot ≈ ~10 competitor URLs + ~10 competitor domains + client URL + client domain ≈ **~22 backlink lookups per keyword** (batch as many targets per POST as the endpoint allows; still billed per item). Confirm the per-snapshot cost is acceptable before enabling broadly; consider a confirm step / not auto-scheduling.

### 14.3 Shape & UX (proposed)
- New table `serp_snapshots` — `(id, tracked_keyword_id → tracked_keywords(id), client_id, created_at, snapshot jsonb)`; RLS on, no client-facing policies (service-role only), per the suite pattern. `snapshot` JSON holds AIO, intent, the top-10 rows, and the per-page/per-domain authority numbers.
- On-demand **"SERP Snapshot"** action per tracked keyword (the Keywords table / keyword expansion) → builds + stores a snapshot → a read view rendering the landscape (top-10 table with UR/RD per page + DR per domain, AIO box, intent badge, client row highlighted). Dated archive per keyword for over-time comparison.
- Backend lives in `services/` + `routers/rank.py`; frontend in `components/rankings/`.

**Status:** spec only — confirm the per-snapshot DataForSEO cost + propose the data model before building.
