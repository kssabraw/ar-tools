# Missed-opportunity valuation — the dollar pain point (PRD v0.1)

**Status:** design, not built. A per-prospect **dollar estimate** of the local demand a business
forgoes by not ranking in the Google Maps pack, framed as a competitive pain point. Read alongside
`reporting-layer-spec.md` (§4 report, §5 delivery, the approval gate), `scoring-spec.md` (the value
vocabulary this deliberately does NOT reuse — see §Boundaries), and the `DECISIONS.md`
2026-09-05 entries that settled every choice here.

**Vocabulary — say "estimated missed opportunity," never "loss."** A business that is not in the
pack has not *lost* money it once had; it is *failing to capture available demand*. "Loss" invites
"prove it" and cannot be defended; "estimated missed opportunity" is honest and survives scrutiny.
Every surface uses the former.

---

## 1. What it measures, and the discipline it must keep

The module's governing invariant is *never a fabricated fact/number, never an LLM guess* — the whole
report is deterministic and fact-grounded, the same discipline as the heatmap renderer. **A dollar
figure is not a fact.** It is the output of a multi-link model in which only the first link is
measurable for a business we have never spoken to; the rest are assumptions.

This feature is therefore the module's first *modeled* number, and it earns its place the way the
heatmap does — **by showing its work**, not by being precise:

- It is a **range**, never a bare point.
- Every soft input is **labeled and editable**, shown next to the number, never a silent constant.
- It carries a one–two-sentence **"how we estimated this"** line wherever it appears.
- It is framed as **potential / estimated missed opportunity**, never "you are losing $X."

The number is honest because it is auditable, not because it is exact.

## 2. The valuation chain

```
estimated missed opportunity  =  local monthly demand          (searches)
                              ×  map-pack click-share missing   (visibility gap)
                              ×  [ close rate × value per job ]  (missed-revenue framing only)
```

- **Local monthly demand** — metro search volume (DataForSEO, measured) **downscaled to the
  measured footprint by Census population share** (§4). The only near-measured link.
- **Map-pack click-share missing** — from the `rank_vector` already on disk: the fraction of the 81
  grid points where the prospect is **outside the top 3**, multiplied by a published **3-pack
  CTR curve** (config). Uniform grid weighting in v1.
- **Close rate × value per job** — per-category **assumptions** (§6). Used only by the
  missed-revenue framing; the ad-cost-equivalent framing skips them entirely.

## 3. Two framings, two surfaces

Both are built. They lead different surfaces because they carry different assumption loads.

| Framing | Formula | Assumption load | Leads |
|---|---|---|---|
| **Ad-cost-equivalent** | `demand × gap × CPC` | none beyond demand+gap — CPC is measured and already prices a click | the **client-facing PDF** (the defensible anchor) |
| **Missed-revenue** | `demand × gap × close × job-value` | two soft assumptions (close, job-value) | the **internal call hook** (the emotional number) |

**The range comes from a conservative→high band on the two softest assumptions** (close rate and
job value): the low end runs the conservative close-rate/job-value, the high end the aggressive one.
The ad-cost-equivalent shows as a single defensible **anchor** beside the band. Rendered as, e.g.:

> *"~$3,100/mo to replace this in Google Ads; an estimated $6k–$14k/mo in booked work at typical
> close rates for your trade."*

**Surfaces (from the report/approval invariants — §Boundaries):**
- **Call hook + internal brief** — computed-on-read, no approval gate. Leads with the missed-revenue
  band as spoken "potential" ammunition for the caller.
- **Client PDF** — a clearly-labeled **estimate box with its assumptions visible**, led by the
  ad-cost-equivalent anchor, riding the existing `report_approval` gate. Never a bare headline
  dollar figure.

## 4. Demand: fetch, and the Census downscale

**The hard floor, stated so nobody chases it:** sub-metro absolute search volume does not exist at
the source. Google Keyword Planner's finest geo is ~city/metro/DMA; no vendor sells "searches within
5 miles of this pin." Anything more local than metro is a **modeled downscale** of a metro number.

**Fetch (paid, once per keyword × location).** Search volume + CPC are a property of the
*(keyword, location)*, identical for every prospect in a submarket — so we fetch **once and cache**,
never per prospect. This mirrors the organic auto-enqueue path exactly:

- On snapshot finalize, `scan_runner.collect_ready` auto-enqueues a **`demand_fetch_request`**
  signed order (sentinel `requested_by`, budget-gated, idempotent per `(keyword, location_code)`),
  drained ≤1/tick by a new `demand_fetch_queue`. It runs **one** DataForSEO
  `keywords_data/google_ads/search_volume/live` call and caches `{search_volume, cpc, competition}`
  in a new outreach table **`keyword_demand`** keyed by `(keyword, location_code)`. Re-orders are a
  free no-op (already-cached), same as organic.
- **Location resolution.** `search_volume/live` needs a DataForSEO `location_code`, not the
  `location_coordinate` the module already uses everywhere. The module stores neither a
  `location_code` nor a `place_id`. So the onboard/scan path must **resolve the nearest city/metro
  `location_code` from the submarket center lat/lng and store it on the submarket** (an additive
  column — `submarket` is owned by `PRD-prospect-pipeline.md`; this adds `location_code`, never
  touches geometry). The suite's `dataforseo_rank.location_code_for` does exactly this and is the
  port reference. *(Verify the exact resolution endpoint at build — §Spikes.)*

**Localize (free, at report-assembly time in platform-api).** The metro volume is downscaled to the
measured footprint:

```
local_demand = metro_volume × ( population within the footprint ÷ metro population )
```

- Footprint = the **grid radius (5 mi), config-editable** — so demand and the grid-measured gap
  share one geography (this is what fixes the metro-volume unit mismatch). A wide-service-area trade
  can widen it.
- Population comes from the suite's existing **`census_demand.py`** (ACS block-group population
  within a radius) — it already runs the LeadOff placement advisor, and it lives in **platform-api,
  the same service that assembles the outreach report**, so the downscale is a free at-report-time
  computation. No new Census integration.

## 5. Gap: from `rank_vector` × a config CTR curve

The visibility gap is derived from data already on disk — no new call:

- `rank_vector` (one byte per grid point) → **fraction of live points where rank is outside the top
  3** = the missed-state fraction. `255` = dead/unmeasured (excluded from the denominator per the
  coverage invariant); `0` = measured-absent (counts as missed); `1..3` = in pack (captured).
- Multiply by a **published 3-pack CTR curve** seeded as versioned config (roughly: the local pack
  captures ~40–45% of clicks; position 1 takes the majority, tapering across 2–3). The
  counterfactual is deliberately modest — "if you were *in the pack*," not "#1 everywhere" — keeping
  the estimate conservative.
- Uniform grid weighting in v1. Population-weighting the grid is a later precision upgrade, not a v1
  dependency.

## 6. Per-category assumptions

Close rate and job value vary enormously by trade, so they are a **per-category table**, keyed on the
**module's existing vertical taxonomy** (the `category_status` vertical allow-list) — never a second
category vocabulary that would drift from it. `prospect.category` (Outscraper, populated at ingest)
resolves to a vertical; the table gives that vertical a conservative and an aggressive close-rate and
job-value. A prospect whose vertical is `unknown`/`off_category` falls to a **conservative global
default** — the honest behavior, since we don't know its economics.

Defaults are seeded from Census receipts-per-establishment (County Business Patterns / Economic
Census) plus published industry benchmarks, cited in the config so the "how we estimated this" line
can name the source.

## 7. Competitive framing

The pain point names the competition, but the dollars stay aggregate:

- **Aggregate dollar figure** — "you're missing ~$N/mo of searchable demand in your area."
- **Named competitors as the "who"** — the pack holders already in the MAPS signal
  (`summarize_competitors`): "ABC Plumbing shows in the pack on all 12 searches where you're
  invisible."
- **Never a per-competitor dollar amount.** We cannot measure a competitor's revenue, and it is the
  one claim a prospect can instantly dispute. (Consistent with the I-099 evidence-tagging discipline
  and the one-directional name-match rule.)

## 8. Storage, freeze, replayability

Three input classes, handled per the module's `score_factors`-replayable and
coverage-contemporaneous invariants:

- **Per-category defaults + CTR curve → versioned config**, following the scorecard-coefficient
  precedent (`OUTREACH_SCORECARD_COEFFICIENTS_JSON`). Git-versioned, cited, transparent.
- **Internal surfaces (call hook, brief) → computed-on-read** — a derived read over
  (cached demand) × (stored `rank_vector`) × (config), like `v_prospect_placeholder_score`. **No
  stored score row** — respects I-082 (`prospect_score` belongs to the Phase-4 model).
- **Client PDF → freezes every input at approval** (metro volume, CPC, resolved `location_code`,
  Census population figures, CTR-curve version, category-default version, any operator override)
  onto the `report_approval` / `report_artifact` provenance record (owned by `reporting-layer-spec`).
  The dollar figure a prospect saw is reproducible forever — the same discipline as contemporaneous
  coverage.
- **Operator override** (the caller learns the real job value on the call) lands on that frozen
  record, and **never mutates the config defaults**.

## 9. Invariants this feature must honor, and the two it touches

Honors: computed-on-read only for internal surfaces; no `prospect_score` write; coverage denominator
counts measured-not-found; approval gate on any prospect-facing asset; unknown ≡ absent (a missing
demand figure omits the number, never zeroes it); a paid call only through a signed order.

**Touches — flag for the build session:**

1. **The call-hook composer currently FORBIDS money/lead/traffic-volume numbers** (`_compose_hook`,
   *"a claim the prospect can falsify in one sentence costs the call"*). This feature carves a
   **scoped exception** for the estimate-that-shows-its-work — and only because it is a range with
   visible assumptions, not a bare claim. The prohibition otherwise stands.
2. **A new signed-order type `demand_fetch_request`** and a new cached table `keyword_demand`, plus
   an additive `submarket.location_code` column. All in `outreach/migrations/` (never
   `writer/supabase/migrations/`).

## 10. Config keys (all `OUTREACH_*` env / settings)

| Key | Purpose | Default |
|---|---|---|
| `valuation_enabled` | master gate for the whole feature | off until v1 ships |
| `demand_fetch_auto_enabled` | auto-enqueue the demand fetch on snapshot finalize (mirrors `organic_auto_enabled`) | True |
| `demand_fetch_actor_id` | sentinel `requested_by` for auto orders | `00000000-…` |
| `valuation_footprint_radius_miles` | Census downscale footprint | 5 (= grid radius) |
| `valuation_pack_ctr_curve` | 3-pack CTR curve, position→click-share (JSON) | seeded from a cited study |
| `valuation_category_assumptions_json` | per-vertical close-rate low/high + job-value low/high | seeded, cited |
| `valuation_global_close_low` / `_high` | fallback close-rate band | conservative |
| `valuation_global_job_value_low` / `_high` | fallback job-value band | conservative |

## 11. Build phasing (module phase-discipline)

- **Phase A — internal-only, computed-on-read.** The `demand_fetch_request` order + `keyword_demand`
  cache + `location_code` resolution; the Census downscale in platform-api; the gap × CTR math; the
  two framings + band; surfaced in the **call hook + internal brief only**. No PDF, no freeze. This
  is the whole model working, at zero client-facing risk — ship and pressure-test it on real calls
  first.
- **Phase B — client PDF.** The labeled estimate box, the input freeze onto the approval record, the
  operator override. Rides the existing approval gate. Only after Phase A's numbers have been sanity-
  checked against real markets.
- **Deferred:** population-weighted grid (vs uniform); multi-keyword / category-basket demand
  (single-keyword is the v1 decision); competitor review-velocity as a revealed-demand cross-check
  (§Boundaries); a per-vertical CTR curve.

## 12. Spikes to run before/at build (measure-don't-infer)

1. **DataForSEO location resolution.** Confirm the exact endpoint that maps a lat/lng to the nearest
   Google-Ads `location_code`, and that `search_volume/live` returns usable volume+CPC at
   **city/metro** granularity for the small-local keywords this pipeline targets (not just national
   terms). Port reference: the suite's `dataforseo_rank.location_code_for`.
2. **CTR-curve source.** Pin a citable published 3-pack CTR study for the seed values; record the
   source in config next to the numbers.
3. **`census_demand.py` reuse from the outreach report path.** Confirm it is cleanly callable at
   report-assembly time and that its Census egress works on the worker (the build sandbox is
   egress-blocked, per the module note).

## 13. What is genuinely unvalidated

Say so in comments where it matters, per the module's posture:

- Every **close-rate and job-value** benchmark is an elicited estimate until real outcomes exist.
- The **3-pack CTR curve** values are a published prior, not measured for this portfolio.
- The **population-∝-searches downscale** is a reasonable, explainable assumption — not a measured
  fact. Local search intent skews with commercial corridors, commuters, and tourism, which
  population alone doesn't capture. It stays inside the "estimate that shows its work" frame; the
  deferred review-velocity cross-check is how a badly-off downscale would be caught.

The chain arithmetic is careful reasoning in real mathematics, which makes the output look more
authoritative than it has earned. Treat the dollar figure as a **conservative, defensible estimate
for a cold conversation** — never a measurement.
