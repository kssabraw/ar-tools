# Coverage Audit — Build Handoff

**Module slug:** `coverage_audit` · **Authoritative plan:** `docs/modules/coverage-audit-module-plan-v1_0.md` (design authority; owner decisions §0; adversarial-review findings + resolutions §8).

**Status (2026-09-14):** **Phase 0 MERGED** (PR #1069 — pure core + tables/RPC/per-tier job type, applied live). **Phase 1 (Tier 1: city × main-service) MERGED** (PR #1070). **Phase 2 (Tier 2: city × subservice) MERGED** (PR #1072 — all CI green). **Phase 3 (Tier 3: CDP × main-service) MERGED** (PR #1076 — all CI green: platform-api tests + lint & typecheck + Netlify; squash-merged to `main` as `fc1afa5`; the new census CDP integration, worker-only; migration `20260914130000_coverage_audit_cdp_cache.sql` applied live). **Next step is Phase 4 (Tier 4: CDP × subservice — cross the CDP axis with the subservice axis).**

> ⚠️ **The live TIGERweb CDP query is UNVERIFIED from the sandbox** (census.gov is egress-blocked, same as `census_demand.py` / `leadoff_geocode.py`). The pure decision helpers around it are unit-tested; the enumeration query itself must be confirmed on the deployed Railway worker now that it's merged — run a Tier-3 audit on a US client with a `business_location` + `GOOGLE_MAPS_API_KEY` set, and check the run's `provenance.location_axis` (for a Tier-3 run this is the CDP provenance: `kind:"cdp"` + states / counties / candidate+verified counts + notes) and the `census_cdp_cache` rows (one per state). If `pick_cdp_layer` mis-selects the layer or the `STATE='SS'` query shape is wrong, the tier degrades with a visible note (never aborts) — check `census_cdp.*` logs on the worker.

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

## Phase 2 — BUILT (Tier 2: city × subservice)

The delta from Tier 1 was the **subservice axis** + threading `tier=2` end-to-end. Everything else (location axis, demand rank + floor, matrix seed, report UI, meter, job decomposition) is reused unchanged.

**Backend**
- **`services/coverage_audit.py` (pure addition):** `merge_subservice_axis(per_service_labels)` — the cross-service merge/dedupe. Input is a list of `{"service": <main>, "labels": [{label, group}]}` (each `labels` = the output of `local_seo_matrix.service_labels_from_pages(per_silo, representative_city)` for ONE main service, already city-stripped + slug-deduped within that service). It merges across services, re-dedupes case-insensitively by label (first-seen order), and tags each surviving subservice with its parent main `service` + planner `group`. Entries carry `label` + `sources` so a subservice axis flows through `build_coverage_grid` / `build_matrix_seed_body` / the UI **byte-identically** to a main-service axis. Pure, unit-tested.
- **`services/coverage_audit_service.py`:** `SUPPORTED_TIERS = (1, 2)`. New `_derive_subservice_axis(client, main_axis, representative_city)` — best-effort, async: resolves the ICP block (`icp_service.resolve_icp_text`, non-fatal), gets the planner LLM (`local_seo_silo._service_llm`), runs `local_seo_silo._generate_service_pages(service, representative_city, llm, icp_block)` **once per confirmed main service** (via `asyncio.to_thread` so N LLM calls don't block the worker loop), strips the representative city via the reused `local_seo_matrix.service_labels_from_pages`, and merges with `core.merge_subservice_axis`. `run_coverage_audit_tier` no longer hard-raises on `tier != 1`; it branches: an **override** (edited axis) is used verbatim for either tier (Tier 2 = confirmed subservices); a fresh **Tier 1** derives main services; a fresh **Tier 2** derives main services → expands to subservices, **degrading cleanly to the main-service axis with a visible note** if the planner is unavailable / every call fails (never aborts). Representative city = the seed city (`loc_prov["seed_city"]`, same string the planner composes with and the strip removes).
- **`routers/coverage_audit.py`:** `GET .../coverage-audit?tier=<n>` (defaults 1) returns the per-tier `latest` (+ `supported_tiers`); `list_audits` history spans all tiers. Start / edit-axis / seed-matrix already thread the run's tier.

**Frontend** — `pages/CoverageAudit.tsx` gained a **T1 / T2 tier selector** (each tier keeps its own `latest` run + in-flight job via a tier-scoped `useResumableJob` storage key). The report is tier-agnostic; for T2 the labels read "Subservice axis" / "Missing subservices" / "Subservice × City cells", and the Cities stat + Missing-cities table are hidden (see the location-row decision below).

**Tier-2 location-row decision (open item — RESOLVED):** **show subservice + cell gaps only; DROP the location-hub "missing cities" rows.** A city-hub gap (does a city have a *main-service* landing page) is exactly Tier 1's question, measured against the MAIN service axis; re-reporting it inside a subservice audit would (a) double-count what Tier 1 already surfaces and (b) rank it against a keyword (`"<primary main service> <city>"`) that isn't even on the Tier-2 service axis. Implementation: for `tier != 1` the runner sets `diff["missing_locations"] = []` (which also stops the demand fetch from spending on hub keywords the tier won't show) and passes `primary_service=None` to `build_coverage_grid`; provenance carries `location_rows_shown=false`, and the frontend keys the Cities stat + table off it. The location axis itself is unchanged — it still builds the subservice×city cells and seeds the matrix (subservices × cities). **The Tier-2 matrix + its cell gaps carry all the actionable location signal.**

**Cost / guardrails held:** the subservice planner is one LLM call per main service (cheap, no paid SERP) — reserves nothing, kept best-effort. The `coverage_cell_volume_min` floor still applies to cells (matters MORE here — the subservice cross-product is larger). The Matrix's own 200-page sign-off gate (`MATRIX_SIGNOFF_THRESHOLD`) fires at seed/generate time via `create_matrix`, unchanged. Axes-only seed contract, per-tier job decomposition, and reserve-before-spend/idempotency all untouched.

**Tests:** `tests/test_coverage_audit.py` (pure `merge_subservice_axis` — cross-service merge/dedupe, flow-through `_axis_names`/`build_matrix_seed_body`, empty/blank degrade) + `tests/test_coverage_audit_service.py` (`_derive_subservice_axis` happy path + city-strip, no-LLM degrade, no-main-services degrade, per-service failure isolation, non-fatal ICP failure, `SUPPORTED_TIERS` includes 2).

---

## Phase 3 — MERGED (Tier 3: CDP × main-service — NEW census integration, worker-only), PR #1076

CDP enumeration is **genuinely new engineering** (plan §0.3 / §3.2 / §8 Major #2), not reuse — `census_demand.py` queries only the TIGERweb *block-group* layer. The delta from Tier 1 is the **location axis**: the authoritative Census CDP list for the service area, instead of `resolve_target_cities`' cities. The service axis stays main services (the runner reuses the Tier-1 path verbatim).

**New: `services/census_cdp.py` (worker-only).** Three steps, each best-effort/degrade-never-abort:
- **(a) service area → county FIPS.** Forward-geocode the seed city (cache-served) + `resolve_target_cities` → the footprint city geos; reverse-geocode each footprint centre → its county via the census `geographies/coordinates` endpoint (reuses `leadoff_counties._county_for_coord`, the same census.gov family). The **states** those counties belong to are the TIGERweb enumeration unit; counties record the scope.
- **(b) TIGERweb CDP-layer query.** `pick_cdp_layer` resolves the **Census Designated Places** polygon layer by name from the service metadata (excludes label + tribal layers, mirrors `census_demand.pick_bg_layer`). Per state, `_fetch_state_cdps` enumerates every CDP (`where=STATE='SS'`, paginated, name + centroid) — a static, deterministic pull **cached per state in `census_cdp_cache`** (migration `20260914130000`, applied live) and shared across every client in that state. Candidates are then pre-filtered to the service-area footprint bbox (pure `footprint_bbox` + `point_in_bbox`, free).
- **(c) geocode-verify containment.** Forward-geocode each surviving candidate (`maps_geocode.forward_geocode_places`, cached in `geocode_forward_cache`) and keep it only when it falls inside a resolved footprint city (`place_is_within_city` against any footprint city — the exact neighborhood-verification pattern). `assemble_cdp_axis` dedupes / sorts by name / caps at `coverage_cdp_max` (60).

**No paid DataForSEO calls** happen in CDP resolution — it's all keyless census + Google-geocode (both cached) — so the `coverage_audit_usage` meter is untouched by the location axis (the demand fetch on the resulting gap keywords is the only metered step, unchanged). Idempotent: a reaper requeue finds the per-state CDP cache + the forward-geocode cache warm and re-bills nothing.

**Runner/router/frontend wiring:** `SUPPORTED_TIERS = (1, 2, 3)`. `run_coverage_audit_tier` branches for tier 3: location axis = `census_cdp.resolve_cdp_axis(...)`; the place vocabulary for classification/service-derivation is the **cities** (+ CDP names) — a Tier-3 service page is still `/service-city/`, so cities (not CDPs) strip its place tokens, keeping the MAIN-service derivation clean even if the CDP axis degrades. Tiers 1 and 3 share: `_derive_service_axis` (main), `primary_service` set, location-hub rows KEPT. `pages/CoverageAudit.tsx` gained a **T3** tier selector chip + CDP-aware location nouns (Stats / Location axis / Missing-CDPs table / cell column read "CDP" for tier 3).

**Config:** `coverage_cdp_cache_days` (365 — per-state cache freshness; TIGER vintage is ~yearly), `coverage_cdp_max` (60 — axis cap). Plus a `job_stale_timeout_overrides["coverage_audit"] = 60` (a Tier-3 run's cold-cache geocoding can graze the 30-min reaper; the requeue re-runs the tier cheaply since every step is cached).

**Tests:** `tests/test_census_cdp.py` (22 — every pure helper: layer pick / feature parse / footprint bbox / containment pre-filter / county scope / axis assembly / staleness, plus `resolve_cdp_axis` happy path + the no-seed / no-maps-key / no-counties / no-CDPs degrade paths, all with the network mocked) + a Tier-3 runner wiring test in `tests/test_coverage_audit_service.py` (CDP location axis, main-service axis, location-hub rows kept, cities threaded into the place vocab). **The live TIGERweb query is NOT sandbox-verifiable — see the ⚠️ note at the top; confirm on the worker.**

### Decisions made this phase (plan §7)

- **CDP county scope → the counties the resolved service-area cities sit in (city-anchored, "Scope B").** The counties merely scope which **states** we enumerate CDPs from (a state is the cacheable TIGERweb unit) and are recorded in provenance; the geocode-verified footprint containment (step c) is what actually decides a CDP's membership. This bounds the census pulls to the counties the client demonstrably operates in — never a broad radius-edge probe — while the containment gate keeps far CDPs out. It won't miss obvious CDPs because the resolved footprint (seed + `resolve_target_cities`' nearby/GBP/manual/site cities) already spans where the client operates, and a state's whole CDP set is enumerated (then footprint-filtered), so a CDP straddling into an adjacent county still surfaces if it's inside the footprint.
- **Tier-3 location-hub rows → KEPT** (like Tier 1). A CDP hub IS a main-service concept (does a CDP have a `"<primary main service> <CDP>"` landing page), so the Tier-1 rationale applies and the Tier-2 "drop it, it double-counts Tier 1" rationale does not — Tier 3 measures against the CDP axis, a different location universe than Tier 1's cities. `location_rows_shown = tier in (1, 3)`; `primary_service` set for tiers 1 and 3.

Did NOT touch: the axes-only seed contract, the per-tier job decomposition, the reserve-before-spend/idempotency, or the demand floor.

## Phase 4 scope (the next chat's job) — Tier 4: CDP × subservice

The last tier, and where the demand floor earns its keep — the CDP × subservice cross-product is the largest of the four. The two axes both already exist; Phase 4 just crosses them:

1. **Location axis = CDPs** (reuse `census_cdp.resolve_cdp_axis` exactly as Tier 3 — no census change).
2. **Service axis = subservices** (reuse `_derive_subservice_axis` exactly as Tier 2 — expand each main service into its city-agnostic variations).
3. **Add `4` to `SUPPORTED_TIERS`** and branch `run_coverage_audit_tier`: tier 4 = the CDP location branch (like tier 3) + the subservice service branch (like tier 2). The location-hub decision follows **Tier 2's** rationale, not Tier 3's — a subservice audit drops the location-hub ("missing CDPs") rows (measured against the main-service axis, a different tier), so `location_rows_shown` should be `False` for tier 4 and `diff["missing_locations"] = []` (the current `if tier == 2:` guard becomes `if tier in (2, 4):`). Confirm this — it's the mirror of the Tier-2 decision, applied to the CDP location universe.
4. **The demand floor (`coverage_cell_volume_min`) is the primary defense** against the CDP × subservice tail — it's already wired on cells; calibrate it (and `coverage_cdp_max`) from the first live Tier-3/4 CDP runs.
5. **Frontend:** add a **T4** tier selector chip; the report is already tier-agnostic (subservice labels come from `isSubservice = reportTier === 2` — extend to `reportTier % 2 === 0` or `reportTier in (2, 4)`; CDP location noun comes from `isCdp = reportTier === 3` — extend to `reportTier in (3, 4)`).

No new census integration, no new migration expected (Tier 4 reuses the Tier-3 `census_cdp_cache` + the Phase-0 tables/RPC/`coverage_audit` job type — re-verify against the live constraint set as always). Do NOT touch: the axes-only seed contract, the per-tier job decomposition, the reserve-before-spend/idempotency, or the demand floor.

---

## Open items (plan §7 — none block Phase 3)

- Module name (kept "Coverage Audit").
- ~~Location-hub keyword~~ — **RESOLVED (Phase 1):** `"<primary main service> <city>"`.
- ~~Service-axis confirmation UX~~ — **RESOLVED (Phase 1):** run-on-auto-derived + confirm-to-refine banner.
- ~~Tier-2 location-row question~~ — **RESOLVED (Phase 2):** subservice audits show subservice + cell gaps only; location-hub rows dropped (a Tier-1 concern). See the Phase 2 section.
- ~~CDP county scope~~ — **RESOLVED (Phase 3):** city-anchored (Scope B) — the counties the resolved footprint cities sit in scope which states are enumerated; the geocode-verified footprint containment decides membership. See the Phase 3 "Decisions made this phase".
- ~~Tier-3 location-row question~~ — **RESOLVED (Phase 3):** KEPT (like Tier 1 — a CDP hub is a main-service concept). See the Phase 3 section.
- Refresh cadence (on-demand v1 vs. monthly scheduled re-audit) — still on-demand only.
- Calibrate `coverage_cell_volume_min` + the daily ceiling + `coverage_cdp_max`/`coverage_cdp_cache_days` from a first live run (all placeholders — 10 / 200 / 60 / 365).

---

## Build conventions (from CLAUDE.md)

Pure logic unit-tested + mocked externals; `HTTPException` with string error codes; service-role Supabase; migrations in `writer/supabase/migrations/` applied live via the Supabase MCP; async work through `async_jobs` + the asyncio worker; best-effort/degrade-never-abort throughout; no new external dependencies or infra.
