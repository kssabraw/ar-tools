# Geo-Grid Tracker — Module PRD (v1.0)

**Authored:** 2026-06-29 · **Status:** plan draft, **no code written yet** · **Module #5 (suite roadmap — Maps / local-pack ranker)**

> Read alongside **`docs/suite-architecture-and-roadmap-v1_0.md`** (the suite decision log this module inherits), **`docs/modules/organic-rank-tracker-prd-v1_0.md`** (Module #4 — the reporting/alerting/scheduler spine this document adapts), and **`CLAUDE.md`** (stack, conventions, RLS/service-role rule). Where this doc and the organic tracker PRD disagree on shared mechanics, the organic tracker is the source of truth for the *spine* (scheduler, report archive, Google-Doc delivery, notifications dependency) and this doc layers the geo-grid specifics on top.

---

## 0. Access note — what is locked vs. what must be reconciled

The user has stated that a **geo-grid scanning module already exists** (it tracks competitors) and asked that this PRD adapt the organic tracker's reporting + alerting to it. **That existing scanner is not in this repository (`kssabraw/ar-tools`)** — a thorough search found only GBP fetching, single-location maps top-10 checks (`writer/nlp-api/main.py` `_fetch_maps_top10`), and a "Maps Ranker — Coming soon" placeholder (`frontend/src/pages/ClientWorkspace.tsx`). The full scanner most likely lives in a **separate repo** (e.g. `showup-local`), which this session cannot read (GitHub access is scoped to `ar-tools`; the repo-add tools are unavailable here).

So this PRD splits cleanly into two halves:

| Half | Source of truth | Confidence |
|---|---|---|
| **Reporting, alerting, scheduling, report archive, Google-Doc delivery, data-access pattern, suite conformance** | Built in this repo (Module #4) — adapted here verbatim | **High — build as written** |
| **Grid geometry (shape, point count, radius/spacing, units) and competitor capture specifics** (§5.1, §6) | The **existing scanner module** the user referenced | **Proposed design — RECONCILE before build.** Marked ⚠️ throughout. |

The ⚠️ sections below are a concrete, suite-conformed proposal grounded in the DataForSEO Maps API's real capabilities (already wired into `nlp-api`). They are written so that, once the existing scanner's actual grid geometry and competitor model are confirmed (or its code is shared), only those parameters change — the reporting/alerting/scheduler scaffolding does not.

### Locked with the user (2026-06-29)
- **Grid center = the client's Google Business Profile** (`clients.gbp` lat/lng; `gbp_place_id` for self-identification in results).
- **Cadence = per-client configurable, reusing the report-schedule model** (`as_needed` / `weekly`+day / `monthly`+day / every 7·14·30 days) — same shape as `rank_report_config`.
- **Tracks competitors** (the module's defining feature vs. the organic tracker).
- **Rank/maps provider = DataForSEO** (suite decision log — the only maps/local-pack source; already wired).
- **No billing, internal-only, single-tenant** (no per-VA client scoping) — inherited suite-wide.

---

## 1. Product summary

A **per-client Geo-Grid Tracker** on each client's workspace. For a client's local keywords (e.g. "emergency plumber", "ac repair near me"), it runs a **grid of Google Maps / local-pack rank checks** across geographic points around the client's business, on a schedule. For each scan it answers three questions the organic tracker structurally cannot:

1. **Where does the client rank on the map, point by point** — local pack rank varies sharply by the searcher's location, so a single national/city rank is meaningless. The grid renders this as a heatmap.
2. **What is the client's local visibility, as one number** — aggregate metrics (Average Map Rank, Share of Local Voice, grid coverage) that roll the grid up into a trendable KPI.
3. **Who is beating them, and where** — the **competitors** holding the local pack at each point, so the report shows not just "you slipped" but "you slipped *to whom* and *in which neighborhoods*."

It is **Module #5 (Scheduled time-series + geo)** in the suite roadmap — Group B, Phase 1. It is the second consumer of the **shared scheduler** (after Module #4) and the second consumer of the **report archive + Google-Doc delivery** pattern. Its alerting feeds the same (planned) **suite notifications service**.

Not customer-facing. Internal agency use only. No billing.

---

## 2. The geo thesis (why a grid, not a rank)

The organic tracker (Module #4) treats rank as roughly location-stable: one tracked rank per keyword at a per-client *tracking location*. **Local-pack rank is the opposite** — Google ranks Maps results by proximity to the searcher, so a client can be #1 at their storefront and invisible three miles away. A single number hides exactly the thing a local SEO is paid to fix: the **shape and reach** of local visibility.

**Decision: a grid of point-level Maps checks, aggregated.** Each scan fans the same keyword across N grid points (each a distinct lat/lng), records the client's pack position at each point, and computes:

- **ARP — Average Rank Position:** mean of the client's rank across points where it appears (lower = better; the headline KPI).
- **SoLV — Share of Local Voice:** % of grid points where the client appears in the **top 3** local pack (the "money" positions). The single number clients understand fastest.
- **Coverage:** % of grid points where the client appears at all (in the scanned depth).
- **Competitor ARP / SoLV:** the same two numbers for each tracked/discovered competitor, so the report ranks rivals by local dominance.

The grid is centered on the **client's GBP** (locked) and each point is offset by the configured spacing (⚠️ §5.1). The DataForSEO Maps endpoint takes a single `location_coordinate` (lat/lng) per call, so **a scan = one DataForSEO Maps call per grid point per keyword** — the dominant cost driver (§7), exactly as the suite roadmap's Open Item #2 ("maps geo-grid density — primary driver of DataForSEO cost") anticipated.

This is the local-pack complement the organic tracker PRD explicitly defers to Module #5 (organic PRD §2: "True local-pack geo-grid tracking remains Module #5").

---

## 3. Suite-conformance: what this inherits vs. the existing scanner

This module **does not reinvent** the spine — it reuses Module #4's, the same way Module #4 reused `async_jobs` + `job_worker`.

| Concern | Reuse from Module #4 | Geo-grid delta |
|---|---|---|
| Scheduler | The asyncio loop in `services/gsc_scheduler.py` (suite Open Item #1, decided) — add `enqueue_due_geogrid_scans()` + `enqueue_due_geogrid_reports()` passes | New job types `geogrid_scan`, `geogrid_report` on `async_jobs` |
| Job execution | The existing `job_worker` | New handlers in `services/geogrid_*` |
| Report schedule | `rank_report_config` model verbatim (mode / day_of_week / day_of_month / interval_days / deliver_google_doc / last_generated_at) | A sibling `geogrid_report_config` (same columns) — keeps maps + organic schedules independent per client |
| Report archive | `rank_reports` (snapshot jsonb + Google-Doc fields) | A sibling `geogrid_reports` (same shape; snapshot holds grid + competitor data) |
| Report render → Doc | `render_report_markdown` + `publish_report_doc` (Apps Script webhook, `{folder_id, title, content}`) | A `render_geogrid_report_markdown` (heatmap rendered as a per-point table + ARP/SoLV summary + competitor table) |
| Alerting | The suite notifications service dependency (organic PRD §10) | Geo-grid-specific triggers (§9) — ARP/SoLV drop, competitor overtaking, points falling out of the pack |
| Data access | RLS on, **no client-facing policies**, service-role only, API-layer `client_id` authorization | Identical |
| Stack | React+Vite/Netlify, FastAPI/Railway, supabase-py service role, hand-rolled SVG (no charting dep) | The heatmap is a hand-rolled SVG/CSS grid — same "no new charting dep" rule |

⚠️ **From the existing scanner (reconcile before build):** the actual grid geometry (§5.1), how competitors are captured/identified (§6), and whether competitors are a fixed tracked set or discovered per-scan. The proposals below are the default if the existing module isn't available at build time.

---

## 4. Grid center & local keywords

### 4.1 Center — the client's GBP (locked)
The grid centers on the client's Google Business Profile, already fetched and stored on `clients.gbp` (see `GbpProfile` — `latitude`, `longitude`, `gbp_place_id`, `business_name`). This means:

- **Center = `clients.gbp.latitude` / `clients.gbp.longitude`.** No new geocoding — reuse the GBP service (`services/gbp_service.py`).
- **Self-identification in results = `gbp_place_id`** (exact match), with a `business_name` significant-token fallback — the **same match logic already proven** in `nlp-api` `_fetch_maps_top10` (place_id exact → all-significant-tokens fuzzy). Port that matcher; don't re-derive it.
- **Precondition:** a client with no GBP cannot be grid-tracked. Settings surfaces "Connect a Google Business Profile to enable geo-grid tracking" and links to the existing GBP resolve/auto-fetch flow (`/clients/gbp/resolve`).

### 4.2 Keywords
Local keywords are user-defined per client (CRUD, open to any authenticated team member — same access stance the organic tracker landed on). Kept in a **dedicated `geogrid_keywords` table** rather than overloading the organic tracker's `tracked_keywords` (which is client-anchored and organic-only) — maps scans, cadence, and cost are different enough that mixing them invites the GSC/DataForSEO source-confusion the organic PRD warns against. CSV import mirrors the organic tracker's keyword upload.

---

## 5. Data model

All tables via migrations in `writer/supabase/migrations/`. **RLS enabled on every table, no client-facing policies** (service-role only) — the `async_jobs`/Module-#4 pattern. Authorization is API-layer `client_id` filtering.

```
clients(id, name, gbp jsonb, gbp_place_id, ...)   -- exists. GBP supplies grid center + self-match.

geo_grids(                                          -- ⚠️ geometry RECONCILE w/ existing scanner (§5.1)
  id, client_id → clients(id),
  center_lat, center_lng,                           -- defaulted from clients.gbp; overridable
  shape          check in ('square','circle')  default 'square',
  size           integer  default 7,                -- N (an N×N grid → N² points)
  radius_value   numeric,                           -- distance from center to edge
  radius_unit    check in ('mi','km')  default 'mi',
  active         boolean default true,
  created_at, updated_at
)
  -- One active grid per client (multiple allowed for A/B service-area tests). Points are
  -- DERIVED from center+shape+size+radius at scan time (not stored as rows) so geometry
  -- edits don't orphan history; each scan records the geometry it used (geogrid_scans.geometry).

geogrid_keywords(
  id, client_id → clients(id),
  keyword,
  active         boolean default true,
  created_at, updated_at
)
  -- Local keywords to grid-scan. CRUD + CSV import. Open to any authenticated team member.

geogrid_scans(                                       -- one row per (keyword, scan run)
  id, keyword_id → geogrid_keywords(id), client_id → clients(id),
  grid_id → geo_grids(id),
  scanned_at,
  geometry       jsonb,                              -- {center, shape, size, radius, unit} snapshot
  point_count    integer,                            -- N² actually scanned
  -- computed aggregate KPIs (the trendable headline numbers):
  arp            numeric,                            -- Average Rank Position (client), null if absent everywhere
  solv           numeric,                            -- Share of Local Voice: % points in top-3
  coverage       numeric,                            -- % points where client appears at all
  found_points   integer,                            -- # points client appeared in
  status         text,                               -- computed (§8): improving/stable/slipping/lost/no_data
  created_at
)
  -- THE TREND AXIS for the grid: one summary row per keyword per scan. ARP/SoLV/coverage
  -- over scans drives the trendlines + status, the same role rank_keyword_metrics plays for #4.

geogrid_points(                                      -- one row per grid point per scan
  scan_id → geogrid_scans(id),
  point_index    integer,                            -- 0..N²-1, row-major from NW
  lat, lng,
  client_rank    integer,                            -- client's pack position at this point, null = absent
  pack           jsonb,                              -- ordered top-K maps items at this point (§6)
  PK (scan_id, point_index)
)
  -- The heatmap source: client_rank per cell. `pack` carries the ranked competitors at that
  -- cell for competitor analysis + the "who beat us here" view.

geogrid_competitors(                                 -- ⚠️ capture model RECONCILE (§6)
  id, client_id → clients(id),
  place_id,                                          -- DataForSEO maps place_id (stable identity)
  name, domain,
  tracked        boolean default false,              -- pinned by the team vs. auto-discovered
  first_seen_at, last_seen_at,
  created_at
)
  -- Competitor registry. Auto-upserted from scan packs; team can pin (tracked=true) the ones
  -- they want on every report. ARP/SoLV per competitor are computed from geogrid_points.pack.

geogrid_report_config(client_id PK → clients(id),    -- mirrors rank_report_config exactly
  mode check in ('as_needed','weekly','monthly','interval') default 'as_needed',
  day_of_week, day_of_month, interval_days,
  deliver_google_doc boolean default false,
  last_generated_at, updated_at)

geogrid_reports(id, client_id → clients(id), title,  -- mirrors rank_reports exactly
  snapshot jsonb,                                     -- full grid + competitor data as-of generation
  doc_id, doc_url, delivered_at, created_by, created_at)
```

### 5.1 ⚠️ Grid geometry — proposed default (RECONCILE with existing scanner)
Until the existing module's geometry is confirmed, build to these defaults, all **configurable per client** in Settings:

- **Shape:** square grid (industry standard; circle is a post-v1 mask over the square).
- **Size:** `7×7 = 49 points` default; allow `3×3` (9), `5×5` (25), `7×7` (49), `9×9` (81). Size is the direct cost multiplier (§7).
- **Radius:** default `5 mi` center-to-edge; configurable in mi/km. Point spacing = `2·radius / (size−1)`.
- **Point derivation:** offset each cell from the GBP center using a simple equirectangular approximation (`Δlat = meters/111_320`, `Δlng = meters/(111_320·cos(lat))`) — accurate at metro scale, no geo library needed.

These four parameters are the **only** things that change if the existing scanner differs; everything downstream (scan loop, aggregation, heatmap, report) is parameter-driven off `geo_grids` + `geogrid_scans.geometry`.

---

## 6. ⚠️ Scanning & competitor capture (RECONCILE with existing scanner)

**The scan loop (per `geogrid_scan` job for one keyword):**
1. Load the client's active `geo_grids` row; derive the N² points from center+size+radius.
2. For each point, call DataForSEO Maps `serp/google/maps/live/advanced` with that point's `location_coordinate` (`"lat,lng"`), `keyword`, `depth` (≥ pack depth wanted, e.g. 20), `language_name`. **This is the exact endpoint + payload already used in `nlp-api` `_fetch_maps_top10`** — lift its request/parse code, batch points concurrently with a bounded semaphore.
3. For each point: find the client by `gbp_place_id` (exact) → `business_name` tokens (fuzzy) → record `client_rank` (null if absent in depth); store the ordered top-K items as `geogrid_points.pack` (`place_id`, `title`, `domain`, `rank`).
4. Upsert every distinct competitor seen across points into `geogrid_competitors` (by `place_id`); stamp `last_seen_at`.
5. Compute `arp` / `solv` / `coverage` / `found_points` over the points; write the `geogrid_scans` row; compute `status` (§8).

**Competitor model (proposed):** competitors are **auto-discovered** from the packs every scan and registered in `geogrid_competitors`; the team can **pin** a subset (`tracked=true`) to guarantee them a row on every report even when they don't appear that scan. Per-competitor ARP/SoLV are computed on demand from `geogrid_points.pack` — no separate per-competitor scan needed (their ranks are already in the same Maps responses the client's rank came from — **competitors are free** within a scan). This is the key efficiency: tracking competitors costs **zero extra DataForSEO calls**.

> ⚠️ If the existing scanner instead uses a **fixed competitor list** the user maintains, or a different identity key than `place_id`, adjust `geogrid_competitors` + the pin model accordingly. The auto-discover-and-pin model above is the default.

---

## 7. Scan jobs, cadence & cost

All jobs run on the **suite shared scheduler** (`services/gsc_scheduler.py` — add the passes below) and execute via the existing `job_worker`.

| Job | Cadence | Notes |
|---|---|---|
| `geogrid_scan` | Per-client configurable (see report cadence) — one job **per keyword per due client** | The cost center. Cost ≈ `keywords × N² points` DataForSEO Maps calls per scan. A 49-point grid × 10 keywords = 490 calls/scan. Bound concurrency; surface estimated call count in Settings before saving a grid size. |
| `geogrid_report` | Per-client `geogrid_report_config` due-logic (reuses `is_report_due`) | Snapshots the latest scans into `geogrid_reports`; optional Google-Doc delivery. |

**Scheduler additions (`services/gsc_scheduler.py`):**
- `enqueue_due_geogrid_scans()` — for each client with active `geogrid_keywords` whose `geogrid_report_config` (or a dedicated scan cadence) is due today, enqueue one `geogrid_scan` per active keyword (dedupe on pending/running per keyword, exactly like `_has_pending_ingest`).
- `enqueue_due_geogrid_reports()` — mirror `enqueue_due_reports()` against `geogrid_report_config`.

> **Cost guardrail (suite Open Item #2 — "maps geo-grid density"):** grid size is the multiplier. Default 7×7; show the per-scan call estimate (`keywords × size²`) and an approximate $ figure in Settings, and **never auto-schedule a grid larger than 7×7 without an explicit confirm** — the same "confirm cost before enabling broadly" stance the organic PRD took for the Backlinks-API SERP snapshot (§14.2). `as_needed` is the safe default.

---

## 8. Status taxonomy (computed per scan)

Adapts Module #4's computed-status idea to grid KPIs. Computed when each `geogrid_scans` row is written, from the trend of `arp`/`solv`/`coverage` vs. the prior scans:

- `improving` — ARP falling (rank getting better) or SoLV rising past a band
- `stable` — holding within a band
- `slipping` — sustained ARP rise / SoLV fall, still present
- `lost` — was present (had coverage), now absent across the grid (the local-pack analog of `deindex_risk`)
- `no_data` — never appeared (tracked/aspirational, awaiting first presence)

These are the sort/filter keys for the keyword triage (§10) and the alert triggers (§9).

---

## 9. Alerting (suite notifications service)

Same dependency and rationale as the organic tracker (organic PRD §10): the alarm must leave the screen because local visibility erodes silently between logins. Routes through the **suite notifications service** (in-app feed + email/Slack) — **not** Telegram/n8n. Geo-grid-specific triggers, configured per client in an `Alerts` tab:

- **ARP drop** — average map rank worsens by ≥ threshold positions scan-over-scan.
- **SoLV drop** — share of local voice falls by ≥ threshold % (e.g. lost the top-3 in a chunk of the grid).
- **Coverage collapse / `lost`** — client disappears from a sustained share of points after established presence (the deindex-analog).
- **Competitor overtaking** — a competitor's ARP crosses below (beats) the client's, or a new competitor enters the top-3 in ≥ threshold points.

Like Module #4's alerting, this **ships behind the notifications service** — if that service isn't built when the rest of this module is, the triggers and `Alerts` config land but delivery is gated on it. (Suite roadmap: notifications service + Ranking-drop agent #6 are the downstream consumers; the drop agent reasons over #4 **and #5**.)

---

## 10. UI / UX

Tabs inside the per-client workspace (the "Maps Ranker" card placeholder in `ClientWorkspace.tsx` becomes this), React + Vite, TanStack Query, **hand-rolled SVG/CSS** (no charting dep — same rule as #4).

- **Overview** — client-level local health: ARP / SoLV / Coverage KPI cards, the **heatmap** for a selected keyword (the signature view — an N×N grid of cells colored by `client_rank`: green top-3 → yellow → red → grey "absent"), and a lean keyword triage list (keyword + SoLV + ARP + Δ + status).
- **Keywords** — full table: per-keyword ARP / SoLV / coverage / status + sparkline of SoLV over scans; row expansion → the heatmap + the per-point competitor packs ("who beat you here").
- **Competitors** — the registry: each competitor's ARP / SoLV across the grid, ranked by local dominance; pin/unpin (`tracked`). This is the module's differentiator — the organic tracker has no competitor view.
- **Reports** — schedule (reuse the `RankReports.tsx` component shape: as_needed / weekly+day / monthly+day / every 7·14·30 days + Google-Doc toggle) + the generated-reports archive (printable, like `RankReport.tsx`).
- **Settings** — GBP-center confirmation, grid geometry (shape/size/radius/unit — ⚠️ §5.1) with the live per-scan **cost estimate**, keyword CRUD + CSV import, scan cadence.

### Heatmap (the one chart that matters)
A square SVG/CSS grid, one cell per point, positioned row-major from the NW corner, each cell colored by `client_rank` band (1–3 / 4–10 / 11–20 / absent) with the numeric rank on hover. The client's storefront marker sits at center. This is the artifact clients react to — it makes "you're #1 at your door but invisible across town" obvious at a glance, and it's what the report (and Google Doc, rendered as a per-point table) reproduces.

---

## 11. Build plan

Mirrors Module #4's milestone shape; the spine milestones (scheduler, report archive, Doc delivery) are **adaptations of already-built code**, so they're fast.

| Milestone | Scope | Notes |
|---|---|---|
| **M1 — Grid + keywords** | `geo_grids` + `geogrid_keywords` migrations; Settings: GBP-center confirm, geometry config (⚠️ §5.1) with cost estimate, keyword CRUD + CSV import. Port the GBP self-match from `nlp-api` `_fetch_maps_top10`. | Gated on a connected GBP. |
| **M2 — Scan + storage** | `geogrid_scans` + `geogrid_points` + `geogrid_competitors`; the `geogrid_scan` job (point fan-out over DataForSEO Maps, concurrency-bounded), ARP/SoLV/coverage compute, competitor upsert; scheduler `enqueue_due_geogrid_scans()`; a manual "Scan now" trigger + last-scan status. | The DataForSEO Maps call is already proven in `nlp-api`. |
| **M3 — Heatmap + triage + competitors** | Overview heatmap, Keywords table + SoLV sparklines + per-point competitor packs, the Competitors tab (ARP/SoLV per rival, pin/unpin), computed `status`. | Hand-rolled SVG/CSS, no charting dep. |
| **M4 — Reports + alerts** | `geogrid_report_config` + `geogrid_reports` (mirror #4), snapshot builder, `render_geogrid_report_markdown`, Google-Doc delivery via the Apps Script webhook, scheduler `enqueue_due_geogrid_reports()`; alert triggers (§9) behind the notifications service. | Reuses `rank_report.py` patterns near-verbatim. |

---

## 12. Open / next up
- ⚠️ **Reconcile grid geometry + competitor model with the existing scanner** (§0, §5.1, §6) — the one true blocker; everything else can build on the proposed defaults.
- **Scan cadence vs. report cadence** — proposed: one `geogrid_report_config` drives both (a scan precedes each report). Decide whether scans should run *more often* than reports (e.g. weekly scans, monthly reports) — if so, split into a `geogrid_scan_config`. Default: shared.
- **Grid density default + cost ceiling** (suite Open Item #2) — confirm 7×7 / 5 mi defaults and the auto-schedule size cap with the user once real per-call DataForSEO cost is known.
- **Notifications service dependency** — §9 alerting ships behind it (shared with Module #4 and the Ranking-drop agent #6).
- **Multiple service areas** — `geo_grids.active` allows >1 grid per client (e.g. two storefronts); v1 can ship single-grid and expand.
- **Historical comparison in the heatmap** — scan-over-scan cell diffs (gained/lost points) — post-M3 enhancement.

---

## 13. Inheritance & cross-references
- **Suite decision log** (`docs/suite-architecture-and-roadmap-v1_0.md`): Module #5 = Maps/local-pack ranker, **DataForSEO geo-grid**, scheduled time-series + geo, Phase 1; rank provider = DataForSEO (only maps source); alerting = in-app + email/Slack; Open Item #2 = maps geo-grid density. This module realizes those rows.
- **Organic Rank Tracker PRD** (`organic-rank-tracker-prd-v1_0.md`): the spine — scheduler (`gsc_scheduler.py`), report archive + schedule model (`rank_report_config` / `rank_reports`), Google-Doc delivery (`render_report_markdown` / `publish_report_doc`), notifications dependency, the "computed status" and "no new charting dep" conventions. Adapted here, not duplicated.
- **`nlp-api` `_fetch_maps_top10`** (`writer/nlp-api/main.py`): the proven DataForSEO Maps request/parse + GBP self-match (place_id → significant-token fuzzy) to port into the scan loop.
- **CLAUDE.md:** stack, RLS-via-service-role, "ask before adding scheduler/queue infra" (reuse the asyncio loop — don't add new infra), snake_case/PascalCase conventions.
- **Existing geo-grid scanner** (external repo, not in `ar-tools`): the authority for ⚠️ §5.1 and §6 — reconcile before building those parts.
