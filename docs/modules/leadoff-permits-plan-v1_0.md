# LeadOff — Building-Permits "Prospect Pipeline" Column (Plan v1.0)

**Status:** SOURCE NAILED + DESIGN + ready-to-run scanner script
(`docs/reference/leadoff-scanner/05b_pull_permits.py`). The pull itself runs
on the desktop (scanner pipeline + Supabase loader live there; the cloud
session's egress can't reach census.gov). **Validation gate:** run
`05b --validate` on the two test markets and eyeball before the wide pull —
which is free either way.

## 1. Source of truth (corrects the task's premise)

Place-level Building Permits Survey data is **NOT in the Census Data API**
(`api.census.gov` has no place-level BPS dataset — the economic-indicator
timeseries is national/regional only). It ships as **keyless flat files**:

- `https://www2.census.gov/econ/bps/Place/<Region><YYYY>A.TXT` — annual
  (survey date `YYYY99`), regions Northeast/Midwest/South/West.
- Layout per `www2.census.gov/econ/bps/Documentation/placeasc.pdf`: FIPS
  state (2) + FIPS place code, CBSA/county codes, place name, then
  buildings/units/valuation for 1-unit, 2-unit, 3–4-unit, 5+-unit classes
  (reported and imputed variants — **use the imputed estimates**, they are
  the published numbers).
- Monthly current-year files exist; v1 uses annual only (a leading
  indicator with a 6–18-month horizon does not need monthly freshness).

Consequences: `CENSUS_API_KEY` is not needed for this at all; the reusable
piece from script 05 is the **city → FIPS place-code join**, not the API
plumbing. Latest vintage: the most recent complete year's `A.TXT` (the
script auto-detects by probing the current year and stepping back).

## 2. Coverage honesty

BPS covers **permit-issuing places**. Cities that don't issue their own
permits (county-issued, some unincorporated areas) simply aren't in the
place file. The script therefore:

1. joins place-level (state FIPS + normalized place name — cities.csv
   carries no FIPS place code, so v1 name-matches with suffix stripping and
   reports its match rate);
2. leaves `null` + `permit_source='none'` for non-matches — a null is
   honest; an imputed zero is not;
3. **county fallback is a phase-2 follow-up**: the county annual file
   (`.../County/co<YYYY>a.txt`) apportioned by population share, flagged
   `permit_source='county'` — it needs a city→county-FIPS map that
   cities.csv doesn't carry (GeoNames admin2 codes can supply it).

The validate run reports match rates so the real coverage is known before
anyone reads the column as complete.

## 3. The metrics (context, definitions locked)

Per city (market-level — identical across that city's categories):

| Field | Definition | Why |
|---|---|---|
| `permit_units_1yr` | total units authorized, latest full year (all structure classes, imputed est.) | the raw level |
| `permits_pc` | `permit_units_1yr / population × 1000` | comparable across city sizes |
| `permit_sf_share` | 1-unit units ÷ total units | single-family skew — SFH correlates most with home-services demand; a 5+-tower boom is a weaker signal for roofers |
| `permit_trend` | latest year ÷ mean of the prior 3 years | direction — a leading indicator is about slope; 3-yr base smooths lumpy approvals |
| `permit_flag` | `HOT-pipeline` when `permits_pc` ≥ p90 across board cities AND `permit_trend` ≥ 1.2, `COLD-pipeline` when ≤ p10 AND ≤ 0.8, else `-` | the luck-flag idiom — glanceable, threshold-explicit |

## 4. The load-bearing ruling: context column, NOT a grade input

`build_score`/`grade` are untouched. Permits contextualize measured demand
exactly the way `peak_months` contextualizes `growth_yoy` and `luck`
contextualizes `xdem` — dollars decide, context informs, no frankenscore.
Two reinforcing reasons beyond discipline: (a) permits are **lagged and
category-specific** — a housing boom lifts roofing demand in 12 months and
locksmith demand barely at all; folding one multiplier into every
category's grade is wrong on its face; (b) there is **no outcome data**
proving the indicator's local predictive power yet — the calibration
framework (leadoff-calibration-plan §5) is precisely where a permits weight
could eventually be *earned*, per-category, from realized engagements.

**Category relevance — decision: present market-level, tag relevance in
display, weight nothing.** A construction-adjacent category list (HVAC,
plumbing, roofing, landscaping, electrical, fencing, concrete, garage door,
painter, flooring…) drives *prominence* — the brief shows the pipeline
line prominently for those categories and mutes it ("low relevance for this
category") for locksmith/appliance-repair-class markets. Numeric relevance
weights would be invented numbers; display relevance is honest and costs
nothing to change later.

## 5. Pipeline integration (desktop side — the script ships with this doc)

`05b_pull_permits.py` (reference copy in `docs/reference/leadoff-scanner/`;
copy into the scanner project root):

- Pipeline conventions: numbered 05-family, JSON checkpoint
  (`checkpoints/permits.json`), plain-ASCII `permits_status.txt`, idempotent
  (re-runs skip downloaded vintages; `--force` re-pulls).
- `--validate`: pulls ONLY the region files needed for the two test
  markets — **McKinney, TX** (Sun-Belt boomtown) vs **Cleveland, OH**
  (stable Rust-Belt) — and prints level + per-capita + trend side by side.
  Expected shape if the signal is real: McKinney `permits_pc` several times
  Cleveland's, trend ≥ 1. If the two look interchangeable, stop and say so.
- Full run: all four region annual files × (latest year + 3 prior) ≈ 16
  small text downloads — **$0, minutes**. Joins to `cities.csv` (reusing
  05's place-FIPS mapping), writes `intermediate/permits.csv`, and emits
  `leadoff_board` update SQL / loader input adding the §3 columns.
- Supabase: the loader adds the five columns to `market_scanner.
  leadoff_board` at next reload (or an `alter table ... add column` +
  UPDATE for an in-place backfill — script emits both variants).
  ⚠ Grants: table recreation strips `service_role` grants (2026-07-12
  lesson); default privileges now cover SELECT, but verify after reload.

## 6. App-side follow-up (this repo, after the columns exist)

Data flows with zero backend change (`/leadoff/board` and the brief
`select("*")`). Surfacing, once the desktop reload lands:

- `MarketRow`/`MarketBrief` types + a board column (`Pipeline` — the flag
  chip) + a brief line: "Prospect pipeline: 4,120 units authorized last yr
  (9.8/1k residents, 72% single-family, trend 1.4× — HOT-pipeline)" with
  the §4 relevance mute for non-construction-adjacent categories.
- Column names are the contract: `permit_units_1yr`, `permits_pc`,
  `permit_sf_share`, `permit_trend`, `permit_flag`, `permit_source`.
  Change them on the desktop side and this doc + the app follow-up must
  change with them.

## 7. Coordination

- Desktop memory-file mirror note: "Permits column designed
  (ar-tools docs/modules/leadoff-permits-plan-v1_0.md); script at
  docs/reference/leadoff-scanner/05b_pull_permits.py — validate on
  McKinney/Cleveland first, then free wide run; adds 6 columns to
  leadoff_board (names in doc §6); app-side surfacing follows the reload."
- No app/scanner scoring change; the calibration framework is the only
  sanctioned path to ever weighting this.
