# LeadOff — Local Service Market Opportunity Scanner

**The tool is named LeadOff** (the goal is to get leads; the leadoff hitter's
job is to get on base — this finds where you get on base most reliably and
cheapest). Refer to it by name: the report is the *LeadOff board*, `check_city`
is a *tryout*, `enrich_shortlist` is the *scouting report*.

LeadOff is a data pipeline that scores US city × home-service-category
combinations for lead-gen website/GBP opportunities, using DataForSEO (Maps
SERPs, Google Ads keyword data, backlinks) + US Census demographics, then
grades every market sabermetrically (WAR-style build grades, OBP/expected-leads,
xFIP-regressed demand, BABIP luck flags, WPA effort-ROI). Results live in
Supabase and are queried through PowerShell report tools.

**PRD:** `C:\Users\kssab\OneDrive\Desktop\Projects\AR Internal\Market_Opportunity_PRD_v2_Reconciled.md`

## Directory layout

| Path | Contents |
|---|---|
| this folder (project root) | pipeline scripts, `config.py`, `common.py`, `inputs/` |
| `%USERPROFILE%\market-scanner-data\` | data root (deliberately OUTSIDE OneDrive), user-facing tools, logs, checkpoints, intermediate CSVs, output xlsx |
| `inputs/` | cities.csv (4,682 US places ≥10k pop, GeoNames), categories.csv (100 GBP categories), lead_values.csv (per-category CPL low/mid/high, user-supplied), field_quality.csv, aio_presence.csv, nameable*.csv, neighborhood*.csv |

## Credentials — NEVER print values

Stored as **User-registry env vars**: `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`,
`CENSUS_API_KEY`, `SUPABASE_DB_URL`. Load into process before running anything:

```powershell
foreach ($n in "DATAFORSEO_LOGIN","DATAFORSEO_PASSWORD","CENSUS_API_KEY","SUPABASE_DB_URL") {
  Set-Item -Path "Env:$n" -Value ([Environment]::GetEnvironmentVariable($n,"User")) }
```

DataForSEO account has a **$500/day money limit** (resets midnight UTC).
Supabase project: `AR-Internal-Tools` (id `wvcthtmmcmhkybcesirb`), schema
`market_scanner`, scoped login role `market_scanner_loader` (NOT table owner —
DDL needs the admin MCP connection, then `grant` to the loader).

## Pipeline (scripts/, run in order)

| Script | Does | Notes |
|---|---|---|
| 01_download_geonames | builds inputs/cities.csv | done |
| 01b_map_location_codes | city → Google Ads location_code | matcher misses Borough type, "City,County,State" format, hyphenated names — 27 recoveries were patched directly into cities.csv (backup: cities_prematch_backup.csv); script itself NOT yet fixed |
| 02_pull_serp | Maps SERP per city×category: top-5 + supply count | **coordinates MUST end ",13z"** (see Lessons). Env: `SERP_METHOD` standard/live, `SERP_KEEPLIST` (file of city:cat keys = demand gate) |
| 03_pull_domain_rank | Backlinks Bulk Ranks per unique domain (~$3) | cheap: cached score |
| 04_pull_cpc | Google Ads volume+CPC per city, **both keyword forms** (base + "near me"), 30-thread concurrent | billed per task not per keyword; `KEEPLIST_MIN_VOL` |
| 04b_make_keeplist | demand gate: max(base,nearme) ≥ 20 → serp_keeplist.txt | |
| 05_pull_demographics | Census ACS per state | idempotent |
| 06_score_and_rank | joins everything → scores → output xlsx | keeps below-gate combos w/ CPC (supply_measured=false) |
| 07_load_to_supabase | stamps run in `runs`, appends to master | |

Runners: `run_full.ps1` (full pipeline), `run_repull.ps1`, `run_addcities.ps1`,
`run_rankability.ps1` — all detached via `Start-Process`, write plain-ASCII
status files (`*_status.txt`) because mixed-encoding logs broke watchers.
Checkpoints (`market-scanner-data\checkpoints\*.json`) make everything resumable.

## Supabase state

- `market_scanner.market_opportunity_master` — **run_id=3 is current** (149,100
  rows, 1,491 cities incl. 5 NYC boroughs + 27 recovered cities). run_id=1/2 are
  superseded (1 had broken supply, 2 pre-recovery).
- `market_scanner.neighborhood_opportunities` — 955 nameable-neighborhood combos
  (78 top-metro neighborhoods) with v3 + lead economics. **Reloading via
  load_v3.py wipes the econ columns — rerun nbhd_econ_load.py after.**
- Cache tables (Pass-2, 90-day freshness): `domain_backlinks` (RD by domain),
  `business_reviews` (velocity by business), `demand_trend` (by city+category).
- **Input CSVs are mirrored to Supabase (2026-07-09)** so a web deployment has
  zero file dependencies on this machine: `categories`, `lead_values`,
  `field_quality`, `cities`, `exp_val_percentiles`, `aio_presence`,
  `nameable_neighborhoods`, `nameable_top50_metros`, `neighborhood_demand`.
  Local CSVs remain the working copies for the PowerShell tools; re-run the
  migration (scratchpad/migrate_inputs.py pattern) after changing an input.

## Scoring methodology (the sabermetrics stack)

Computed live in `report.py` unless noted:

- **xdemand** (xFIP): demand regressed to category population-expectation —
  `0.75·min(obs, 4·expected) + 0.25·expected`, expected = per-category median
  per-capita rate × pop. Kills outliers (Ashburn 90,500→109) without vetoes.
- **rankability (0–1)** = `0.75/(1+top5_reviews/50) + 0.25/(1+exact_holders/5)`
  — field weakness + exact-category-lever openness.
- **exp_val** = leads(=xdemand×capture) × lead_value(csv) × rankability — the
  absolute $ decision metric ("OPS"). **exp_leads** = leads × rankability ("OBP").
- **build_score/grade** = national percentile of exp_val with vetoes (<5
  leads/mo or rankability<0.15 → cap C; no lead value → F). A+≥99 A≥97 B+≥94 B≥90.
- **luck** (BABIP): dem_ratio = obs/expected demand, park-adjusted vs the city's
  own median; HOT? = verify before building (needs trend data to adjudicate).
- **WPA columns** (from field_quality.csv, precomputed off serp_results.csv):
  `rev_win` (reviews to beat #3), `roi` = exp_val/rev_win ($/mo per review of
  effort), `rating` (field star quality), `namekw` (keyword-name saturation),
  `conf` (demand-bucket confidence).
- **opportunity_score_v3** (in DB) = within-category percentile blend — answers
  "best CITY for category X"; exp_val answers "what to build IN city X". Don't
  confuse the two.

## User-facing tools (in %USERPROFILE%\market-scanner-data\)

```powershell
.\report.ps1 --city Vancouver --state WA            # Pass 1: screen (free)
.\report.ps1 --sort roi --min-demand 150            # WPA lens: win cheapest
.\report.ps1 ... --csv shortlist.csv                # export a shortlist
.\check_city.ps1 "Moses Lake" WA                    # Pass 1.5: any off-list city (~$0.20)
.\enrich_shortlist.ps1 shortlist.csv                # Pass 2: RD+velocity+trend (~$0.5–5, cached)
```
Knobs: `--capture` (search→lead rate, default 0.10), `--lead-tier low|mid|high`,
`--sort build|roi|leads|v3|expected|value|demand`, `--run N`, `--include-unmeasured`.

## Hard-won lessons (do not relearn these)

1. **Maps SERP without a zoom level is garbage** — default viewport gives false
   zeros/undercounts (KC locksmith 0 vs 100+ real). Always append `,13z` to
   `location_coordinate` (calibrated: scales with city size; 14z too tight,
   city-name targeting caps at 100).
2. **Check task-level status codes.** Envelope 20000 ≠ task success. 40203 =
   daily money limit (retry, never record); **40102 "No Search Results" = a
   VALID zero** (record supply 0).
3. **Category strings are treacherous:** "Handyman" was renamed
   `Handyman/Handywoman/Handyperson`; **"Plumbing" is not a selectable GBP
   category at all** (alias to Plumber). Exact-holder counts are only meaningful
   for verified-current labels — run `detect_renames`-style sweep (~$0.60) when
   adding categories. Also: keyword search returns whole category *families*
   (a "Moving company" search returns Mover/Trucking company primaries), so
   never count competitors by exact-primary-label match against a keyword.
4. **Demand needs BOTH keyword forms** — "near me" dominates in many markets
   (KC locksmith 1,900 near-me vs 880 base); costs nothing extra (per-task
   billing). Explicit "[service] [place]" volume has a **homonym trap**
   (Wilmington/Glendale/Corona) — geo-targeted is the safe default.
5. **Neighborhoods: GBP-nameability is the hard gate** — count≥2 businesses
   listing the neighborhood as address city (Maps `address_info.city`).
   Hollywood/Buckhead = famous but NOT nameable; 437 of 4,849 Google
   neighborhoods are nameable, 78 in top-50 metros. Neighborhood supply ≈ parent
   metro at 13z, so score them on demand not competition.
6. **CPC ≠ lead value** — Landscape architect has $0 CPC but $80 real leads.
   Use inputs/lead_values.csv.
7. **Validate scoring inputs against an adversarial case before paying for a
   full pull** (the $87 precise-count lesson: validated on plumber where the
   label matched, failed on moving).
8. **growth_yoy is seasonal-confounded** with only 12 months of history
   (roofing 0.21 = spring-vs-peak artifact) — read with peak_months; true fix
   is `date_from` 24mo.
9. AIO (AI Overviews): only 3% of "[cat] near me" SERPs, 0% on money trades,
   pack present 98% — GBP lane insulated; re-probe quarterly (~$1.60).
10. Run long jobs detached with ASCII status files + background watchers;
    OneDrive must not hold the data dir; Python logs via `*>>` are UTF-16 while
    Add-Content is ANSI — never parse the mixed log, parse the status file.

## Budget & pending

- Spent ≈ $700 of $1,000 DataForSEO credits; **balance ≈ $275**.
- La Jolla (user's home market): validated nameable; plumber = 6 weak primary-
  category GBPs (all <21 reviews) but strong top-5 pack (~256 avg) — locksmith/
  landscape-architect are the softer entries.

## Idea bank / backlog (bounced around, not yet built)

**Coverage & data upgrades**
- **10k–29,999 city tier** (~$150): set `MIN_POPULATION` and rerun — resumes
  via checkpoints, no re-pull of existing cities. Roughly doubles city coverage
  with real standalone markets (higher ROI than more neighborhoods).
- **Trend/seasonality, done right**: per-shortlist via enrich (built) is the
  default; the ~$73 national re-pull bakes growth into the screen itself so a
  fast-rising B can outrank a flat A. Either way, the true fix for the
  seasonal-confounded `growth_yoy` is `date_from` **24 months** (same-month YoY).
- **Census building permits** (free API): housing-permit issuance as a
  leading indicator of home-services demand — a "prospect pipeline" column.
- **Proximity signal** (the unmodeled Distance pillar — highest-leverage gap):
  competitor clustering / underserved sub-zones within a market; where should
  the GBP address sit. Partly measurable from data we already pull.
- Patch the 01b matcher properly (Borough type, "City,County,State" format,
  hyphenated names — currently fixed in data, not in code).

**AI-lane (AIO/AEO offense) — pending a ~$5 pilot probe of DataForSEO
`ai_optimization` endpoint quality/cost before building any of it:**
- Wire `aio_presence.csv` as an organic-lane capture discount + board column.
- **AIO citation analysis** (~$2 re-probe): when an AIO appears, does it cite
  directories or local sites? Open citation slot = AEO first-mover play.
- **LLM recommendation field** — the "AI pack": who do ChatGPT/Gemini/etc name
  for "[service] in [city]"? Empty field + real demand = land grab. Natural
  Pass-2 add; feeds/complements the suite's AI Visibility (LABS) module.
- **AI demand volume** (`ai_keyword_data`): how much of the intent is
  migrating to AI assistants, per category.
- Quarterly re-probes: AIO presence (~$1.60), category-rename sweep (~$0.60).

**Scoring & tools**
- **Feedback-loop calibration** (the moat): SerMaStr engagement outcomes
  (did `rev_win` hold? actual leads vs estimate) tune the weights — the PRD's
  "calibration surface" fed by real lead-flow.
- **Jobs/month close-rate dial** (leads × close rate) in report + app.
- `--grade-by leads` option (grade re-based on lead volume for a
  volume-driven business model, vs the default $-weighted grade).
- `check_city` for towns <10k pop (needs a geocode step; cities.csv floor is 10k).
- Report-tool conveniences: `--neighborhoods` mode; double-clickable .bat
  shortcuts; shareable multi-tab Excel workbook.

**App-module v2 (tracked in ar-tools `docs/modules/leadoff-prd-v1_0.md` §5)**
- Paid endpoints (`/leadoff/tryout`, `/leadoff/scout` + per-user budget guard),
  Create-Client-from-market handoff, neighborhood tab, SerMaStr `sop_library`
  domain routing.

**Considered and rejected (don't relitigate without new info)**
- National RD pull (~$390): poor ROI + exceeds balance — shortlist-only (built).
- All-4,849 neighborhood demand sweep (~$465): long tail is dead; the
  nameable-in-top-metros filter (78) is the right universe. If expanding,
  curate ~300–600 dense big-metro districts (~$50), select by density not prestige.
- CTR-curve capture as a separate factor: double-counts rankability×capture.
- xwOBA-style demographics-only scoring: throws away measured demand.
- A third blended score: dollars decide, percentile contextualizes, v3 compares
  within category — no frankenscore.

## Working agreements

- User has standing permission to proceed without confirmation prompts, BUT
  surface cost estimates before multi-dollar API pulls and validate methods on
  small samples first.
- Update the auto-memory file (`market-opportunity-scanner.md`) after
  significant changes; it holds the running project narrative.
- Report failures honestly and immediately — this user catches data problems
  (KC zoom bug, category renames, exact-match lift) and expects candor over
  polish.
