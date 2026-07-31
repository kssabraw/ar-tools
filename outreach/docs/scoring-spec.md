# Outreach App — Lead Scoring Specification v1.0

**Status:** Draft, cold start (zero outreach outcomes; client-book data available)
**Method:** Log-odds scorecard as presentation layer → hierarchical Bayesian logistic regression with elicited informative priors → Thompson sampling for contact selection
**Scope:** Scoring only. Filtering/gating covered separately.

---

## 0. Architecture note: three models, one chain

The three requested rankings are not independent. They compose:

```
E[revenue] = P(reply) × P(close | reply) × R × T
```

- **Model A** — P(reply). Scorecard.
- **Model B** — P(close | reply). Scorecard.
- **Model C** — E[revenue]. Not a scorecard; a composition of A × B × value estimators.

One shared feature set feeds all three. The βs differ per model because the same signal
predicts differently at each stage — e.g. severe geogrid pain drives replies strongly but
barely moves close rate, because a prospect who replied has already self-selected on pain.

`score_factors` MUST store per-model contributions separately so the UI can show why a
prospect ranks differently under each view.

---

## 1. Scaling parameters

```
Score  = Offset + Factor × ln(odds)
Factor = PDO / ln(2)
Offset = TargetScore − Factor × ln(TargetOdds)
```

Shared config: **PDO = 50**, **TargetScore = 500**, Factor = 50 / ln(2) = **72.13**

| Model | Channel | Assumed base rate | Base odds | Offset |
|---|---|---|---|---|
| A — P(reply) | **email** | 5.5% | 0.0582 | **705.0** |
| A — P(reply) | **phone** | 25% | 0.3333 | **579.3** |
| B — P(close \| reply) | both | 15% | 0.1765 | **625.1** |

Interpretation: 500 = market-average prospect. Every **+50 points doubles the odds**.

Base rates are assumptions (MUST be config, not constants) and are **sequence-level, not
per-touch** — they predict P(reply) across a full 5-touch sequence, not from one send.

### Model A base rates are per-channel

**A single base rate would mis-calibrate whichever channel it did not describe.** The offsets
differ by 126 points — the two channels are not close.

They also measure **different events**, not merely the same event at different rates:

- **Email reply** = a written response to a sequence of sends, from a passive recipient.
- **Phone reply** = a conversation. Across 5 dial attempts at a 15–25% per-dial connect rate,
  most sequences reach a human at least once; the 25% figure is the share that becomes a real
  conversation rather than a gatekeeper or an immediate brush-off.

Consequences that MUST be honoured:

- Phone and email scores are computed against different offsets and MUST NOT be ranked in one
  list (already required by §Reachability).
- **Refits MUST be per-channel, or must carry channel as an explicit level** in the hierarchical
  model (§7 Stage 3). Pooling email and phone replies into one fit conflates two different
  outcome definitions and would corrupt every coefficient.
- Both rates are guesses. The email figure was revised from 8% to 5.5% because the original
  implicitly assumed social proof AR does not yet have; the phone figure has no comparable
  anchor at all and is the weaker of the two.

Both are measurable within three weeks of first send in their respective channels. Overwrite
them with observed data rather than tuning coefficients around them — and note the phone rate
will be observable first, since the email track is gated on domain warming.

---

## 2. Model A — P(reply)

Points = β × 72.13, rounded. Reference bins = 0 points.

### Reachability — channel-specific

**Corrected in v0.4.** v0.3 scored reachability as a single block that penalized phone-only at
−66. That is correct for email and wrong for calling, where phone *is* the channel. Reachability
MUST be selected by the active outreach track, and the two tracks MUST NOT be ranked together.

**Email track**
| Bin | OR | β | Points |
|---|---|---|---|
| Direct owner email + phone | 2.5 | 0.92 | **+66** |
| Role email (info@, office@) | 1.0 | 0.00 | 0 *(ref)* |
| Phone only, no email | 0.4 | −0.92 | **−66** |

**Phone track**
| Bin | OR | β | Points |
|---|---|---|---|
| Direct line, owner-operated | 2.0 | 0.69 | **+50** |
| Listed phone, independent business | 1.0 | 0.00 | 0 *(ref)* |
| Main line, likely gatekept (large/multi-location) | 0.6 | −0.51 | **−37** |
| No phone | — | — | *filtered upstream* |

Phone reachability derives entirely from the Outscraper base pull, so the phone track requires
**no enrichment spend**. Email reachability requires enrichment and is therefore unavailable at
pass 1 — see the two-pass requirement in the pipeline PRD.

### Change signals (delta since prior scan)

Available from the second scan cycle onward. These are the strongest openers available and cost
nothing beyond the rescan cadence already required for evidence freshness. All bins evaluate to
`unknown` (0 points, flagged) on a submarket's first scan — absence of a baseline is not
evidence of stability.

| Bin | OR | β | Points |
|---|---|---|---|
| Lost pack coverage >15pp since last scan | 2.4 | 0.88 | **+63** |
| Named competitor overtook them at ≥5 grid points | 2.2 | 0.79 | **+57** |
| Ads newly turned on (absent → present) | 1.9 | 0.64 | **+46** |
| Dropped out of AI citations (present → absent) | 1.7 | 0.53 | **+38** |
| Organic position lost ≥5 places | 1.5 | 0.41 | **+29** |
| Review velocity newly stalled | 1.4 | 0.34 | **+24** |
| No material change | 1.0 | 0.00 | 0 *(ref)* |
| First scan — no baseline | — | — | 0 *(unknown)* |

Deltas MUST NOT be computed across a gap exceeding `2 × scan_interval_days`; a stale comparison
produces a "sudden drop" claim the prospect can falsify.

### Vendor-failing (compound — highest-intent signal available)

Fires only when **both** halves are true: a vendor/agency tag is present (they are paying
someone) **and** a negative delta on pack coverage or organic position (that someone is
losing). Active budget plus visible dissatisfaction. Requires two scan cycles; evaluates to
`unknown` on a first pass, never `absent`.

| Bin | OR | β | Points |
|---|---|---|---|
| Vendor tag + lost pack coverage >15pp | 3.0 | 1.10 | **+79** |
| Vendor tag + lost organic ≥5 positions | 2.4 | 0.88 | **+63** |
| Vendor tag, no measured decline | — | — | *scores as ordinary vendor tag (+16)* |

**Interaction — MUST suppress `likely_represented`.** Representation normally carries −21 in
Model A on the reasoning that a business who believes it is handled replies less. When the
incumbent is visibly failing, representation is the *premise* of the pitch, not an obstacle.
The two features MUST NOT both apply; vendor-failing wins and sets
`primary_pitch = 'displacement'`.

At +79 this is the largest single positive in Model A, narrowly ahead of a same-vertical
comparable-market case study (+69). The ordering reflects that acute, current, evidenced pain
against a paid incumbent should outpull even strong social proof — but both are elicited
priors, and their relative order is a good early candidate for the isolate-testing described
in §7.

### Case-study proof match

No API cost. Sets `primary_pitch = 'proof'` when confidence is high, overriding pain-based
pitch selection.

| Bin | OR | β | Points | Status at launch |
|---|---|---|---|---|
| Same vertical + comparable market | 2.6 | 0.96 | **+69** | `unavailable` |
| Same vertical, any market | 1.8 | 0.59 | **+42** | `unavailable` |
| Adjacent vertical + comparable market | 1.4 | 0.34 | **+24** | check WheelHouse IT |
| No match | 1.0 | 0.00 | 0 *(ref)* | **active** |

**AR holds no case studies in the target verticals at launch.** The top two bins MUST be marked
`unavailable` rather than deleted — they activate automatically as case studies are documented,
with no coefficient change needed.

Two consequences, different in kind:

- **Ranking is unaffected.** A feature that fires for nobody has zero variance and shifts every
  prospect equally. Ordering does not change.
- **Conversion is affected.** The +69 was doing closing work, not ranking work. Its absence is
  priced into the reduced base rate in §1.

The adjacent bin (+24) may be reachable now — AR's multi-market local SEO work for WheelHouse IT
is documentable as a before/after and would qualify against home-services prospects. Worth
checking before assuming zero proof.

Vendor-failing (+79) is unaffected and becomes the largest active positive, so Model A is not
decapitated — it simply needs two scan cycles before its top signal can fire.

The top bin is the single largest positive coefficient in Model A, ahead of email reachability.
That ordering is deliberate: in local SEO a named, comparable result is the strongest opener
available, and it is the only high-weight signal that costs nothing to obtain.

### Geogrid pain (primary discriminator)
| Bin | OR | β | Points |
|---|---|---|---|
| Coverage <20% + steep decay from pin | 2.2 | 0.79 | **+57** |
| Coverage 20–50% | 1.4 | 0.34 | **+24** |
| Coverage 50–80% | 1.0 | 0.00 | 0 *(ref)* |
| Coverage >80% | 0.5 | −0.69 | **−50** |

### GBP quality gate (interaction with above)
| Bin | OR | β | Points |
|---|---|---|---|
| Strong GBP (rating ≥4.0, photos, categories set) | 1.6 | 0.47 | **+34** |
| Adequate | 1.0 | 0.00 | 0 *(ref)* |
| Weak GBP (rebuild, not a rankings engagement) | 0.7 | −0.36 | **−26** |

### Organic / AI pain (low variance — small weights by design)
| Bin | OR | β | Points |
|---|---|---|---|
| No organic top-20 presence | 1.15 | 0.14 | **+10** |
| Not mentioned in 0/3 AI samples | 1.20 | 0.18 | **+13** |
| AI cites ≥3 named competitors, not them | 1.25 | 0.22 | **+16** |

### Buying intent (one-directional — absence never subtracts)
| Bin | OR | β | Points |
|---|---|---|---|
| LSA present + absent from pack | 2.0 | 0.69 | **+50** |
| Google Ads + no top-10 organic + no pack | 1.9 | 0.64 | **+46** |
| AW- conversion tag present | 1.3 | 0.26 | **+19** |
| Vendor tag (CallRail / Podium / Birdeye) | 1.25 | 0.22 | **+16** |
| Meta pixel present | 1.15 | 0.14 | **+10** |

### Decision structure
| Bin | OR | β | Points |
|---|---|---|---|
| Owner-operated | 1.5 | 0.41 | **+29** |
| Independent, non-owner-named | 1.0 | 0.00 | 0 *(ref)* |
| `likely_represented` (2+ agency/vendor signals) | 0.75 | −0.29 | **−21** |
| Franchise / chain pattern (`flagged` or `confirmed_franchise`) | 0.3 | −1.20 | **−87** |

### Trajectory
| Bin | OR | β | Points |
|---|---|---|---|
| Review velocity declining >40% vs own baseline | 1.3 | 0.26 | **+19** |
| Velocity growing | 1.2 | 0.18 | **+13** |
| Velocity flat | 1.0 | 0.00 | 0 *(ref)* |
| Review count top quartile in market | 0.85 | −0.16 | **−12** |
| Review count bottom quartile (≥10) | 1.1 | 0.10 | **+7** |

**Two counterintuitive signs, deliberate:**
- *Declining velocity is positive.* A business watching its own lead flow dry up is
  receptive. This is the single most falsifiable prior in the model — flag for early review.
- *Top-quartile review count is negative.* Bigger businesses have gatekeepers. Size predicts
  **value**, not **reply**; it earns its weight in Models B and C, not here.

---

## 3. Model B — P(close | reply)

Weights shift hard toward budget and decision authority. Pain barely matters — a replier has
already conceded the pain.

| Feature | Bin | OR | β | Points |
|---|---|---|---|---|
| Decision authority | Owner-operated / DM reached | 3.0 | 1.10 | **+79** |
| Franchise / corporate-marketed | — | 0.2 | −1.61 | **−116** |
| Proven spend | Est. ad spend >$2k/mo | 2.5 | 0.92 | **+66** |
| Proven spend | Est. ad spend $500–2k/mo | 1.6 | 0.47 | **+34** |
| Proven spend | LSA active | 2.2 | 0.79 | **+57** |
| Displaceable budget | Vendor tags present | 1.8 | 0.59 | **+42** |
| Displaceable budget | **Vendor-failing** (tag + measured decline) | 3.5 | 1.25 | **+90** |
| Representation | `likely_represented` | 0.7 | −0.36 | **−26** |
| Capacity | Review count top quartile | 1.5 | 0.41 | **+29** |
| Capacity | Review count bottom quartile | 0.6 | −0.51 | **−37** |
| Capacity | Multi-location (2+) | 1.7 | 0.53 | **+38** |
| Stability | Years in business >5 | 1.4 | 0.34 | **+24** |
| Pain | Geogrid coverage <20% | 1.2 | 0.18 | **+13** |

Note `likely_represented` is negative in **both** models but for different reasons: lower
reply (they believe they're handled) and lower close (switching costs). It should not be a
disqualifier — it selects a *displacement* pitch, which is a different sequence.

---

## 4. Model C — E[revenue]

> **DECIDED: flat pricing. The value layer is inert and the operative ranking is
> `p_reply × p_close`.**
>
> At AR's observed 1.67× retainer spread, R varies far less than propensity does, so expected
> revenue and unconditional close probability rank prospects almost identically. With pricing
> held flat, there is no value dimension left to optimise: `R` and `T` become constants and drop
> out of the ordering entirely.
>
> **Implementation:** compute and store `p_reply × p_close` as the `value` model. Retain the R
> and T machinery below, unused, with `R_base` and `T_base` as constants — reactivating it is a
> config change if AR later prices larger prospects higher (revisit ~month 9).
>
> **Consequence:** the propensity/value split remains architecturally correct but currently does
> no work. Do not spend effort tuning `cat_mult`, `size_mult`, or tenure estimates — they cannot
> affect ranking while pricing is flat.

Not a scorecard. Compose:

```
E[revenue] = p_reply × p_close_given_reply × R × T
```

Where `p_*` come from Models A and B via the inverse scaling:

```
odds = exp((Score − Offset) / Factor)
p    = odds / (1 + odds)
```

### R — expected monthly retainer

```
R = R_base × cat_mult × size_mult
```

- `R_base` = **2000** (config; AR's observed local SEO median is $1,500–2,500)
- `cat_mult` — category lead value (plumbing/HVAC/legal high; retail low). Lookup table.
- `size_mult` — from review-count percentile and location count.

> **Finding: observed retainer spread is only ~1.67× ($1,500–2,500).** Meanwhile `p_reply`
> plausibly varies ~10× across prospects and `p_close` ~5×. R therefore contributes almost
> nothing to ranking variance, and **Model C collapses toward Model A × Model B.**
>
> This does not make the propensity/value split wrong — it makes it currently inert. The split
> only pays off if AR is willing to **price larger prospects higher**. Under flat pricing,
> expected-revenue ranking cannot beat unconditional-close ranking, because there is no value
> dimension left to optimize. See Open Decision 6.

**Anchor override:** where est. ad spend is known, `R ≈ 0.3–0.5 × monthly ad spend` is a
better estimator than the size multiplier, because it measures revealed willingness to pay
rather than inferred capacity. Prefer it when ads data exists; note which was used in
`score_factors`.

### T — expected tenure (months)

- `T_base` = 15 (config)
- Owner-operated: ×1.3 · Multi-location: ×1.2 · Declining velocity: ×0.8

### Expected disagreement

Model C will systematically rank **larger businesses higher** than Model A does, because size
raises value while slightly lowering reply probability. This is correct, not a bug — but it
means the three tabs genuinely disagree, and which one to use is a capacity question:

| Bottleneck | Rank by |
|---|---|
| Contact/send capacity is scarce | **Model C** — maximize revenue per contact |
| Fulfillment capacity is scarce | **Model C** with a floor on Model B |
| Need logos/case studies fast | **Model A** — maximize conversations |
| **First 2–3 campaigns (no data)** | **Model A** — it generates outcome data fastest |

**Resolved: AR is contact-capacity bound** (can fulfill more than it can reach). Two
consequences:

1. **Default view = Model C**, which under flat pricing means effectively ranking by
   unconditional close probability (`p_reply × p_close`). Scoring precision matters most at
   the **top of the distribution**, since only the top N are ever contacted — mid-range
   calibration is nearly irrelevant.
2. **v1 scope leaves the actual constraint untouched.** Identify + score + audit optimizes
   *which* prospects to reach when the binding limit is *how many* can be reached at all. The
   scope call still stands for v1, but the outbound handoff (webhook → n8n/Encharge) MUST ship
   in v1 rather than being deferred, and sending should be reprioritized for v2 above further
   scoring refinement. Better ranking has low ceiling value while contact volume is the cap.

---

## 5. Cold-start honesty: the model will be badly calibrated

Elicited odds ratios are systematically overconfident, and these features are correlated
(ads + AW tag + vendor tags co-occur), so naive summation double-counts. Worked example — a
strong plumber prospect accumulates +284 raw points → 82% predicted reply. That is not real.

### MUST: shrinkage on all priors

Apply `λ_shrink = 0.5` to every elicited β at v1. Store both `beta_prior` and
`beta_effective`. The example above lands at ~48% — still optimistic, but usable.

### MUST: treat v1 scores as ordinal only

Rank order is far more trustworthy than the probabilities. The UI SHOULD show decile/rank,
not a percentage, until Stage 2 below. Displayed probabilities MUST be clamped to ≤60%.

---

## 6. Three-stage refit path

This is the part that matters most given ~5% exploration budget.

### Stage 1 — priors (now)
Ship as specified. Log everything.

### Stage 2 — recalibration (~30–50 outcomes)
Do **not** attempt a full refit. Instead fit a **two-parameter logistic regression using the
current model's predicted log-odds as the single input variable** — the standard scorecard
recalibration move (implemented as `creditR::scaled.score` and equivalents).

```
ln(odds_calibrated) = α + γ × ln(odds_prior)
```

This corrects calibration (α) and over/under-confidence (γ) **without touching rank order**,
and it needs an order of magnitude less data than refitting 20 coefficients. At 5% exploration
this is the only stage you'll realistically reach within a few months — and since ranking is
what actually drives prioritization, it captures most of the practical value.

### Stage 3 — hierarchical Bayesian refit (~80+ reply outcomes)

**Correction from v0.2, which specified Firth.** Firth's penalty *is* the Jeffreys invariant
prior — a deliberately non-informative one. Under a "best predictions from least data"
objective that is the wrong tool: it discards the ~20 elicited odds ratios in §2–3, which are
the most valuable asset available at low n. Use Bayesian logistic regression with those
elicited values as **informative Normal priors** instead. It keeps every property Firth was
chosen for (finite estimates under separation, small-sample stability) and additionally uses
the domain knowledge rather than throwing it away.

```
β_j ~ Normal(β_prior_j, σ_j)      σ_j encodes confidence in each elicited OR
y_i ~ Bernoulli(logit⁻¹(Xβ))
```

Set σ_j wide (≈1.0) for priors flagged as speculative — the declining-velocity sign, the
LSA weight — and narrow (≈0.3) for ones with strong reasoning behind them. Confidence becomes
an explicit, per-coefficient parameter rather than a single global shrinkage constant.

**Add hierarchy — this is the largest efficiency gain available.** At 50–200 contacts/month
spread across markets, verticals, and pitch types, every subgroup is tiny. Partial pooling
handles exactly this shape: small groups get stable estimates pulled toward the population
mean, large groups are left essentially alone, and the degree of pooling is learned from
between- vs within-group variance rather than set by hand.

```
β_vertical ~ Normal(β_global, τ)
β_market   ~ Normal(β_vertical, τ₂)
```

A brand-new vertical starts at the global average and earns its own coefficients as evidence
accrues — no cold-start cliff per vertical, which is otherwise fatal when each one carries a
handful of outcomes. Known caveat: partial pooling systematically shrinks small groups toward
the mean, so a genuinely unusual vertical will look average until it has the data to prove
otherwise. Surface the group-level posterior width in the UI so this is visible rather than
silent.

**Cut parameters before adding data.** Roughly 20 correlated features against ~8 reply events
per month is unfittable. Group co-occurring signals into single latent factors — ads spend,
AW- tag, vendor tags, and pixel are largely one "spends money on marketing" dimension — which
cuts the parameter count ~3× and the data requirement with it. Cheapest available win, and
it's feature engineering, not modeling.

**Fit on replies, not closes.** Replies are 10–20× more common. Close-based refits of Model B
remain 1–2 years out; reply-based refits of Model A are reachable within months.

**Implementation:** PyMC or NumPyro. At ~20 parameters and low-thousands of rows, MCMC fits in
seconds — no infrastructure implications for the existing FastAPI/Railway stack.

### Evaluation — pairwise concordance, not accuracy

Ordering is the stated priority, so evaluate ordering directly. With ~96 replies in year one
there is nowhere near enough signal to fit on events, but those same outcomes yield thousands
of orderable pairs — enough to measure whether higher-scored prospects actually reply more
often. Report concordance (equivalently AUC/Gini) as the primary metric; use calibration error
as a secondary check on the probability layer only.

---

## 7. Exploration — Thompson sampling, no fixed budget

**Supersedes the stratified 5% scheme in v0.2.** Once Stage 3 produces a posterior rather than
point estimates, a dedicated exploration quota becomes unnecessary. Thompson sampling maintains
a distribution over coefficients, draws one sample per selection round, and ranks by the scores
that draw implies. Uncertain prospects sometimes rank high because the sampled coefficients
happened to favor them; confident ones rank high consistently.

```
for each selection round:
    β_sample ~ posterior(β)
    rank prospects by score(x, β_sample)
    contact top N
```

Three properties that matter given a contact-capacity constraint and reluctance to spend
contacts on exploration:

1. **No wasted budget.** Exploration is folded into ranking rather than carved out of it.
   Every contact is a best-guess contact under some plausible parameter draw — there is no
   bucket of deliberately suboptimal sends.
2. **Self-annealing.** As the posterior sharpens, sampled draws converge and the policy
   naturally becomes greedier. No decay schedule to tune.
3. **Targets uncertainty, not strata.** It explores where the model is genuinely unsure rather
   than where a hand-written heuristic guessed uncertainty would be.

For logistic rewards, Pólya-Gamma augmentation (PG-TS) gives efficient Gibbs sampling of the
posterior; at this scale a simpler Laplace approximation around the posterior mode is also
adequate and cheaper to implement.

**Until Stage 3 exists, keep a 5% uniform random hold-out.** Thompson sampling needs a
posterior; before one exists there is nothing to sample from. The random subset is also the
only unbiased baseline reply-rate estimate the system will ever produce, so it is worth
retaining at low volume (~2–3% ) even after TS is live, purely as a measurement control.

`selection_reason ∈ {thompson, random_control}` MUST be logged on every contact. Refits MUST
NOT be evaluated on the Thompson subset alone.

---

## 7a. Planned re-weighting triggers

Some coefficients are expected to change in known directions as the market changes. These are
measured triggers, not items to remember to revisit.

### AI features will likely invert

Today, absence from AI answers is near-universal across the qualified set — which is why §2
weights it small: a feature with no variance cannot discriminate, however important it sounds.

As AI answers become a real traffic source and businesses begin optimizing for them, presence
becomes variable, and AI features move from pitch colour to primary discriminator.

- The pipeline MUST track **variance of AI presence across each market's qualified set** as a
  monitored metric, not just presence itself.
- While variance stays below `ai_variance_threshold` (default **0.10**), AI features remain
  low-weight pitch flags.
- Crossing the threshold is the signal to re-elicit AI coefficients as real discriminators and
  to consider promoting AI Mode grids from shortlist tier to scoring tier.
- Log the metric from cycle one. The trigger is worthless without the baseline that shows it
  moving.

The same logic applies in reverse to geogrid coverage: it carries the discrimination today
because it is the only continuous feature with real spread. If local pack results ever compress,
its weight should fall.

---

## 8. Data model additions

```
score_run(id, market_id, model_version, lambda_shrink, calibration_alpha,
          calibration_gamma, created_at)

prospect_score(prospect_id, score_run_id, model, raw_points, score,
               predicted_prob, decile, score_factors jsonb)

score_factors: [{feature, bin, beta_prior, beta_effective, points, evidence_ref}]

outcome(prospect_id, contacted_at, selection_reason, replied_at, closed_at,
        retainer_actual, churned_at)

conflict_check(prospect_id, existing_client_id, vertical_match, market_overlap_pct,
               risk_level, reviewed_by, decision)
```

**Conflict handling — soft policy.** AR judges exclusivity case-by-case, so this MUST be a
flag, not a filter. Compute `risk_level` from vertical match × service-area overlap with the
existing client book, surface it as a badge in the prospect table, and require an explicit
decision before a prospect enters an outreach sequence. Do **not** let it modify the score —
conflict is an eligibility question, not a quality one, and blending it into the score would
hide the judgment call the policy exists to preserve.

`outcome` MUST be written from campaign one even though nothing reads it for months.
Retrofitting it means the first hundred data points are lost permanently.

---

## 9. Open decisions

1. **Base reply rates (email 5.5%, phone 25%)** — per-channel; the phone figure is the weaker
   guess of the two and is observable first. Drives Offset for
   Model A. Replace with observed data after ~3 weeks of sends; raise toward 8% as case studies
   accumulate.
2. ~~**Declining-velocity sign (+19)**~~ — **DECIDED: keep +19 with a wide prior (σ ≈ 1.0).**
   Still the most falsifiable prior in the spec and the first isolate-test candidate; the wide
   prior means modest evidence will move it, including flipping the sign.
3. **Retainer anchoring** — 0.3–0.5× ad spend vs. size multiplier. Which wins when both exist?
4. **`likely_represented`** — modeled as a score penalty. Alternative: keep score neutral and
   route to a separate displacement sequence. Current spec penalizes; revisit after Stage 2.
5. ~~**Model C tenure estimates**~~ — **MOOT under flat pricing.** `T` is constant and drops out
   of ranking. Worth pulling from the client book eventually for reporting, but it cannot affect
   prospect ordering and is not a launch task.
6. ~~**Flat vs. scaled pricing**~~ — **DECIDED: flat.** Value layer inert; see §4. Revisit
   ~month 9, once case studies exist and premium pricing is defensible.

## 10. Acceptance criteria

- [ ] Every score reproducible from `score_factors` alone (sum of points + offset = score)
- [ ] All βs config-driven; zero hardcoded coefficients
- [ ] Stage 2 recalibration runnable as a standalone job against `outcome`
- [ ] `selection_reason` recorded on 100% of contacts
- [ ] Displayed probabilities clamped ≤60% until `calibration_alpha` is non-null
- [ ] Rank order under all three models exposed side-by-side in the prospect table
