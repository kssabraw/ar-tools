# Coverage Audit — Build Handoff

**Module slug:** `coverage_audit` · **Authoritative plan:** `docs/modules/coverage-audit-module-plan-v1_0.md` (design authority; owner decisions §0; adversarial-review findings + resolutions §8).

**Status (2026-09-14):** **Phase 0 MERGED** (PR #1069 — pure core + tables/RPC/per-tier job type, applied live). **Phase 1 (Tier 1: city × main-service) BUILT** — draft PR #1070, all CI green (ruff/mypy/pytest/Netlify). Branch `claude/hopeful-rubin-dk9t19`. **Next step is Phase 2 (Tier 2: city × subservice).**

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

## Phase 0 — MERGED (PR #1069)

Pure foundations, applied live:
- **`services/coverage_audit.py`** — `classify_site_pages`, `build_coverage_grid` (AXES-ONLY), `diff_coverage`, `rank_gaps` (with the `coverage_cell_volume_min` floor), `MATRIX_CELL_STATE_KEYS`.
- **`services/site_page_index.py`** — `is_blog_url` (formalizes the non-page exclusion).
- **Migration `20260914120000_coverage_audit.sql`** (applied live) — `coverage_audits` run table, `coverage_audit_usage` meter + `reserve_coverage_audit_calls` RPC, `coverage_audit` async-job type.
- **`config.py`** — the `coverage_audit_*` block (`coverage_audit_enabled`, `coverage_audit_daily_call_budget`=200, `coverage_cell_volume_min`=10, `coverage_neighborhood_volume_min`=20, `coverage_neighborhood_serp_dedicated_min`=3).

## Phase 1 — BUILT (Tier 1: city × main-service), draft PR #1070, CI green

The shippable core. **No new migration** — the service axis lives on the run's jsonb; Phase 0's tables/RPC/job-type already cover it (re-verified live via Supabase MCP).

**Backend**
- **`services/coverage_audit.py` (pure additions):**
  - `derive_site_services(classified, place_vocab)` / `service_phrase_from_url(url, place_tokens)` — the *site* half of the service axis (place-stripped, slug-order-preserving service phrases from `service_only` + `service_location` pages).
  - `build_coverage_grid(..., *, primary_service=None)` — added a keyword-only `primary_service` param. Location rows: keyword = `"<primary_service> <city>"` (resolves the plan §7 location-hub keyword); presence = a bare `/city/` hub OR the primary-service city page. **Omitting `primary_service` is byte-identical to Phase 0** (bare place keyword, hub-only match).
  - `build_matrix_seed_body(name, location, location_code, service_axis, location_axis)` — AXES ONLY; a test asserts it never carries `MATRIX_CELL_STATE_KEYS`.
- **`services/coverage_audit_service.py` (new, impure runner):** `run_coverage_audit_tier` (Tier-1 only), `run_coverage_audit_job`, `enqueue_coverage_audit`, `get_audit`/`list_audits`/`latest_audit`, `seed_matrix_from_audit`, own `reserve_budget`/`budget_remaining`. Service axis: `derive_site_services` + GBP-category seed expanded by a best-effort planner LLM (`_service_llm`, Sonnet) → team-edit re-run. Location axis: `resolve_target_cities` + a visible geocoding-unavailable note. Demand: cached-first via `keyword_market`, reserve-before-spend + cache-idempotent (reaper-safe). Floor on cells only.
- **`routers/coverage_audit.py` (new):** `GET .../coverage-audit` (status+history+latest), `POST` (start), `GET .../jobs/{job_id}` (poll), `GET .../{audit_id}` (run), `PUT .../{audit_id}/service-axis` (edit→fresh re-run), `POST .../{audit_id}/seed-matrix`. Registered in `main.py`; dispatch in `job_worker.py` (lazy import; NOT freeze-gated — it's analysis).
- **Tests:** `tests/test_coverage_audit.py` (pure additions) + `tests/test_coverage_audit_service.py` (planner merge/provenance/fallbacks, geocoding degrade, demand reserve/idempotency, keyword collector).

**Frontend**
- `frontend/src/pages/CoverageAudit.tsx` (new) — Tier-1 gap report (missing services / cities / service×city, demand-ranked), editable service axis with a "confirm to refine" banner, "Seed matrix" + per-gap "Create page" deep links (`/clients/:id/local-seo?tab=matrix&matrix=<id>` / `?tab=new`).
- Route `clients/:id/coverage-audit` in `App.tsx`; a **separate** "Coverage Audit" workspace card in `ClientWorkspace.tsx` (SEO Strategist section, `LayoutGrid` icon) — not a Local SEO tab (§0.6).

**Plan §7 open items resolved this phase:**
- **Location-hub keyword** → `"<primary main service> <city>"` (a bare place name has no isolated commercial demand).
- **Service-axis confirmation UX** → run on the auto-derived axis with a "confirm to refine" banner + edit/re-run (non-blocking).

**Seed-location note:** Tier 1 derives the seed city from `clients.business_location` and the location code from `dataforseo_rank.location_code_for(client)`. No `business_location` → location axis is empty with a visible note (service-axis-only audit still runs). Carry this into Tier 2/3.

---

## Phase 2 scope (the next chat's job) — Tier 2: city × subservice

Reuse the Tier-1 runner; the delta is the **subservice axis** and threading `tier=2` through enqueue/run/UI.

1. **Subservice axis** — for each *confirmed main service* run the Local SEO planner `local_seo_silo._generate_service_pages(service, representative_city, llm, icp_block)`, which emits **per-city** pages, then **derive a city-agnostic axis** by stripping/deduping the representative city (plan §0.2 / §6). `local_seo_matrix.service_labels_from_pages(per_silo, city)` already strips the city — reuse it. Pick one representative city (the seed city).
2. **Run + matrix** — `tier=2` produces a city × subservice grid + matrix seed. `SUPPORTED_TIERS` currently `(1,)` — add `2`; `run_coverage_audit_tier` currently hard-raises on `tier != 1`, so branch it. The service axis for Tier 2 = the subservice list (not main services); the location axis is unchanged (cities). `primary_service` for the location-hub keyword → the first *main* service (keep, or drop location rows for Tier 2 since the matrix is subservice×city — owner call).
3. **Cost** — the subservice axis can be large (main services × variations); the `coverage_cell_volume_min` floor matters more. The planner call is one LLM call per main service (cheap, no paid SERP) — reserve nothing for it, but keep it best-effort.
4. **UI** — a tier selector (T1 / T2) on `CoverageAudit.tsx`, or a second run button; the report + seed-matrix code is tier-agnostic already.

Do NOT touch: the axes-only seed contract, the per-tier job decomposition, the reserve-before-spend/idempotency, or the demand floor.

---

## Open items (plan §7 — none block Phase 2)

- Module name (kept "Coverage Audit").
- ~~Location-hub keyword~~ — **RESOLVED (Phase 1):** `"<primary main service> <city>"`.
- ~~Service-axis confirmation UX~~ — **RESOLVED (Phase 1):** run-on-auto-derived + confirm-to-refine banner.
- Refresh cadence (on-demand v1 vs. monthly scheduled re-audit) — still on-demand only.
- CDP county scope (all touched counties vs. only those with a verified CDP inside the footprint) — decide before Phase 3.
- Calibrate `coverage_cell_volume_min` + the daily ceiling from a first live run (both still placeholders — 10 / 200).
- **Tier-2 location-row question** (above §2.2): keep location-hub rows in a subservice audit, or show subservice + cell gaps only?

---

## Build conventions (from CLAUDE.md)

Pure logic unit-tested + mocked externals; `HTTPException` with string error codes; service-role Supabase; migrations in `writer/supabase/migrations/` applied live via the Supabase MCP; async work through `async_jobs` + the asyncio worker; best-effort/degrade-never-abort throughout; no new external dependencies or infra.
