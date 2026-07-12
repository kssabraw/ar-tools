# LeadOff — Proximity Signal (Plan v1.0): the unmodeled Distance pillar

**Status:** FEASIBILITY VALIDATED (partial) + DESIGN — no wide pull run, no
scoring change made. Owner decision gates everything past the free tier.
**Relationship:** the pre-client sibling of the app's post-client geo-grid
stack (`services/maps_octants.py`, `services/maps_geocode.py`,
`services/maps_analytics.py`) — shared method + vocabulary (octants, weak
zones, `dest_point` pins) by design.

## 1. Feasibility finding: PARTIAL YES, with a sharp resolution caveat

### 1.1 Which world we're in (the step-1 inventory)

| Source | Coordinates? | Checked |
|---|---|---|
| `market_scanner.serp_top5` (Supabase, serves the board/brief) | **NO** — 7 columns, no lat/lng, no address_info | live schema read |
| DataForSEO Maps SERP response (what every pull returns) | **YES** — per-business GPS lat/lng + structured `address_info` | current API docs |
| Desktop `serp_results.csv` | **RESOLVED (2026-07-12):** no lat/lng, and the `02_serp.json` checkpoint is only a progress ledger — coords are gone. BUT a populated text **`address`** column survived (~88.5% of rows) → free geocode path, see §5 option 0 | `head -1` done |

So: the *loaded* data cannot support proximity analysis; the *API* always
could; the *already-paid historical* data might. If the desktop CSV kept
lat/lng, a coarse historical backfill is **$0**. If not, proximity is a
fresh-pull feature (costs in §5).

### 1.2 Prototype on a real market (zero spend)

Run on the 7 competitor GBP pins the app already holds for the Melbourne
roofing market (First Class Roofing's turf; center −37.7898, 144.9713,
5 mi). Method: bearing → octant per competitor, prominence-weighted
(reviews) and distance-decayed (1/(1+d/2 mi)) coverage per octant:

```
SE  40.7  ████████████████  (All Seasons 127rev @4.8mi, MRR&R 7rev @1.9mi)
W   38.8  ███████████████   (Roof Makeover Specialist 172rev @6.9mi)
N   27.3  ██████████        (Seven Roofing 53rev @1.9mi)
NE  20.8  ████████          (Roofrite 61rev @3.9mi)
NW  13.9  █████             (RR Northern Suburbs 63rev @7.0mi)
S   10.3  ████              (Melbourne Roof Repairs 19rev @1.7mi)
E    0.0                    ← empty
SW   0.0                    ← empty
```

The read is mechanically sound and *appears* actionable ("place the GBP
east or southwest — no major rival is anchored there").

### 1.3 The cross-validation that sets the resolution limit

FCR has real post-client geo-grids. Its measured weak octants are
**S / SE / E** (SW recurring in weak areas) — the client *loses* pack cells
in zones my 7-pin read calls "empty of competitors." Both are true: no
**major tracked rival** is anchored east/southwest, yet somebody still wins
those cells — **hyper-local small players who never make a top-5 leaderboard**.

**Conclusion (the honest one):** top-5 pins under-sample the field.
"Empty octant among major rivals" is a *different claim* than "undefended
zone." A trustworthy pre-client proximity read needs the **full depth-100
Maps SERP with per-business coordinates** — data every pull already returns
and our pipeline currently throws away. Feasibility: **YES for the method,
NO for top-5-only data as the sole input.**

## 2. What the signal computes (design)

Per market (city × category), from the full competitor pin set:

1. **Octant coverage map** — per compass octant: competitor count,
   prominence mass (review-weighted), distance-decayed defense score
   (§1.2 formula; constants tunable, eventually calibratable).
2. **Underserved-zone read** — octants whose defense score sits below a
   fraction of the market median, intersected with *populated* area (an
   empty octant over water/industrial land is not an opportunity — reuse
   `maps_geocode` reverse-geocoding to name the zone and drop unpopulated
   ones, exactly like `report_weak_locations` does post-client).
3. **Placement recommendation** — "where should the GBP sit": suggested
   pin(s) via the geo-grid module's own `maps_octants.dest_point` at a
   bounded radius along the weak-octant bearing, each labeled with its
   nearest locality name. Same vocabulary the team already reads in
   Local Rank Analysis reports.
4. **`proximity_opportunity` (0–1)** — the share of the market's
   demand-space that is weakly defended (mean of normalized per-octant
   weakness). Surfaced as a **context column + brief section, NOT a grade
   input** — Distance is a "where to enter" lever, not a "whether to enter"
   veto, and the no-frankenscore rule stands. (If calibration Phase 1 ever
   shows proximity predicts rank outcomes, weighting it into rankability is
   a *proposal* under that framework — leadoff-calibration-plan §5.)

## 3. Where it surfaces

- **Market brief:** a "Proximity" section — octant bars, named underserved
  zones, suggested placement pins (Google Maps deep links, like the
  geo-grid's weak-area table).
- **Tryout:** free rider — the tryout already pulls the depth-100 SERP per
  gated category; retaining coordinates costs nothing and gives every
  tryout a proximity read immediately.
- **Scout:** the natural Pass-2 home (+~$0.004/market — one Maps SERP live
  advanced call for the primary category, coordinates retained).
- **Create-client handoff:** the placement recommendation lands in the
  campaign-goal notes ("suggested GBP zone: E — Doncaster side"), and the
  frozen prediction (calibration Phase 0) records the proximity read so the
  geo-grid later grades it — the two modules close their own loop.

## 4. Method sharing with the geo-grid module (don't reinvent)

Reuse, not port: `maps_octants` (octant math, `dest_point`, weakness
ranking), `maps_geocode` (reverse-geocode + locality aggregation + the
geocode cache), `maps_analytics` vocabulary (ring/octant rollups). The
LeadOff variant differs only in its input (competitor pins vs client rank
grid) — a small pure `proximity.py` computing §2 from a pin list, calling
into the existing helpers. Post-client, the geo-grid remains the ground
truth; pre-client proximity is the forecast the geo-grid later verifies.

## 5. Cost/benefit — the owner's decision menu

**Option A resolved (desktop `head -1`, 2026-07-12):** `serp_results.csv`
kept **no lat/lng**, and the `02_serp.json` checkpoint is only a progress
ledger of completed keys — so coordinates are genuinely gone, nothing to
re-parse. **BUT** the CSV *did* retain a populated **text `address`** column:
150,478 / 169,991 rows (~88.5%) carry a street address ("177 Broadway",
"154 Grand St #103"); the ~11.5% blanks are service-area businesses with no
address. That opens a door the original menu missed:

| Option | What | Cost | Verdict |
|---|---|---|---|
| **0. Census-geocode existing addresses** (the head -1 finding) | Reconstruct "`<address>, <city>, <state>`" and batch through the **free US Census Geocoder** (keyless, no DataForSEO spend) → coordinates for ~88% of the field | **$0** | **BUILT — the chosen path** |
| **0b. Outscraper SAB fill** (NEW) | The ~12% service-area businesses have no address, so Census can't place them — but Outscraper returns Google's **pin lat/lng even when the address is hidden** (our `gbp_service` already reads it). Query by name+city to recover them | ~**$20–40** board-wide (pennies for test markets) | built, **flag-gated off** — enable only if the SAB gap visibly hurts the signal |
| ~~A. Desktop CSV check~~ | done → no coords, but addresses present (drove option 0) | — | resolved |
| ~~B. Historical coord backfill~~ | not possible — no coords on disk (option 0 replaces it) | — | n/a |
| ~~C. Pass-2 proximity~~ | exact pins for considered markets | ~$0.004/mkt | superseded by 0/0b for the initial build |
| ~~**D. Wide fresh pull ($137)**~~ | Depth-100 SERP w/ exact coords, all markets | ~$137 | **DECLINED by owner (2026-07-12)** — recover from owned data instead; revisit only if 0+0b prove insufficient |

**On the SAB gap (option 0b):** the ~12% missing are service-area
businesses — mobile trades with no storefront. They may be the *least*
relevant competitors for an address-placement signal (nothing fixed to
cluster against), so the free 88% might be the *right* population, not a
compromise. 0b exists as the cheap, already-integrated, app-side fix **if
the gap turns out to matter** — decided on evidence, not bought blind.

**Option 0 tradeoffs (be honest):**
- **~88% coverage** — misses the 11.5% SAB rows (which have no address at all,
  so no pull recovers them cheaply either).
- **Street-centroid, not the GBP pin** — the geocoder resolves to the street
  segment centroid, not the business's exact map marker. For a **dense
  downtown** (many competitors on the same few blocks) this coarseness can
  blur the very clustering the signal measures — so option 0 is a
  **feasibility test**, not necessarily the final data. If the sub-zone
  signal is real but noisy on dense markets, *that* is the earned argument
  for the $137 exact-pin pull (option D) — decided on evidence, not guessed.
- **$0 and already-owned data** — the whole point: prove the signal cheap
  before paying to sharpen it.

The sharpest structural observation still holds: **option D is eventually
free** — the quarterly re-scan already makes these exact calls; the fix is
retaining lat/lng at write time (02_pull_serp output schema + the loader).

### 5a. Prototype (runs desktop-side — that's where the addresses are)

The loaded Supabase `serp_top5` did **not** retain the address column (7
cols: city_id/category_id/rank_position/business_name/rating/review_count/
domain), so the addresses live only in the desktop `serp_results.csv`. The
$0 prototype therefore runs **desktop-side** (CSV + `CENSUS_API_KEY` +
census.gov reachable there): geocode the La Jolla plumber/locksmith/
landscape-architect + KC locksmith rows, compute the §2 octant clustering +
underserved zone, and eyeball whether the sub-zone read matches known
geography (La Jolla's field should lean toward central San Diego). Reference
script: `docs/reference/leadoff-scanner/proximity_prototype.py`.

### 5c. The import mechanism — BUILT (app-side, "off the desktop")

The whole coordinate recovery now lives in the app; the desktop's only role
is a **single one-time upload** of the addresses it alone holds.

1. **Desktop (once):** `docs/reference/leadoff-scanner/upload_competitor_addresses.py`
   reads `serp_results.csv` and upserts (city_id, category_id,
   rank_position, business_name, domain, review_count, address) into the new
   app-owned **`public.competitor_locations`** via `SUPABASE_DB_URL`
   (~170k rows, one pass, seconds; idempotent; a changed address nulls the
   stale coordinate). After this the desktop never touches proximity again.
2. **App (worker):** the `leadoff_geocode` job (`services/leadoff_geocode.py`,
   migration `20260712180000`, applied live) geocodes the addressed rows via
   the free Census batch geocoder, optionally fills SABs via Outscraper
   (`leadoff_geocode_sab_outscraper`, default off), writes lat/lng +
   `geo_source`, and reports coverage + the La Jolla/KC validation on every
   run. The worker reaching `geocoding.geo.census.gov` is the same egress the
   permits BPS pull proved.
3. **Next phase (gated on these coordinates validating):** the proximity
   computation itself — `services/leadoff_proximity.py` reusing
   `maps_octants` for octant clustering / underserved zones, then the brief
   surfacing (§2/§3). Not built until the imported coordinates prove the
   signal real on the test markets (working agreement: validate before build).

`public.competitor_locations` is app-owned (not `market_scanner`, which the
scanner loader drop/recreates + grant-strips). No DataForSEO spend anywhere;
Census is free, Outscraper (if enabled) is the only paid step.

## 6. Coordination (cross-repo / cross-session)

- **Proposed shared table (NOT created yet):** `market_scanner.serp_geo`
  (city_id, category_id, pins jsonb [{name, lat, lng, reviews, rating,
  rank_position}], pulled_at) — written by app scout/tryout and/or the
  scanner's 02_pull_serp; same freshness conventions as the other caches.
  Do not create until the desktop CSV check (option A) decides whether the
  scanner backfills it or the app populates it lazily.
- **Desktop memory-file note to mirror** (cloud can't edit it): "Proximity
  signal designed (ar-tools docs/modules/leadoff-proximity-plan-v1_0.md).
  Action on scanner side: (1) check serp_results.csv for lat/lng columns;
  (2) next re-scan should retain per-business coordinates (02_pull_serp) —
  proposed shared cache `market_scanner.serp_geo`, contract in the doc."
- No scoring change anywhere in v1; `proximity_opportunity` is context, and
  any future weighting goes through the calibration framework's
  proposes-never-executes gate.

## 7. Validation plan before any build

1. Option A (desktop, $0).
2. One paid probe (~$0.01): depth-100 SERP for La Jolla plumber + KC
   locksmith **retaining coordinates**, render the §2 read, eyeball against
   known geography (La Jolla's field concentrating toward central San Diego
   would be the expected, checkable pattern).
3. Only then wire Pass-2 (option C) — and record the proximity read into
   calibration predictions so the geo-grid grades it over time.
