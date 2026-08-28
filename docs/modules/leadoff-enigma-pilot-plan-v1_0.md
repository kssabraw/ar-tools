# LeadOff — Enigma card-transaction data (Pilot Plan v1.0): coverage-first feasibility

**Status:** PROPOSED — pilot not run. This is a **go/no-go feasibility
pilot**, not a build. No Enigma contract, no code, no new dependency is
committed by this doc. The build sketch in §7 is contingent on the pilot
passing the §5 thresholds.

**Owner decision required before any of this:** Enigma is a new **enterprise
data vendor** (contract + per-record/subscription cost), which the repo's
rules say we don't wire in without explicit sign-off. This pilot exists to
answer "is it even worth signing" cheaply, using a trial/eval key.

**Relationship:** LeadOff measures the *incumbent competitive field* per
`city × category` market. Enigma would attach a **real card-transaction
revenue signal** to those incumbent businesses — the one economic signal we
cannot get from Google/DataForSEO. Two candidate uses were chosen by the
owner (2026-08-28): **incumbent growth signal** and **lead-value
calibration**. This doc treats them separately because they have very
different coverage tolerances.

---

## 1. The question the pilot answers

Everything about whether Enigma is worth it for LeadOff reduces to **one
cheaply-testable fact**:

> Does Enigma have usable card-transaction coverage for **home-service SABs**
> (service-area businesses) — roofers, plumbers, water-damage restoration,
> tree service, pest control — the categories LeadOff actually grades?

This is Enigma's structural weak spot, for three reasons we already know
independently from the LeadOff brand-footprint work:

1. **Payment mix.** Home-service jobs are heavily **insurance / invoice /
   check / ACH** paid, not card-present. A water-damage restoration job is
   billed to an insurer ($3k–$40k), not swiped. Card networks — Enigma's
   source — see a fraction of the real revenue.
2. **Identity / matching.** Many incumbents are **address-less SABs** or
   **generic-named** ("Pest Control KC"). Enigma matches on name + address;
   these are exactly the rows that already forced the brand-footprint signal
   into phone-NAP + city co-occurrence filters.
3. **Enigma's sweet spot is elsewhere** — card-present consumer retail,
   restaurants, salons. Great for those; unproven for contractors.

If coverage is thin or the dollars are implausible for home services, **both**
chosen use cases fail regardless of how good the integration would be. So we
test coverage **before** building anything.

---

## 2. Why the two chosen uses have different risk

| | Incumbent growth signal | Lead-value calibration |
|---|---|---|
| **Needs** | *Relative* revenue trend (up/down %) | *Absolute* dollar amount (avg ticket → CPL) |
| **Tolerance to partial coverage** | **Higher** — a % change is meaningful even if card data captures only a stable *fraction* of revenue | **Lower** — a systematically undercounted ticket biases CPL **down** for exactly our core (insurance-paid) categories |
| **Novelty vs. what we have** | High — today only review velocity + market search-volume YoY; no real revenue trend anywhere | Medium — `lead_values` is a manual per-category `cpl_low/mid/high` today |
| **Better alternative exists?** | Not really — Google can't give a per-incumbent revenue trajectory | **Yes** — the agency's own won-client close data via the existing `leadoff_calibration` loop |
| **Pilot verdict bar** | Trend stability + match rate (§5) | Absolute plausibility vs. ground truth (§5) — a much harder bar |

**Working hypothesis going in:** growth is the salvageable use; lead-value is
the risky one and may be better served by our own client outcomes. The pilot
is designed to confirm or kill each independently.

---

## 3. What we're calling (functional, confirm against live Enigma docs)

Enigma's Small Business API surface (verify exact endpoint names/versions at
integration time — treat the below as capabilities, not literal paths):

1. **Business match / search** — resolve `{name, address, city, state}` →
   Enigma business id(s) + a **match confidence**. This is the make-or-break
   step for SABs.
2. **Card-transaction attributes** for a matched business — typically:
   estimated **card revenue** (monthly/annual), **transaction count**,
   **average ticket**, **card-revenue growth / trend**, and a
   **coverage/quality** indicator (how much of the merchant Enigma believes it
   sees). Capture whatever quality/observation-window field Enigma exposes —
   it's essential for interpreting everything else.

We call **only** these two, **only** for the §4 test businesses. No board-wide
pull, no scheduled job, no cache table in the pilot — results go in a scratch
CSV.

---

## 4. The test set (~12 businesses, ground-truth anchored)

Chosen so we can judge *plausibility*, not just presence. Two buckets:

**A. Known-field incumbents (coverage + trend test)** — the 5 competitors LeadOff
already holds for **Little Rock, AR — water damage restoration** (the market in
the screenshot that opened this). We have their names, and via
`competitor_locations` / `leadoff_gbp_pins` their addresses and review counts.
These test the realistic worst case: insurance-paid, some SAB, some generic.

**B. Ground-truth anchors (plausibility test)** — 2–3 businesses whose **real
revenue we actually know**: current agency clients who've shared numbers, or a
storefront business (a restaurant/retailer) included deliberately as a
*positive control* — if Enigma can't even nail a card-present storefront, the
trial key or our matching is the problem, not the category.

For each: record `name, address, category, known_revenue (if any),
known_trend (if any)` before pulling, so the scoring is blind to the result.

> Pull the exact test list from the live DB at pilot time:
> `competitor_locations` + `leadoff_gbp_pins` for the Little Rock water-damage
> market give names/addresses/reviews; the ground-truth anchors come from the
> owner.

---

## 5. The scorecard + go/no-go thresholds

Record per business: `matched? (y/n)`, `match_confidence`, `card_revenue`,
`avg_ticket`, `revenue_trend`, `coverage/quality`, and a human
`plausible? (y/n/unsure)` vs. ground truth or category expectation.

### 5.1 Coverage (gates everything)

- **Match rate** = matched / attempted, over bucket A (home services).
  - **≥ 60%** → strong; proceed to signal-quality checks.
  - **40–60%** → marginal; usable only if the matched rows are *also*
    plausible (§5.2) and we accept that ~half of fields go unscored.
  - **< 40%** → **NO-GO for board-wide/field use.** Home-service coverage is
    too thin to build either signal on the incumbent field.
- **Positive control:** the bucket-B storefront **must** match with plausible
  numbers. If it doesn't, stop and fix matching/key before judging category
  coverage — the pilot is inconclusive, not negative.

### 5.2 Growth signal (the promising use)

On the *matched* rows only:
- **Trend present** on ≥ 60% of matched rows (a revenue trend, not just a
  point estimate).
- **Trend plausibility:** where we have `known_trend`, sign agreement (is a
  growing business shown growing?) on the anchors.
- **Coverage stability:** the quality/observation field is stable enough that
  a trend isn't an artifact of Enigma's own coverage changing.
- **PASS →** growth is worth building (§7), entering the grade only via the
  calibration loop.

### 5.3 Lead-value calibration (the risky use)

On the *matched* rows only:
- **Absolute plausibility:** does `avg_ticket` land in the real range for the
  category? For water-damage restoration, a card-derived avg ticket far below
  the known $3k–$40k job range = the insurance-undercount failure mode, and is
  a **NO-GO for lead-value** even if match rate is high.
- **PASS →** consider feeding `lead_values` from Enigma; **FAIL (expected) →**
  fill `lead_values` from agency close data via `leadoff_calibration` instead,
  and drop Enigma from this use.

### 5.4 Decision matrix

| Coverage (§5.1) | Growth (§5.2) | Lead-value (§5.3) | Outcome |
|---|---|---|---|
| < 40% | — | — | **Full NO-GO.** Neither use; revisit only if we add card-present categories (salons, retail). |
| ≥ 40% | PASS | FAIL | **Build growth only** (§7). Lead-value stays on close data. *(Expected outcome.)* |
| ≥ 40% | PASS | PASS | Build growth; pilot lead-value as a second phase. |
| ≥ 40% | FAIL | PASS | Unusual — reconsider; lead-value alone rarely justifies the contract. |

---

## 6. Effort + cost of the pilot itself

- **Spend:** trial/eval key + ~12 lookups ≈ negligible. If no trial key,
  the pilot is a short sales conversation + a metered eval, not a contract.
- **Work:** ~half a day — pull the test list from the DB, a throwaway script
  hitting match + attributes, fill the §5 scorecard by hand. **No** migration,
  **no** service code, **no** dependency added. Results: one CSV + a one-page
  findings note appended to this doc as §8.
- **Who runs it:** needs the Enigma key (owner-provisioned) and, for §5.3, the
  ground-truth revenue for the bucket-B anchors.

---

## 7. Build sketch — ONLY if §5 passes (not authorized here)

Kept deliberately minimal and consistent with LeadOff's existing patterns, so
a green pilot has a clear, small next step:

- **Vendor shape:** a metered external client like DataForSEO —
  `services/leadoff_enigma.py` (match + attributes), **scoped to
  scouted / tryout / handoff / calibration markets**, never a board-wide
  34k-market pull. Own daily budget guard + `leadoff_spend` ledger entry,
  mirroring the domain-intel / brand-footprint meters.
- **Cache:** app-owned table (e.g. `public.enigma_business_metrics`), keyed by
  Enigma business id with the globally-normalized brand key alongside (franchise
  dedupe, same as `brand_mentions`), 90-day freshness. Card data ≠ scanner
  data, so it lives in app-owned tables, never in reload-wiped `market_scanner`.
- **Growth into the grade (if §5.2 passed):** a **bounded, calibration-tuned
  multiplier** on the winnability/timing pillar — same discipline as every
  other enrichment signal (no-frankenscore rule). It enters the grade **only
  after** the calibration loop validates it against real outcomes; until then
  it's context/display, frozen into `leadoff_predictions` like proximity.
- **Lead-value (only if §5.3 passed):** feed the `lead_values` store
  (per-category, optionally per-market), **not** a grade multiplier — it's an
  economics input, not a competition signal.
- **Coverage honesty:** every surface that shows an Enigma number carries its
  match-confidence + coverage caveat; an unmatched incumbent shows "no card
  data", never a zero (the brand-footprint lesson — a missing signal is not a
  weak one).

---

## 8. Pilot findings

_To be filled after the pilot runs. Record: the §5 scorecard table, the match
rate, the positive-control result, growth-trend plausibility, lead-value
plausibility, and the §5.4 outcome. Then either close this doc as NO-GO or open
the §7 build with the owner's go-ahead._
