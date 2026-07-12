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
| Desktop `serp_results.csv` / raw 02_pull_serp output | **UNKNOWN from the cloud side** — the raw JSON had `address_info` (the neighborhood work keyed on `address_info.city`); whether the CSV writer kept lat/lng columns only the desktop can answer | ⚠ one `head -1` on the desktop settles it |

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

| Option | What | Cost | Verdict |
|---|---|---|---|
| **A. Desktop CSV check** | `head -1` of `serp_results.csv` — did 02_pull_serp keep lat/lng? | $0, 1 min | **Do first, either way** |
| **B. Historical backfill** (if A = yes) | Load coordinates from already-paid CSVs → new `market_scanner.serp_geo` cache; coarse full-board proximity | $0 API; a loader script | High value if available |
| **C. Pass-2 proximity** (recommended regardless of A) | Scout/tryout retain full-SERP coordinates for the markets we actually consider; brief renders §2 | ~$0.004/market incremental | **Recommended v1** |
| **D. Wide fresh pull** | Depth-100 SERP w/ coords for all 34,352 markets | ~34,352 × $0.004 ≈ **$137** (+ optionally covered by the next quarterly re-scan retaining coords for free) | Not now — defer to the next scheduled re-scan, which should simply STOP DISCARDING coordinates |

The sharpest observation from the feasibility work: **option D is eventually
free** — the quarterly re-scan already makes these exact calls; the fix is
retaining lat/lng at write time (scanner-side change to 02_pull_serp's
output schema + the Supabase loader). Proximity then arrives board-wide with
the next data vintage at zero marginal cost.

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
