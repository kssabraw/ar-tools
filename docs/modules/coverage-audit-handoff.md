# Coverage Audit — Build Handoff

**Module slug:** `coverage_audit` · **Authoritative plan:** `docs/modules/coverage-audit-module-plan-v1_0.md` (design authority; owner decisions §0; adversarial-review findings + resolutions §8).

**Status (2026-09-14):** **Phase 0 MERGED** (PR #1069 — pure core + tables/RPC/per-tier job type, applied live). **Phase 1 (Tier 1: city × main-service) MERGED** (PR #1070). **Phase 2 (Tier 2: city × subservice) MERGED** (PR #1072 — all CI green). **Phase 3 (Tier 3: CDP × main-service) MERGED** (PR #1076 — all CI green: platform-api tests + lint & typecheck + Netlify; squash-merged to `main` as `fc1afa5`; the new census CDP integration, worker-only; migration `20260914130000_coverage_audit_cdp_cache.sql` applied live). **Phase 4 (Tier 4: CDP × subservice) MERGED** (PR #1078 — all CI green: ruff + mypy + pytest + Netlify; squash-merged to `main` as `e80ed24`; pure wiring — no new census integration, no migration). **The module is now FEATURE-COMPLETE — all four tiers ship.** **Live-verified on the deployed worker 2026-09-14** (WheelHouse IT Fort Lauderdale) — the CDP path works end-to-end and two real bugs surfaced-and-fixed during verification (PRs #1082 / #1084 / #1085). See **"Live verification (2026-09-14)"** below. Remaining work is calibration only.

> ✅ **The live TIGERweb CDP query is VERIFIED (2026-09-14).** A Tier-3 audit on WheelHouse IT Fort Lauderdale (US, `business_location` + `GOOGLE_MAPS_API_KEY` set) enumerated **547 real Florida CDPs** into `census_cdp_cache` (state_fips=12), resolved the correct state/county (Florida / Broward), and — after the seed-city fix (#1084) — verified **5 real Fort Lauderdale CDPs** (Boulevard Gardens, Broadview Park, Franklin Park, Roosevelt Gardens, Washington Park) from 15 footprint candidates. `pick_cdp_layer` + the `STATE='12'` query shape are correct. Full detail below.

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

## Phase 4 — MERGED (Tier 4: CDP × subservice — the last tier), PR #1078

The largest cross-product, and where the demand floor earns its keep. **Pure wiring — no new census integration, no new engineering, no new migration.** Tier 4 crosses the two axes that both already exist: the CDP location axis (Tier 3) × the subservice service axis (Tier 2). Verified against the full live constraint set: `coverage_audits.tier` has no CHECK, `async_jobs` job_type already includes `coverage_audit`, and Tier 4 reuses the Tier-3 `census_cdp_cache` + the Phase-0 `coverage_audits`/`coverage_audit_usage`/`reserve_coverage_audit_calls` RPC — no migration applied.

**Backend (`services/coverage_audit_service.py`, `run_coverage_audit_tier`):**
- `SUPPORTED_TIERS = (1, 2, 3, 4)`.
- **Location axis** — the CDP branch extended `if tier == 3:` → `if tier in (3, 4):`, so tier 4 resolves the census CDP axis exactly like tier 3 (`census_cdp.resolve_cdp_axis`, `place_vocab = city_vocab + CDP names`). Cities stay the classifier place-vocab (a Tier-4 subservice page is still `/<subservice>-<city>/`).
- **Service axis** — the fresh-derive subservice branch (`else:`) now runs for tiers 2/4: it derives main services, then `_derive_subservice_axis(client, main_axis, representative_city=seed_city)` where `seed_city = loc_prov.get("seed_city")` — for tier 4 that comes from `census_cdp`'s provenance (confirmed it carries `seed_city`). The main-service branch stays `elif tier in (1, 3):`. The override (edited-axis) kind extended `"subservice" if tier == 2` → `tier in (2, 4)`, so an edited Tier-4 axis is tagged `subservice` + `confirmed`.
- **Location-hub rows DROPPED** (follows Tier 2's rationale, not Tier 3's): a subservice audit measures against the main-service axis, so the `if tier == 2:` guard that sets `diff["missing_locations"] = []` extended to `if tier in (2, 4):`. `location_rows_shown = tier in (1, 3)` (tier 4 → False, unchanged) and `primary_service` set only for `tier in (1, 3)` (tier 4 → None, unchanged) — both already excluded tier 4, so only verified.

**Router** — no change (validation reads `SUPPORTED_TIERS`; start / edit-axis re-run / seed-matrix already thread the run's tier).

**Frontend (`pages/CoverageAudit.tsx`):** a **T4** tier selector chip (label "CDPs · subservices", title "CDP × subservice", via new `tierLabel`/`tierTitle` maps); `isSubservice = reportTier === 2 || reportTier === 4`; `isCdp = reportTier === 3 || reportTier === 4`; `showLocations` default off for tiers 2/4; description paragraph gained the Tier-4 line. So T4 composes "Subservice × CDP cells", "Missing subservices", CDP location nouns, and drops the missing-locations table.

**Guardrails held (not touched):** the demand FLOOR (`coverage_cell_volume_min`) — the primary defense against the CDP × subservice tail, matters most at this tier — is still wired on cells; the axes-only seed contract; the per-tier job decomposition (one `coverage_audit` job per tier, the 60-min stale-timeout override already covers CDP geocoding); reserve-before-spend + cache-idempotent (CDP resolution has no paid calls; the demand fetch is the only metered step); best-effort/degrade-never-abort.

**Tests:** `tests/test_coverage_audit_service.py` — `test_tier_4_is_supported`, `test_run_tier_4_uses_cdp_axis_and_subservice_axis_and_drops_location_rows` (CDP location axis, SUBSERVICE service axis, location-hub rows DROPPED + `missing_locations == []`, `location_rows_shown` False, seed city threaded as the subservice representative city, footprint cities + CDP names in the place-vocab, subservice × CDP cells built), and `test_run_tier_4_override_axis_is_confirmed_subservice`.

> ⚠️ Tier 4 reuses Tier 3's `census_cdp.py`, whose live TIGERweb CDP enumeration query is **still unverified from the sandbox** (census.gov egress-blocked). It needs the same deployed-worker check as Tier 3 — run a Tier-3 or Tier-4 audit on a US client with `business_location` + `GOOGLE_MAPS_API_KEY` and inspect `provenance.location_axis` + the `census_cdp_cache` rows.

---

## Live verification (2026-09-14) — WheelHouse IT Fort Lauderdale

First live CDP run on the deployed PLATFORM worker (the sandbox is egress-blocked from census.gov, so this could only run on Railway). Enqueued a `coverage_audit` job directly into `async_jobs` (the same row `enqueue_coverage_audit` writes) and read the result back from the DB. Test client: a US client with a **street-address** `business_location` (`"2890 Marina Mile Blvd, 108 W State Rd 84 Suite, Fort Lauderdale, FL 33312"`), `GOOGLE_MAPS_API_KEY` + DataForSEO + `CENSUS_API_KEY` all set. It surfaced three real issues, all fixed and re-verified:

- **The live TIGERweb CDP query works** (the one previously-unproven piece): 547 FL CDPs enumerated + cached, correct Florida/Broward resolution, `pick_cdp_layer` + `STATE='12'` correct.
- **Bug 1 — worker lane (PR #1082, merged `c5249f2`):** `coverage_audit` was only claimable by the single sequential MAIN lane, so an audit queued ~15 min behind a long `dataforseo_rank` sweep. Added `coverage_audit` to `interactive_job_types` (it's a user-awaited, priority-0 job) so the idle interactive lane claims it. Race-safe (still in the MAIN catch-all; `status='pending'` guard picks one winner).
- **Bug 2 — CDP seed city (PR #1084, merged `6877916`):** the first run resolved the TIGERweb CDPs but verified **0** — `local_seo_silo._parse_area` mis-read the street-address `business_location` (`seed_city="2890 Marina Mile Blvd"`, `seed_state="108 W State Rd 84 Suite"`, `seed_country="FL 33312"`), so the containment footprint was a rooftop-sized box and the CDP verify queries carried garbage state/country. Fix: `census_cdp.resolve_cdp_axis` geocodes the raw `business_location`, adopts the geocode's own `locality`/`admin_area_level_1`/`country` (pure `resolve_seed_place`), and re-geocodes the clean city for a real city-bounds footprint. Corrects the seed city, footprint, classifier place-vocab, CDP verify queries, and the Tier-4 representative city in one place; a clean `"City, ST"` location is unchanged.
- **Bug 3 — demand-fetch scale (PR #1085, merged `859fc12`):** with CDPs now verifying, the service × CDP cell grid produced thousands of cell keywords, and `keyword_market.fetch_cached_market`'s single unchunked `.in_("keyword", [...])` overflowed the PostgREST URL (`URL component 'query' too long`). Latent until a caller passed a very large list. Fix: chunk the cache read at 200/query + the `refresh_keywords` upsert at 1000/body (general robustness fix for every `keyword_market` caller).

**Verified Tier-3 result (post-fix, 65s, `status: complete`):** `seed_city: "Fort Lauderdale"`, `states: [12]`, `county_names: ["Broward County"]`, **candidates 15 → verified 5** (Boulevard Gardens / Broadview Park / Franklin Park / Roosevelt Gardens / Washington Park CDP — all real Broward CDPs inside the city footprint), `location_rows_shown: true`. The 5 missing CDP location-page hubs are the actionable Tier-3 output; the 1,775 service×CDP cells (355 services × 5 CDPs) **all fell below the demand floor** (`cells_shown: 0`, `cell_floor: 10`) — the floor doing exactly its job (tiny CDPs have ~zero `"<service> <CDP>"` demand).

**Calibration finding — the service axis over-derives.** `n_services: 355` on this 1,146-URL site. Two pollution sources in the sample: (a) **other-metro location pages read as services** (`"Orlando Managed It Baldwin Florida"`, `"…Wadeview Florida"`) — the place-strip only knows the seed city's vocab (Fort Lauderdale + FL CDPs), so pages for OTHER cities the client serves aren't stripped; (b) **blog/news slipping the exclusion** (`"Press City Phishing Scam"`). This inflated axis is what made the cell grid 1,775 (and pricing it is what exposed Bug 3). Tightening the service-axis derivation — cap it, strip off-metro location slugs (the client's full target-city set, not just the seed), firmer blog/news exclusion — is the priority calibration item. It also makes **Tier 4 practical**: the subservice planner runs one LLM call per main service, so 355 main services ⇒ 355 planner calls (very slow/expensive); a sane ~15-service axis ⇒ ~15 calls. **Confirmed live 2026-09-14** — a Tier-4 run on this client sat in the subservice-planner loop for many minutes (the ~355 sequential Sonnet calls), which is exactly why de-polluting the service axis is the prerequisite for Tier 4 rather than a nice-to-have. The Tier-4 wiring itself is correct (unit-tested + shares the verified Tier-3 CDP axis); its cost, not its correctness, is the blocker.

## Sitemap override + higher scan caps — SHIPPED (PR #1087, merged `ee36dca` 2026-09-14)

Because the audit's accuracy depends on seeing **every** page (a missed page reads as a false gap), two site-scan improvements — **merged to `main` and deployed** (all CI green: ruff + mypy + pytest + Netlify):
- **Optional "Sitemap URL" on the audit setup** — `StartAuditRequest.sitemap_url` → stored on the run (`coverage_audits.sitemap_url`, migration `20260914150000`, applied live) → threaded to `site_page_index.discover_site_urls(..., sitemap_url=)` → `_fetch_sitemap_urls(seed_sitemaps=[...])`, which crawls that sitemap/sitemap-index **verbatim** (skips robots.txt + conventional-path guessing) and still follows an index one level into its children. For a site whose sitemap is at a non-standard path, or to point a VA straight at a large site's index; on miss, falls to the paid `site:` fallback. Carried forward on edit-axis re-runs, and the frontend field is seeded from the latest run so a plain "Re-run" keeps the override (clear it to opt back into auto-discovery). Blank = auto-discover (unchanged).
- **Audit-specific scan caps** (`coverage_sitemap_max_urls`=20000 / `coverage_sitemap_max_files`=100, vs the shared `local_seo_sitemap_*` 5000/30) so a big multi-sitemap site doesn't silently under-scan; when a cap truncates the crawl, `discover_site_urls` returns `source="sitemap_truncated"` and the run surfaces a visible **"some pages weren't scanned (N pages / M sitemaps) — gaps may be over-reported"** degraded note. `_fetch_sitemap_urls` returns `(urls, truncated)`.
- **Adversarial-review hardening (folded into the same PR):** truncation no longer false-positives when a complete crawl lands on exactly the cap (only flags when raw URLs strictly exceed the cap or a cap stopped the loop with sitemaps still queued); `discover_site_urls` gained a `paid_only` mode so the coverage-audit budget retry runs only the `site:` query instead of re-crawling the sitemap; and that retry (+ its `reserve_budget`) is guarded on a website domain existing (no wasted reservation on a sitemap-only, website-less run). All of the above are unit-tested (`tests/test_site_page_index.py`: seed override / index following / exact-cap-not-truncated / truncation / `paid_only` skips the sitemap / non-http override ignored). The `source="sitemap_truncated"` value was verified safe across all 10 `discover_site_urls` callers and the (unconstrained) `client_site_pages.source` column.

## Feature-complete — remaining follow-ups (calibration only; the live worker check is DONE)

All four tiers ship and the CDP path is live-verified. What's left is measurement, not engineering:

- **Live TIGERweb CDP-query worker check** (inherited from Phase 3, still open) — the census CDP enumeration is not sandbox-verifiable. Confirm on the deployed worker (a Tier-3/4 run on a US client with `business_location` + `GOOGLE_MAPS_API_KEY`); check `census_cdp.*` logs + the `census_cdp_cache` rows if the axis degrades.
- **Calibrate the placeholders from a first live CDP run:** `coverage_cell_volume_min` (10 — matters MOST at Tier 4, the largest cross-product), `coverage_cdp_max` (60), `coverage_cdp_cache_days` (365), and the daily ceiling `coverage_audit_daily_call_budget` (200). All are `config.py` env-tunable — recalibrate, don't change defaults blindly.
- **Refresh cadence** — still on-demand only (no scheduled monthly re-audit yet). A deliberate v1 scope choice.

---

## Next chat's job — calibration (NO more tiers to build; the live CDP check is DONE)

**The four-tier build is DONE and merged, and the live CDP path is verified** (see "Live verification (2026-09-14)" above — the TIGERweb query works, and the seed-city + demand-scale + worker-lane bugs it exposed are all fixed and re-verified). There is no Phase 5 and no new tier. What remains is **calibration**, and the **priority item is the service-axis over-derivation** (below), which both improves report quality AND is the prerequisite for a practical Tier-4 run.

**1. ✅ DONE — live CDP verification.** Tier-3 on WheelHouse IT Fort Lauderdale populated a real 5-CDP axis; the census/geocode caches are warm. To re-run for another client, enqueue a `coverage_audit` job (the `/coverage-audit` page, `POST /clients/{id}/coverage-audit {tier:3|4}`, or a direct `async_jobs` insert) and read `provenance.location_axis` + `census_cdp_cache`.

**1a. PRIORITY — fix the service-axis over-derivation** (`services/coverage_audit.py::derive_site_services` + the `_derive_service_axis` planner in `coverage_audit_service.py`). The live run derived **355 "main services"** from a 1,146-URL site, polluted by (a) other-metro location pages (`"Orlando Managed It Baldwin Florida"`) the seed-city place-strip can't strip, and (b) blog/news slugs (`"Press City Phishing Scam"`). Strip against the client's FULL target-city set (not just the seed city), firm up the `is_blog_url` exclusion, and cap the axis. This shrinks the cell grid AND makes Tier 4 practical (355 main services ⇒ 355 subservice-planner LLM calls today).

**2. Calibrate the placeholders (all `config.py` env-tunable — change the env on PLATFORM, don't blind-edit defaults). Observed from the live Tier-3 run:**
- `coverage_cdp_max` (60) — **leave as-is for now.** The Fort Lauderdale footprint verified only 5 CDPs (15 candidates), well under the cap; a denser metro is the test that would exercise it.
- `coverage_cell_volume_min` (10) — **the floor worked correctly**: all 1,775 service×CDP cells fell below it (tiny CDPs have ~zero `"<service> <CDP>"` demand), so Tier-3's value is the CDP location-hub gaps, not cells. Don't lower it — that would flood the report with zero-volume CDP cells. Re-check once the service axis is de-polluted (1a) so the grid is sane.
- `coverage_audit_daily_call_budget` (200) — the Tier-3 run reserved ~`ceil(1775/1000)`=2 calls for the (mostly-cached) demand fetch; a full 4-tier sweep's real spend can't be measured until the service axis is capped (today Tier 4's cost is dominated by ~355 LLM planner calls, not DataForSEO). Re-measure after 1a.
- `coverage_cdp_cache_days` (365) — fine as-is.

**3. Decide refresh cadence (owner call).** Still on-demand only. If a scheduled monthly re-audit is wanted, that IS a small new build (a `gsc_scheduler` hook enqueuing per-tier `coverage_audit` jobs, self-gated + due-checked — mirror `enqueue_due_domain_intel`). Ask the owner before building it.

**What NOT to do:** don't add a Phase 5 tier (there are only four), don't touch the axes-only seed contract / per-tier job decomposition / reserve-before-spend / the demand floor mechanism, and don't recalibrate a default without a live number behind it.

---

## Open items (plan §7)

- Module name (kept "Coverage Audit").
- ~~Location-hub keyword~~ — **RESOLVED (Phase 1):** `"<primary main service> <city>"`.
- ~~Service-axis confirmation UX~~ — **RESOLVED (Phase 1):** run-on-auto-derived + confirm-to-refine banner.
- ~~Tier-2 location-row question~~ — **RESOLVED (Phase 2):** subservice audits show subservice + cell gaps only; location-hub rows dropped (a Tier-1 concern). See the Phase 2 section.
- ~~CDP county scope~~ — **RESOLVED (Phase 3):** city-anchored (Scope B) — the counties the resolved footprint cities sit in scope which states are enumerated; the geocode-verified footprint containment decides membership. See the Phase 3 "Decisions made this phase".
- ~~Tier-3 location-row question~~ — **RESOLVED (Phase 3):** KEPT (like Tier 1 — a CDP hub is a main-service concept). See the Phase 3 section.
- ~~Tier-4 location-row question~~ — **RESOLVED (Phase 4):** DROPPED (mirrors Tier 2 — a CDP × subservice audit measures against the main-service axis, so re-reporting a location-hub gap would double-count Tier 3 and rank against a keyword absent from this tier's axis). `location_rows_shown = False`, `diff["missing_locations"] = []`. See the Phase 4 section.
- ~~Live TIGERweb CDP-query worker check~~ — **RESOLVED (2026-09-14):** verified on the deployed worker (WheelHouse IT Fort Lauderdale); 547 FL CDPs enumerated, 5 verified. See "Live verification (2026-09-14)".
- **NEW — service-axis over-derivation (priority calibration):** the site-service derivation over-produces (355 on a 1,146-URL site) — off-metro location pages + blog/news leak in. Strip against the full target-city set + firmer blog exclusion + a cap. Prerequisite for a practical Tier 4. See "Live verification".
- Refresh cadence (on-demand v1 vs. monthly scheduled re-audit) — still on-demand only.
- Calibrate `coverage_cell_volume_min` / daily ceiling / `coverage_cdp_max` / `coverage_cdp_cache_days` — **initial live read done** (see the calibration bullets above; defaults kept, re-measure after the service axis is de-polluted).

---

## Build conventions (from CLAUDE.md)

Pure logic unit-tested + mocked externals; `HTTPException` with string error codes; service-role Supabase; migrations in `writer/supabase/migrations/` applied live via the Supabase MCP; async work through `async_jobs` + the asyncio worker; best-effort/degrade-never-abort throughout; no new external dependencies or infra.
