# Coverage Audit — Build Handoff

**Module slug:** `coverage_audit` · **Authoritative plan:** `docs/modules/coverage-audit-module-plan-v1_0.md` (design authority; owner decisions §0; adversarial-review findings + resolutions §8).

**Status (2026-09-13):** Plan written, adversarially reviewed, all four Major findings fixed in-plan. **Nothing is built yet.** PR #1067 (docs-only) carries the plan + this handoff. Next step is **Phase 0**.

---

## What this module is (one paragraph)

Scans a client's current site as it stands, infers which service/location pages already exist, computes the *ideal* coverage universe across four tiers, diffs ideal-vs-actual to surface gaps (missing service pages, missing location pages, missing service×location combos), ranks the gaps by real search demand, and **auto-seeds a Service×Location Matrix per tier** so recommendations are one click from execution. It is the whole-site inversion of the seed-based Plan Silo. It gets its **own client-workspace card + `/coverage-audit` page** (route `clients/:id/coverage-audit`) — NOT a Local SEO tab.

---

## Locked owner decisions (plan §0)

1. **Tiered rollout, T1 first.** T1 city×main-service · T2 city×subservice · T3 CDP×main-service · T4 CDP×subservice. Output is also tiered.
2. **Service axis auto-derived, team-editable.** Main services from site service pages + GBP-category *seed* + planner. Subservices from `_generate_service_pages`.
3. **CDPs from the authoritative Census list**, geocode-verified. First-class location tier, distinct from neighborhoods.
4. **Neighborhoods: own-page vs. fold-into-city by demand + SERP evidence** (two-stage: volume gate → live SERP only on survivors). Default = fold in.
5. **Auto-seed the Matrix — AXES ONLY** (see Major #1 below).
6. **Separate card + `/coverage-audit` page**, deep-linking into Local SEO / the Matrix.

---

## The four load-bearing constraints (adversarial-review §8 — do NOT regress these)

- **Major #1 — seed the Matrix with AXES ONLY.** `local_seo_matrix_store.create_matrix` already calls `mark_coverage` on seed (re-scans the live site). The audit must **never** write its own present/absent verdict onto matrix cells — its grid feeds the report/ranking only. Two coverage sources = silent divergence.
- **Major #2 — CDP enumeration is a NEW, worker-only build.** The existing census code (`census_demand.py`) queries only the TIGERweb *block-group* layer; nothing enumerates CDPs. Building `census_cdp.py` = a new TIGERweb Places/CDP-layer query + service-area→county-FIPS resolution + geocode-verify. **census.gov is egress-blocked from the sandbox** — build/test on the deployed worker only (Phase 3, not Phase 0/1).
- **Major #3 — one job per tier, paid steps idempotent.** The stale-job reaper (`job_worker.py`, `job_stale_timeout_minutes`=30) reaps + requeues a long job. Do NOT run the whole 4-tier audit as one job. One `coverage_audit` job **per tier**; every paid step (demand batch, neighborhood volume, neighborhood SERP) idempotent/cached + metered before spend.
- **Major #4 — demand FLOOR on cell gaps, not just ranking.** `coverage_cell_volume_min` hides sub-floor cells (mirrors the neighborhood gate). Ranking alone leaves thousands of zero-volume Tier 3/4 combos as "gaps."

Also folded in (don't reintroduce): `classify_page_type` is nlp-api-only — use platform-side `content_tokens` + `is_blog_url` instead; `_generate_service_pages` emits *per-city* pages, so derive a city-agnostic subservice axis by one representative-city call + city-strip/dedupe; GBP categories are a *seed*, not the service list; without `GOOGLE_MAPS_API_KEY` the location universe silently collapses — surface a visible degraded note.

---

## Verified reuse anchors (grounded during review — all exist as described)

| Purpose | Symbol | Location |
|---|---|---|
| Scan site | `discover_site_urls` | `services/site_page_index.py:415` |
| Token split / match | `content_tokens`, `build_page_token_index`, `match_site_page_for_keyword`, `match_site_service_page` | `services/site_page_index.py:193/203/221` |
| City universe | `resolve_target_cities(client, seed_location, location_code, supabase)` → `(cities, notes)`; needs `google_maps_api_key` | `services/target_cities.py:83` |
| Neighborhoods | `_neighborhoods_for_city`, `place_is_within_city` | `services/local_seo_silo.py:575`, `services/maps_geocode.py:576` |
| Service variations | `_generate_service_pages(service, city, llm, icp_block="")` (per-city pages) | `services/local_seo_silo.py:408` |
| Demand | `keyword_market.py` (80-char/10-word caps; cross-client cache) | `services/keyword_market.py` |
| Live SERP | `fetch_serp(keyword, location_code, language_code, depth)` | `services/serp_snapshot.py:571` |
| Matrix seed | `create_matrix(client_id, body, user_id)` (body carries `services`/`locations`; calls `mark_coverage`), `build_cells`, `diff_cells` | `services/local_seo_matrix_store.py:237`, `services/local_seo_matrix.py` |
| Sign-off gate | `MATRIX_SIGNOFF_THRESHOLD` = 200 | `services/website_plan.py:96` |
| Census host/pattern (pattern reuse only) | TIGERweb ArcGIS REST | `services/census_demand.py:40` |
| Reaper | `stale_timeout_for`, `job_stale_timeout_minutes`=30 | `services/job_worker.py:275` |
| Meter pattern to mirror | `keyword_research_usage` / `domain_intel_usage` + reserve RPC | — |

---

## Phase 0 scope (the next chat's job)

Pure foundations, no external calls, no UI:

1. **`services/coverage_audit.py`** — pure core:
   - `classify_site_pages(urls, place_vocab)` → bucket URLs into `service_only` / `location_only` / `service_location` / `other` via `content_tokens` + `is_blog_url` (place-tokens = intersection with the location universe names).
   - `build_coverage_grid(service_axis, location_axis, site_index, in_tool_index)` → per-cell `present`/`absent` **for the report only** (never written to matrix cells).
   - `diff_coverage(...)` → `{missing_services, missing_locations, missing_cells}`.
   - `rank_gaps(gaps, market, min_volume)` → attach volume/CPC/est-value + opportunity score, **apply the `coverage_cell_volume_min` floor**.
2. **Data model** — migration in `writer/supabase/migrations/` (apply live via Supabase MCP): `coverage_audits` run table (jsonb-heavy, like `keyword_research_runs`), `coverage_audit_usage` meter + `reserve_coverage_audit_calls` RPC, widen the `async_jobs` type CHECK for a **per-tier** `coverage_audit` job.
3. **`config.py`** — `coverage_cell_volume_min`, `coverage_neighborhood_volume_min`, `coverage_neighborhood_serp_dedicated_min`, `coverage_audit_usage` daily ceiling (placeholder ~200/day).
4. **Unit tests** (`tests/test_coverage_audit.py`) — pure core against fixtures: classification buckets, the AXES-ONLY grid, the demand floor, empty-state degrade.

Phase 0 decides and enforces the **axes-only Matrix seed contract** up front. No `resolve_target_cities`/planner/SERP wiring yet (that's Phase 1).

---

## Open items (plan §7 — none block Phase 0)

- Module name (kept "Coverage Audit").
- **Location-hub keyword definition** — what keyword represents a bare location page (`/melbourne/` → `{melbourne}`, but a city page is usually `"[primary service] [city]"`). Decide before Phase 1's `build_coverage_grid` treats location-axis pages.
- Service-axis confirmation UX (block audit vs. run-on-auto-derived-with-banner).
- Refresh cadence (on-demand v1 vs. monthly scheduled re-audit).
- CDP county scope (all touched counties vs. only those with a verified CDP inside the footprint).
- Calibrate `coverage_cell_volume_min` + the daily ceiling from a first live run.

---

## Build conventions (from CLAUDE.md)

Pure logic unit-tested + mocked externals; `HTTPException` with string error codes; service-role Supabase; migrations in `writer/supabase/migrations/` applied live via the Supabase MCP; async work through `async_jobs` + the asyncio worker; best-effort/degrade-never-abort throughout; no new external dependencies or infra.
