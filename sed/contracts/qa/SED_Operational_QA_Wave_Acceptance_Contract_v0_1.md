# SED Local Search Intelligence Platform
## Operational QA / Wave Acceptance Contract v0.1

**Date:** 2026-09-09  
**Status:** Implementation-ready draft  
**Governing inputs:** collection manifest v0.7; physical Supabase/Postgres schema v0.1; authoritative handoff through Section 37.

---

## 1. Purpose

This contract defines when a collection wave is operationally complete, scientifically usable, partially usable, failed, or quarantined. It binds deterministic collection expectations from the machine-readable manifest to the actual physical objects in PostgreSQL/Supabase.

It does **not** alter the research methodology. It does not add queries, prompts, coordinates, result depths, replicates, signals, or enrichment categories.

The core rule is:

> **Scientific absence is a valid observation. Technical failure is not. Structural missingness is neither.**

A valid refusal, clarification request, no-local-recommendation response, negative/cautionary mention, no AIO trigger/presentation, or zero returned businesses must not be retried merely to make results appear more complete.

---

## 2. Physical objects used by this contract

Primary operational lineage:

`ops.collection_wave → ops.collection_job → ops.collection_attempt → ops.observation`

QA state:

- `ops.qa_contract_version`
- `ops.qa_rule`
- `ops.qa_event`
- `ops.wave_evaluation`

Raw evidence:

- `ops.raw_blob`
- `ops.provider_payload`
- `ops.collection_attempt_event`

Surface evidence:

- `maps.observation`, `maps.result`
- `organic.observation`, `organic.result`
- `aio.observation`, `aio.presentation_unit`, `aio.business_appearance`, `aio.source_occurrence`, `aio.citation`, `aio.destination`, `aio.evidence_link`
- `chatgpt.observation`, `chatgpt.fanout_query`, `chatgpt.retrieved_source`, `chatgpt.citation`, `chatgpt.entity_mention`, `chatgpt.recommendation`, `chatgpt.rationale`, `chatgpt.destination`, `chatgpt.evidence_link`

Resolution and enrichment telemetry:

- `core.observed_object`
- `core.resolution_run`, `core.resolution_candidate`, `core.resolution_assertion`
- `enrichment.enrichment_request`, `enrichment.enrichment_run`, `enrichment.signal_snapshot`
- `ops.cost_event`, `ops.cost_allocation`

---

## 3. Count vocabulary

Every wave evaluation must calculate these counts from database state rather than operator-entered totals.

### 3.1 `expected_jobs`
All deterministic scientific jobs implied by the frozen manifest for the wave before structural exclusions.

Reference planning counts for manifest v0.7:

- Full Panel: 280,000 pre-water jobs.
- One Sentinel wave: 11,200 pre-water jobs.

These are reference assertions only. The authoritative expected count is the job generator output tied to the frozen methodology version.

### 3.2 `structurally_excluded_jobs`
Jobs whose required coordinate has `manifest.market_coordinate.eligibility = 'structural_water_exclusion'` and therefore must have `ops.job_status = 'blocked_structural'` or equivalent terminal non-executable state.

Structural exclusions remain expected manifest members but are not executable jobs.

### 3.3 `configuration_failed_jobs`
Jobs associated with `manual_review`, `configuration_failure`, missing coordinate configuration, invalid center, unresolved treatment/provider profile, or any other pre-execution defect.

These do **not** count as valid structural exclusions.

### 3.4 `executable_jobs`
`expected_jobs - structurally_excluded_jobs`, excluding only methodology-authorized structural exclusions. Configuration failures remain defects and must not reduce the denominator silently.

### 3.5 `attempted_jobs`
Executable jobs with at least one `ops.collection_attempt`.

### 3.6 `terminal_observations`
Executable jobs with one `ops.observation` row. Because `ops.observation.job_id` is unique, there must be at most one scientific observation per job.

### 3.7 `valid_scientific_observations`
Terminal observations whose state represents a scientifically valid response or scientifically valid explicit absence. This includes ordinary returned responses and valid ChatGPT refusal/clarification/generic/no-local-recommendation states when consistent with the normalized surface record.

### 3.8 `technical_failures`
Executable jobs ending in provider failure, parser failure, malformed/unverifiable payload, schema mismatch, retry exhaustion, or missing accepted response evidence.

### 3.9 `quarantined_jobs`
Jobs retained for provenance but excluded from primary analysis because integrity, provenance, parser, provider, or comparability rules were violated or cannot yet be resolved.

---

## 4. Wave statuses

Database enum values are lowercase (`complete`, `partial`, `failed`, `quarantined`). UI/reporting may display uppercase.

### COMPLETE
A wave is `complete` only when all of the following hold:

1. deterministic manifest/job generation reconciles exactly;
2. zero duplicate `job_key` values and zero duplicate scientific observations;
3. all intended coordinates have resolved pre-wave eligibility;
4. all executable jobs have terminal scientific observations after allowed retries;
5. zero unresolved critical raw-payload integrity failures;
6. zero unresolved critical parser/schema-drift failures;
7. surface-normalization integrity rules pass;
8. cost ledger reconciliation is within configured tolerance;
9. the wave is not under a known product/provider comparability quarantine.

This is the strongest operational state and should be the default target for Full Panel and Sentinel waves.

### PARTIAL
A wave is `partial` when the wave remains usable for explicitly bounded analyses but one or more non-critical completeness rules fail.

Recommended v0.1 threshold:

- terminal scientific observation coverage >= **99.5%** of executable jobs overall;
- each surface >= **99.0%**;
- each industry × market × surface stratum >= **95%** where the expected stratum contains at least 20 executable jobs;
- no critical integrity rule failure;
- missing jobs and affected strata are explicitly retained in `ops.wave_evaluation.metrics` and `ops.qa_event`.

A partial wave is **not automatically analysis-eligible for every estimand**. Analysis eligibility must be evaluated against the requested population/strata.

### FAILED
A wave is `failed` when collection did not produce a defensible research wave and the defect is primarily execution/completeness rather than evidence corruption.

Any of the following is sufficient:

- terminal scientific observation coverage < **99.5%** overall and the wave cannot be safely bounded as partial under this contract;
- any surface < **99.0%** without an approved surface-specific quarantine/exception;
- a required stratum falls below **95%** and the missingness threatens the intended analysis population;
- job generation differs from the frozen manifest;
- unresolved configuration failures affect executable-job identity;
- retries are exhausted for a material number of jobs.

Raw and partial normalized data are retained. Failure never means delete the wave.

### QUARANTINED
A wave is `quarantined` when data exist but scientific comparability or integrity is uncertain enough that primary analysis must not consume the affected scope automatically.

Examples:

- raw payload hash mismatch or missing raw bytes for accepted observations;
- provider response schema drift causing uncertain normalized meaning;
- parser defect that may systematically alter surface outcomes;
- wrong query/prompt, wrong coordinate, wrong market substitution, wrong replicate metadata, or wrong provider profile used;
- known ChatGPT/AIO product event that changes the observation process and requires adjudication;
- evidence of shared session/context contamination across ChatGPT replicates;
- a provider returns materially different surface semantics than the configured endpoint contract.

Quarantine may apply to a whole wave, one surface, one stratum, one provider batch, or individual observations. The stored QA event must define the scope.

---

## 5. Retry policy and scientific-result protection

### 5.1 Retryable technical conditions
Retries are permitted for:

- HTTP/network timeout;
- provider task timeout;
- provider-declared retryable error;
- transient rate-limit/service-unavailable response;
- missing/incomplete transfer where payload integrity cannot be established;
- collection worker crash before a terminal provider result is accepted.

### 5.2 Non-retryable scientific outcomes
Do **not** retry simply because the result is scientifically undesirable or sparse.

Examples:

- ChatGPT `refusal`;
- ChatGPT `clarification_requested`;
- ChatGPT `generic_guidance_only`;
- ChatGPT `no_local_recommendations`;
- no business mentions;
- negative/cautionary recommendations;
- AIO does not trigger / no AIO presentation where that is a valid endpoint result;
- Maps/Organic return fewer businesses than hoped when the response itself is technically valid;
- a business does not appear in the returned depth.

Technical retries are additional `ops.collection_attempt` rows under the same `job_id`. They never create a new scientific replicate.

---

## 6. Global manifest and identity rules

### QA-MAN-001 — methodology consistency — critical
Every job in a wave must reference the same `methodology_version_id` as `ops.collection_wave.methodology_version_id`.

### QA-MAN-002 — deterministic job-key uniqueness — critical
`ops.collection_job.job_key` must be globally unique and must match the versioned job-generator serialization/hash.

### QA-MAN-003 — exact wave membership — critical
The set of jobs in the database must equal the frozen generated matrix for the wave after applying the approved subset and structural-water execution gate.

No extra query/prompt/coordinate/replicate may be silently collected as part of the permanent panel.

### QA-MAN-004 — coordinate eligibility resolved before execution — critical
All coordinate-bound jobs must point to a coordinate with an eligibility state resolved before provider submission. `pending` and `manual_review` must not be executed as ordinary production jobs.

### QA-MAN-005 — structural exclusion semantics — critical
A structurally excluded coordinate must not have a normal provider attempt. It remains in manifest/provenance and is not encoded as rank zero or returned absence.

### QA-MAN-006 — ChatGPT replicate contract — critical
Production ChatGPT jobs must have exactly replicate numbers 1, 2, 3 for each expected industry × market × prompt condition in the wave. No replicate may reuse conversational state intentionally.

---

## 7. Collection/attempt/observation integrity rules

### QA-OPS-001 — one observation per job — critical
The physical `unique(job_id)` constraint must hold. Any attempt to create multiple scientific observations for one job is a critical defect.

### QA-OPS-002 — accepted attempt belongs to job — critical
`ops.observation.accepted_attempt_id` must reference an attempt under the same `job_id`.

### QA-OPS-003 — attempt numbering — error
Attempts for a job must be contiguous starting at 1 unless a documented recovery/import path explains the gap.

### QA-OPS-004 — successful observation has accepted evidence — critical
A normal returned observation must reference the accepted provider attempt and accepted raw response payload unless the provider integration contract explicitly documents an endpoint that cannot return raw response bytes.

### QA-OPS-005 — terminal failure classification — error
A job that exhausts retry policy must have a terminal job event plus an `ops.observation` state or other terminal failure representation required by the pipeline contract. It must not remain indefinitely `submitted`/`retryable_failure` after wave evaluation.

### QA-OPS-006 — event chronology — error
Attempt submission, response, observation timestamps and wave collection windows must be temporally plausible. Future timestamps, response-before-submit, or impossible negative durations are QA events.

---

## 8. Raw-payload integrity rules

### QA-RAW-001 — blob hash — critical
Recompute SHA-256 for retained raw bytes and require equality with `ops.raw_blob.sha256`.

### QA-RAW-002 — raw pointer resolvable — critical
Every accepted raw payload reference must point to a retrievable private Storage object at `storage_bucket/storage_path`.

### QA-RAW-003 — immutable path/hash identity — critical
A Storage path must not later resolve to bytes whose hash differs from the recorded blob hash.

### QA-RAW-004 — provider provenance — error
`ops.provider_payload.provider_id`, payload kind, provider task ID where available, captured time, and occurrence context must be present and consistent with the accepted attempt.

### QA-RAW-005 — normalization hash — warning/error
Where `ops.observation.normalized_output_sha256` is populated, deterministic re-normalization with the same parser/component version must reproduce the hash. Mismatch is error; repeated/systematic mismatch escalates to quarantine.

---

## 9. Surface-specific validation

### 9.1 Maps

- one `maps.observation` row per returned Maps `ops.observation`;
- `maps.result.result_sequence` unique per observation and contiguous for returned items;
- rank fields nonnegative/plausible and consistent with sequence/provider semantics;
- primary collection target depth = Top 10; fewer than 10 returned results is not automatically technical failure if the provider response validly contains fewer results;
- every normalized returned business-like result has an associated `core.observed_object` where identity resolution is applicable;
- no derivation should fabricate a non-returned business as rank zero.

### 9.2 Organic

- one `organic.observation` row per returned Organic `ops.observation`;
- result ordering and absolute rank/page position internally consistent;
- target collection depth = Top 10 for core matched Organic research;
- canonical URL/domain normalization must preserve the raw URL;
- Organic-only appearance does not silently create a paid-enrichment exception.

### 9.3 AIO / AI Mode

A valid AIO observation must preserve all provider-observable presentation/evidence objects without requiring any particular object type to be present.

Validate:

- one `aio.observation` subtype per returned AIO observation;
- presentation-unit sequence uniqueness;
- business-appearance sequence uniqueness;
- source-occurrence sequence uniqueness;
- citation references a valid source occurrence from the same observation;
- destination belongs to the relevant business appearance;
- evidence links do not point across unrelated observations;
- raw source URLs/titles and business labels remain preserved;
- no-presentation/no-business/no-citation outcomes are valid when supported by raw provider evidence.

### 9.4 ChatGPT

Validate:

- one `chatgpt.observation` subtype per returned/scientifically terminal ChatGPT observation;
- response outcome matches the allowed taxonomy;
- three fresh-context jobs are represented by separate `job_id` values, not repeated attempts;
- observed fanout (`origin='observed'`) is never populated from guessed/inferred reconstruction;
- retrieved source sequence is unique per observation;
- citation points to a source from the same observation;
- every normalized identifiable entity mention has a `core.observed_object`;
- every classified identifiable mention receives exactly one `chatgpt.recommendation` row when normalization/classification is complete;
- recommendation Boolean/strength constraint remains valid (`false → 0`, `true → 1..4`);
- shortlist/top-choice flags cannot be true when `recommended=false`;
- destinations preserve raw URL and controlled destination type;
- negative/cautionary mentions remain valid evidence;
- zero fanout, zero citation, zero mention, or no recommendation can be valid scientific outcomes.

Cross-replicate contamination checks should compare collection metadata for reused conversation/session identifiers where observable. Any explicit reuse of conversational state across R1/R2/R3 is critical quarantine.

---

## 10. Entity-resolution QA

Resolution completeness is measured separately from collection completeness.

### 10.1 Required semantics

- raw observed objects remain immutable regardless of resolution status;
- `resolved`/`probable_match` assertions require a canonical entity;
- ambiguous/unresolved/insufficient states do not receive a fabricated canonical entity;
- superseding assertions preserve the prior assertion;
- analyses record the entity-graph release/resolution version used.

### 10.2 Coverage metrics

Every wave evaluation should report, by surface and observed-object type:

- observed objects requiring resolution;
- resolved;
- probable match;
- ambiguous;
- unresolved;
- insufficient information;
- likely nonexistent;
- resolution coverage percentage;
- median/95th-percentile resolution latency.

No universal minimum resolution percentage is treated as a scientific validity threshold in v0.1 because surface/entity difficulty can differ. During the engineering pilot, establish empirical operating baselines. However:

- missing resolution jobs caused by pipeline failure are QA errors;
- unresolved identity due to genuinely insufficient evidence is valid missingness and must remain explicit.

---

## 11. Enrichment QA and reuse telemetry

For each enrichment signal family, capture:

- eligible economic units;
- sufficiently fresh cache hits;
- cache misses;
- changed/unchanged decisions;
- paid requests issued;
- successful runs;
- technical failures;
- signal snapshots created;
- reused snapshots;
- bytes fetched where relevant;
- cost by provider/signal/purpose;
- age distribution of reused state.

Rules:

- cached reuse must never rewrite `observed_at` to the current wave;
- unchanged content may reuse prior parsing/classification/embedding state by content hash;
- recurrence across surfaces must not create duplicate paid enrichment for the same sufficiently fresh economic unit;
- ChatGPT appearance alone does not trigger new backlink purchase;
- an entity appearing on only one valid research surface is not excluded from universal explanatory-variable enrichment merely because it lacks recurrence.

---

## 12. Cost QA

### QA-COST-001 — nonnegative append-only costs — critical
Every `ops.cost_event.amount_microusd` is nonnegative and immutable.

### QA-COST-002 — attribution coverage — warning/error
Paid provider/enrichment calls must be attributable to wave/job/attempt/economic unit/purpose as appropriate.

Recommended target: >= **99.9%** of nonzero paid cost events attributable to at least one operational or economic-unit object. Missing attribution above 0.1% is error.

### QA-COST-003 — price version — error
Where provider pricing is versioned, the cost event must reference the applicable `provider_price_version_id` or document why the amount is externally billed/unversioned.

### QA-COST-004 — provider-price drift — warning/critical
Compare realized unit cost against the active planning/price version.

Recommended thresholds:

- > **10%** unexplained unit-cost change: warning;
- > **25%** unexplained change: error and cost review;
- > **50%** unexplained change or absolute monthly forecast breach likely to exceed the current planning ceiling materially: critical/quarantine of cost-sensitive future scheduling until reviewed.

Cost drift alone does not invalidate scientific observations already collected if evidence integrity is sound.

---

## 13. Analysis eligibility

Wave status and analysis eligibility are related but distinct.

### 13.1 Complete wave
A complete wave is eligible for all analyses whose other Analysis Specification Contract requirements are satisfied.

### 13.2 Partial wave
A partial wave may be eligible only when:

- the target analysis population excludes or appropriately models affected missing strata;
- technical missingness is explicitly represented;
- the analysis specification does not silently treat missing observations as zero/nonappearance;
- sensitivity analysis shows conclusions are not driven by the technical-missingness pattern where relevant.

### 13.3 Failed wave
A failed wave is not eligible for primary longitudinal panel analyses as a complete interval. It may be used for engineering diagnostics or explicitly scoped methodological/failure studies.

### 13.4 Quarantined data
Quarantined scope cannot enter primary analysis until a documented adjudication either:

- releases it with the same evidence bytes and corrected/rebuildable parser/derived layer; or
- permanently excludes it with a reason code.

Raw evidence is never deleted merely because it is quarantined.

---

## 14. Recommended v0.1 QA metrics stored in `ops.wave_evaluation.metrics`

At minimum:

```json
{
  "manifest_expected_jobs": 0,
  "structural_exclusions": 0,
  "configuration_failures": 0,
  "executable_jobs": 0,
  "attempted_jobs": 0,
  "terminal_observations": 0,
  "valid_scientific_observations": 0,
  "technical_failures": 0,
  "quarantined_jobs": 0,
  "coverage_overall": 0.0,
  "coverage_by_surface": {},
  "coverage_by_industry_market_surface": {},
  "raw_payload_hash_failures": 0,
  "parser_failures": 0,
  "schema_drift_events": 0,
  "resolution_state_counts": {},
  "enrichment_cache_hit_rate": {},
  "paid_enrichment_calls": {},
  "cost_microusd_by_surface": {},
  "cost_microusd_by_provider": {},
  "unit_cost_drift": {},
  "analysis_eligibility_notes": []
}
```

---

## 15. Pilot acceptance before production promotion

The bounded engineering pilot should not promote to 25 × 50 production unless all of the following are demonstrated at least once end-to-end and critical defects are corrected and rerun:

1. exact manifest-to-job reconciliation;
2. water eligibility applied before coordinate-bound execution;
3. zero duplicate scientific jobs/observations;
4. >= 99.5% terminal-observation coverage overall after permitted technical retries;
5. >= 99.0% per-surface terminal coverage;
6. raw bytes retained and hash-verifiable for 100% of accepted provider responses sampled by the integrity checker, with a target of 100% system-wide;
7. no unresolved critical parser/schema-drift defects;
8. Maps/Organic/AIO/ChatGPT normalized-object integrity rules pass;
9. ChatGPT R1/R2/R3 independence is operationally demonstrated;
10. entity-resolution pipeline executes for every eligible observed object even where the final state remains ambiguous/unresolved;
11. enrichment cache/dedup/freshness telemetry is captured;
12. costs reconcile to provider activity closely enough to explain >=99.9% of nonzero paid events by operational/economic-unit attribution;
13. marginal 13-vs-nested-9 pilot telemetry can distinguish the four incremental Maps/Organic points in counts, unique entities, cost, and later spatial analyses;
14. failed/quarantined data remain recoverable and do not contaminate primary analysis views;
15. an entire derived dataset can be rebuilt from recorded methodology/entity-graph/parser/code/input-artifact versions.

These are engineering promotion gates. They do not authorize tuning the research panel toward preferred outcomes.

---

## 16. QA severity semantics

- `info` — telemetry or expected condition, no corrective action required.
- `warning` — unusual condition; data remain usable unless another rule escalates.
- `error` — defect requiring correction, scoped exclusion, or explicit partial-wave treatment.
- `critical` — threatens scientific identity, provenance, integrity, or comparability; affected scope must fail or quarantine automatically.

---

## 17. Contract versioning

Insert a row into `ops.qa_contract_version` for every frozen QA contract.

Recommended initial identifiers:

- `contract_code = 'SED_WAVE_QA'`
- `version_code = '0.1'`

Every evaluated wave must reference the exact `qa_contract_version_id` used. QA thresholds may evolve from pilot telemetry, but old wave evaluations must remain reproducible under their original contract version.

---

## 18. Next artifact

After this QA contract is seeded and validated against the development schema, produce the **Bounded Pilot → Production Protocol**. That protocol must define the recommended 3-industry × 5-market engineering pilot membership, run order, preflight checklist, migration/storage setup, retry/failure drills, water-mask execution, QA adjudication, 13-vs-9 telemetry capture, and explicit go/no-go criteria for the 25 × 50 launch.
