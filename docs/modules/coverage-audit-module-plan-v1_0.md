# Coverage Audit — Location & Service Gap Finder (Module Plan v1.0)

> **Working name:** "Coverage Audit" (module slug `coverage_audit`). Rename freely before Phase 0 lands — the slug is easy to change now, expensive later.
>
> **Status:** plan / not built. This is the design authority; owner decisions are in §0.

## 1. What this is

A per-client module that **scans a client's current site as it stands**, infers which service and location pages already exist, computes the *ideal* coverage universe across four tiers, diffs ideal-vs-actual to surface gaps (missing service pages, missing location pages, missing service×location pages), ranks the gaps by real search demand, and **auto-seeds a Service×Location Matrix per tier** so the recommendations are one click from execution.

It answers, per client: *what cities should have their own page, what services, what service+location combos — plus CDPs and neighborhoods — that don't exist yet, ranked by whether they're worth building.*

**It is not a new generator.** Most of the machinery already exists in the Local SEO module (site scanning, existing-page matching, the city/neighborhood universe, the service-variation planner, and the whole Service×Location Matrix with generation/drip-release/bulk-publish). This module is the **inference + diff + demand-ranking layer** that inverts the Plan Silo (which starts from a seed you type) into a whole-site audit, and pipes the result into the Matrix. The reuse is near-total for **Tier 1**; **Tier 3 (CDP enumeration)** and the **neighborhood decision gate (Phase 5)** are genuinely new engineering, not thin glue — see §8.

## 0. Owner decisions (locked 2026-09-13)

1. **Tiered rollout.** Build and ship tier by tier, T1 first. The audit *output* is also tiered (recommendations grouped/ordered by tier).

   | Tier | Location granularity | Service granularity | Matrix |
   |---|---|---|---|
   | **1** | Cities | Main services | city × main-service |
   | **2** | Cities | Subservices | city × subservice |
   | **3** | CDPs | Main services | CDP × main-service |
   | **4** | CDPs | Subservices | CDP × subservice |

2. **Service axis = auto-derive, team edits.** Main services auto-derived from the site's classified service pages + GBP categories + the planner, presented for the team to confirm/edit. **GBP categories are business-type taxonomy values ("Roofing contractor"), not service phrases ("roof restoration")** — they seed the list and are expanded, never read as the service axis directly. Subservices from the Local SEO planner's variation expansion (`_generate_service_pages`), which emits per-city pages — so the city-agnostic subservice *axis* is derived by running it once for a representative city and stripping/deduping the city (see §3.1 note + Phase 2).
3. **CDPs = authoritative Census list.** Per service-area county from census.gov, geocode-verified against the service area. CDPs are a first-class location tier, distinct from neighborhoods. **This is a new integration, not a reuse** — the existing LeadOff census code shares only the *host and access pattern* (TIGERweb ArcGIS REST, worker-reachable) but queries the block-group layer; enumerating CDPs is a new query against the Places/CDP layer plus service-area→county-FIPS resolution, buildable/testable **only on the deployed worker** (census.gov is egress-blocked from the sandbox). See §8.
4. **Neighborhoods = own-page vs. fold-into-city, decided by demand + SERP evidence.** Two-stage gate: batch DataForSEO volume for `"[main service] [neighborhood]"` first (cheap), then a live SERP **only on the volume survivors** to check whether *dedicated* neighborhood pages actually rank vs. city pages. Default = fold into the city page's "areas we serve" section.
5. **Auto-seed the Matrix — axes only.** Each tier maps to one `local_seo_matrix` (axes = that tier's service list × location list). The audit seeds the **axes**; the Matrix's own `mark_coverage` owns per-cell present/absent (it re-scans the live site on create/reconcile), so the audit **never persists a second coverage verdict** (see §8, Major #1). The audit's own diff exists only to build the demand-ranked gap **report** — the review screen. Execution, sibling links, drip-release, and bulk-publish come free from Matrix Phases 0–5.
6. **Separate client-workspace card + its own page.** Coverage Audit is its own dashboard card and a standalone `/coverage-audit` page (route `clients/:id/coverage-audit`), **not** a tab inside the Local SEO tool — it spans the whole site, not one seed. It deep-links *into* Local SEO / the Matrix for execution.

## 2. Reuse map — what already exists

| Need | Reuse | Where |
|---|---|---|
| Scan site as-is | `discover_site_urls` (sitemap → robots → DataForSEO `site:` fallback) | `services/site_page_index.py:415` |
| Split a page's tokens into service vs place + exclude blog/product | `content_tokens` + the blog-slug detector (`is_blog_url`) — all platform-side (nlp-api's `classify_page_type` is cross-service and **not** used, see §8) | `services/site_page_index.py` |
| Existing-page match by content-word-set (incl. national/city-less service page) | `build_page_token_index` / `match_site_page_for_keyword` / `match_site_service_page`, `content_tokens` | `site_page_index.py:193/203/221` |
| City universe (seed + GBP service area + manual + site place-names + nearby via Overpass, geocode-verified, capped) | `resolve_target_cities` | `services/target_cities.py:83` |
| Per-city neighborhoods (LLM propose → geocode containment) | `_neighborhoods_for_city`, `place_is_within_city`, `maps_geocode.forward_geocode_places` + `geocode_forward_cache` | Local SEO silo planner, `services/maps_geocode.py` |
| Service-variation expansion (main → subservices) | `_generate_service_pages` | Local SEO silo planner |
| GBP categories (a **seed** for main services, not the axis — see §0.2) | `clients.gbp` (primary + additional categories) | client row |
| Demand data (volume / CPC / competition, cross-client cached) | `keyword_market.py` | `services/keyword_market.py` |
| Live SERP (for neighborhood evidence) | `serp_snapshot.fetch_serp` + parsers | `services/serp_snapshot.py` |
| Census **host + ArcGIS-REST access pattern** (worker-reachable) — *pattern reuse only; the CDP-layer query itself is new, see §3.2/§8* | TIGERweb (`tigerweb.geo.census.gov`, used by `census_demand.py` for block groups), address geocoder (`leadoff_geocode.py`), `leadoff_counties` for county names | LeadOff services |
| Persisted N×M grid + gap-fill + generate + drip-release + bulk-publish + sibling links | **Service×Location Matrix** (Phases 0–5) | `services/local_seo_matrix*.py`, `routers/local_seo_matrix.py` |
| Marking targets found / on_site / missing | Plan Silo `_to_items` + #951/#953 matching | `services/local_seo_service.py` |
| Paid-call meter pattern (daily budget + reserve RPC) | `keyword_research_usage` / `domain_intel_usage` | mirror it as `coverage_audit_usage` |

## 3. The genuine delta (what's new)

1. **Whole-site inference (`services/coverage_audit.py`, pure).** Invert the Plan Silo: derive both axes from reality instead of a typed seed.
   - `classify_site_pages(urls, place_vocab)` → per URL, split content tokens into service-tokens vs place-tokens (place-tokens = intersection with the resolved location universe names) and bucket into `service_only` / `location_only` / `service_location` / `other` (blog/product excluded via the existing blog-slug detector).
   - `build_coverage_grid(service_axis, location_axis, site_index, in_tool_index)` → mark each cell `present` (site match OR an in-tool `local_seo_pages`/matrix page exists) / `absent`. **This grid feeds the report/ranking only — it is NOT written back to the Matrix as cell state; the Matrix's `mark_coverage` recomputes coverage itself on seed (see §8, Major #1).** Standalone service pages = the service-axis (city-less) pages; standalone location pages = the location-axis (city/CDP hub) pages; combos = the cells. (Open definitional point: what keyword represents a bare "location hub" page — see §7.)
   - `diff_coverage(...)` → `{missing_services, missing_locations, missing_cells}` per tier.
   - `rank_gaps(gaps, market, min_volume)` → attach volume/CPC/est-value + an opportunity score (reuse the keyword-research scoring shape), ordered, and **apply a minimum-demand floor** (`coverage_cell_volume_min`): cells below the floor are collapsed/hidden, not just sorted last (mirrors the neighborhood gate — see §8, Major #4). Ranking alone does not tame Tier 3/4's cross-product tail.
   - All pure, unit-tested; no external calls in the core (callers pass in the scanned index + market data).

2. **Census CDP source (`services/census_cdp.py`) — new integration, worker-only.** (a) Resolve the service area to its county FIPS set (reverse-geocode each resolved city/anchor → county via the census geocoder / `leadoff_counties`); (b) query the **TIGERweb Places / CDP layer** (a *different* ArcGIS-REST layer than `census_demand.py`'s block-group layer, same `tigerweb.geo.census.gov` host) for CDPs in those counties; (c) geocode-verify containment within the service-area footprint (reuse `maps_geocode` + `place_is_within_city`); cache like `geocode_forward_cache`. **census.gov is egress-blocked from the sandbox, so this is built and tested only on the deployed worker** (as with `census_demand.py`). Best-effort: no key / dead source / no counties resolved → CDP tiers degrade with a note, never abort.

3. **Neighborhood decision layer (`services/neighborhood_gate.py`, pure decision + impure two-stage runner).**
   - Stage 1 — batch DataForSEO volume for `"[primary main service] [neighborhood]"` across candidates; drop below `coverage_neighborhood_volume_min`.
   - Stage 2 — live SERP **only on survivors**; `has_dedicated_neighborhood_pages(serp, place)` (pure) checks whether ≥ `coverage_neighborhood_serp_dedicated_min` of the top organic results carry the place token in URL/title (a dedicated page) vs. being city pages.
   - Output per neighborhood: `{decision: own_page | fold_into_city, volume, serp_evidence, city}`. `fold_into_city` neighborhoods feed the city page's "areas we serve" list (the writer already renders that section — pass the list through the matrix cell / page context).

4. **The audit run + report (`services/coverage_audit_service.py`, `routers/coverage_audit.py`, `pages/CoverageAudit.tsx`).** Persisted run (per-tier gaps + resolved axes + provenance) as a cheap re-read; per-tier gap tables (demand-ranked) with "Seed matrix" / "Create page" / "Edit service axis" actions deep-linking into Local SEO + the Matrix. **Runtime is decomposed to survive the 30-min stale-job reaper** (`job_worker.py`, `job_stale_timeout_minutes`=30 — jobs that graze it get reaped + requeued; a `stale_timeout_for` per-type override exists): rather than one long `coverage_audit` job, run **one job per tier**, and keep every paid step (demand batch, neighborhood volume, neighborhood SERP) **idempotent/cached** so a requeue never re-bills. Each paid step reserves through the meter before spending. See §8, Major #3.

## 4. Data model (proposed)

- `coverage_audits` — one run per client: `{client_id, status, tiers_run int[], service_axis jsonb, location_axis jsonb, gaps jsonb (per-tier), provenance jsonb, created_at, error}`. jsonb-heavy so re-opening a run is a read, like `keyword_research_runs`.
- `coverage_audit_usage` + `reserve_coverage_audit_calls` RPC — daily paid-call meter (mirror `keyword_research_usage`).
- `census_cdp_cache` (or reuse `geocode_forward_cache` keyed by CDP query) — per-county CDP list, freshness-bounded.
- `async_jobs` type `coverage_audit` (widen the live CHECK).
- Matrices seeded from a run reuse the existing `local_seo_matrices` / `local_seo_matrix_cells` — **no new execution model.**

No schema for standalone/service/location pages — those are the matrix axes and existing `local_seo_pages`.

## 5. Cost & guardrails

- **Paid calls per run:** demand volume batch (`keyword_market`, cross-client cached — cheap on repeat), neighborhood Stage-2 SERP (bounded to volume survivors), CDP geocoding (cheap + cached). All metered through `coverage_audit_usage` with a free `estimate` preflight (mirror keyword-research). **Every paid step reserves before spending and is idempotent/cached**, so a reaper requeue (below) never re-bills.
- **Job duration vs. the reaper:** the whole-site, 4-tier audit must not run as one job — the stale-job reaper (`job_worker.py`, 30-min default) reaps + requeues a long job, restarting paid work. Decompose into **one job per tier** (the Local SEO bulk lesson); a single tier that legitimately needs longer gets a `stale_timeout_for` override rather than an unbounded job.
- **Grid explosion:** cities × CDPs × subservices can reach thousands of cells. Three defenses: a **minimum-demand floor** on the cell gaps (`coverage_cell_volume_min`, §3.1 — zero/near-zero-volume cells are hidden, not just ranked last; this is what actually tames Tier 3/4, not ranking alone), demand ranking on what clears it, and the Matrix's **200-page sign-off gate** (`website_plan.MATRIX_SIGNOFF_THRESHOLD` = 200) at seed/generate time. The audit report shows the count and the sign-off before any generation.
- **Best-effort everywhere:** a dead source degrades that slice with a **visible** note and never aborts the audit. In particular, without `GOOGLE_MAPS_API_KEY` `resolve_target_cities` returns only the seed city, so the location universe silently collapses — the report must surface "geocoding unavailable — limited to the seed city" rather than showing an empty axis as if it were complete. (The key is set on PLATFORM; this guards misconfigured envs.)

## 6. Tiered phasing (build order)

- **Phase 0 — foundations.** `coverage_audit.py` pure core (site classification via `content_tokens`/`is_blog_url` + coverage grid + diff + demand-floored ranking), the `coverage_audits` run table + `coverage_audit_usage` meter + a **per-tier** async job type, config block (incl. `coverage_cell_volume_min`). Unit-tested against fixtures; no UI. *(No external calls in the core.)* Decides the axes-only Matrix seed contract (Major #1) up front.
- **Phase 1 — Tier 1 (city × main-service).** Service-axis auto-derive (site service pages + GBP-category seed + planner) + team-edit endpoint; location axis via `resolve_target_cities` (with the geocoding-unavailable degraded note); diff + demand rank; auto-seed a T1 matrix **axes only** (Matrix `mark_coverage` owns cells); `pages/CoverageAudit.tsx` + a **separate client-workspace "Coverage Audit" card** and `/coverage-audit` route (§0.6). **This is the shippable core** — the most valuable tier on its own.
- **Phase 2 — Tier 2 (city × subservice).** Planner variation expansion per confirmed main service; **derive a city-agnostic subservice axis** (one representative-city call → strip/dedupe the city, since `_generate_service_pages` emits per-city pages) → city × subservice matrix.
- **Phase 3 — Tier 3 (CDP × main-service) — new census integration, worker-only.** `census_cdp.py`: service-area→county-FIPS resolution → TIGERweb Places/CDP-layer query → geocode-verify → CDP location axis → CDP × main-service. Built/tested on the worker (sandbox egress-blocked).
- **Phase 4 — Tier 4 (CDP × subservice).** Cross the CDP axis with the subservice axis; the demand floor matters most here.
- **Phase 5 — Neighborhoods (cross-cutting).** The two-stage demand+SERP decision layer + fold-into-city wiring (own-page neighborhoods become matrix location rows; folded ones feed the city page's areas-we-serve list). Applies to every location tier.

Each phase ships a working audit for its tier and its matrix seed; nothing is stubbed waiting on a later phase.

## 7. Open items / to grill before Phase 0

- ~~**Where the report lives**~~ — **RESOLVED (§0.6):** separate client-workspace card + standalone `/coverage-audit` page, not a Local SEO tab.
- **Module name** — confirm "Coverage Audit" or pick another (owner left as-is for now).
- **Location-hub keyword** — what keyword represents a bare "location page" for the standalone location-page gap? (`/melbourne/` → `{melbourne}`, but a city page is usually targeted as `"[primary service] [city]"`.) Define before Phase 1's `build_coverage_grid` treats location-axis pages.
- **Service-axis confirmation UX** — auto-derived main services need a review/edit screen before the diff runs; does an unconfirmed axis block the audit, or run on the auto-derived set with a "confirm to refine" banner?
- **Refresh cadence** — on-demand only for v1, or a scheduled re-audit (monthly) like GSC Research? (The site changes as pages ship, so a re-audit should show shrinking gaps.)
- **CDP county scope** — all counties the service area touches, or only counties with a geocode-verified CDP inside the footprint? (Bounds the Census pulls.)
- **`coverage_cell_volume_min` + `coverage_audit_usage` daily ceiling** — set real numbers once the DataForSEO budget is known (placeholders like the domain-intel 200/day; the volume floor calibrated from a first live run).

## 8. Adversarial-review findings & resolutions (2026-09-13)

An adversarial-review pass grounded every §2/§3 reuse claim against the live code. The Tier-1 core held (the Matrix seed path, `resolve_target_cities`, the `site_page_index` matchers, `MATRIX_SIGNOFF_THRESHOLD`=200, `_generate_service_pages`/`_neighborhoods_for_city`/`place_is_within_city`/`fetch_serp` all exist as described). The four **Major** findings below are now **fixed in-plan** (owner: "fix all"); the Minor/Advisory corrections are folded into the sections cited.

**Major #1 — audit must not double-mark coverage.** `create_matrix` (`local_seo_matrix_store.py:284`) already calls `mark_coverage` on seed, re-scanning the live site; the earlier "cells pre-marked from the audit diff" was a second, divergence-prone source of truth. **Fixed:** §0.5/§3.1 — audit seeds **axes only**; its grid feeds the report/ranking, never the Matrix's cell state.

**Major #2 (CDP) — "reuse the census infra" understated a new, worker-only build.** `census_demand.py:40–244` queries only the TIGERweb block-group layer; `leadoff_geocode.py:41` is the address geocoder; neither enumerates CDPs, and census.gov is sandbox-egress-blocked (`leadoff_geocode.py:6`). **Fixed:** §0.3/§2/§3.2/§6 — reframed as a new TIGERweb Places/CDP-layer query + county-FIPS resolution, built/tested only on the worker; "reuse" narrowed to host+pattern.

**Major #3 — one long audit job would be reaped.** `job_worker.py:275–296` (default `job_stale_timeout_minutes`=30; comment records `gsc_page_ingest` "grazed the 30-min default in prod and got reaped"). **Fixed:** §3.4/§5/§6 — **one job per tier**, every paid step idempotent/cached + metered before spend.

**Major #4 — a demand floor existed for neighborhoods but not for cells.** §0.4 gates neighborhoods on volume; the cell gaps only had `rank_gaps` (ordering). Tier 3/4 (CDP × subservice) would surface thousands of zero-demand "gaps." **Fixed:** §3.1/§5 — `coverage_cell_volume_min` floor hides sub-floor cells, mirroring the neighborhood gate.

**Minor/Advisory (folded in):** `classify_page_type` is nlp-api-only and unneeded — replaced in §2 with the platform-side `content_tokens`/`is_blog_url` approach §3.1 already uses. `_generate_service_pages` emits per-city pages — §0.2/§6 note the city-strip step to derive a city-agnostic subservice axis. GBP categories are business-type values, not services — §0.2/§2 mark them a seed to expand. Without the Maps key the location universe silently collapses — §5 requires a visible degraded note. The "~85%/thin layer" framing — §1 qualified (near-total reuse for Tier 1; Tiers 3 & 5 are real new work).
