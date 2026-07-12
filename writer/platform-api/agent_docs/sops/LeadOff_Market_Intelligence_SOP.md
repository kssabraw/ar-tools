# LeadOff Market Intelligence SOP — Market Selection & Competitive Quantification

**Current as of:** 09 July 2026
**Purpose:** Defines how agents (SerMaStr) and humans consult **LeadOff** — the
sabermetric local-market scanner — to make market-selection decisions and to
*quantify* the generic recipes in the other SOPs with per-market numbers.
**Cross-reference:** Routing, shared definitions, and global rules live in
`_ORCHESTRATOR.md`. This SOP does not redefine them.

---

## 1. Decisions this SOP owns

| Decision | Owned here |
|---|---|
| Which market (city × service category) to enter / build a new asset in | ✅ |
| Expansion targeting for an existing client (which adjacent markets, in what order) | ✅ |
| Quantifying market difficulty: review targets, link budgets, category choice per market | ✅ (numbers feed the Maps and Link Building SOPs, which own the *execution* procedures) |
| Whether a neighborhood merits its own GBP / location page (nameability) | ✅ (feeds Site Architecture SOP's page list) |
| Which GBP primary category to select in a market | ✅ (verification rules §6) |

LeadOff does **not** own: how to acquire reviews (Maps SOP), how to build links
(Link Building SOP), page structure (Architecture SOP), or drop response
(Rank Drop Mitigation).

## 2. What LeadOff is

A scored database of **34,373 measured US market combos** (1,491 cities ≥30k pop
× 100 home-service categories, incl. NYC boroughs) plus **955 nameable-neighborhood
combos**, living in Supabase (`AR-Internal-Tools` → schema `market_scanner`,
run_id=3 current). Three access tools (PowerShell today; FastAPI port planned as
platform Module 6 — see `LEADOFF_PRD.md`):

| Tool | Function | Cost |
|---|---|---|
| `report.ps1` (the **LeadOff board**) | screen/filter/grade all markets | free |
| `check_city.ps1` (**tryout**) | score any off-list city on demand | ~$0.20 |
| `enrich_shortlist.ps1` (**scouting report**) | RD + review velocity + demand trend for finalists; cached 90 days | ~$0.50–5 per shortlist |

## 3. Metric dictionary (read this before quoting numbers)

| Metric | Meaning | Use |
|---|---|---|
| `grade` (A+…F) | national-percentile build score with vetoes (too-small or too-hard markets capped at C) | the one-number screen |
| `exp_val` | expected $/mo = leads × lead value × win-likelihood | absolute cross-category comparison; "what to build in city X" |
| `v3` | within-category percentile | "best city for category X" — do NOT use across categories |
| `rankab` (0–1) | win-likelihood: field review-strength + exact-category openness | difficulty at a glance |
| `rev_win` | reviews needed to pass the #3 incumbent | **review target for the Maps SOP** |
| `roi` | exp_val ÷ rev_win — $/mo per review of effort | prioritization when capacity-constrained |
| `rating` | field's avg star rating | <4.3 ⇒ compete-on-quality angle |
| `namekw` | top-5 with keyword business names (0–5) | 0–1 ⇒ name-relevance lever open |
| `exact_open` | competitors holding the exact primary category | low ⇒ category lever open (verify per §6) |
| `luck` = HOT?/COLD? | demand runs ≥2×/≤0.5× the city's own norm | HOT? ⇒ verify with trend before committing |
| `conf` | demand-estimate confidence (Google volume bucketing) | low ⇒ treat leads estimate as ±wide |
| `field_vel30` / `momentum` | field reviews gained last 30d vs prior 30d, summed over the `vel_matched` top-5 competitors found in the review cache | accel ⇒ window closing; dead ⇒ sitting ducks; <2 matched ⇒ no verdict (thin data) — read the raw velocity, don't call momentum |
| `rd_min` / `rd_med` | referring domains of top-5 sites — **tool reads** | see §5 conversion before using |
| `growth_yoy` / `peak_months` | 12-mo demand trend | ⚠ seasonal categories confound growth_yoy; read with peak_months |

Economics knobs: `--capture` (default 0.10 of searches → leads; rank-dependent
in reality) and `--lead-tier` (per-category CPL low/mid/high from
`inputs/lead_values.csv`). Estimates are **planning numbers, not promises**.

## 4. Standard procedures

**P1 — New-market selection (build a new asset):**
1. Board screen: `--sort expected` within the target geography, or `--sort roi`
   when review-capacity is the constraint. Keep grade ≥ B, `conf` ≠ low.
2. Off-list city of interest → run a **tryout**.
3. Shortlist 10–50 → run the **scouting report**.
4. Kill or verify every `HOT?` (trend), every `momentum=accel` (closing window),
   and any market whose case rests on `exact_open=0` (see §6).
5. Human eyeball of the top ~5 in live Google Maps before commitment (mandatory —
   LeadOff caught its own bugs this way).

**P2 — Client expansion:** filter the board to the client's category across
neighboring cities; rank by `exp_val`; deliver as an expansion roadmap with
`rev_win`/`rd` effort estimates per market.

**P3 — Quantify an engagement plan (feeds other SOPs):**
- Review target → `rev_win` (+ margin; check `momentum` — an accel field needs a
  moving target: rev_win + field_vel30 × expected months to rank).
- Link budget → §5 conversion of `rd_min`/`rd_med` into true-RD targets for the
  Link Building SOP.
- GBP primary category → highest-demand family member with the fewest verified
  holders (§6). Location pages → nameable places only (§7).

**P4 — Pitch/audit brief:** market grade, exp_val at stated capture/lead-tier,
field strength (rev_win, rating, velocity), and effort estimate. Always state
the assumptions (capture %, lead tier, data date).

## 5. RD conversion (mandatory before quoting link numbers)

LeadOff `rd_min`/`rd_med` are DataForSEO **tool reads**. Per `_ORCHESTRATOR.md`
§2, tool-visibility ≈10% ⇒ **true RD ≈ LeadOff RD × 10**. Apply before comparing
to the shared "highly competitive" thresholds (page-1 avg true RD ≥ 250 ⇔
LeadOff read ≥ 25; DR ≥ 50 via `avg_top5_dr`). Example: Van Nuys locksmith
rd_min 2 ⇒ ~20 true RD (soft); Vancouver water-damage rd_min 70 ⇒ ~700 true RD
(fortress). LeadOff measures the **Maps-pack field**; the Link Building SOP's
page-level analysis still governs organic-page targets.

## 6. Category-selection verification (hard rule)

`exact_open` is only meaningful for **verified-current, selectable** GBP category
labels. Known traps (already corrected in the data, but the class of error
recurs): "Handyman" → renamed `Handyman/Handywoman/Handyperson`; **"Plumbing"
is not a selectable category** (real category: Plumber). Before recommending a
primary category because it "has 0 holders": confirm the label exists in the
current GBP taxonomy and check a live SERP for what incumbents actually use.
A keyword search returns whole category *families* (Mover / Moving company /
Trucking company) — never equate keyword-competitor counts with
primary-category-holder counts.

## 7. Neighborhood / location-page rule

A neighborhood merits its own GBP or location page **only if GBP-nameable**:
≥2 real businesses list it as their address city (Maps `address_info.city`).
Famous ≠ nameable (Hollywood and Buckhead fail; La Jolla and Van Nuys pass).
The vetted lists: `inputs/nameable_neighborhoods.csv` (437 US-wide) and
`nameable_top50_metros.csv` (78 in top-50 metros) — use these before adding
neighborhood pages to a site plan. Neighborhood *supply* ≈ parent metro;
score neighborhoods on demand + nameability, not competition.

## 8. Halt-and-ask triggers (LeadOff-specific; global rules still apply)

1. A recommendation rests on `exact_open=0` for an unverified category label (§6).
2. `HOT?` flag unresolved and no trend data pulled — do not commit spend.
3. `conf = low` on a market whose case depends on the demand estimate.
4. Data age > 6 months without a refresh (scan snapshot: **July 2026**).
5. A paid pull would exceed ~$20 without explicit human approval
   (escalate to Kyle Sabraw / Ryan Maizis).
6. LeadOff numbers conflict with a tracker/tool the suite already trusts —
   report the conflict, don't pick silently.

## 9. Maintenance & known limits

- **Refresh cadence:** quarterly — AIO presence re-probe (~$1.60), category-rename
  sweep (~$0.60); full demand/supply re-scan as needed (~$150). Pass-2 caches
  (`domain_backlinks`, `business_reviews`, `demand_trend`) self-refresh at 90 days.
- AIO status (Jul 2026): AI Overviews on only ~3% of "[category] near me" SERPs,
  0% on core money trades; local pack present 98% ⇒ GBP lane insulated. Re-check quarterly.
- Coverage: cities ≥30k scanned (run_id=3); 10k–29,999 tier not yet run; cities
  without a Google Ads location code have no demand data.
- `growth_yoy` is seasonal-confounded (12-mo window) — pending 24-mo fix.
- Full technical reference: `GBP Demographics Script\CLAUDE.md`.

---

**Registry line for `_ORCHESTRATOR.md` §1 (add on next orchestrator update):**

| Market selection / expansion targeting; market-difficulty quantification (review targets, link budgets, category & location-page choice inputs) | **LeadOff Market Intelligence SOP** | ✅ Active |

**Data-source line for §5:** LeadOff (Supabase `market_scanner`, run_id=3 + Pass-2 caches) — used by: this SOP; feeds Maps, Link Building, Architecture SOPs.
