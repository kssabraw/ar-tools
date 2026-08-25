# LeadOff — GBP Placement Advisor (Plan v1.0): demand-aware "where should the GBP live"

**Status:** PLANNED — owner decisions locked 2026-08-25 (§1). Nothing built yet.
**Relationship:** the demand-side upgrade of the Proximity signal
(`docs/modules/leadoff-proximity-plan-v1_0.md`, BUILT) and the live-GBP market
map (PR #719/#721, SHIPPED). Reuses the market map's captured competitor pins
(`public.leadoff_gbp_pins`), the octant/decay vocabulary
(`services/leadoff_proximity.py`, `services/maps_octants.py`), and the Census
plumbing precedent (`leadoff_geocode`, `leadoff_counties`, `leadoff_income`).
Deliberately designed so the **scoring core is a pure module** the post-client
geo-grid stack can re-use later (client-side "should we add/move a location").

## 1. Owner decisions (2026-08-25 — these are the spec)

1. **Use case: BOTH.** Ranked zone recommendations by default, PLUS the user can
   drop a pin on the map / paste an address or GBP link and get that exact
   point scored against the zones (this absorbs the two deferred market-map
   follow-ups: click-to-drop and re-anchor).
2. **Scope: LeadOff first, client later.** Ships on the market brief
   ("if we entered this market, here's where a GBP wins"). The scoring core is
   pure + input-agnostic so the client workspace can later feed it geo-grid +
   client data instead.
3. **Demand data: include paid demand signals** — as an **opt-in paid layer on
   top of a free core**, per the honesty caveats in §4.3. The core must work at
   $0/market.
4. **ROI depth: score now, dollars later.** v1 emits a 0–100 placement score +
   plain-English narrative per zone. The dollar layer (expected leads × lead
   value via the tryout economics) is gated on the calibration loop (§8)
   validating zone scores against real geo-grid outcomes first.

## 2. The gap this closes

Today's `placement_recommendation` is **competition-only**: weakest octants →
a suggested pin at ⅔ radius along that bearing, reverse-geocode-named, with an
unpopulated-zone filter (a pin that names to no locality is dropped). It never
asks whether **customers** are in the gap. An octant can be empty of ranked
competitors because it is empty of *people* — the current filter catches water
and industrial land, but not "3,000 residents vs 60,000 residents". "Best
access to potential customers + best ROI" requires the demand surface.

The physics being modeled: the local pack heavily weights **searcher-to-GBP
proximity**, so a GBP's catchment is roughly "searchers near it, discounted by
how many strong competitors are also near them". Placement quality is therefore
a classic gravity read: reachable demand ÷ nearby competitive pressure.

## 3. The model (deterministic; no LLM; pure core)

For a candidate point `c` in the market:

```
demand_access(c)  = Σ_bg  households(bg) × w_cat(bg) × 1/(1 + d(c,bg)/D_DEMAND)
pressure(c)       = Σ_pin max(reviews,1)            × 1/(1 + d(c,pin)/D_DECAY)
placement_score(c)= 100 × norm(demand_access) × (1 − norm(pressure))
```

- `bg` = Census block groups within the analysis radius (§4.1); `pin` = the
  live competitor GBPs already captured by scout/tryout (`leadoff_gbp_pins`).
- `1/(1+d/2mi)` decay and `max(reviews,1)` weighting are **verbatim** the
  proximity plan's §1.2 prototype formula — one vocabulary, one calibration
  story. `D_DEMAND` defaults larger than `D_DECAY` (customers travel farther
  than pack-proximity reaches; both config knobs, §10).
- `w_cat` = optional per-category demand weights on the same free Census pull
  (median income; housing age for repair trades — older housing stock → more
  roof/plumbing/chimney work). Ships ON but weight-0 until calibrated.
- `norm()` = min-max over the market's own candidate set (a score is
  market-relative, like Rankability — never comparable across markets, and the
  UI must say so).

**Candidate generation:** the same centred 1-mile lattice as the geo-grid
(`maps_grid`) over the analysis radius → score every cell → greedy pick of the
top zones with a `placement_min_separation_miles` spacing so two adjacent cells
don't both surface → reverse-geocode-name the winners (existing
`maps_geocode.reverse_geocode_points` + cache; the existing unpopulated-zone
drop applies) → keep top 3–5 **zones**.

**Scoring an arbitrary point** (the "Both" half): `score_point(lat, lng)` runs
the same two sums for one point and returns its score, its percentile vs the
market's cell distribution, distance to the best zone, and the nearest
competitors — so a dropped pin gets "this address scores 61/100 — 78th
percentile; the best zone (near Maumelle) scores 84, 4.2 mi NW".

## 4. Data sources & costs

### 4.1 Free core (always on, $0/market)

- **Demand:** US Census **ACS 5-year block-group** data via the free Census
  API (households `B25001`/population `B01003`, median income `B19013`,
  housing-age `B25034` buckets) + **TIGERweb block-group centroids** for the
  counties overlapping the radius (county already resolvable via the existing
  `city_counties` map / coordinates endpoint). Same infra family as the three
  Census integrations already live (geocoder batch, geographies/coordinates,
  income backfill) — free, keyless-or-free-key, cacheable ~forever (ACS
  updates annually). Cached in an app-owned table (§6) so a market's second
  read is a DB hit.
- **Competition:** the live GBP pins scout/tryout already persist — **no new
  paid call**. A market with no pins yet is offered the existing
  "Plot the live GBPs (~$0.004)" map-refresh first (PR #721) — the advisor
  needs the real field.
- **City-level demand total:** the `demand_trend` volume the scout already
  paid for calibrates the narrative ("~1.9k searches/mo across the metro"),
  not the spatial shape.

### 4.2 Already-paid signals folded in

`lead_values`, `rev_win`, capture-tier economics — reserved for the dollar
layer (§8); v1 narratives may cite the city search volume + lead value as
context lines but must not multiply them into a per-zone dollar claim.

### 4.3 The opt-in PAID demand layer — honest scoping (owner accepted the caveats)

The only purchasable sub-city search-demand signal is **per-ZIP Google Ads
search volume** (DataForSEO `keywords_data/google_ads/search_volume` with
postal-code `location_code`s; ~$0.05/task-batch → **~$1.50–4/market**
depending on ZIP count, budget-guarded via the existing `leadoff_spend`
ledger). When present, ZIP volumes **re-weight** the Census surface
(demand share by ZIP, distributed within a ZIP by block-group households).

Hard caveats, stated in-product:

1. **Google thresholds low volume at small geos.** Niche categories
   (chimney sweep) will read zero/null in most ZIPs — the layer only adds
   signal for high-volume categories in real metros. When >60% of ZIPs come
   back null, the scan is marked `inconclusive` and the surface stays
   Census-only (the spend is honest-noted, not silently absorbed).
2. **Phase-0 feasibility probe required** (§9): one ~$0.05 probe on a known
   high-volume market must confirm DataForSEO actually returns non-null
   postal-code volumes before the layer is built past the probe. If the probe
   fails, the layer is dropped from v1 and this section becomes the record of
   why.
3. Never on by default — a per-market "Deep demand scan (~$X)" button with the
   estimate shown first, mirroring the scout affordance.

## 5. Surfaces & UX (the "Both" experience)

On the market brief's Proximity card (below the live-GBP map, which is the
prerequisite):

1. **Placement zones** — top 3–5 zones as a new pin class on the existing
   `MarketMap` (distinct from the current octant diamonds, which they
   replace when the advisor has run), each with a card: score, name
   ("near Maumelle"), households reachable, competitive pressure read,
   nearest-competitor distance, and the plain-English line. Zones are the
   **default** answer.
2. **Drop / paste a candidate** — click the map (inverse of the existing
   `projectToPixel` Mercator math) **or** paste an address/GBP link (existing
   `/clients/gbp/resolve`) → the point is scored via `score_point` and
   rendered as a scored candidate pin with its percentile-vs-best-zone line.
   Multiple candidates can be compared side-by-side (the "compare my office
   vs the partner location" case).
3. **Re-anchor (optional toggle):** the octant bars re-centre on a chosen
   candidate so "what does the field look like from *here*" reads correctly.
   Display-only; the market's grade never re-anchors (grade safety, §7).

## 6. Data model & code map (planned)

- `services/leadoff_placement.py` — the **pure core**: surface build,
  `score_grid`, `score_point`, zone selection, narrative lines. Unit-tested
  like `leadoff_proximity`. Zero imports from LeadOff impure modules so the
  client-side reuse is an import, not a port.
- `services/census_demand.py` — impure fetch + cache of ACS block-group rows.
  App-owned table **`census_block_demand`** (GEOID pk, county, centroid
  lat/lng, households, population, median_income, housing-age buckets,
  pulled_at; ~annual freshness). Filled per-market on first advisor run via an
  async **`leadoff_placement`** job (Census pulls for a metro are dozens of
  requests — background, reaper-safe, self-continuing like `leadoff_geocode`).
- Optional paid layer: **`zip_demand`** table (zip, category_id, volume,
  pulled_at) + `leadoff_zip_demand` job, budget-guarded.
- Results **computed on read** from the caches (like forecasting — no result
  table), EXCEPT the frozen calibration copy (§8). API:
  `GET /leadoff/placement?city_id&category_id` (+ `POST …/placement/score-point`),
  degrading exactly like `/leadoff/proximity` (`{available:false, reason}` —
  `no_gbp_pins` → nudge to the $0.004 map refresh; `census_not_cached` →
  enqueue + poll).

## 7. Honesty guards & guardrails

- **Grade safety (unchanged rule):** placement is display/advice only — it
  never touches the board grade, `competitor_locations`, or
  `proximity_opportunity`'s inputs.
- **Thin data floors:** < `placement_min_pins` (default 5, same bar as
  proximity) competitor pins → no zone ranking, only the demand surface with a
  "field too thin to score against" note. < `placement_min_blockgroups` → the
  advisor declines entirely (a rural one-block-group town has no meaningful
  sub-city placement question).
- **Market-relative score:** the 0–100 is normalized within the market;
  copy must never compare scores across markets.
- **Real-presence guardrail (in-product copy):** recommendations are "the best
  area to establish a real, staffed location". Google requires a GBP address
  to be a genuine staffed premises; the tool must not present zones as
  "register an address here" advice. SAB nuance stated: an SAB's ranking still
  anchors on its verified address even though the address is hidden, so
  placement matters for SABs too (`clients.is_sab` exists for the client-side
  version).
- **Point-in-time:** zones derive from the last-captured pin field; the card
  carries the capture date + the existing Refresh-map affordance.

## 8. Calibration → dollars later (owner decision #4)

Like proximity, each create-client handoff freezes the market's zone set +
the chosen/candidate point's score into `leadoff_predictions` (new
`placement` jsonb). The post-client geo-grid then grades whether high-score
zones actually correspond to better pack outcomes. **Only after** that loop
shows signal does the dollar layer ship: expected leads/mo per zone =
zone demand share × city volume × pack CTR assumption × capture, valued at
`lead_values` — clearly labeled estimates, reusing tryout economics. Until
then, no dollars in the UI.

## 9. Phasing

- **Phase 0 — probes ($0.05 total, owner-run or via the deployed worker):**
  (a) Census ACS + TIGERweb pull for one real market, confirming block-group
  coverage + centroid quality; (b) the one ZIP-volume probe (§4.3.2).
  Findings recorded here before Phase 1 code.
- **Phase 1 — free core on LeadOff:** `census_demand` cache + job,
  `leadoff_placement` pure core + tests, zones on the brief map + cards,
  degraded states. $0/market beyond the existing pins.
- **Phase 2 — candidate scoring:** click-to-drop (inverse projection), paste
  resolve, `score_point`, side-by-side compare, optional octant re-anchor.
- **Phase 3 — opt-in paid ZIP layer** (only if the Phase-0 probe passed):
  scan button + estimate + budget guard + surface re-weighting +
  `inconclusive` honesty path.
- **Later (out of this plan's scope):** client-workspace version fed by
  geo-grid + client GBP; dollar layer post-calibration.

## 9a. Phase 0a findings + Phase 1 build status (2026-08-25)

**Phase 0a (Census probe) — GO, validated via the worker path.** The session
sandbox egress proxy blocks census.gov (`api.census.gov:443` → `403 CONNECT
policy denial`), so the ACS/TIGERweb probe could not run from the sandbox
(anticipated). It didn't need to: the deployed worker's reachability of
census.gov is already proven by three live integrations —
`leadoff_income` (api.census.gov ACS5), `leadoff_geocode`
(geocoding.geo.census.gov batch), `leadoff_counties`
(geocoding.geo.census.gov geographies/coordinates) — and every ACS mechanic
(browser-UA + JSON Accept past Akamai, optional `CENSUS_API_KEY`,
retry/backoff, `leadoff_income_acs_year`=2023) is reused from those precedents.
The **one unproven host is TIGERweb** (`tigerweb.geo.census.gov`, block-group
centroids — the ACS API returns no geometry). The `leadoff_placement` job
resolves the block-group layer id from the service metadata (robust to vintage
drift) and **reports centroid coverage + a 5-row sample on every run**, so the
first live run against Little Rock (city_id 4119403) confirms it; if TIGERweb
is unreachable, `merge_demand_rows` yields 0 rows and the advisor degrades to
`available:false` with an explicit note (no crash). Phase 0b (paid ZIP probe)
NOT run — it only gates Phase 3.

**Phase 1 — BUILT (behind `leadoff_placement_enabled`, default True; not yet
live-verified).**
- Pure core `services/leadoff_placement.py` (`build_demand_surface`/`score_grid`/
  `score_point`/`select_zones`/`build_zones`/narrative) — zero impure imports,
  reuses `leadoff_proximity.haversine_miles` + the `maps_grid` 1-mile lattice.
  Unit-tested `tests/test_leadoff_placement.py` (21 cases: weight-0 households
  parity, gravity decay, market-relative min-max, 2-mi zone spacing, point
  percentile, empty/flat edges).
- `services/census_demand.py` — ACS block-group + TIGERweb centroid fetch,
  county discovery via edge-point `geographies/coordinates`, cache upsert, the
  `leadoff_placement` async job, and the impure market read (`market_placement`/
  `score_market_point`) tying pins + cache + pure core + reverse-geocode naming.
  Pure helpers unit-tested `tests/test_census_demand.py` (11 cases).
- Cache table `census_block_demand` (migration `20260825150000`, applied live)
  + `async_jobs` CHECK recreated with `leadoff_placement` (`20260825160000`,
  applied live).
- `GET /leadoff/placement` + `POST /leadoff/placement/score-point` (the §5.2
  "Both" backend half) on `routers/leadoff.py`; job dispatch in `job_worker`.
- Frontend: ranked zones as a numbered pin class on `MarketMap` (replacing the
  octant diamonds once the advisor has run) + a "Best areas to plant a GBP"
  card list in `ProximityDetail`, with every degraded state (`no_gbp_pins` →
  map-refresh nudge; `census_not_cached` → poll spinner; `too_few_blockgroups`;
  `thin_field`). Config knobs per §10.
- **Grade safety honored:** placement reads only `leadoff_gbp_pins` +
  `census_block_demand` and writes only its own cache — never the board grade,
  `competitor_locations`, or `proximity_opportunity`.
**Phase 2 — BUILT (the "Both" experience, §5.2/§5.3).**
- `pixelToLatLng` (inverse of `projectToPixel`) added to `components/maps/visuals.tsx`.
- `MarketMap` gained a `candidates` pin class + an `onMapClick` click-to-drop
  handler (crosshair cursor; competitor pins keep their own click).
- `ProximityDetail` scores dropped/pasted points via
  `POST /leadoff/placement/score-point` and compares them side-by-side
  (`CandidateScorer`): per-candidate score, market percentile, reachable
  households, nearest competitor, and delta-vs-best-zone; paste reuses
  `/clients/gbp/resolve`; capped at 6. The optional **octant re-anchor** toggle
  re-centres the octant defense bars on a candidate client-side (view only —
  never re-anchors the market's grade), reusing the proximity `1/(1+d/2mi)`
  defense. Only active when zones are available; the legacy GBP reference-pin
  input stays for the proximity-only (no-zones) path. `tsc -b` clean.

- **Not yet built:** Phase 3 paid ZIP layer; the calibration freeze (§8).

## 10. Config (planned knobs, `config.py`)

`leadoff_placement_enabled`, `placement_demand_decay_miles` (D_DEMAND, ~5),
`placement_pressure_decay_miles` (D_DECAY, 2 — locked to proximity's),
`placement_zone_count` (4), `placement_min_separation_miles` (2),
`placement_min_pins` (5), `placement_min_blockgroups` (8),
`placement_income_weight` / `placement_housing_age_weight` (0 until
calibrated), `leadoff_zip_demand_enabled` (False),
`placement_zip_null_share_inconclusive` (0.6).
