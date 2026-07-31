# CLAUDE.md — Outreach Pipeline

## Orientation

Pre-client prospecting pipeline for Amazing Rankings. Scans local markets semi-monthly, scores
the businesses in them, produces a per-prospect audit for cold outreach. Prospecting evidence,
campaign baseline, and client reporting are one measurement stream.

**Read `START-HERE.md` first.** It carries the build phases, table ownership, and the full
configuration reference. The six specs are reference material, not a work order.

## Session protocol

1. Read `DECISIONS.md` before proposing any architectural change. Most things that look open are
   settled, with reasoning recorded.
2. Read `ISSUES.md` for known problems and their status.
3. Work the current phase only. Do not pull work forward from later phases.
4. Append to `DECISIONS.md` when a genuine choice is made — with the reasoning, not just the
   outcome.
5. Append to `ISSUES.md` when something is discovered that cannot be fixed immediately.
6. If a spec is ambiguous, log it in `ISSUES.md` and pick the interpretation that is cheapest to
   reverse. Do not silently resolve ambiguity in the specs themselves.

## Current phase

**Phase 1 — Ingest and filter.** Read `docs/PHASE-1-BRIEF.md` — it is self-contained and you do
not need the PRD for this phase. Eight acceptance criteria. **No scoring of any kind**, no
scanning, no deltas, no enrichment, no audits.

**Phase 1b — Lead CRM — runs in parallel, not after.** Independent of the scanning pipeline; see
`START-HERE.md` §4. If asked to work on the CRM, that is a separate track, not scope creep into
Phase 1. Do not merge the two.

## Invariants — violating these breaks things expensively

- **Grid geometry is immutable.** Changing a submarket's centre, radius, or spacing invalidates
  every prior snapshot and resets its delta history. Names are editable; geometry is not.
- **`grid_result` is owned by `docs/storage-retention-spec.md`.** Partitioned by month, no
  lat/lng columns. The copy in the PRD is context only.
- **Partitioning must exist before cycle two writes data.** At the portfolio size, unpartitioned
  append breaches Supabase Pro's 8 GB allowance inside year one.
- **`outcome` is the modelling substrate.** Workflow changes never mutate it. `touch` is
  authoritative for "a contact attempt happened"; `lead_activity` carries commentary only.
- **All coefficients load from config.** Zero hardcoded βs, ever.
- **`score_factors` must be replayable.** Points + offset must reproduce the stored score exactly.
- **Phone and email scores use different offsets** (579.3 / 705.0) and must never be ranked in one
  list.
- **Unknown ≡ absent for ad/tech signals.** Neither ever subtracts.
- **No prospect-facing asset is generated without explicit human approval.**
- **`outcome` is outbound-only.** Rows exist solely for leads with `source = 'outbound_scan'`.
  Inbound and referral leads converted for different reasons; including them would inflate every
  coefficient. Business reporting reads `lead.stage`; model fitting reads `outcome`.
- **Never fabricate a `place_id`.** Grid results join on it, so an invented one silently matches
  nothing — leaving a prospect that can never be scored or audited. Use single-business lookup.

## Traps — plausible-looking actions that are wrong

- Tuning `λ_shrink` to improve ranking. It is a uniform multiplier and cannot change rank order.
- Adjusting grid geometry after seeing results.
- Blocking evidence-randomization overrides instead of logging them.
- Treating `payload_path IS NULL` as "no payload" — it means not yet migrated.
- Pooling phone and email replies in one model fit.
- Regenerating golden fixtures from the implementation. They are independently computed; if they
  disagree, the code is wrong.

## Stack

FastAPI on Railway · Supabase (Postgres 15+, pg_cron) · Cloudflare R2 · DataForSEO · Outscraper ·
WeasyPrint

## Testing

`tests/fixtures/golden-fixtures.json` contains seven hand-computed scorecard cases. CI must fail on any
deviation beyond tolerance. Scorecard arithmetic fails silently — a sign-flipped offset produces
plausible but inverted scores — so these are not optional.

## What is unvalidated

Every scoring coefficient is an elicited estimate. No part of the model has been tested against a
single reply. Treat rank order as a strong prior, not a prediction, until ~100 prospects have been
contacted. Say so in comments where it matters.
