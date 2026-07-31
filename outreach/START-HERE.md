# START HERE — Outreach Pipeline Build Guide

**Read this first. The six specs are reference, not a work order.**

---

## 1. What this is

A continuous market-monitoring system for AR's SEO agency. It scans local markets on a
semi-monthly cycle, scores the businesses in them, and produces a per-prospect audit used for
cold outreach. Prospecting evidence, campaign baseline, and client reporting are all the same
measurement stream.

## 2. The single most important instruction

**Do not attempt to satisfy all the acceptance criteria before shipping.** There are ~80 across
six documents. Roughly 15 apply to Phase 1. The rest describe a system that has been running for
months and has data it does not yet have.

A working pipeline that ingests, filters, scans one market, and renders one heatmap is worth more
than a complete implementation of the scoring model, because the scoring model's coefficients are
estimates that real outcomes will overwrite within two quarters.

## 3. Documents

| Doc | Read when |
|---|---|
| `docs/PHASE-1-BRIEF.md` | **Phase 1 only. Self-contained — do not read the PRD for Phase 1.** |
| `docs/PRD-prospect-pipeline.md` | Phase 2 onward. Pipeline stages, data model, integrity guards. |
| `docs/scoring-spec.md` | Phase 4, when replacing the placeholder score. |
| `docs/storage-retention-spec.md` | Phase 2, before the second scan cycle writes data. |
| `docs/reporting-layer-spec.md` | Phase 3, heatmap and PDF. |
| `docs/crm-layer-spec.md` | **Phase 1b — build in parallel with Phase 1.** Lead pipeline, sources, suppression. |
| `docs/dataforseo-dependency-note.md` | Only if the provider changes. Not build input. |

## 3a. Table ownership

Each table is **defined in exactly one document.** Where a table appears elsewhere it is context
only — implement from the owning doc. `grid_result` in particular was duplicated with conflicting
schemas during drafting; the storage spec's partitioned version is authoritative.

| Owner | Tables |
|---|---|
| `docs/PRD-prospect-pipeline.md` | `market`, `submarket`, `ai_region`, `keyword`, `prospect`, `filter_result`, `scan_snapshot`, `serp_result`, `ai_check`, `prospect_delta`, `grid_point_status`, `prospect_alias`, `site_signal`, `case_study`, `case_study_match`, `score_run`, `prospect_score`, `enrichment`, `slot`, `conflict_check`, `audit_asset`, `audit_evidence`, `asset_engagement`, `touch`, `outcome`, `cost_ledger` |
| `docs/storage-retention-spec.md` | **`grid_result`** (partitioned), `grid_result_retained`, `prospect_coverage` |
| `docs/reporting-layer-spec.md` | `report_artifact`, `audit_approval` |
| `docs/crm-layer-spec.md` | `lead`, `lead_activity`, `suppression` |

## 3b. Configuration reference

Every tunable, with its decided value and where the reasoning lives. All MUST be config, never
hardcoded.

| Key | Value | Source |
|---|---|---|
| `monthly_prospect_starts` | 100 | PRD §8 |
| `touches_per_sequence` | 5 | PRD §15a |
| `cycles_per_month` | 2 (semi-monthly) | PRD §4a |
| `scan_interval_days` | 15 | PRD §4a |
| `min_history_cycles` | 2 | PRD §4.2 |
| `bootstrap_share` | 1.0 | PRD §4.4 |
| `max_evidence_age_days` | 30 | PRD §4.1 |
| `max_delta_span_days` | 45 | PRD §5 |
| `slot_depth_max` | 5 | PRD §8 |
| `slot_attempt_limit` | 8 | PRD §8 |
| MMR `λ` | 0.5 → 0.6 → 0.8 (refit-gated) | PRD §8 |
| `λ_shrink` | 0.5 | PRD §15a |
| `completeness_threshold` | 0.98 | PRD §9a.3 |
| `max_market_run_cost_cents` | 5000 | PRD §13 |
| `max_portfolio_cycle_cost_cents` | 40000 | PRD §13 |
| `email_track_ready` | gate, not a value | PRD §15a |
| Channel split | 100/0 → 50/50 → 30/70 (gated) | PRD §15a |
| `url_expiry_days` | 30 | Reporting §7a |
| `auto_approve_clean` | off | Reporting §4a |
| Hot window | 90 days | Storage §11a |
| `ai_variance_threshold` | 0.10 | Scoring §7a |
| PDO / TargetScore | 50 / 500 | Scoring §1 |
| Model A offset (email / phone) | 705.0 / 579.3 | Scoring §1 |
| Model B offset | 625.1 | Scoring §1 |

Two are **gates rather than values** — `email_track_ready` and the MMR λ progression. Both MUST
advance on verified conditions, never on elapsed time.

## 4. Build phases

### Phase 0 — Prerequisites (start immediately, in parallel with everything)

These have calendar lead time and cannot be compressed by working faster.

- [ ] Email sending vendor decided. **GetResponse is likely disqualified** — its anti-spam policy
      prohibits non-opt-in addresses and suspension can be permanent. See `crm-layer-spec` §7.
- [ ] Sending domain acquired, SPF/DKIM/DMARC configured, warming started (3–4 weeks)
- [ ] Supabase project, R2 bucket, DataForSEO and Outscraper accounts provisioned
- [ ] Verification spikes run (PRD §16a): Outscraper pixel field (~1h), AI prompt granularity
      (~20m), map tile licensing (~30m)
- [ ] Submarket and `ai_region` names drafted for the first market (~1 afternoon, manual)

### Phase 1 — Ingest and filter *(no score)*

**Goal: a filtered prospect list from a real market.** No scoring at all — a geogrid placeholder
is impossible here because no grid data exists until Phase 2. Order by review count if an order
is needed for inspection.

- [ ] Outscraper base pull, tiled by category × geography, deduplicated on `place_id`
- [ ] Raw response persisted to `prospect.raw` before any parsing
- [ ] Filter gates applied: closed, no phone, review count < 10, no review in 9 months, suppression
- [ ] Franchise pattern matches **flag**, never exclude
- [ ] Every exclusion logs all failing rules, not just the first
- [ ] No scoring. `prospect_score` is not written in this phase.
- [ ] `cost_ledger` written per stage per provider

*Ignore for now: all three scoring models, deltas, evidence attribution, slot allocation.*

### Phase 2 — Scan and snapshot

**Goal: real pain signals and the data a heatmap needs.**

- [ ] Placeholder score = raw geogrid coverage deficit (one SQL expression). This belongs here,
      not Phase 1 — it needs grid data to exist.

- [ ] Grid geometry generated from pinned, versioned function; parameters persisted per snapshot
- [ ] Maps geogrid via DataForSEO standard queue, batched, postback not polling
- [ ] Organic SERP + AI Overview per submarket × keyword; paid results parsed for ads-gap
- [ ] AI checks per `ai_region` (not per submarket), ≥3 samples, deduplicated by region
- [ ] `scan_snapshot` immutable, append-only, with `expected_points` / `actual_points`
- [ ] Snapshots below 98% completeness marked incomplete and excluded from scoring
- [ ] Dead grid points excluded from coverage denominator after 3 consecutive null scans
- [ ] Partitioning and retention jobs in place **before** cycle two writes data

> **This is not optional and not deferrable.** At the recorded portfolio size, `grid_result` grows
> ~64M rows/year (~7.7 GB). Unpartitioned append-forever breaches Supabase Pro's 8 GB allowance
> within the first year, and retrofitting partitioning onto a multi-gigabyte table is materially
> harder than building it first.

*Storage spec becomes relevant here. Partitioning is far cheaper to set up now than to retrofit.*

### Phase 3 — Heatmap, audit, and the phone track

**Goal: a real conversation with a real prospect.** This is the first phase that produces revenue.

- [ ] Heatmap renders from `prospect_coverage.rank_vector` + geometry alone
- [ ] Dead points visually distinct from "not found"; legend and scale bar present
- [ ] Renderer deterministic — identical inputs produce identical `content_hash`
- [ ] Audit PDF assembled; generation gated on explicit approval, never on cycle completion
- [ ] Send-time LLM verification runs at generation for any engine-specific claim
- [ ] Call hook rendered from persisted evidence
- [ ] Emit webhook delivers an audit-ready queue
- [ ] `outcome` row written for every emitted prospect

*Ship the phone track first. Zero enrichment cost, tests the whole pipeline on real conversations
before any per-record spend.*

### Phase 4 — Scoring model

**Goal: replace the placeholder.** Only worth doing once Phase 3 is producing audits.

- [ ] Scorecard per `docs/scoring-spec.md`; all coefficients config-driven, zero hardcoded
- [ ] Per-channel offsets (email 705.0, phone 579.3) — never a shared Model A base rate
- [ ] `score_factors` fully replayable: points + offset reproduces the stored score exactly
- [ ] Two-pass scoring; pass 1 excludes reachability rather than defaulting it
- [ ] Golden fixtures pass in CI, including a phone/email pair and an all-unknown case
- [ ] Slot allocation with MMR selection at λ = 0.5
- [ ] Deltas computed against the mean of the prior two snapshots

*Deltas need three snapshots — roughly six weeks in. They arrive naturally, not on demand.*

### Phase 1b — CRM (runs in PARALLEL with Phase 1, not after)

**Goal: your partner has something usable immediately.** This track has no dependency on the
scanning pipeline and can be populated by hand from day one.

- [ ] `lead`, `lead_activity`, `suppression` tables
- [ ] Manual and inbound lead entry (`source` ∈ inbound_form, inbound_call, referral, manual)
- [ ] Per-owner RLS policies written and tested, however permissive
- [ ] Low-code UI over the Supabase tables (Retool or similar) — 2–3 days, board + detail views
- [ ] Suppression check present, tolerant of empty tables

*Outbound leads flow in later, when Phase 3's emit webhook starts writing `lead` rows with
`source = 'outbound_scan'`. Nothing here blocks on that.*

> **Why parallel rather than Phase 5.** A lead CRM is useful the day it exists — inbound and
> referral leads can be tracked while the pipeline is still being built. Deferring it to Phase 5
> means months of untracked leads for no benefit.
>
> **Do not build a custom React app first.** Start with the low-code layer. If it gets used
> heavily, that is the signal to invest; if it does not, you have spent three days.

### Phase 5 — Enrichment, email track, lead promotion

**Goal: manage a pipeline and open the second channel.**

- [ ] Suppression checked before scoring and enrichment, not at send
- [ ] Single-business lookup — promote an inbound lead into a full prospect (~$0.003)
- [ ] Ad-hoc submarket creation and scan for out-of-portfolio leads (~$0.05)
- [ ] Outscraper contact enrichment, email track only, depth = 70% of `prospects_per_cycle`
- [ ] ESP integration: `prospect_id` custom field, webhooks, suppression sync
- [ ] ESP send-time optimization and native A/B verified **off**
- [ ] Channel ramp gated on `email_track_ready`, never elapsed time

### Phase 6 — Measurement

**Goal: start replacing estimates with evidence.** Nothing here pays off for months, but the
logging must exist from Phase 3 or the early data is lost permanently.

- [ ] Evidence randomization at generation; overrides logged, not blocked
- [ ] `sequence_version` and `template_version` stamped on outcomes and assets
- [ ] Operator and analysis views
- [ ] Stage 2 recalibration job (runnable at ~30–50 outcomes)
- [ ] AI presence variance tracked as a re-weighting trigger

---

## 5. Things that will be tempting and are wrong

**Adjusting grid geometry after seeing results.** Geometry is immutable. Changing a centroid or
radius invalidates every prior snapshot for that submarket and resets its delta history. Names are
editable; geometry is not.

**Tuning `λ_shrink` to improve ranking.** It cannot. It is a uniform multiplier and therefore a
monotonic transform — order is mathematically unchanged. Stage 2 recalibration exists to correct it.

**Blocking evidence-randomization overrides.** Blocking guarantees the rule gets bypassed
invisibly. Logging preserves the experiment.

**Treating `payload_path IS NULL` as "no payload."** It means not yet migrated. Fall back to the
Postgres column.

**Pooling phone and email replies in one fit.** They measure different events, not the same event
at different rates.

**Building the full scoring model before the pipeline ingests anything.** The coefficients are
estimates awaiting data that only a running pipeline produces.

---

## 6. What is genuinely unvalidated

Say so in commit messages and code comments where it matters. Nobody has tested any of this
against a single reply.

- Every scoring coefficient is an elicited estimate, not a measurement
- Base reply rates (email 5.5%, phone 25%) are guesses; phone is the weaker one
- The declining-velocity sign (+19) may well be backwards
- Vendor-failing (+79) is the largest coefficient and has never fired

The pipeline mechanics — ingestion, filtering, scanning, cost control, entity resolution — are
sound. The scoring is careful reasoning in real mathematics, which makes it look more authoritative
than it has earned. Treat rank order as a strong prior, not a prediction, until ~100 prospects have
been contacted.
