# LeadOff — Market Valuation Plan (v1.0): grounding lead value, revenue & monetization

**Status:** PROPOSED — plan, not built. No code, no schema change, no new vendor
is committed by this doc. It captures the owner decisions of 2026-09-18 and the
architecture they imply, so v1 is built against a spec rather than chat history.
The Enigma-dependent phases (v2+) are contingent on the Enigma coverage pilot
(`docs/modules/leadoff-enigma-pilot-plan-v1_0.md`) passing its §5 thresholds.

**Relationship:** this is the *valuation* half of LeadOff — how much a
`city × category` market is worth and how you'd monetize it. It sits on top of
the existing grade engine (`services/leadoff.py`, `services/leadoff_actions.py`)
and feeds, but does not replace, the sabermetric grade. Companion docs:
`leadoff-prd-v1_0.md` (the module), `leadoff-enigma-pilot-plan-v1_0.md` (the
per-incumbent card-revenue probe), `leadoff-permits-plan-v1_0.md` (city permit
demand), `leadoff-gbp-placement-plan-v1_0.md` (census income/demand), and the
calibration framework (`leadoff-calibration-plan` §5 — the "earn a grade weight
through outcomes" rule this plan honors).

---

## 1. The problem

LeadOff grades a market by expected value. In code today
(`leadoff_actions.tryout_rows`):

```
value = leads × leadval        # leadval = the flat, national catalog CPL
leads = volume × capture       # volume IS per-market
ev    = value × rankability     # rankability IS per-market
```

Three concrete defects follow:

1. **CPL is a flat national manual estimate.** `market_scanner.lead_values`
   carries a hand-authored `cpl_low/mid/high` per category (~105 rows). It has no
   source, no confidence, and no market variation.
2. **The CPL is anchored to *shared-lead* (low) economics.** Cross-checked
   against real rate cards (the HomeAdvisor/networks pricing spec), LeadOff
   under-prices the high-ticket emergency trades by multiples — water damage
   **$138 mid** vs an exclusive resale range of **$500–2,250**; roofing **$75**
   vs **$85–550**; HVAC **$62** vs **$65–325**. Because `ev = leads × CPL ×
   rankability`, this makes the board **under-rank exactly the emergency trades a
   rank-and-rent operator most wants** — the opposite of the goal.
3. **Market variation is thrown away.** The grader pulls Google Ads **CPC**
   per `city × category` (`demand_from_items` returns it) and then **discards it
   from the value calc** — `tryout_rows` never takes `cpc`. So a painting lead in
   Manhattan and in Mobile, AL get the *identical* CPL, which is wrong: ad-market
   cost, job-ticket size, and customer affluence all vary by metro.

The fix is to (a) re-anchor CPL to real exclusive-lead prices, (b) restore a
per-market modifier, (c) ground a payment-agnostic **revenue** estimate so the
top-down monetization view is trustworthy, and (d) print the monetization models
so the operator sees what a market is worth *and how*.

---

## 2. Owner decisions (2026-09-18) — locked

1. **Lead model = EXCLUSIVE.** LeadOff serves the rank-and-rent / exclusive-lead
   thesis (you generate a lead and rent/sell it to ONE contractor). CPLs anchor
   to exclusive prices, never shared. The two are different products and are
   never blended into one number.
2. **HomeAdvisor/networks data is the national CPL ANCHOR** (the dollar *level*),
   replacing the manual `lead_values` estimates — with a confidence-tiered
   fallback ladder for the verticals it doesn't cover (§4).
3. **Enigma is a top-down CHECK / upgrade, NOT the source of truth.** Enigma
   card revenue undercounts insurance-paid home-service revenue, so it is
   *corrected* (§5), never trusted raw, and never the sole basis of a number.
4. **Total revenue is estimated from JOB signals (payment-agnostic), not payment
   rails** — review-flow reconstruction + permit valuations, with Enigma card
   revenue as one corrected input (§5).
5. **Print the monetization models** (PPL-exclusive, rank-and-rent rent,
   PPL-shared) plus an Enigma affordability ceiling, each with a confidence flag —
   as a market-brief breakdown, not new board columns (§7).

---

## 3. The core model — anchor × local modifier

Stop treating any single source as "the price." Decompose CPL into a national
*level* and a per-market *shape*:

```
CPL(city, category) = national_anchor(category) × local_modifier(city, category)
```

- **`national_anchor(category)`** — the exclusive lead value on average, from the
  HomeAdvisor/networks data via the §4 ladder. Home-service-native, free,
  universal. Home-service *job value* (which does NOT undercount insurance)
  extends coverage well past the ~7 verticals with a published exclusive price.

- **`local_modifier(city, category)`** — a **confidence-weighted blend** of
  market signals, each contributing in proportion to its coverage in that market,
  built as **ratios** (market ÷ national median) so a click-cost or a revenue
  figure becomes a unitless "this metro runs hot/cold" multiplier:

  | Signal | Measures | Coverage | Cost | Role |
  |---|---|---|---|---|
  | **CPC ratio** | ad-market lead cost | universal (already pulled, then discarded) | $0 extra | **primary** scaler |
  | **Income / home-value ratio** | job-ticket size, affluence | universal (`leadoff_income` / `census_demand`) | free | always-on |
  | **Enigma incumbent-revenue ratio** | how the market's businesses are *actually* doing | coverage-gated | paid | confirming/upgrading |

  The modifier degrades gracefully: universal signals (CPC, income) always
  contribute; Enigma contributes only where it matches ≥N incumbents in the
  market, and its absence never penalizes a market (the "a missing signal is not
  a weak one" rule). Every graded CPL records which signals fed its modifier
  (mirrors the grader's existing `cpl_default` flag).

**Governance:** re-anchoring CPL fixes an *existing* grade input with better
data, so it legitimately affects the grade in v1 — but a 4–16× swing on the
emergency trades is large, so it ships behind a visible **before→after board
comparison** and is sanity-checked against a few real closes, never blind-swapped.
The CPC/income *modifier* is a NEW mechanic, so it follows the `leadoff_scoring`
precedent: a **bounded, conservative, flag-gated multiplier** ("starting
coefficients, not truths") that the calibration loop tunes from real outcomes.

---

## 4. The CPL anchor + the coverage fallback ladder

The spec has ~22 verticals; LeadOff has ~105 `lead_values` rows across ~30
clusters. We don't need a published price for each — we need an exclusive CPL,
and there are honest ways to get one. Every rung records `source` + `confidence`
so nothing is fabricated:

1. **Direct exclusive price (high).** Category → a vertical with a Service Direct
   exclusive range → use it. Covers the big trades (HVAC, plumbing, roofing,
   water damage, electrical, pest, appliance, locksmith, window/door, siding).
2. **Formula-derived (medium-high).** `CPL = job value × close rate × margin
   share` (the spec's §4). The job-value scrape covers **more** verticals than
   the resale tables, so a category whose parent vertical has a job value gets a
   derived exclusive CPL even with no observed price (garage door, fencing,
   gutters, tree, handyman). Painting's OfferVault affiliate floor ($198) is a
   hard *lower bound*.
3. **Cluster-sibling inheritance (low-medium).** A sub-service with no vertical
   inherits from its covered cluster anchor, scaled by *relative* job size:
   air-duct cleaning → HVAC's floor (not its mid); countertop/marble → Remodeling
   /finishing; home automation/security → Electrical; home builder → Remodeling-
   addition.
4. **Keep the current manual estimate, flagged (low).** True niches with no
   vertical, formula input, or sensible sibling (piano tuning, upholstery, house/
   pressure/window cleaning, pool, design/consulting/inspection, snow removal) →
   retain today's `cpl_low/mid/high`, mark `source='manual_estimate'`,
   `confidence='low'`. Never invent a number.
5. **Live CPC proxy (the general fallback).** Moving is the one vertical with
   **zero** resale signal anywhere; the spec says use Google Ads CPC — which the
   grader already pulls. Self-calibrate: fit the CPC→CPL ratio across the covered
   verticals, then apply it to the uncovered ones. Data-driven, per-market;
   held for v2 (introduces per-market value variance).

**Net coverage:** ~two-thirds of categories get a direct or formula-derived
exclusive CPL (rungs 1–2), most of the rest via cluster inheritance (rung 3), and
only ~15 true niches keep a flagged manual estimate (rung 4).

**Schema:** add `source` + `confidence` columns to `lead_values`. **Source of
truth is the scanner's `inputs/lead_values.csv`** — a `market_scanner` reload
drops/recreates the table and wipes Supabase-only edits, so the CSV is
authoritative and the Supabase mirror-upsert is the interim (identical constraint
to the 4-category board-add runbook, re-grant SQL included).

---

## 5. Revenue estimation — the keystone (payment-agnostic)

The insurance problem: roofing, water/fire/mold restoration, and storm work are
heavily insurance/invoice/check/ACH-paid, so **card data (Enigma) undercounts
them badly** — a restorer doing $2M real may show $150k card. The reframe:
**measure the WORK done (job count × job value), not the money (payment rail).**
A $17k roof is $17k however it's paid. Build a **composite revenue estimate** from
payment-agnostic signals, each weighted by coverage/confidence:

1. **Job-flow reconstruction (best value, mostly in hand).**
   `revenue ≈ (reviews_per_month ÷ review_rate) × HomeAdvisor job value`.
   Review velocity is already pulled per-business (`business_reviews` /
   `velocity_row`, scout); job value comes from the HomeAdvisor scrape. The lone
   fudge factor `review_rate` (~2–10%, category-dependent) is **calibratable**
   against the measured anchors below. No new vendor.
2. **Per-contractor permit valuations (strongest DIRECT signal for the insurance-
   heavy trades).** A roof/HVAC/restoration/remodel/solar job pulls a public
   permit with a stated dollar valuation regardless of who pays. LeadOff has
   *city-level* permit demand today (`leadoff_permits` → `city_permits`); the
   *per-contractor* version (who pulled how many permits worth how much) is a new
   source — **Shovels.ai** (purpose-built), BuildZoom, Construction Monitor, or
   direct county records. v2 eval, like Enigma.
3. **Enigma card revenue — one CORRECTED input, not the truth.** Good for the
   low-insurance, card-heavy trades (appliance repair, locksmith, carpet
   cleaning, handyman, pest). Everywhere else, methods 1/2 give real revenue and
   Enigma gives card revenue, so the ratio *is* the **card-share per category**
   (`card_share = enigma_card_rev ÷ real_revenue`) — which then corrects Enigma
   everywhere. HomeAdvisor/permits calibrate Enigma; they don't compete with it.
4. **Firmographic headcount triangulation.** D&B/ZoomInfo/Apollo/Data Axle
   "estimated revenue" for a tiny SAB is modeled + bucketed (weak); use their
   **employee count** × home-service revenue-per-employee (~$150–250k) instead.
5. **Free size proxies.** Review count, ad presence (the outreach module already
   detects paid LSA/Ads), trucks in GBP photos, years in business, service-area
   breadth — rank who's bigger even without dollars.

**Worked example — water-damage restorer:**

| Method | Estimate | Note |
|---|---|---|
| Job-flow | 2 reviews/mo ÷ 10% × $6,503 | ≈ **$1.56M/yr** |
| Permit valuations | 18 mitigation permits/mo × ~$7k | ≈ **$1.5M/yr** (converges) |
| Enigma card | $12.5k/mo × 12 | **$150k/yr** → card-share ≈ **10%** (the undercount, quantified) |

**The honest limit:** you cannot *know* a private SAB's exact revenue. The
deliverable is a **defensible range + a reliable relative ranking**, with the
fudge factors (`review_rate`, `card_share`) calibrated against measured anchors:
permit valuations, Enigma card, and — best — your own **won-client close data**
(`leadoff_calibration`). Per LeadOff governance, the revenue estimate enters as a
**context/display** value first and only becomes a grade weight once the
calibration framework earns it.

---

## 6. Two estimators, reconciled

The composite revenue estimate unlocks a **top-down** view that cross-checks the
**bottom-up** CPL view:

- **Bottom-up:** `income ≈ leads(volume) × CPL(anchor × modifier) × your share`
- **Top-down:** `income ≈ corrected_market_revenue × marketing% × addressable-
  digital-share`  (the "revenue × ~5%" idea, corrected + chained)

They should **converge**; where they diverge sharply, that's *diagnostic* — e.g.
high revenue + low search volume = a referral/repeat market that's poor for
rank-and-rent despite the money. Both are tuned by `leadoff_calibration` +
real closes. Neither replaces the other; the reconciliation is the value.

**On the "× 5%":** 5% is a real SMB *total-marketing* rule of thumb (ads, brand,
trucks, referral, PPC, SEO). The digital-lead-gen slice is a fraction of it, and
that fraction is split across the incumbent's own site, LSA, Angi, Thumbtack, PPC
*and* your site. So raw `revenue × 5%` is a **market-size ceiling (TAM)**, not
literal income — most useful as a market-attractiveness / affordability signal
(§7), never as the income number itself.

---

## 7. Monetization print

Show, per market, what it's worth *and how* — as a **"Monetization" breakdown on
the grade card / market brief**, not new board columns (the board is already
dense: grade / exp_val / ROI / beatability / payback). The board's single grade
stays the sort key; this is the "how would I make money here" drill-in.

**Honesty rule — same lead flow, two billing models, NOT independent streams.**
Rank-and-rent rent is *derived from* the lead value; you cannot bank both PPL and
rent from one site/market. Frame accordingly, and (since the model is exclusive)
note that PPL-exclusive and rank-and-rent nearly converge — the daylight is
against SHARED PPL.

| Model | Formula | Confidence |
|---|---|---|
| **PPL — exclusive** | `leads/mo × exclusive CPL` | grounded (LeadOff already computes `value_mo`) |
| **Rank-and-rent (flat rent)** | `PPL-exclusive × rent_discount` (~0.5–0.7 — one recurring buyer, near-zero ongoing sales effort) | grounded |
| **PPL — shared** | `leads/mo × shared price × ~N buyers` | grounded, higher operational effort |
| **Affordability ceiling** | `corrected_market_revenue × marketing% ÷ 12` | **speculative** until the Enigma pilot — flag distinctly or hide |

Rendered as, e.g.: *"Rank-and-rent ~$2,100/mo — 25% of a ~$8,300/mo incumbent
marketing budget."* The grounded three ship in v1 (all factors on the
`leads × CPL` LeadOff already computes); the affordability ceiling is v2.

Constants to pin (config, calibratable): `capture` (already exists),
`rent_discount`, shared `n_buyers`, `margin_share`, `marketing_pct`,
`addressable_digital_share`.

---

## 8. Build sequencing

- **v1 — no new vendor, universal, cheap. The correctness win.**
  1. Recalibrate `lead_values` to **exclusive** CPLs via the §4 ladder; add
     `source` + `confidence`. Deliver as a new `inputs/lead_values.csv` for the
     scanner machine + the idempotent Supabase mirror-upsert. Ship behind a
     before→after board comparison.
  2. Add the **CPC local modifier** (bounded, conservative, flag-gated) — restore
     the per-market CPC the grader already pulls, as a ratio multiplier on CPL.
     Fixes Manhattan ≠ Mobile for every market with data already in hand.
  3. Add the **monetization breakdown** (the three grounded models) to the market
     brief / grade card.
- **v1.5 —** fold the **income / home-value ratio** into the modifier (free,
  already computed for the Placement Advisor).
- **v2 — revenue keystone + Enigma, gated on the coverage pilot.**
  1. **Composite revenue estimation:** job-flow reconstruction first (no vendor),
     then per-contractor **permit valuations** (Shovels.ai eval) for the
     insurance-heavy trades.
  2. **Enigma top-down estimator** + the **card-share correction** + the
     **affordability ceiling** — only where the pilot proves Enigma matches
     home-service SABs. If the pilot says coverage is thin, v1 stands alone.
- **v3 —** full CPC→CPL self-calibration for uncovered categories; the two
  estimators reconciled and tuned through `leadoff_calibration` on real closes.

---

## 9. Data inputs & where they live

| Input | Source | State |
|---|---|---|
| Exclusive CPL anchor + job value | HomeAdvisor/networks pricing spec (Drive: `lead_pricing_data_spec.md`) | in hand (summary); **request the raw 713-row `homeadvisor_true_cost_guide_full.csv`** for sub-job precision |
| CPC per `city × category` | DataForSEO (grader already pulls it) | in hand, currently discarded |
| Median income / home value | `leadoff_income` / `census_demand` (ACS, keyless) | built (Placement Advisor) |
| Review velocity per business | `business_reviews` / `velocity_row` (scout) | in hand |
| City permit demand | `leadoff_permits` → `city_permits` (Census BPS, keyless) | built (city-level only) |
| Per-contractor permit valuations | Shovels.ai / BuildZoom / county records | **new — v2 eval** |
| Per-incumbent card revenue + growth | Enigma (GraphQL, `x-api-key`) | **pilot pending** — harness merged (`scripts/enigma_coverage_pilot.py`) |
| Won-client close data | `leadoff_calibration` | the ground-truth calibrator |

**Reload-wipe rule:** anything the app writes into `market_scanner.*` is dropped
on the next scanner reload. `lead_values` lives in `inputs/lead_values.csv` (edit
there); card/permit/revenue caches live in **app-owned `public.*` tables** (never
`market_scanner`), as the Enigma §7 build sketch and the brand-footprint caches
already do.

---

## 10. Open questions

- **The raw 713-row HomeAdvisor CSV** — sharpens rungs 1–2 (map septic → $8,017,
  air-duct → its own page, instead of a cluster average). Requested.
- **`review_rate` per category** — the job-flow fudge factor; calibrate against
  permit valuations + closes on the first markets that have both.
- **Shovels.ai (or equivalent) eval** — coverage + cost for per-contractor
  permit revenue on the insurance-heavy trades. Gate any commit on it, like
  Enigma.
- **Enigma coverage pilot result** — decides whether the top-down estimator +
  affordability ceiling are built at all (run `scripts/enigma_coverage_pilot.py`
  with a trial key; the pilot's ground-truth run should also record the
  **card-share** per matched business — the number §5.3 needs).
- **Rollout guardrail** — the exclusive re-anchor is a large re-rank; confirm the
  before→after board and a handful of real closes before it goes live.

---

## 11. Acceptance criteria (v1)

1. Every `city × category` grade produces a CPL that **varies by market** (CPC
   modifier applied), not a flat national number.
2. The exclusive recalibration **re-ranks the high-value emergency trades up**
   (water damage / roofing / HVAC visibly rise vs the current board), with a
   before→after comparison available.
3. Every `lead_values` row carries a `source` + `confidence`; uncovered niches
   keep a flagged manual estimate — **nothing fabricated**.
4. The market brief renders the **monetization breakdown** (PPL-exclusive,
   rank-and-rent, PPL-shared) with confidence flags; the speculative Enigma
   affordability ceiling is absent until v2.
5. No new grade *weight* ships unearned: the CPC modifier is bounded + flag-gated;
   the revenue estimate is context/display until the calibration framework earns
   it.
