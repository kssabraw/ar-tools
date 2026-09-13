# Coverage Audit — Location & Service Gap Finder (Module Plan v1.0)

> **Working name:** "Coverage Audit" (module slug `coverage_audit`). Rename freely before Phase 0 lands — the slug is easy to change now, expensive later.
>
> **Status:** plan / not built. This is the design authority; owner decisions are in §0.

## 1. What this is

A per-client module that **scans a client's current site as it stands**, infers which service and location pages already exist, computes the *ideal* coverage universe across four tiers, diffs ideal-vs-actual to surface gaps (missing service pages, missing location pages, missing service×location pages), ranks the gaps by real search demand, and **auto-seeds a Service×Location Matrix per tier** so the recommendations are one click from execution.

It answers, per client: *what cities should have their own page, what services, what service+location combos — plus CDPs and neighborhoods — that don't exist yet, ranked by whether they're worth building.*

**It is not a new generator.** ~85% of the machinery already exists in the Local SEO module (site scanning, existing-page matching, the city/neighborhood universe, the service-variation planner, and the whole Service×Location Matrix with generation/drip-release/bulk-publish). This module is the thin **inference + diff + demand-ranking layer** that inverts the Plan Silo (which starts from a seed you type) into a whole-site audit, and pipes the result into the Matrix.

## 0. Owner decisions (locked 2026-09-13)

1. **Tiered rollout.** Build and ship tier by tier, T1 first. The audit *output* is also tiered (recommendations grouped/ordered by tier).

   | Tier | Location granularity | Service granularity | Matrix |
   |---|---|---|---|
   | **1** | Cities | Main services | city × main-service |
   | **2** | Cities | Subservices | city × subservice |
   | **3** | CDPs | Main services | CDP × main-service |
   | **4** | CDPs | Subservices | CDP × subservice |

2. **Service axis = auto-derive, team edits.** Main services auto-derived from GBP categories + the site's classified service pages + the planner, presented for the team to confirm/edit. Subservices from the Local SEO planner's variation expansion (`_generate_service_pages`).
3. **CDPs = authoritative Census list.** Per service-area county from census.gov (reuse the LeadOff census infra), geocode-verified against the service area. CDPs are a first-class location tier, distinct from neighborhoods.
4. **Neighborhoods = own-page vs. fold-into-city, decided by demand + SERP evidence.** Two-stage gate: batch DataForSEO volume for `"[main service] [neighborhood]"` first (cheap), then a live SERP **only on the volume survivors** to check whether *dedicated* neighborhood pages actually rank vs. city pages. Default = fold into the city page's "areas we serve" section.
5. **Auto-seed the Matrix.** Each tier maps to one `local_seo_matrix` (axes = that tier's service list × location list), cells pre-marked present/absent from the audit diff. The demand-ranked gap report is the review screen. Execution, sibling links, drip-release, and bulk-publish come free from Matrix Phases 0–5.

## 2. Reuse map — what already exists

| Need | Reuse | Where |
|---|---|---|
| Scan site as-is | `discover_site_urls` (sitemap → robots → DataForSEO `site:` fallback) | `services/site_page_index.py:415` |
| Classify a URL (service / location / city_service / blog) | `classify_page_type` | `writer/nlp-api/main.py` |
| Existing-page match by content-word-set (incl. national/city-less service page) | `build_page_token_index` / `match_site_page_for_keyword` / `match_site_service_page`, `content_tokens` | `site_page_index.py:193/203/221` |
| City universe (seed + GBP service area + manual + site place-names + nearby via Overpass, geocode-verified, capped) | `resolve_target_cities` | `services/target_cities.py:83` |
| Per-city neighborhoods (LLM propose → geocode containment) | `_neighborhoods_for_city`, `place_is_within_city`, `maps_geocode.forward_geocode_places` + `geocode_forward_cache` | Local SEO silo planner, `services/maps_geocode.py` |
| Service-variation expansion (main → subservices) | `_generate_service_pages` | Local SEO silo planner |
| GBP categories | `clients.gbp` (primary + additional categories) | client row |
| Demand data (volume / CPC / competition, cross-client cached) | `keyword_market.py` | `services/keyword_market.py` |
| Live SERP (for neighborhood evidence) | `serp_snapshot.fetch_serp` + parsers | `services/serp_snapshot.py` |
| Census county resolution + geocoding infra | `leadoff_counties` (`city_counties`, `parse_county`), `census_demand.py`, `leadoff_geocode`, Census API family | LeadOff services |
| Persisted N×M grid + gap-fill + generate + drip-release + bulk-publish + sibling links | **Service×Location Matrix** (Phases 0–5) | `services/local_seo_matrix*.py`, `routers/local_seo_matrix.py` |
| Marking targets found / on_site / missing | Plan Silo `_to_items` + #951/#953 matching | `services/local_seo_service.py` |
| Paid-call meter pattern (daily budget + reserve RPC) | `keyword_research_usage` / `domain_intel_usage` | mirror it as `coverage_audit_usage` |

## 3. The genuine delta (what's new)

1. **Whole-site inference (`services/coverage_audit.py`, pure).** Invert the Plan Silo: derive both axes from reality instead of a typed seed.
   - `classify_site_pages(urls, place_vocab)` → per URL, split content tokens into service-tokens vs place-tokens (place-tokens = intersection with the resolved location universe names) and bucket into `service_only` / `location_only` / `service_location` / `other` (blog/product excluded via the existing blog-slug detector).
   - `build_coverage_grid(service_axis, location_axis, site_index, in_tool_index)` → mark each cell `present` (site match OR an in-tool `local_seo_pages`/matrix page exists) / `absent`. Standalone service pages = the service-axis (city-less) pages; standalone location pages = the location-axis (city/CDP hub) pages; combos = the cells.
   - `diff_coverage(...)` → `{missing_services, missing_locations, missing_cells}` per tier.
   - `rank_gaps(gaps, market)` → attach volume/CPC/est-value + an opportunity score (reuse the keyword-research scoring shape), ordered.
   - All pure, unit-tested; no external calls in the core (callers pass in the scanned index + market data).

2. **Census CDP source (`services/census_cdp.py`).** Given the service-area counties, pull the Census places list, filter to CDP types, geocode-verify containment within the service-area footprint (reuse `maps_geocode` + `place_is_within_city`), cache like `geocode_forward_cache`. Best-effort: no key / dead source → CDP tiers degrade with a note, never abort.

3. **Neighborhood decision layer (`services/neighborhood_gate.py`, pure decision + impure two-stage runner).**
   - Stage 1 — batch DataForSEO volume for `"[primary main service] [neighborhood]"` across candidates; drop below `coverage_neighborhood_volume_min`.
   - Stage 2 — live SERP **only on survivors**; `has_dedicated_neighborhood_pages(serp, place)` (pure) checks whether ≥ `coverage_neighborhood_serp_dedicated_min` of the top organic results carry the place token in URL/title (a dedicated page) vs. being city pages.
   - Output per neighborhood: `{decision: own_page | fold_into_city, volume, serp_evidence, city}`. `fold_into_city` neighborhoods feed the city page's "areas we serve" list (the writer already renders that section — pass the list through the matrix cell / page context).

4. **The audit run + report (`services/coverage_audit_service.py`, `routers/coverage_audit.py`, `pages/CoverageAudit.tsx`).** Async `coverage_audit` job; persisted run (per-tier gaps + resolved axes + provenance) as a cheap re-read; per-tier gap tables (demand-ranked) with "Seed matrix" / "Create page" / "Edit service axis" actions deep-linking into Local SEO + the Matrix.

## 4. Data model (proposed)

- `coverage_audits` — one run per client: `{client_id, status, tiers_run int[], service_axis jsonb, location_axis jsonb, gaps jsonb (per-tier), provenance jsonb, created_at, error}`. jsonb-heavy so re-opening a run is a read, like `keyword_research_runs`.
- `coverage_audit_usage` + `reserve_coverage_audit_calls` RPC — daily paid-call meter (mirror `keyword_research_usage`).
- `census_cdp_cache` (or reuse `geocode_forward_cache` keyed by CDP query) — per-county CDP list, freshness-bounded.
- `async_jobs` type `coverage_audit` (widen the live CHECK).
- Matrices seeded from a run reuse the existing `local_seo_matrices` / `local_seo_matrix_cells` — **no new execution model.**

No schema for standalone/service/location pages — those are the matrix axes and existing `local_seo_pages`.

## 5. Cost & guardrails

- **Paid calls per run:** demand volume batch (`keyword_market`, cross-client cached — cheap on repeat), neighborhood Stage-2 SERP (bounded to volume survivors), CDP geocoding (cheap + cached). All metered through `coverage_audit_usage` with a free `estimate` preflight (mirror keyword-research).
- **Grid explosion:** cities × CDPs × subservices can reach thousands of cells. Two defenses already exist: demand ranking (only surface gaps with real volume) and the Matrix's **200-page sign-off gate** (`website_plan.MATRIX_SIGNOFF_THRESHOLD`) at seed/generate time. The audit report shows the count and the sign-off before any generation.
- **Best-effort everywhere:** a dead source (no sitemap, no GBP, geocoding off, no market key) degrades that slice with a note and never aborts the audit — the suite-wide pattern.

## 6. Tiered phasing (build order)

- **Phase 0 — foundations.** `coverage_audit.py` pure core (site classification + coverage grid + diff + ranking), the `coverage_audits` run table + meter + async job type, config block. Unit-tested against fixtures; no UI. *(No external calls in the core.)*
- **Phase 1 — Tier 1 (city × main-service).** Service-axis auto-derive (GBP + site + planner) + team-edit endpoint; location axis via `resolve_target_cities`; diff + demand rank; auto-seed a T1 matrix from the gaps; `pages/CoverageAudit.tsx` report + a client-workspace "Coverage Audit" card. **This is the shippable core** — the most valuable tier on its own.
- **Phase 2 — Tier 2 (city × subservice).** Planner variation expansion per confirmed main service → subservice axis → city × subservice matrix.
- **Phase 3 — Tier 3 (CDP × main-service).** `census_cdp.py` source → CDP location axis → CDP × main-service.
- **Phase 4 — Tier 4 (CDP × subservice).** Cross the CDP axis with the subservice axis.
- **Phase 5 — Neighborhoods (cross-cutting).** The two-stage demand+SERP decision layer + fold-into-city wiring (own-page neighborhoods become matrix location rows; folded ones feed the city page's areas-we-serve list). Applies to every location tier.

Each phase ships a working audit for its tier and its matrix seed; nothing is stubbed waiting on a later phase.

## 7. Open items / to grill before Phase 0

- **Module name** — confirm "Coverage Audit" or pick another.
- **Where the report lives** — standalone `/coverage-audit` page vs. a tab inside the existing Local SEO tool (leaning standalone workspace card + page, since it spans the whole site not one seed).
- **Service-axis confirmation UX** — auto-derived main services need a review/edit screen before the diff runs; does an unconfirmed axis block the audit, or run on the auto-derived set with a "confirm to refine" banner?
- **Refresh cadence** — on-demand only for v1, or a scheduled re-audit (monthly) like GSC Research? (The site changes as pages ship, so a re-audit should show shrinking gaps.)
- **CDP county scope** — all counties the service area touches, or only counties with a geocode-verified CDP inside the footprint? (Bounds the Census pulls.)
- **`coverage_audit_usage` daily ceiling** — set a real number once the DataForSEO budget is known (placeholder like the domain-intel 200/day).
