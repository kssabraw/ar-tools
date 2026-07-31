# PRD — Prospect Ingestion & Scoring Pipeline v2.8

**Module:** `outreach-pipeline` (AR Tools)
**Depends on:** `scoring-spec.md` (coefficient tables, scaling constants, refit path)
**Stack:** FastAPI on Railway · Supabase (Postgres) · DataForSEO · Outscraper
**Status:** Draft for implementation

**Changes from v2.7:** `grid_result` reconciled with the storage spec (was a conflicting duplicate);
`trigger_reason` and `geometry_version` added to `scan_snapshot`.

**Changes from v2.6:** §17 marked superseded by START-HERE; verification cost corrected.

**Changes from v2.5:** audit fixes — broken scoring-spec reference, stale slot depth in §8.

**Changes from v2.4:** consistency pass — stale depth-3 figures, cost terminology and portfolio
reconciliation, touch/lead_activity boundary.

**Changes from v2.3:** §8b corrected — `ai_region` separated from `submarket`, since neighbourhood
names anchor AI prompts rather than bounding grids.

**Changes from v2.2:** coordinate-sensitivity spike replaced with prompt-granularity spike;
§8b added covering submarket naming, recognition testing, and the fallback ladder.

**Changes from v2.1:** §16a added — three verification spikes recorded with test procedure and
what each result would change.

**Changes from v2.0:** selection parameters recorded — slot depth 5, MMR λ scheduled from 0.5,
λ_shrink held at 0.5 and documented as non-ranking.

**Changes from v1.9:** franchise detection changed from hard exclude to review flag, resolving a
dead-coefficient inconsistency; review recency confirmed absolute.

**Changes from v1.8:** evidence/cadence decisions recorded; bootstrap share raised to 100% with
separate contamination rules for base-rate vs effect estimation.

**Changes from v1.7:** channel split ramped and gated on `email_track_ready`; per-channel Model A
base rates recorded.

**Changes from v1.6:** channel split 30/70, flat pricing, manual reply capture recorded;
email sending stack flagged as a critical-path prerequisite.

**Changes from v1.5:** CRM layer cross-referenced; suppression noted as an upstream gate.

**Changes from v1.4:** asset generation gated on explicit approval; emit delivers a queue.

**Changes from v1.3:** reporting layer cross-referenced.

**Changes from v1.2:** provider contingency cross-referenced; parallel-run requirement flagged
at the provider decision.

**Changes from v1.1:** operational mitigations — logged randomization overrides, response-latency
instrumentation, diagnose-not-promise copy constraint, auto-drafted case studies.

**Changes from v1.0:** §9a data integrity guards — land masking, place_id drift suppression,
snapshot completeness, scoped cost ceilings.

**Changes from v0.9:** four blockers resolved and recorded — touches_per_sequence = 5,
hybrid submarket decomposition, split LLM source, evidence randomization assignments.

**Changes from v0.8:** §15a added recording six decisions settled in design discussion
(portfolio scope, no scan tiering, Supabase, R2 blobs, split trigger, no case studies at launch).

**Changes from v0.7:** capacity config re-expressed as `monthly_prospect_starts` (default 100)
with touch volume derived; tuning asymmetry documented; sequence and template versions stamped
on outcomes and assets so effect estimates stay separable.

**Changes from v0.6:** semi-monthly uniform scan cadence (15 days); deltas computed against
the mean of the prior two snapshots; delta claims gated at 3 snapshots while contact stays at 2;
event-triggered scans; send-time LLM verification.

**Changes from v0.5:** DataForSEO recorded as the decided sole scan provider with rationale;
filled slots continue scanning so prospecting evidence becomes unbroken client tracking.

**Changes from v0.4:** minimum-history gate added alongside the freshness ceiling;
multi-snapshot pain aggregation and coverage variance; bootstrap mode for cycle one.

**Changes from v0.3:** evidence attribution logging added — per-asset element manifests,
randomized assignment, and engagement instrumentation.

**Changes from v0.2:** selection objective changed from top-N prospects to expected slots
filled, with MMR-style diversification against correlated failure; slot state model added;
vendor-failing compound signal added.

**Changes from v0.1:** pipeline restructured into a one-time market phase and a recurring scan
cycle; evidence freshness enforced as a hard gate; change-detection promoted to a first-class
scoring signal; reachability split by outreach channel; phone track separated from email track
(no enrichment cost); case-study matching added; shortlist sized against touch capacity rather
than market size; call-hook generation added alongside audit evidence.

---

## 1. Purpose

Given a market and a set of GBP categories, produce a ranked, contact-ready prospect queue with
the evidence needed to generate a per-prospect audit or call hook — sized to what AR can
actually work, and refreshed before it goes stale.

Two economic principles govern the design:

**Scan at market level, score at business level, spend at shortlist level.** One geogrid scores
every business in a submarket simultaneously. Contact enrichment — the most expensive
per-record service in the stack — runs only on prospects that survive filtering and scoring,
and only on the email track.

**Never score more than you can work before the evidence decays.** Pack positions move, ads
turn on and off, reviews accumulate. A queue larger than working capacity is prepaid waste. It
is cheaper to rescan a small area monthly than to scan a large one once — and rescanning
produces change signals that a single scan cannot.

---

## 2. Scope

**In scope**
- Outscraper base ingestion by category × geography
- Deterministic filter gates
- Case-study matching against the existing client book
- DataForSEO scan cycles (Maps geogrid, organic SERP, AI Overview) with snapshotting
- Change detection between snapshots
- Site-fetch signal detection (pixel, ad tags, vendor tags)
- Channel-aware two-pass scoring per `scoring-spec.md`
- Selective contact enrichment — email track only
- Structured evidence bundle + templated call hook
- Evidence attribution logging with randomized element assignment
- Cost accounting, freshness enforcement, capacity-based queue sizing
- Webhook emission to n8n / Encharge

**Out of scope (separate modules)**
- Audit PDF rendering and heatmap graphics — see `reporting-layer-spec.md`
- Email sending, sequencing, deliverability
- Pipeline/lead management after emission — see `crm-layer-spec.md`
- Dialer integration and call logging
- Bayesian refit and Thompson sampling (Stage 3 in the scoring spec; this PRD implements
  Stage 1 priors and the logging required to reach Stages 2–3)

---

## 3. Pipeline structure

### Phase A — market setup (once per market)

```
A1. Ingest     Outscraper base pull, category × geographic tile
A2. Filter     Deterministic gates (cheap, pre-spend)
A3. Match      Case-study matching against client book (free, no API)
```

### Phase B — scan cycle (recurring, default monthly, per submarket)

```
B1. Scan       DataForSEO submarket scans → immutable snapshot
B2. Delta      Diff against prior snapshot for this submarket × keyword
B3. Detect     Site fetch for tech/ad signals (survivors only)
B4. Score P1   pain × money × delta × proof → provisional rank
```

### Phase C — channel tracks (per cycle, forked)

```
C1. Phone track    Score P2 using base-pull phone → emit.  NO ENRICHMENT.
C2. Email track    Enrich top N → Score P2 using email reachability → emit
```

Phase A runs once and is durable. Phase B repeats on cadence and is where nearly all recurring
cost lives (~$1–3 per submarket per cycle). Phase C forks by channel and is the only place
per-prospect spend occurs.

### Why scanning is separated from ingestion

The Outscraper listing set is stable month to month; ranking, ads, and AI citations are not.
Separating them means a rescan costs pennies instead of dollars, and each rescan yields deltas
that a one-time scan cannot produce.

---

## 4. Evidence windows (hard gates)

Two bounds, not one. §4 in earlier versions enforced only a maximum evidence age; a minimum
history requirement is equally load-bearing.

### 4.1 Maximum age — evidence must be fresh

- Every prospect emitted for outreach MUST carry evidence younger than `max_evidence_age_days`
  (default **30**).
- The pipeline MUST refuse to emit a prospect whose backing snapshot is older than the
  threshold, and MUST queue its submarket for rescan instead.
- Rescan cost is negligible (~$0.05 per submarket per keyword for the geogrid), so the correct
  response to an aging queue is always rescan, never "ship it anyway."

### 4.2 Minimum history — evidence must be corroborated

A single geogrid is one sample of a system that genuinely fluctuates. Local pack positions move
day to day for reasons unrelated to the business, and since geogrid coverage is the dominant
scoring discriminator, sampling noise there propagates into every downstream ranking. One scan
also cannot distinguish "always been invisible" from "recently became invisible" — identical
scores, completely different sales situations.

- A prospect MUST NOT be emitted for outreach unless its submarket has at least
  `min_history_cycles` completed snapshots (default **2**) for the primary keyword.
- Scanning is NOT gated. **Every submarket scans from cycle one**; only *contacting* waits.
- Pain features SHOULD be computed from the mean of available snapshots rather than the latest
  one once history exists, with `snapshot_count` recorded in `score_factors`. A score derived
  from one observation and a score derived from three are not equally trustworthy and MUST be
  distinguishable after the fact.
- MUST record `coverage_variance` across snapshots. High variance means the prospect's position
  is unstable, which is itself a pitch ("you're bouncing in and out of the pack") and a caution
  against over-trusting a single favourable or unfavourable reading.

### 4.3 Why this costs nothing

The gate is free because contact capacity, not scan capacity, is the constraint. At ~20 new
prospects per cycle across ~10 submarkets at `slot_depth_max` = 5, a market always has more
scanned inventory than workable capacity. By the time the first batch is worked, later
submarkets have accumulated history unprompted. The observation window is a byproduct of the
capacity gap, not a deliberate delay.

### 4.4 Bootstrap exception

Cycle one would otherwise emit nothing at all.

- `bootstrap_mode` (config, default **on** for a market's first cycle) permits emission at
  `min_history_cycles = 1`.
- Prospects emitted under bootstrap MUST be flagged `evidence_provisional = true` in the emit
  payload and MUST NOT carry delta-based or vendor-failing claims.
- `bootstrap_share` = **1.0** (100% of cycle-one capacity). Cycle one coincides with the
  phone-only ramp phase, so bootstrap contacts cost nothing per prospect and land in the channel
  whose base rate is the weakest assumption in the scoring spec. Doubling that sample is worth
  more than the evidence-quality loss, and 50 extra prospects is well under 1% of qualified
  inventory.
- `outcome.selection_reason` MUST distinguish bootstrap contacts.

> **Bootstrap data has different contamination tolerances for different uses.**
>
> - **Excluded from effect estimates.** Coefficient and evidence-attribution estimates require
>   clean assignment and comparable selection. Bootstrap contacts were selected on noisier
>   scores and MUST NOT be pooled with steady-state contacts.
> - **Included in base-rate calibration, as a floor.** Single-snapshot scoring is noisier but not
>   systematically biased — it makes the contacted set slightly *less* selected than steady
>   state, so the observed reply rate is a conservative estimate rather than a wrong one. That is
>   strictly better than the current phone figure, which has no empirical basis at all. Record it
>   as a lower bound and revise upward as steady-state cycles accumulate.


---

## 4a. Scan cadence

`scan_interval_days` default **15** (semi-monthly), applied uniformly to all scan layers.

### Why uniform rather than per-layer

A mixed cadence — geogrid weekly, LLM monthly, listings quarterly — was evaluated and rejected.
Cost is comparable (~$100–165/yr vs ~$126–174/yr for LA plumbing at 10 submarkets × 3 keywords),
so the mixed schedule buys nothing while adding per-layer cadence state that must be reasoned
about on every scheduler change. One cron, one delta window, one config value is worth more than
the marginal resolution, particularly under unattended overnight execution.

Semi-monthly retains the main benefit of higher frequency: a market becomes workable in ~30 days
rather than ~60, and outcome data is the scarcest resource in the system. It also means the §4.1
freshness gate never fires in normal operation — evidence is at most 15 days old against a
30-day ceiling.

**Accepted inefficiency, stated plainly.** The LLM layer at 24×/year buys additional samples for
mention-rate estimation but effectively no change detection, because those engines' underlying
sources drift on a scale of months. That is roughly $16–48/yr of low-value spend accepted in
exchange for avoiding a second cadence. It is a good trade, not a free one.

### Event-triggered scans

Semi-monthly cannot catch "the week after a hard freeze." A standing weekly schedule is a poor
solution to that anyway — the right mechanism is on demand, not more frequent.

- The pipeline MUST expose a trigger to scan named submarkets immediately, outside cadence.
- Triggered scans MUST write a normal `scan_snapshot` (they are part of the series, not a side
  channel) and MUST be flagged `trigger_reason` for later analysis.
- Triggered scans MUST honour every other gate — cost ceiling, freshness, delta-span limits.
- Cost is pennies per submarket, so the trigger SHOULD be liberal: weather events, competitor
  activity, a market going quiet, or manual curiosity.

### Send-time LLM verification (not a cadence question)

No scan frequency makes a claim true at the moment of sending. Only checking at send time does.

- Before any audit or call hook ships a claim about a specific LLM's output ("we asked ChatGPT
  and you weren't mentioned"), the pipeline MUST re-run that engine, 3 samples, at generation
  time.
- The claim MUST be served from that verification, never from a scheduled scan.
- If verification contradicts the scheduled scan, the claim MUST be dropped and the asset
  regenerated without it — a contradicted claim is worse than a missing one.
- ~$2–6/month at ~70 audits/month. The highest-value spend per dollar in the stack, because it
  protects the single most falsifiable statement in the product.

---

## 5. Change detection

The strongest cold opener is not a state ("you rank poorly") but a change ("you dropped out of
the pack in Overland Park last month"). Deltas are both a scoring feature and the first line of
the pitch, and they cost nothing beyond the rescan already required by §4.

### Delta window — current vs. mean of prior two

At a 15-day scan interval, consecutive-snapshot deltas span only 15 days. Real ranking movement
accumulates with elapsed time; measurement noise does not. A short window therefore has
materially worse signal-to-noise, and the failure mode is expensive — a false "you dropped last
period" claim is trivially falsifiable by the prospect and costs the lead.

- B2 MUST compute deltas as **current snapshot vs. the mean of the prior two snapshots**, not
  against the immediately prior one. This yields a ~30-day effective comparison window with two
  samples of noise reduction — better than monthly consecutive comparison on both axes.
- Delta metrics per prospect per submarket × keyword:

| Delta metric | Source | Pitch value |
|---|---|---|
| `pack_coverage_change` | grid_result diff | Highest — "you lost visibility in X" |
| `competitor_overtake` | grid_result rank diff, named | Highest — names a rival |
| `ads_state_change` | serp_result paid parse | High — ads just turned on/off |
| `aio_citation_change` | ai_check diff | Medium |
| `organic_position_change` | serp_result diff | Medium |
| `review_velocity_change` | prospect diff | Medium — dormancy onset |

- MUST persist deltas to `prospect_delta` with direction and magnitude, referencing both
  snapshot IDs.
- Fewer than three snapshots produces no deltas. Delta features MUST evaluate to `unknown`,
  never `no_change` — absence of a baseline is not evidence of stability.
- Deltas MUST NOT be computed when the span from the oldest contributing snapshot to the current
  one exceeds `max_delta_span_days` (default **45**). A gap means missed cycles, and comparing
  across one produces false "sudden drop" claims.
- **Contact eligibility and delta-claim eligibility differ.** A prospect becomes contactable at
  `min_history_cycles` (2 snapshots, ~30 days). Delta-based *claims* in an audit or call hook
  require 3 snapshots. A prospect may therefore be contacted with a state-based pitch one cycle
  before change-based openers become available.

---

## 6. Channel-aware reachability

**This corrects a live defect in v0.1.** Model A penalized phone-only-no-email at −66, which is
correct for email outreach and wrong for calling, where phone is the channel. Reachability MUST
be computed per channel and selected by the active track.

| Track | Reachability inputs | Enrichment required |
|---|---|---|
| Phone | Base-pull phone, owner-operated, phone type | **None** |
| Email | Enriched email, email confidence, role vs owner address | Yes |

Consequences:

- The **phone track has no per-prospect API cost.** Phone arrives in the Outscraper base pull.
  A calling list MUST be emitted without enrichment, removing the single largest per-prospect
  line item.
- Enrichment MUST run only on prospects selected for the email track.
- `score_factors` MUST record which channel's reachability was applied. A prospect scored for
  calling and a prospect scored for email are not comparable and MUST NOT be ranked in one list.

### Two-pass requirement (retained from v0.1)

- **Pass 1** computes `pain × money × delta × proof`. Reachability is **excluded, not
  defaulted** — a missing factor MUST NOT be silently treated as neutral.
- **Pass 2** applies channel-specific reachability and produces the final score.
- Both passes MUST persist with `pass` = 1 or 2. Pass 1 MUST NOT be overwritten; the pass-1 →
  pass-2 rank delta is the only measurement of whether enrichment depth is set correctly.

---

## 7. Case-study matching

The cheapest conversion lever available, requiring no API call.

- A3 MUST match every filtered prospect against `case_study` on vertical and market
  comparability (population band, metro type, competitive density).
- Match types, in descending strength: same vertical + comparable market → same vertical, any
  market → adjacent vertical + comparable market.
- A match MUST contribute a substantial positive to the money/propensity score AND MUST set
  `primary_pitch = 'proof'`, overriding pain-based pitch selection when confidence is high.
  "We took [client] from invisible to top-3 in [comparable city]" outperforms any pain-led
  opener in local SEO.
- Matched prospects SHOULD route to a distinct outreach sequence. The emit payload MUST include
  the matched case study's identifiers and headline metrics.
- **Case-study drafts MUST be auto-generated at 90 days post-close**, not left to memory. The
  before/after grid data already exists; the pipeline SHOULD emit a draft (heatmap pair, coverage
  delta, timeframe) into a review queue so the manual step is "approve or edit" rather than
  "write this up someday." Market selection depends on proof accumulating, and agencies
  chronically skip the documentation step.
- Case studies flagged `is_public = false` MUST NOT have client names emitted; the pipeline
  MUST substitute an anonymized descriptor ("a plumbing company in a similar metro").

---

## 8. Selection objective — slots, not prospects

**This supersedes the top-N shortlist logic implied by v0.1–v0.2.**

Under soft exclusivity (§11), the unit of value is not a client — it is a **submarket × vertical
slot**. KC plumbing is not a 400-prospect market; it is roughly a 10-slot market, one per
submarket. A submarket that already holds a client is worth zero regardless of how many
high-scoring prospects remain in it.

The objective is therefore expected slots filled, not expected clients:

```
E[slots filled] = Σ_slots [ 1 − Π_i (1 − p_i) ]
```

where `p_i` is close probability for each prospect contacted in that slot.

### Consequence: spread across slots before going deep in one

Ten contacts inside one submarket have a hard ceiling of **one** client. One contact in each of
ten submarkets has a ceiling of ten. The marginal value of the k-th contact within a slot
declines steeply because every contact after the first competes for the same prize.

- The selector MUST allocate capacity across open slots before deepening within a slot.
- `slot_depth_max` (default **5**) caps contacts per slot per cycle.
- Slots in state `filled` or `conflicted` MUST be excluded from allocation entirely.
- **Filled slots MUST continue scanning.** Exclusion applies to contacting, never to
  measurement. Once a slot is filled the prospect is a client, and the same scan cycle that was
  prospecting evidence becomes campaign tracking — same provider, same grid geometry, unbroken
  series. A closed client therefore arrives with however many months of ranking history the
  submarket had already accumulated before they signed, at no additional cost and with no
  onboarding baseline step. Nothing else in the market can offer that, because nobody else was
  already scanning them.
- Slots marked `exhausted` (attempts ≥ `slot_attempt_limit`, default 8, with no reply) SHOULD
  be deprioritized rather than excluded — record the state and revisit on a later cycle.

### Consequence: diversify only against correlated failure

A precise caveat, because the intuitive version of this is wrong. If prospect outcomes were
independent, greedy top-k selection would already maximize `1 − Π(1 − p_i)` and diversification
would gain nothing. Diversification pays **only when failures are correlated** — and here they
plainly are. If the three top-scored plumbers in a submarket are all large, established,
well-reviewed operations, they likely ignore cold outreach for the same underlying reason, and
their failures arrive together.

Selection within a slot MUST therefore penalize similarity to already-selected prospects:

```
next = argmax_i [ λ · normalized_score(i) − (1 − λ) · max_similarity(i, selected) ]
```

- `λ` default **0.5** at launch, scheduled to rise. This is the MMR pattern already used in the
  AR Tools brief generator for heading selection; reuse that implementation rather than writing a
  new one.

> **λ is insurance against the model being wrong, so it must be scheduled, not fixed.** At launch
> the scorecard is entirely unvalidated — elicited coefficients, zero replies, no case studies —
> which is exactly when hedging against correlated failure is worth most. As refits earn the
> ranking credibility, deviating from rank order starts costing expected value instead of buying
> protection.
>
> | Phase | λ |
> |---|---|
> | Launch, priors only | **0.5** |
> | After Stage 2 recalibration | 0.6 |
> | After Stage 3 refit on ≥80 replies | 0.8 |
>
> Progression MUST be gated on refit milestones, not elapsed time.
- Similarity MUST be computed over the profile features that plausibly drive correlated
  non-response — review-count band, business age band, GBP quality tier, ad presence, site
  sophistication — and MUST NOT include the pain features, which are what the score is for.
- MUST record `selection_rank` and `similarity_penalty` in `score_factors` so a prospect's
  position is explainable when it differs from raw score order.

### Capacity sizing (retained, now applied per slot)

v0.1 implicitly assumed one touch per prospect. Real sequences run 4–7 touches, and multi-touch
reply rates substantially exceed single-touch.

**Config unit is prospect starts, not touches.** Earlier versions used
`monthly_touch_capacity`, which is ambiguous by a factor of five — "100 contacts a month" reads
as either 100 sends or 100 sequences, and those differ by the sequence length. The primary
config is therefore the number of *new prospects entered into sequence per month*; touch volume
is derived from it, not the other way round.

```
prospects_per_cycle   = monthly_prospect_starts ÷ cycles_per_month
implied_touch_volume  = monthly_prospect_starts × touches_per_sequence   -- sanity check only
```

- Default `monthly_prospect_starts` = **100**, `touches_per_sequence` = **5**. At
  semi-monthly cadence that is **50 new prospects per cycle**, allocated across open slots at ≤5
  per slot, implying **~500 sends/month**.
- `monthly_prospect_starts`, `touches_per_sequence`, `slot_depth_max`, and `λ` MUST be config.
- Enrichment depth (email track) MUST equal `prospects_per_cycle` × email share.
- Scoring models predict P(reply | full sequence), not P(reply | one touch). Base rates in the
  scoring spec are documented as sequence-level.

### Tuning asymmetry

`monthly_prospect_starts` is freely tunable in both directions, but the two directions are not
symmetric in cost:

- **Down** is free. Unspent inventory keeps.
- **Up** is one-way. A contacted prospect who ignores a weak pitch is unavailable for 6–12
  months, and cannot be recovered by lowering the setting afterwards.

Evidence quality is at its lifetime worst at launch — no case studies, cold-start coefficients,
bootstrap mode, no delta history, and no vendor-failing detection until the third cycle.
Starting low and ramping as the evidence improves is therefore correct sequencing, not caution:
high volume at launch spends the most inventory at the lowest pitch quality the system will
ever produce.

### Confounds — versioned, not silently changed

`touches_per_sequence` and audit template content are **confounds, not settings**. Reply rates
from a 5-touch and a 7-touch sequence are not comparable, and changing either mid-flight
silently contaminates every downstream effect estimate.

- `outcome` MUST stamp `sequence_version` and `touches_per_sequence_at_send`.
- `audit_asset` MUST stamp `template_version`.
- Analysis MUST segment by these before pooling. Cohorts spanning a version change MUST NOT be
  compared without stating the change.
- Changing either MUST bump the version rather than mutating config in place.

---

## 8a. Vendor-failing detection (compound signal)

The highest-intent moment available in this business, and both halves already exist in the
pipeline unconnected: **vendor tags present** (they are paying someone) **AND declining pack
coverage or lost organic position** (that someone is losing). Active budget plus visible
dissatisfaction means the sale is displacement, not education.

- MUST be evaluated as a single compound feature, not as two independent contributions. Firing
  requires: `site_signal` vendor tag present (CallRail, Podium, Birdeye, or an agency-attributed
  tag) AND a negative `prospect_delta` on `pack_coverage_change` or `organic_position_change`.
- MUST set `primary_pitch = 'displacement'`, overriding both pain-led and proof-led selection.
- MUST suppress the `likely_represented` penalty when it fires. Representation is normally a
  mild negative (they believe they are handled); when the incumbent is visibly failing,
  representation is the entire premise of the pitch and must not also be scored against them.
- Requires two scan cycles, so it is unavailable on a submarket's first pass. Evaluates to
  `unknown`, never `absent`, before a baseline exists.
- Coefficients in `scoring-spec.md`.


---

## 9. Stage requirements

### A1 — Ingest (Outscraper)

- MUST fan out one query per category × geographic tile; Google caps results per query area, so
  a single large-metro query will not return the full market. Deduplicate on `place_id`.
- MUST use the async request pattern (POST returns request ID; poll or webhook).
- MUST persist the raw response in `prospect.raw` before parsing. Re-parsing is free; re-pulling
  is not.
- MUST capture `phone_type` (mobile / landline / unknown) where available — see §12.
- MUST request base tier only. Enrichment services are billed separately and MUST NOT be
  enabled here.

> **Verify against current docs before implementing.** Outscraper endpoint paths, enrichment
> parameter names, and tier boundaries have shifted across versions. Confirm against the live
> API reference rather than the field names in this PRD.

### A2 — Filter

| Rule | Default | Type |
|---|---|---|
| `business_status` closed (permanent or temporary) | exclude | hard |
| No phone number | exclude | hard |
| Franchise / chain name pattern match | **flag for review** | soft — see below |
| Review count < 10 | exclude | soft, configurable |
| Present in `suppression` (any scope) | exclude | hard — see CRM spec §4 |
| No review within 9 months | exclude | soft, configurable |

- MUST log every exclusion with the triggering rule AND every other rule the prospect would
  also have failed. Dead listings typically fail three gates at once; first-match-only logging
  produces misleading tuning data.
- MUST NOT apply client-conflict exclusions here. Conflict is a flag, not a filter (§11).
- **Review recency — DECIDED: absolute 9-month window.** It is the only gate that can kill a
  healthy business, since commercial and builder-focused operators have low consumer review
  velocity. The relative mode (velocity drop against the business's own baseline) is more correct
  but requires history that does not exist until cycle three; it remains a later upgrade, not a
  launch requirement.

### Franchise detection — flag, never auto-exclude

**DECIDED: pattern matches flag for review rather than excluding.** A false positive is a
permanently lost prospect, and plenty of legitimate independents carry chain-like names.

```sql
alter table prospect add column franchise_status text not null default 'unknown'
  check (franchise_status in
    ('unknown','flagged','confirmed_franchise','confirmed_independent'));
```

- Name-pattern match sets `flagged`, never excludes.
- `flagged` prospects ARE scored — market-level scanning already covers them at zero marginal
  cost — but MUST NOT be enriched or contacted until reviewed.
- Review resolves to `confirmed_franchise` (excluded from contact) or `confirmed_independent`
  (proceeds normally, and the Model A franchise penalty MUST NOT apply).

> **This resolves a live inconsistency.** The previous design both hard-excluded franchises at
> the filter and carried a −87 franchise penalty in Model A. Excluded prospects are never scored,
> so that coefficient was dead. Under the flag approach it does real work: `flagged` prospects
> score with the penalty and sink naturally in rank, and review converts the flag into a
> definitive status.

### B1 — Scan (DataForSEO)

> **Provider — decided, not open.** DataForSEO is the sole scan provider for geogrids, organic
> SERP, and AI surfaces. Local Dominator and other per-business geogrid tools were considered
> and rejected. The governing reason is capability, not price: this pipeline needs the **full
> pack at every grid point** (~20 results per coordinate), because that is what allows one grid
> to score every business in a submarket simultaneously. Tools built around a single target
> business's rank cannot support market-wide scoring at any price. Cost reinforces the choice —
> fractions of a cent per point versus dollars per scan.
>
> **Consequence: no baseline reconciliation problem.** Because the same provider and the same
> grid geometry serve both prospecting and post-close client tracking, the audit heatmap *is*
> the day-one campaign baseline. There is no measurement discontinuity at handoff and no
> "baseline provider differs" caveat on the first client report.
>
> Not abstracted behind a provider interface in v1. Entity resolution depends on `place_id`
> arriving from a consistent source; mixing providers later would complicate the join logic,
> and that is the cost of revisiting this. Provider calls SHOULD still be isolated behind a thin
> internal module — cheap, and not the same as building a speculative abstraction.
>
> **Contingency is documented separately** in `dataforseo-dependency-note.md`: capability
> requirements, substitution candidates, migration triggers, and the parallel-run requirement.
> Note in particular that any provider change MUST be parallel-run rather than cut over — a hard
> switch would manufacture a portfolio-wide false delta on day one, since providers differ in
> proxy pools and location simulation. Delta claims are the strongest output this system
> produces and the most damaging to get wrong.

- MUST generate grid geometry per submarket: default 5-mile radius, 1 point per mile, clipped
  to the circle (~89 points). Grid parameters MUST be persisted per snapshot — the audit
  heatmap becomes the day-one campaign baseline and a later provider must reproduce it.
- MUST write an immutable `scan_snapshot` row per submarket × keyword × cycle. Snapshots are
  append-only; deltas depend on history.
- MUST use standard (queued) tier by default. Live mode costs ~3.3× for latency this pipeline
  does not need.
- MUST batch task submission (up to 100 per POST) and use postback/pingback, not polling.
- MUST parse paid results from the organic response for the ads-gap signal. Do not issue
  separate ad queries.
- AI engine checks (ChatGPT / Claude / Perplexity) run **per named region, not per submarket** —
  these engines are locality-coarse and gain nothing from 5-mile granularity. MUST record
  `(engine, prompt, region, sample_n, mentioned_entities[])` with ≥3 samples so the audit
  reports a mention *rate* rather than a single binary miss.

### B3 — Detect (site fetch)

- MUST fetch each surviving prospect's site directly (own HTTP request, not a paid service) and
  detect: Meta pixel, `AW-` conversion tags, GTM container contents, CallRail, Podium, Birdeye,
  Google Guaranteed badge.
- MUST follow the GTM container to catch injected pixels; inline detection alone yields false
  negatives.
- MUST rate-limit and set per-domain timeouts. Failed fetches record `unknown`, never `absent`.
- All ad/tech signals are one-directional: presence adds, absence never subtracts, and
  `unknown` behaves identically to `absent`.

### B4 / C — Scoring

- MUST implement the scorecard per `scoring-spec.md`: `Score = Offset + Factor ×
  ln(odds)`, `Factor = PDO / ln(2)`, PDO 50, base 500.
- All coefficients MUST load from config. Zero hardcoded βs.
- MUST apply `λ_shrink` (default 0.5) and persist both `beta_prior` and `beta_effective`.
- MUST write `score_factors` as a complete replayable decomposition: `[{feature, bin,
  beta_prior, beta_effective, points, evidence_ref, channel}]`. Points + offset MUST reproduce
  the stored score exactly.
- MUST compute all three models (A reply, B close-given-reply, C expected value) separately.
  Default ranking view is C.
- Displayed probabilities MUST be clamped to ≤60%; UI MUST show decile/rank rather than
  percentage until `calibration_alpha` is non-null.

### C2 — Enrich (email track only)

- MUST select by pass-1 rank, depth = `prospects_per_cycle` × email share (§8).
- MUST estimate cost before submitting and abort if the run would exceed the budget ceiling.
- MUST record per-prospect enrichment cost in `cost_ledger`.
- SHOULD run a verification spike before first production use: enrich ~20 businesses with known
  pixel configurations (direct-injected and GTM-injected) and measure detection rate and actual
  tier cost. If GTM-injected pixels are largely missed, the B3 container fetch is promoted from
  false-negative check to required step.

### C — Emit

- MUST emit via configurable webhook (n8n / Encharge) an **audit-ready queue**, not generated
  assets. Payload includes prospect identity, channel, contacts, final score, `score_factors`,
  `primary_pitch`, matched case study, top deltas, and evidence references.
- **Asset generation MUST NOT be triggered by emission.** Prospect-facing assets are generated
  only on explicit human approval — see `reporting-layer-spec.md` §4a. Send-time LLM
  verification and evidence randomization both occur at generation, i.e. after approval.
- Asset copy MUST diagnose, not promise. Claims describe observed state and change ("here is
  where you are invisible"), never committed outcomes ("we will fix this in 90 days"). Because
  scanning continues after close, an over-promise becomes documented failure in the same data
  series that made the pitch. Diagnosis is also the stronger position absent case studies.
- MUST include a templated **call hook** for the phone track: a single sentence built from the
  strongest available evidence, preferring a delta over a state.
  Example shape: *"I searched [keyword] near [neighborhood] this morning — you're not in the
  top three anywhere past [N] miles from your shop, and [competitor] is."*
  Template MUST be config; evidence slots MUST be filled from persisted scan data, never
  improvised at send time.
- MUST write one `outcome` row per emitted prospect with `selection_reason` set, even though
  nothing reads it yet. Retrofitting outcome tracking loses the first hundred data points
  permanently.

---

## 8b. Place naming — two distinct geographies

**Correction to an earlier draft of this section**, which attached `ai_name` to `submarket` and
thereby collapsed a distinction the design depends on.

The grid and the AI layer measure different things at different resolutions, and were never
meant to align:

| | Unit | Typical count per market | What it measures |
|---|---|---|---|
| **Geogrid** | `submarket` — 5-mile radius, ~89 points | ~10 | Proximity-sensitive pack coverage |
| **AI check** | `ai_region` — a recognised place name | ~5 | Whether the model names them at all |

Real neighbourhoods are far smaller than submarkets. Los Feliz is roughly 2 miles across, Queen
Anne about 2, Kew Gardens about 1 — against a 5-mile-radius submarket. A submarket anchored on
Los Feliz also covers Silver Lake, East Hollywood, and part of Griffith Park.

That is not a defect. **The neighbourhood name is an anchor for the AI prompt, not a boundary for
the grid.**

- `ai_region` is a first-class entity. `submarket.ai_region_id` references it.
- **Multiple submarkets MAY share one `ai_region`.** AI checks deduplicate by region, which is
  what keeps AI queries at ~5 per market rather than ~10.
- Grid geometry MUST NOT be adjusted to match neighbourhood boundaries. Geometry is immutable and
  optimised for proximity measurement; names are editable and optimised for model recognition.

> **Audit copy MUST NOT imply the two geographies are the same area.** "You're invisible past two
> miles from your shop" is a grid claim. "ChatGPT doesn't mention you for Los Feliz" is a region
> claim. Stapling them into one sentence invites a correction from a prospect who knows their own
> neighbourhood better than you do.

### Candidate sources, in preference order

1. **Incorporated place names.** In most US metros the suburbs are separate incorporated cities —
   Overland Park, Lee's Summit, Independence. These are universally recognised, correctly scaled,
   and require no judgment. **Prefer them wherever they exist**; the naming problem is largely
   confined to submarkets inside a core city.
2. **Wikidata / Wikipedia-backed places.** For submarkets inside a core city, query Wikidata for
   settlements and neighbourhoods with coordinates and a Wikipedia sitelink within the metro.
   Wikipedia presence is the best available proxy for LLM recognition, because Wikipedia is a
   major training corpus — a neighbourhood with an article is very likely known to the models.
   Sitelink count serves as a recognition-strength ranking signal.
3. **Reverse geocode** (`neighborhood`, `sublocality`) as a fallback. Highest coverage, weakest
   recognition guarantee, and prone to hyper-local names no model knows.

### Recognition MUST be tested, not assumed

Recognition is directly measurable at roughly a cent per name, once per submarket, and geometry
is immutable — so this is a one-time cost of about a dollar across the whole portfolio.

- For each candidate name, issue one cheap LLM call and check that the model places it correctly
  and returns scale-appropriate local businesses rather than metro-wide operators.
- Store the outcome on `ai_region` as `name` and `name_level` ∈
  `{neighbourhood, suburb, city, metro}`.

```sql
create table ai_region (
  id          uuid primary key default gen_random_uuid(),
  market_id   uuid not null references market(id) on delete cascade,
  name        text not null,
  name_level  text not null check (name_level in ('neighbourhood','suburb','city','metro')),
  source      text not null check (source in ('incorporated','wikidata','geocode','manual')),
  recognition_tested_at timestamptz,
  recognition_passed    boolean,
  unique (market_id, name)
);

alter table submarket add column ai_region_id uuid references ai_region(id);
```

**Cheapest available validation, already in your data:** check whether businesses in the
Outscraper pull name themselves after the place — several plumbers with "Los Feliz" in their
business name or address means the name is commercially real, customers use it, and the models
have almost certainly seen it. Free, and it measures recognition more directly than any
notability proxy.

**On sourcing effort:** at ~6–10 anchor names per city across 10 cities, this is ~100 names once,
and geometry is immutable so they never change. Someone who knows these metros can write the list
in an afternoon, faster and more accurately than a Wikidata pipeline. Build the pipeline only
when scaling well past 10 cities.

### Fallback ladder

If a candidate fails the recognition test, fall back to the next-larger recognised place and
record the level actually used. Every submarket gets a usable name; not every submarket gets an
equally strong claim.

> **The level used MUST gate the audit claim.** If a submarket falls back to `metro`, the "we
> asked ChatGPT about [place] and you weren't mentioned" line is weak — a small operator was
> never going to appear in a metro-wide answer, and a sharp prospect will say so. In that case
> the AI line MUST be dropped for that prospect rather than made weakly. A claim that invites an
> easy rebuttal is worse than a claim omitted.

---

## 9a. Data integrity guards

Four failure modes that produce **wrong numbers rather than errors**. Each is silent by default,
and each can put a false claim in front of a prospect.

### 9a.1 Dead grid points (land masking)

A 5-mile radius with 1-mile spacing assumes a roughly circular land area. In coastal metros —
LA, Long Beach, Santa Monica — a material share of points fall in water. They return nothing, and
coverage percentages for every business in that submarket come out uniformly depressed. Coastal
and inland submarkets then score on different scales while appearing comparable. The same applies
to mountains, water bodies, and industrial voids.

**Self-calibrate from scan data; do not buy a coastline dataset.**

- A point is `null` for a scan if it returns zero results, or if the nearest result exceeds
  `2 × grid_spacing_miles` from the point.
- After **3 consecutive null scans**, set `land = false`. The point is retained in geometry
  (geometry is immutable) but excluded from the coverage denominator.
- **Reactivate on any non-null result.** Business density changes; coastlines do not. A point
  that starts returning results rejoins the denominator.
- `prospect_coverage.coverage_pct` MUST use live points as the denominator, and
  `score_factors` MUST record the live-point count so historical scores stay interpretable.

### 9a.2 `place_id` drift

Google merges duplicate listings and reissues IDs on rebrands. When a prospect's ID changes, the
history forks silently: the old record shows a catastrophic coverage loss — your strongest pitch
signal, entirely fabricated — and the new one looks like a cold start.

- MUST maintain `prospect_alias`, matching candidate new IDs on phone + normalized address +
  fuzzy name.
- **Cheap high-value guard, independent of alias quality:** a large negative coverage delta on a
  prospect who is *absent from the current listing pull* is drift, not decline. Such deltas MUST
  be suppressed from scoring and from all claims, and flagged for review.
- This guard MUST apply even when alias resolution fails. Perfect alias matching is not required;
  suppressing the embarrassing case is.

### 9a.3 Snapshot completeness

At ~50,000 tasks per cycle some standard-queue tasks will fail or never return. Missing points
depress coverage, which reads as pain, which promotes prospects for the wrong reason.

- `scan_snapshot` MUST record `expected_points` and `actual_points`.
- Below `completeness_threshold` (default **0.98**), the snapshot is marked `complete = false`.
- Incomplete snapshots MUST be retained and retried, and MUST be excluded from scoring, delta
  computation, and rollup. They MUST NOT be averaged into a multi-snapshot pain estimate.
- Repeated incompleteness on the same submarket SHOULD alert — it usually indicates a geometry
  or quota problem rather than transient failure.

### 9a.4 Cost ceiling scope

`max_run_cost_cents` at $50 was written when a "run" meant one market. At ~50 deep-scanned
market-verticals a full cycle costs ~$200, so an unscoped $50 ceiling aborts every run.

- `max_market_run_cost_cents` — default **5000** ($50), per market-vertical
- `max_portfolio_cycle_cost_cents` — default **40000** ($400), per full cycle
- Both MUST be evaluated. Exceeding either aborts before the next paid stage, never mid-stage.

---

## 10. Data model

```sql
create table market (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  center_lat double precision not null,
  center_lng double precision not null,
  radius_miles numeric not null,
  scan_interval_days integer not null default 15,
  created_at timestamptz not null default now()
);

create table submarket (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  name text not null,
  center_lat double precision not null,
  center_lng double precision not null,
  grid_radius_miles numeric not null default 5,
  grid_spacing_miles numeric not null default 1,
  last_scanned_at timestamptz
);

create table keyword (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  term text not null,
  is_primary boolean not null default false,
  unique (market_id, term)
);

create table prospect (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  submarket_id uuid references submarket(id),
  place_id text not null unique,
  name text not null,
  category text,
  address text,
  phone text,
  phone_type text check (phone_type in ('mobile','landline','unknown')),
  website text,
  rating numeric,
  review_count integer,
  latest_review_at date,
  lat double precision,
  lng double precision,
  business_status text,
  raw jsonb not null,
  ingested_at timestamptz not null default now()
);

create table filter_result (
  prospect_id uuid not null references prospect(id) on delete cascade,
  rule text not null,
  passed boolean not null,
  observed_value text,
  evaluated_at timestamptz not null default now(),
  primary key (prospect_id, rule)
);

-- Immutable scan snapshots; deltas depend on history
create table scan_snapshot (
  id uuid primary key default gen_random_uuid(),
  submarket_id uuid not null references submarket(id) on delete cascade,
  keyword_id uuid not null references keyword(id) on delete cascade,
  grid_radius_miles numeric not null,
  grid_spacing_miles numeric not null,
  point_count integer not null,
  expected_points smallint not null,
  actual_points smallint not null,
  complete boolean not null default false,   -- actual/expected >= completeness_threshold
  trigger_reason text,                       -- null = scheduled cadence; set for event-triggered
  geometry_version text not null,            -- pinned generator version (§8b, reporting §4.1)
  scanned_at timestamptz not null default now()
);
create index on scan_snapshot (submarket_id, keyword_id, scanned_at desc);

-- OWNED BY `storage-retention-spec.md` §5. Reproduced here for context only.
-- Partitioned by month; lat/lng deliberately absent (derivable from scan_snapshot geometry
-- plus point_seq via the pinned generator). Do not implement from this copy — see the
-- storage spec for partition management, retention, and the rollup that depends on it.
create table grid_result (
  id           bigserial,
  snapshot_id  uuid not null references scan_snapshot(id) on delete cascade,
  scan_month   date not null,          -- partition key, denormalized from snapshot
  point_seq    smallint not null,
  place_id     text not null,
  rank         smallint not null,
  primary key (id, scan_month)
) partition by range (scan_month);
create index on grid_result (snapshot_id, place_id);

create table serp_result (
  id uuid primary key default gen_random_uuid(),
  snapshot_id uuid not null references scan_snapshot(id) on delete cascade,
  engine text not null,
  payload jsonb not null
);

create table ai_check (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  region text not null,
  keyword_id uuid references keyword(id),
  engine text not null,
  prompt text not null,
  sample_n integer not null,
  mentioned_entities jsonb not null default '[]',
  raw jsonb,
  checked_at timestamptz not null default now()
);

create table prospect_delta (
  id bigserial primary key,
  prospect_id uuid not null references prospect(id) on delete cascade,
  snapshot_from uuid not null references scan_snapshot(id),
  snapshot_to uuid not null references scan_snapshot(id),
  metric text not null,
  old_value numeric,
  new_value numeric,
  direction text not null check (direction in ('up','down','unchanged','unknown')),
  competitor_place_id text,
  computed_at timestamptz not null default now()
);
create index on prospect_delta (prospect_id, metric, computed_at desc);

create table grid_point_status (
  submarket_id uuid not null references submarket(id) on delete cascade,
  point_seq smallint not null,
  land boolean not null default true,
  consecutive_null_scans smallint not null default 0,
  last_evaluated_at timestamptz,
  primary key (submarket_id, point_seq)
);

create table prospect_alias (
  place_id text primary key,
  prospect_id uuid not null references prospect(id) on delete cascade,
  match_method text not null,
  confidence numeric,
  first_seen timestamptz not null default now(),
  last_seen timestamptz not null default now()
);

create table site_signal (
  prospect_id uuid not null references prospect(id) on delete cascade,
  signal text not null,
  state text not null check (state in ('present','absent','unknown')),
  evidence text,
  fetched_at timestamptz not null default now(),
  primary key (prospect_id, signal)
);

create table case_study (
  id uuid primary key default gen_random_uuid(),
  client_name text not null,
  is_public boolean not null default false,
  anonymized_descriptor text not null,
  vertical text not null,
  market_name text,
  population_band text,
  metric_before text,
  metric_after text,
  timeframe_months integer
);

create table case_study_match (
  prospect_id uuid not null references prospect(id) on delete cascade,
  case_study_id uuid not null references case_study(id) on delete cascade,
  match_type text not null,
  confidence numeric not null,
  primary key (prospect_id, case_study_id)
);

create table score_run (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  cycle_number integer not null,
  model_version text not null,
  lambda_shrink numeric not null,
  calibration_alpha numeric,
  calibration_gamma numeric,
  created_at timestamptz not null default now()
);

create table prospect_score (
  prospect_id uuid not null references prospect(id) on delete cascade,
  score_run_id uuid not null references score_run(id) on delete cascade,
  model text not null check (model in ('reply','close','value')),
  pass smallint not null check (pass in (1,2)),
  channel text check (channel in ('phone','email')),
  raw_points numeric not null,
  score numeric not null,
  predicted_prob numeric,
  decile smallint,
  primary_pitch text,
  evidence_age_days integer not null,
  score_factors jsonb not null,
  primary key (prospect_id, score_run_id, model, pass, channel)
);

create table enrichment (
  prospect_id uuid primary key references prospect(id) on delete cascade,
  email text,
  email_confidence numeric,
  contacts jsonb,
  owner_operated boolean,
  enriched_at timestamptz not null default now(),
  cost_cents integer
);

create table slot (
  id uuid primary key default gen_random_uuid(),
  submarket_id uuid not null references submarket(id) on delete cascade,
  vertical text not null,
  state text not null default 'open'
    check (state in ('open','filled','exhausted','conflicted')),
  attempts integer not null default 0,
  filled_by_prospect_id uuid references prospect(id),
  last_attempt_at timestamptz,
  unique (submarket_id, vertical)
);

create table conflict_check (
  prospect_id uuid primary key references prospect(id) on delete cascade,
  existing_client_id text,
  vertical_match boolean not null,
  market_overlap_pct numeric,
  risk_level text not null check (risk_level in ('none','low','high')),
  reviewed_by text,
  decision text
);

create table audit_asset (
  id uuid primary key default gen_random_uuid(),
  prospect_id uuid not null references prospect(id) on delete cascade,
  score_run_id uuid not null references score_run(id),
  asset_type text not null check (asset_type in ('pdf','call_hook','email_body')),
  template_version text not null,
  content_hash text not null,
  evidence_manifest jsonb not null,
  generated_at timestamptz not null default now(),
  dispatched_at timestamptz
);

create table audit_evidence (
  asset_id uuid not null references audit_asset(id) on delete cascade,
  element text not null,
  available boolean not null,
  included boolean not null,
  assignment text not null
    check (assignment in ('forced','randomized_in','randomized_out','unavailable')),
  assignment_overridden boolean not null default false,
  override_reason text,
  slot text check (slot in ('lead','body','closing')),
  primary key (asset_id, element)
);

create table asset_engagement (
  id bigserial primary key,
  asset_id uuid not null references audit_asset(id) on delete cascade,
  event text not null,
  element_ref text,
  dwell_seconds numeric,
  occurred_at timestamptz not null default now()
);
create index on asset_engagement (asset_id, event);

-- Authoritative record that a contact attempt occurred. Modeling substrate.
-- The CRM's lead_activity carries human commentary and MUST NOT duplicate these rows.
create table touch (
  id bigserial primary key,
  prospect_id uuid not null references prospect(id) on delete cascade,
  touch_number integer not null,
  channel text not null check (channel in ('phone','email')),
  sent_at timestamptz not null,
  template_id text,
  responded boolean not null default false
);

create table outcome (
  prospect_id uuid primary key references prospect(id) on delete cascade,
  first_contacted_at timestamptz,
  selection_reason text not null,
  sequence_version text not null,
  touches_per_sequence_at_send smallint not null,
  touch_count integer not null default 0,
  replied_at timestamptz,
  first_response_at timestamptz,   -- when AR responded to the reply
  closed_at timestamptz,
  retainer_actual numeric,
  churned_at timestamptz
);

create table cost_ledger (
  id bigserial primary key,
  market_id uuid references market(id) on delete cascade,
  cycle_number integer,
  stage text not null,
  provider text not null,
  units integer not null,
  cost_cents integer not null,
  recorded_at timestamptz not null default now()
);
```

---

## 11. Entity resolution & conflict

| Join | Method | Confidence |
|---|---|---|
| Grid → prospect | `place_id` exact | Reliable |
| Organic → prospect | Domain normalization (protocol, `www`, subdomains) | Reliable |
| AI mention → prospect | Fuzzy name match | **Risky — gate it** |

- Directory rankings (Yelp, Angi, Thumbtack) MUST NOT count toward a prospect's organic
  presence. Only their own domain counts. Directory presence SHOULD be captured separately as
  audit color.
- AI name matching MUST carry a confidence score. Below threshold, `score_factors` records
  `ai_match_uncertain` and neither the audit nor the call hook may emit a "you weren't
  mentioned" claim. This is the most falsifiable statement in the product — a prospect can
  disprove it in thirty seconds.
- **Client conflict is a flag, never a filter, and MUST NOT modify the score.** Compute
  `risk_level` from vertical match × service-area overlap against the client book, surface as a
  badge, and require an explicit decision before a prospect enters a sequence.

---

## 12. Calling compliance

`phone_type` is captured because outbound calling rules differ for mobile numbers, and GBP
listings for service-area businesses frequently carry mobile numbers.

- The pipeline MUST store `phone_type` and expose it in the emit payload.
- The pipeline MUST NOT implement dialing, autodialing, or DNC scrubbing — these belong to the
  dialer integration, out of scope here.
- **Open item for Kyle, not the implementer:** confirm the applicable rules with counsel before
  scaling the phone track — federal autodialer and DNC provisions, plus state-level rules
  (California is among the stricter), apply differently to mobile numbers and to B2B calls than
  is commonly assumed. This is a legal question, not a technical one, and the downside is fines
  rather than wasted spend.

---

## 13. Cost guardrails

- Each run MUST estimate cost before executing each paid stage and abort if the cumulative
  projection exceeds either `max_market_run_cost_cents` (default $50 per market-vertical) or
  `max_portfolio_cycle_cost_cents` (default $400 per full cycle).
> **Terminology.** A **market-vertical** is one vertical in one city (e.g. LA plumbing). The
> portfolio is 5 verticals × 10 cities = **50 market-verticals**. All per-unit figures below are
> per market-vertical unless stated otherwise.

- **Per market-vertical, one-time:** ~$2–4 Outscraper base pull.
- **Per market-vertical, per cycle:** ~$0.16 geogrid + <$0.05 organic/AIO + $1.35–4.05 LLM checks
  + ~$1.07 AI Mode ≈ **$3–6**.
- **Phase C, portfolio-wide per cycle:** enrichment on 35 prospects (70% of 50 starts) ≈ **$0.40**.
  Contact volume is a portfolio budget, not a per-market one — it does not scale with market count.
- **Portfolio totals:** ~$150–300 one-time, then **$150–300 per cycle**, i.e. **$3,600–7,200/year**
  at 24 cycles. Reference point: LA plumbing alone runs ~$100–165/year.
- Add ~$2–6/month for send-time LLM verification (~70 audits/month, portfolio-wide and
  capacity-bound — does not scale with market count).

> **Ceiling sanity check.** At 50 market-verticals × $3–6, a full cycle costs $150–300 against a
> `max_portfolio_cycle_cost_cents` of $400. That is 25–60% headroom — deliberate, but tight enough
> that adding verticals or keywords should be accompanied by raising the ceiling.
- Phone-track-only operation incurs **zero** per-prospect cost.
- Hitting the $50 ceiling implies ~10× the default configuration and MUST be treated as a bug
  until proven otherwise.
- `cost_ledger` MUST record real reported cost per stage per provider, not estimates.

---

## 14. Golden test fixtures

Scorecard arithmetic fails silently — a sign flip on the offset produces plausible but inverted
numbers, and unattended runs will not catch it.

- MUST commit ≥6 hand-computed fixtures: high scorer, mid scorer, ceiling-excluded incumbent,
  all-unknown site signals, **phone-track vs email-track pair** (same prospect, both channels,
  divergent scores), and **first-scan** (all deltas `unknown`).
- Each fixture specifies input features → expected points per feature → expected raw total →
  expected score → expected probability.
- MUST include a round-trip test: `score → inverse scaling → probability → forward scaling`
  returns the original score.
- CI MUST fail on any deviation beyond floating-point tolerance.

---

## 14a. Evidence attribution

Every audit and call hook is assembled from a handful of evidence elements — geogrid heatmap,
AI-absence line, ad-spend dollarization, named competitor, case study, delta callout. Which of
those actually drives replies is unknown, unmeasured, and **impossible to recover after the
fact**: once an asset is sent, the underlying evidence changes on the next rescan, so the
composition cannot be reconstructed later. It must be logged at generation time or lost.

### Why this loop can beat the coefficient refit

**Correcting the loose version of this claim:** it is *not* faster simply because sends are
more frequent than replies. At ~35 audits per cycle, a naive one-element-at-a-time A/B would
need well over a year per element — slower than the scoring refit, not faster. Two design
choices are what make it worthwhile:

1. **Randomize all optional elements independently** (fractional factorial), not sequentially.
   Every send then contributes to estimating *every* element's main effect simultaneously,
   rather than one comparison at a time.
2. **Measure engagement, not just replies.** Asset views, per-section dwell, and link clicks
   occur several times more often than replies. That, not send volume, is the actual speedup.

Randomization is also what makes the estimates causal. Prospect features are observed and
confounded; evidence inclusion is *assigned*, so a straightforward comparison is valid with far
fewer observations than untangling the observational case would need.

### Requirements

- MUST write the evidence manifest **before** dispatch. Reconstructing composition from current
  data is invalid — the evidence will have changed.
- MUST store snapshot references in the manifest, not values, so the asset stays reproducible.
  Store a content hash rather than the rendered PDF.
- MUST record `available`, `included`, and `assignment` as separate fields. Inclusion is
  confounded by availability: the AI-absence line only exists where the AI check ran, delta
  callouts only from cycle 2. Treating "not included" and "not available" as the same value
  destroys the analysis.
- MUST randomize only elements whose omission leaves the asset honest. Anything required for
  the asset not to mislead is `forced` and is observational, never randomized.
- **Overrides MUST be permitted and logged, not blocked.** Someone will eventually decide a
  particular prospect needs a particular element. Blocking that guarantees the rule gets bypassed
  invisibly; logging it preserves the experiment. Set `assignment_overridden = true` with a
  reason, and exclude those rows from effect estimates. Silent override is the only failure mode
  that destroys the measurement.
- MUST record `slot` (lead / body / closing) — position plausibly matters more than presence.
- SHOULD instrument engagement at element granularity wherever the delivery channel allows
  (per-section view events, dwell, link clicks).
- Analysis is a regression of outcome on element indicators over the randomized rows only.
  Forced rows are retained for description but MUST be excluded from effect estimates.

### Response latency

Reply value decays in hours. At 100 prospect starts and a 5.5% base rate this is ~5 replies a
month — handleable by one person with no process — but it becomes a staffing question above
roughly 400 starts.

- `outcome.first_response_at` MUST be captured alongside `replied_at`.
- Median reply-to-response latency SHOULD be surfaced as an operational metric.
- Instrument now, staff later. The point is to see the constraint arrive rather than to solve a
  problem that does not yet exist.

### Call hooks

A hook is a single element rather than a composition, so logging is simpler: record which
element was selected as the hook and which others were available but passed over. That
available-set is what makes the comparison meaningful — otherwise strong hooks look better
merely because they were available for stronger prospects.


- [ ] Every score reproducible from `score_factors` alone (points + offset = score)
- [ ] Zero hardcoded coefficients; all βs config-driven
- [ ] Pass-1 and pass-2 scores both persisted; pass 1 never overwritten
- [ ] Missing reachability in pass 1 excluded, not defaulted to neutral
- [ ] Phone-track prospects emitted with zero enrichment API calls
- [ ] Phone-track and email-track scores never ranked in a single list
- [ ] Channel-specific offsets applied; no shared Model A base rate
- [ ] Ramp progression gated on `email_track_ready`, never on elapsed time
- [ ] Ramp reversible via config without code changes
- [ ] Emission blocked when evidence exceeds `max_evidence_age_days`, with rescan queued
- [ ] Emission blocked when submarket history < `min_history_cycles`, except under bootstrap
- [ ] Scanning never gated by history; every submarket scans from cycle one
- [ ] `snapshot_count` and `coverage_variance` recorded in `score_factors`
- [ ] Bootstrap contacts flagged `evidence_provisional` and carry no delta claims
- [ ] Bootstrap outcomes excluded from effect estimates but included in base-rate calibration
- [ ] Bootstrap contacts distinguishable in `outcome.selection_reason`
- [ ] First scan of a submarket produces `unknown` deltas, never `no_change`
- [ ] Deltas computed against the mean of the prior two snapshots, not the latest one
- [ ] Deltas suppressed below 3 snapshots or beyond `max_delta_span_days`
- [ ] Delta-based claims require 3 snapshots even where contact is permitted at 2
- [ ] Event-triggered scans bypass cadence but honour all other gates
- [ ] LLM citation claims re-verified at audit generation, never served from scheduled scans
- [ ] Shortlist depth derives from `monthly_prospect_starts` ÷ cycles per month
- [ ] `sequence_version` and `touches_per_sequence_at_send` stamped on every `outcome`
- [ ] `template_version` stamped on every `audit_asset`
- [ ] Effect estimates segmented by sequence and template version before pooling
- [ ] Capacity allocated across open slots before deepening within any one slot
- [ ] `filled` and `conflicted` slots excluded from allocation entirely
- [ ] `filled` slots continue scanning; scan series unbroken across the client transition
- [ ] No slot receives more than `slot_depth_max` contacts per cycle
- [ ] MMR λ progression gated on refit milestones, never elapsed time
- [ ] λ_shrink applied uniformly; verified not to alter rank order
- [ ] Similarity penalty computed over profile features only, never pain features
- [ ] `selection_rank` and `similarity_penalty` recorded when order differs from raw score
- [ ] Vendor-failing evaluated as one compound feature, not two independent contributions
- [ ] `likely_represented` penalty suppressed whenever vendor-failing fires
- [ ] Vendor-failing returns `unknown` on a submarket's first scan cycle
- [ ] Non-public case studies emit anonymized descriptors only
- [ ] Every filter exclusion logs all failing rules, not just the first
- [ ] Franchise pattern matches flag, never exclude
- [ ] `flagged` prospects scored but never enriched or contacted before review
- [ ] Model A franchise penalty applies only to `confirmed_franchise`
- [ ] `unknown` site signals behave identically to `absent`; neither subtracts
- [ ] Grid geometry persisted per snapshot and reproducible
- [ ] AI checks record ≥3 samples with per-sample entity lists
- [ ] Every submarket references an `ai_region` with a recognition-tested name
- [ ] Multiple submarkets may share one `ai_region`; AI checks deduplicate by region
- [ ] Grid geometry never adjusted to match neighbourhood boundaries
- [ ] AI absence claims suppressed where `name_level = 'metro'`
- [ ] Audit copy never implies grid and AI claims cover the same area
- [ ] Incorporated place names preferred over geocoded neighbourhood names
- [ ] Call hook renders only from persisted evidence; no send-time improvisation
- [ ] Submarket geometry immutable once scanning begins; names editable independently
- [ ] AI region prompts use geocoded place names, never generic submarket identifiers
- [ ] Scheduled LLM scans use Responses; all shipped claims use Scraper
- [ ] Scraper/Responses disagreement resolves to Scraper; scheduled result marked stale
- [ ] `geogrid_heatmap` always forced; the other five elements randomized independently
- [ ] Run aborts before exceeding either the per-market or per-portfolio cost ceiling
- [ ] Dead grid points excluded from the coverage denominator after 3 consecutive null scans
- [ ] Dead points reactivate on any non-null result
- [ ] Live-point count recorded in `score_factors` for historical interpretability
- [ ] Negative coverage deltas suppressed when the prospect is absent from the current pull
- [ ] Drift suppression applies even when alias resolution fails
- [ ] Snapshots below `completeness_threshold` excluded from scoring, deltas, and rollup
- [ ] Incomplete snapshots retained and retried, never averaged into pain estimates
- [ ] `cost_ledger` reconciles against provider dashboards within 5%
- [ ] `outcome` row written for every emitted prospect
- [ ] Evidence manifest written before dispatch, never reconstructed after
- [ ] `available`, `included`, and `assignment` stored as distinct fields
- [ ] Optional elements randomized independently, not one-at-a-time
- [ ] Forced elements excluded from effect estimates
- [ ] Overrides permitted, logged with reason, and excluded from effect estimates
- [ ] `first_response_at` captured on every reply
- [ ] Asset copy diagnoses observed state; no committed-outcome claims
- [ ] Case-study draft auto-generated into a review queue at 90 days post-close
- [ ] Call hooks log both the selected element and the available-but-passed set
- [ ] All three verification spikes (§16a) completed before dependent components ship
- [ ] Golden fixtures pass in CI
- [ ] Full market cycle (400 prospects, 3 keywords) completes under $15 and under 90 minutes

---

## 15a. Recorded decisions

Settled in design discussion. Recorded here so implementers treat them as decided rather than
open, with the reasoning that would need to change to revisit them.

**Portfolio scope — 5 verticals × 10 cities (~50 market-verticals).**
Chosen over 8 × 12 not on cost (tiering makes cost nearly independent of portfolio size) but on
case-study compounding: same-vertical comparable-market proof is the largest positive in Model A,
and concentration is the fastest route to accumulating it. Revisit at month ~9 (see below).

**No scan tiering — deep-scan the full portfolio.**
A two-tier model (deep active / shallow qualification) was specified and rejected. At
`monthly_prospect_starts` = 100 with `slot_depth_max` = 3, ~50 market-verticals is ~300 slots
≈ 900 attempts ≈ **nine months of inventory**, not the multi-year backlog that would justify
rationing scan depth. Deep-scanning everything runs ~$4,840/yr against a portfolio consumed
within a year. **The live risk is running out of inventory, not overspending on it** — plan
portfolio expansion around month 9. Reintroduce tiering only if the portfolio grows past roughly
100 market-verticals while contact volume stays flat.

**Database — Supabase.**
Railway Postgres (consolidation), Neon (branching), Timescale Cloud (native time-series), and
ClickHouse were considered. Supabase wins on MCP and Claude Code integration, which is a
first-order factor given unattended agent-driven development, not a soft preference. At 15M
rows/year this is not a scale problem, and bundled RLS is needed for the client-history feature.
Note Supabase now steers users off TimescaleDB hypertables toward `pg_partman` + native
partitioning — which is exactly what the storage spec already specifies.

**Blob storage — Cloudflare R2, not Supabase Storage.**
R2 has no egress fees and Cloudflare is already in the stack via Pages. Irrelevant at current
volume; material if client-facing historical reports get heavy. Closes storage-spec open
decision 4.

**Split trigger — revisit architecture past ~50 concurrently deep-scanned market-verticals.**
The workload has two shapes: transactional state (~50 MB/yr, needs integrity and RLS) and
time-series scan data (~2 GB/yr, append-only, read as aggregates). Keeping them in one Postgres
is correct now. If deep-scanned pairs exceed ~50 while retention holds, evaluate splitting scan
data to a columnar store. This is a stated trigger so the decision is revisited on evidence.

**Touches per sequence — 5** (both channels initially).
~500 sends/month at 100 prospect starts — sustainable on a warmed domain and well inside the
phone track's dial ceiling. Most replies land in touches 1–3; 4–7 add real incremental yield.
Phone and email may diverge later (4–6 dials vs 5–7 emails) since the tracks are already scored
separately, but that would be a second confound dimension — bump `sequence_version` if split.

**Submarket decomposition — hybrid.**
Auto-tile 5-mile-radius geometry across the metro boundary, reverse-geocode each centroid to a
recognized place name, allow manual override. Named places are required regardless — AI region
prompts must read "plumber in Lee's Summit," not "plumber in submarket 7" — and at 10 cities,
hand-fixing bad auto-names is trivial.

> **Geometry and naming are separable and MUST be treated differently.** Renaming a submarket is
> free at any time. Re-tiling is not: changing centroid or radius invalidates every prior
> snapshot for that submarket and resets its delta history. Names MAY be edited; geometry MUST be
> immutable once scanning begins.

**LLM source — split by purpose.**
DataForSEO **LLM Responses** for scheduled scoring scans (consistent, parameterised, cheaper at
volume). DataForSEO **LLM Scraper** for send-time verification and any audit or call-hook claim,
because the value of "we asked ChatGPT and you weren't mentioned" rests entirely on the prospect
being able to check it in thirty seconds. If the two disagree, **the claim follows Scraper and
the scheduled scan is treated as stale.**

**Randomizable evidence — heatmap forced, five randomized.**

| Element | Assignment |
|---|---|
| `geogrid_heatmap` | **forced** — it is the artifact; an audit without it is not an audit |
| `named_competitor` | randomized |
| `ad_spend_math` | randomized |
| `ai_absence_line` | randomized (requires send-time Scraper verification when included) |
| `delta_callout` | randomized (available cycle 3+; `unavailable` before) |
| `review_gap` | randomized |
| `case_study` | `unavailable` at launch |

Five independently randomized binary elements yield five main effects per send, which is what
makes evidence attribution worth instrumenting at this volume.

**Contact volume — `monthly_prospect_starts` = 100.**
See §8. Freely tunable downward, one-way upward.

**Selection parameters — `slot_depth_max` = 5, MMR `λ` = 0.5 at launch, `λ_shrink` = 0.5.**

Depth 5 over depth 3 is close to a wash on expected slots filled — at ~5% close per prospect,
3 contacts give 14.3% and 5 give 22.6%, but 50 prospects/cycle covers 17 submarkets at depth 3
versus 10 at depth 5, producing ~2.4 versus ~2.3 expected fills. The real trade is coverage:
depth 3 spreads first clients across more submarkets and accumulates comparable-market case
studies faster; depth 5 learns individual markets more thoroughly. Depth 5 also makes MMR matter
more, since the fifth pick sits deeper in the ranked list where candidates increasingly resemble
those already chosen.

`λ_shrink` stays at 0.5 and is explicitly **not** a ranking parameter — it is a uniform
multiplier on every prospect's points, therefore a monotonic transform that preserves order
exactly. It affects predicted probabilities only, which are clamped and displayed as deciles at
launch anyway, and Stage 2 recalibration is designed precisely to correct it. Not worth tuning.

**Filter behaviour — absolute 9-month recency; franchise flags, never excludes.**
Recency stays absolute at launch; relative velocity is a cycle-three upgrade. Franchise pattern
matches route to review rather than exclusion, because a false positive is unrecoverable and the
Model A penalty already deprioritises them without a hard gate.

**Evidence and cadence — `min_history_cycles` = 2, `bootstrap_share` = 1.0,
`scan_interval_days` = 15 uniform.**
Two snapshots at semi-monthly cadence is a 30-day window before a market is fully workable.
Cycle one runs unrestricted on single-snapshot evidence because it is phone-only and therefore
free, and because it calibrates the weakest number in the scoring spec. Scan interval stays
uniform across layers; per-vertical variation was considered and rejected as cadence state
bought for savings that are not needed.

**Channel split — ramped to 30% phone / 70% email.**

The split is **not constant from launch**. Email cannot send at all during domain warming, so
cycle one is phone-only whether planned or not. Making that the plan also front-loads the faster
feedback loop: a dial tells you within a day whether the pitch lands, while an email sequence
takes a week per touch.

| Phase | Gate | Split |
|---|---|---|
| Ramp 1 | Launch | 100 / 0 |
| Ramp 2 | Domain warmed, first sends verified delivering | 50 / 50 |
| Steady | Two clean cycles at Ramp 2 | 30 / 70 |

- Progression MUST be gated on `email_track_ready` — a documented check covering vendor
  compliance, authentication (SPF/DKIM/DMARC), warming completion, and observed inbox placement.
  **Not on elapsed calendar time.** Warming can take longer than planned, and shipping into a
  cold domain wastes the inventory it burns.
- Reverting to a lower ramp on deliverability trouble MUST be possible without code changes.
- Note volume is modest at every stage: steady state is ~350 emails/month (70 prospects × 5
  touches), roughly 12/day. Deliverability risk here is about domain reputation and list
  provenance, not throughput.

**Steady-state split — 30% phone / 70% email.**
Enrichment depth is therefore 70% of `prospects_per_cycle` (≈35 per cycle at 100 starts/month).
A prospect MUST NOT be active in both tracks simultaneously — it confounds measurement and is a
poor recipient experience. Sequential fallback (email sequence completes, then phone) is
permitted and counts as one sequence.

> **Two consequences of the email-heavy split, both on the critical path:**
>
> 1. **The email sending stack becomes a launch blocker.** ~350 emails/month at steady state
>    (70 prospects × 5 touches), from a domain with no sending history. Volume is not the issue —
>    domain warming takes 3–4 weeks of calendar time regardless of rate, and cannot be compressed.
>    Start it before the build finishes, not after.
> 2. **Vendor choice must be resolved first.** GetResponse's anti-spam policy prohibits
>    non-opt-in addresses, screening is automated and opaque, and suspension can be permanent —
>    see `crm-layer-spec.md` §7. Purpose-built cold outreach tooling sending through owned
>    mailboxes is the lower-risk path. This was survivable under a phone-heavy split; under
>    70% email it is not.

**Model A base rates are per-channel.**
Email 5.5% (offset 705.0), phone 25% (offset 579.3) — a 126-point difference. These measure
different events, not the same event at different rates, so scores MUST NOT be ranked across
channels and refits MUST be per-channel or carry channel as an explicit level. See
`scoring-spec.md` §1.

**Pricing — flat. Model C value layer inert.**
Operative ranking is `p_reply × p_close`; `R` and `T` are constants that drop out. See
`scoring-spec.md` §4. Revisit ~month 9.

**Reply capture — manual logging at launch.**
`replied_at` is the field the entire model is fit against, so the gap risk is real, but at ~5
replies/month manual is adequate and most early replies are phone conversations logged as
activity regardless. Build IMAP polling at ~30 replies/month. The CRM overdue-action view is the
forcing function.

**Case studies — none at launch.**
AR holds no documented case studies in the target verticals. Scoring spec §case-study bins are
marked `unavailable` and the Model A base rate is reduced accordingly. Tier-1 market selection
should therefore favour **time-to-documentable-win** over raw opportunity until the first proof
exists — the first case study is worth more than the first three clients.

---

## 16. Open decisions

1. **Case-study match threshold** — how comparable is "comparable market"? Population band alone
   is crude; competitive density is better but needs the grid data to compute.
2. ~~**Outscraper pixel field**~~ — moved to §16a.1 as a verification spike. Not a judgment call.

---

## 16a. Verification spikes

Three items of outstanding work that are **testing or reading, not judgment**. Each blocks an
assumption currently embedded in a shipped design. All should complete before the components
they affect are built.

### 16a.1 Outscraper pixel field — ~1 hour

**Assumption under test:** that Meta pixel presence arrives in the same enrichment pull as
listings and contacts, making it a market-wide, near-free money signal.

- Enrich ~20 businesses with known pixel configurations — roughly half direct-injected, half
  injected via GTM container.
- Record: which tier returns the field, actual billed cost, and detection rate for each
  injection method.
- **If GTM-injected pixels are largely missed**, the §B3 container fetch is promoted from a
  false-negative check to a required step, and the money-signal cost model needs revising.
- Blocks: final cost modelling for the money coefficients.

### 16a.2 AI prompt granularity — ~20 minutes

**Supersedes the coordinate-sensitivity spike.** That test asked whether passing lat/lng changes
an LLM's answer. It is moot: prompts carry geography in their text ("plumber in Overland Park"),
never as coordinates, so whether the models honour a location parameter has no bearing on this
design.

**Assumption under test:** that the place name in the prompt is at the right granularity —
specific enough that a small local operator could plausibly appear, general enough that the model
recognises the place at all.

Three failure modes, and the third is the dangerous one:

| Granularity | Result |
|---|---|
| Too coarse ("Kansas City") | Returns metro-wide operators. A two-truck shop was never going to appear, so "you're not in ChatGPT" is trivially true and easy to dismiss. |
| Right ("Overland Park") | Returns businesses at the prospect's scale. Absence is meaningful. |
| Too fine (unrecognised name) | Model silently falls back to the metro. You get the coarse answer while believing you asked a specific question. |

**Procedure.** One keyword, three granularities — metro, suburb, neighbourhood — three samples
each, one engine. Record:

- Do the named businesses change between levels?
- At which level do small local operators start appearing?
- At which level does the model stop recognising the place and revert to metro-scale answers?

**Output:** the naming level to use for AI prompts, which determines how many AI queries run per
market — the largest variable cost in the scan layer.

### 16a.3 Map tile licensing — ~30 minutes

**Assumption under test:** that map backgrounds can legally appear in client- and
prospect-facing PDFs.

- Read the commercial terms for Mapbox and MapTiler static image APIs.
- Determine specifically: whether embedding a rendered tile inside a derivative PDF constitutes
  redistribution, and what attribution must appear **on the image itself**.
- Attribution requirements affect heatmap layout, so this must resolve before the renderer is
  built, not after.
- Blocks: `reporting-layer-spec.md` open decision 1.

> All three are cheap enough that deferring them costs more than running them. Each currently
> sits in the specs as an assumption with no evidence behind it.

---

## 17. Implementation sequencing

> **Superseded by `START-HERE.md`.** This section was written before the reporting and CRM layers
> existed and covers only stages A–C of this document — it omits heatmap rendering, audit
> generation, and pipeline management entirely. The phase map in `START-HERE.md` is the
> authoritative build order and maps acceptance criteria to phases. Retained here because the
> reasoning below still explains *why* the order is what it is.

Contact capacity is AR's binding constraint, not ranking precision. Build so the pipeline
produces usable output before the scoring layer is tuned:

1. **A1–A2** (ingest + filter) with placeholder score = raw geogrid coverage deficit
2. **B1** (scan + snapshot) — unlocks real pain signals and audit heatmap data
3. **C1 phone track + emit** — zero-cost outbound path, connects to the actual bottleneck first
4. **A3 + case-study matching** — cheapest conversion lever, no API dependency
5. **B2 deltas** — requires two snapshots, so it arrives naturally on the second cycle
6. **B3–B4 + C2** (site signals, full scorecard, email enrichment) — swap the placeholder for
   the real model

The phone track still ships first even though email now carries 70% of volume — and for a
sharper reason. It needs no enrichment and costs nothing per prospect, so it exercises the entire
pipeline on real conversations before a dollar of per-record spend is committed to the primary
channel. Phone is the test harness, not the main event.

**Prerequisite with calendar lead time:** the email sending stack (vendor choice plus 3–4 weeks
of domain warming) MUST be started in parallel with step 1, not after step 6. It is the only item
here that cannot be compressed by working faster.
