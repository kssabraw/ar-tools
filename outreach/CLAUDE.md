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

**Read `HANDOFF.md` first — it carries current state.** As of 2026-08-08: Phase 1 and 1b are
merged, Phase 2's storage foundations / geometry / router / rollup / placeholder score are live,
and **the first live scan is DONE** — `emergency plumber` × whole-city Los Angeles, run through the
new any-city onboard path: 122 discovered, 83 survived, 81/81 points collected, snapshot rolled up,
119 coverage rows. The scan tables hold real data for the first time.

**THE PER-PROSPECT REPORT IS BUILT + MERGED (2026-08-08, PRs #615–#619).** The "why this is a lead"
**call hook** ("Why call?" — deterministic talking points a caller reads before dialing) plus a
two-face competitive **report** (an internal brief + an approval-gated client-facing PDF) carrying
three signals: **MAPS** (rankings vs competitors, has live data from the first scan), **ORGANIC**
(`scan-organic`, PAID, unrun) and **AI VISIBILITY** (`scan-ai` — ChatGPT + Google AI Overview, new
`ai_region` + `ai_scan_result` tables; PAID, unrun). Every part is DETERMINISTIC and fact-grounded —
never an LLM guess, never a fabricated fact/competitor/number (DECISIONS 2026-08-08, the design-fork
ruling), the same discipline as the heatmap renderer. The client PDF is generated only behind an
explicit human approval (`report_approval`, the no-unapproved-asset invariant) and delivered as a
90-day signed URL on Supabase Storage (reporting §5, not R2). Read/assembly logic lives in
`writer/platform-api/services/outreach_justification.py` + `outreach_report.py` (pure) with the I/O
in `services/outreach.py`; the paid producers are `api/services/organic_scan.py` +
`ai_visibility.py`; UI in `frontend/src/pages/Outreach.tsx` + `components/outreach/ProspectReport.tsx`.
Migrations `20260808140000` / `160000` / `180000` applied live. **I-095 is fully resolved.** The
organic + AI scans have never been run — the report's organic/LLM sections read `not_scanned` until
an admin authorizes those paid commands (they gate exactly like `scan`).

**THE PAID-PLACEMENT SIGNAL IS BUILT + MERGED (2026-08-08, PR #621).** The report's FOURTH signal —
is the business (and are its competitors) BUYING Google Ads / Local Services Ads. `scoring-spec.md`
rates it above every organic signal, because a business paying to solve the visibility problem while
still losing organically has proven budget AND intent. **Slice A (presence)** is parsed out of the
organic SERP capture already on disk — `organic_scan.parse_organic_serp` now also reads `paid` and
`local_services` items and writes a `paid` block into `serp_result.payload_summary`, so Google-Ads
presence costs NO new paid call. **Slice B1 (site tech)** is `scan-tech` — a FREE fetch of each
prospect's own site detecting Meta pixel / `AW-` conversion tag / GTM / CallRail-Podium-Birdeye into
`prospect_tech_signal` (`services/tech_signals.py` pure + `scan_tech.py`). **Slice B2 (ad-spend
MAGNITUDE) is deliberately NOT built** — gated behind a DataForSEO Labs yield spike, because Labs
paid data is likely sparse for the small local advertisers this pipeline targets (I-098). The
§16a.1 pixel spike (`probe-pixel-field`, PAID + gated) is built and unrun. Design:
`docs/paid-placement-slice-b-design-v0_1.md`.

**Read I-099 before touching the paid signal.** An adversarial review found three real defects in
this code before it ran, and two were the same shape: *a boolean true for several reasons, with the
sentence built from it naming only the most flattering one.* An `AW-` tag on a prospect's SITE
produced the spoken claim "you're paying for Google Ads on ⟨keyword⟩" for a keyword whose SERP showed
no ad from them. So the signal now carries `paying_evidence` (`serp_ad` | `lsa` | `conversion_tag`)
and a narrow `prospect_paying_this_keyword` beside the broad `prospect_is_paying`, and every surface
branches on it. **When you add a source to a signal, add the evidence tag with it.**

**Phase 2 SCANNING is PROVEN, not just built.** `api/services/maps_scan.py` (pure — task bodies,
`tasks_ready`/`task_get` parsing, completeness) and `api/services/scan_runner.py` (submission,
collection, finalization) with the `scan_task` bookkeeping table ran end-to-end against a live
DataForSEO response. Commands: `scan` (paid, one submarket × one keyword), `collect` (free), and
`tick` (the cron heartbeat — collect + drain at most one `scan_request` + one `onboard_request`),
live on a 15-minute cron since 2026-08-07.

**The ANY-CITY SCAN is BUILT + MERGED (2026-08-08).** The scan is no longer confined to the seeded
LA market. A user types any Google-resolved **city** + optional Google-recognized **sub-area** + a
**free-text consumer search** (what a customer types, not a GBP category) on the `/outreach` page;
platform-api discovers (Outscraper) → filters → scans (geogrid), the consumer search driving BOTH
the ingest category AND the scan keyword. This is required because `prospect_coverage` joins
`grid_result` to *pre-ingested* `prospect` rows on place_id (I-092) — scanning a never-ingested city
would yield zero coverage, so the onboard path ingests-then-scans as one staged **`onboard_request`**
order (migration `20260808120000`, applied live; `api/services/onboard_queue.py`; drained by `tick`,
one per heartbeat, order row is its own spend confirmation). Geo enumeration is OSM-enumerate
(`platform-api services/outreach_geo.py` via `overpass.places_near`) + Google-verify
(`place_is_within_city`, moved to the FastAPI-free `services/maps_geocode.py`). **platform-api is now
configured** with the Outreacher credentials (Railway cross-service reference variables).

**The collector's schedule is load-bearing, not a preference.** The ready list holds a task ~3
days. A collector on the 15-day scan cadence lets every task age off between runs, silently
converting the normal path into the fallback-by-id path — which still works, which is exactly why
nobody would notice. Collection is free; run it hourly or daily.

Owner ruling 2026-08-03: the **first live run is ONE submarket × ONE keyword**, so a wrong
response envelope costs one batch rather than a market. `cmd_scan` refuses to do more.

**The `prospect_coverage` rollup, land masking and dead-point exclusion are BUILT** (2026-08-05,
migration `20260805120000`, applied live). One plpgsql function per snapshot ending in
`finalize_snapshot_rollup()`, so summary statistics cannot be written without their `rank_vector`.
`collect` rolls up what it finalizes; `rollup` stands alone for backlog and `--verify`. Both free.
Eight ambiguities logged as I-074…I-081 rather than resolved in the specs — read I-076 before
building anything that reads coverage.

**The placeholder score is BUILT** (2026-08-05) as `v_prospect_placeholder_score` — a view over
`prospect_coverage`, deliberately NOT a `prospect_score` row (ISSUES I-082: that table is the
Phase 4 model's, and the reporting layer already reads it as one). `scan_snapshot` also records
its own grid centre now (I-078 resolved), which had to happen before the first snapshot was
written rather than after.

**The UI trigger is BUILT + MERGED (2026-08-06 `scan_request`, extended 2026-08-08 to any-city
`onboard_request` — resolves I-072).** Two signed-order types, both placed admin-only from the
`/outreach` page via platform-api and both its own spend confirmation: `scan_request` (scan a
pre-ingested submarket) and `onboard_request` (discover→filter→scan any city). The outreach `tick`
command (collect + drain at most ONE of each per heartbeat) executes them on the 15-minute cron.
`tick` is deliberately NOT in `PAID_COMMANDS` — the order row is its confirmation — and `collect`
stays free and never drains. The env token still gates every config-driven paid command.

**Phase 3 heatmap renderers are BUILT + MERGED** (#580 slice 1: deterministic per-prospect heatmap +
`report_artifact` provenance; #589 slice 2: `heatmap_pair` + `heatmap_delta`). The renderer now has a
live snapshot to draw from, but nothing has rendered an artifact yet (no `report_artifact` rows).

**What is genuinely unbuilt is now short.** Phase 3's renderer, call hook, report, approval gate and
PDF are all merged; the organic / AI / paid scan layers are merged. What remains of Phase 3 is
**`outcome` + `touch` + the emit webhook**, then Phase 4 scoring, Phase 5 email, Phase 6 learning.
See HANDOFF §12 for the value-ordered roadmap.

**`outcome` is the item with a CLOSING WINDOW, and it is the next build.** It is the learning
substrate every later model fits against, and it cannot be backfilled: a call made before `outcome`
exists is a data point lost permanently (`scoring-spec.md` §8 — *"MUST be written from campaign one
even though nothing reads it for months"*). HANDOFF's standing recommendation is "go make the first
calls", and that recommendation and this invariant PULL AGAINST EACH OTHER — every call placed
before the table exists is unmodellable. The DDL is already worked out in
`PHASE3-outcome-constraint.md`. Build it before dialing, or decide deliberately that the first N
calls are lost to the model and write that down.

**FOUR paid producers are built and have NEVER RUN** — `scan-organic`, `scan-ai`,
`probe-pixel-field` (and the free `scan-tech`). HANDOFF §8.1 2c already made the argument that each
additional unrun layer raises the chance the first run surfaces several faults at once, interacting,
in a batch that has been paid for. That argument is stronger now than when it was written, so prefer
RUNNING a built layer over building a fifth.

**The pipeline is an AR Tools SUITE MODULE, not a standalone tool** (owner ruling, HANDOFF §2).
The database stays in the Outreacher project; the API and UI belong in `platform-api` and the
suite SPA. Retool is dropped; access is service-role only. Anything you read that says to create
Supabase auth users for the Outreacher project is out of date, and anything in the schema that
reads `auth.uid()` is now reading a null — see ISSUES I-040.

**Two databases, two migration directories.** Outreach migrations go in `outreach/migrations/`
and never in `writer/supabase/migrations/`, which targets AR-Internal-Tools.

## Invariants — violating these breaks things expensively

- **Grid geometry is immutable.** Changing a submarket's centre, radius, or spacing invalidates
  every prior snapshot and resets its delta history. Names are editable; geometry is not.
- **The grid holds 81 points, and the generator is a version REGISTRY.**
  `api/services/geometry.py` — square lattice, row-major from NW, clipped to the radius, per
  reporting spec §4.1. "89" was an estimate no construction produces (ISSUES I-025). Never
  regenerate a historical snapshot with the default version; pass its stored `geometry_version`.
  An unknown version must raise, never fall back.
- **`grid_result.scan_month` comes from the snapshot, never from `now()`** (ISSUES I-044).
  Deriving it from the clock splits one snapshot across two partitions and makes the retention
  job blame the rollup.
- **`grid_result` is owned by `docs/storage-retention-spec.md`.** Partitioned by month, no
  lat/lng columns. The copy in the PRD is context only.
- **Coverage counts points MEASURED, never points where something was FOUND.** `live_points` reads
  `scan_task.status = 'collected'` intersected with `grid_point_status.land`. An empty pack stays
  in the denominator — it was measured, and "nobody ranks here" is a finding. An uncollected task
  leaves it entirely. This has been the wrong answer three times in three places (DECISIONS.md).
- **A rollup writes `rank_vector` in the same transaction as the numbers, or writes nothing.**
  That is why it is one SQL function: PostgREST gives one transaction per call, so an application
  loop cannot hold both halves. Never add a statement after `finalize_snapshot_rollup()`.
- **A coverage DENOMINATOR is never recomputed after the fact.** `live_points` is stored
  contemporaneously. Re-deriving it from today's land mask silently rewrites every claim already
  made from it.
- **A prospect with no `prospect_coverage` row has ZERO coverage, not unknown** (ISSUES I-076) —
  but only inside a submarket carrying a `snapshot_rollup` marker. Outside one, nothing was
  measured and there is no score to give. Confusing the two scores a failed scan as total
  invisibility, which is the strongest pitch in the market, manufactured.
- **`prospect_score` is the Phase 4 model's table and stays empty until then** (ISSUES I-082). The
  placeholder is a view. The reporting layer already reads `prospect_score` as a fitted score.
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
- **A signal that can fire from several sources must carry WHICH one fired**, and every sentence
  built from it may claim only what that source measured (I-099). `paying_evidence` is the worked
  example: a SERP ad and an `AW-` tag on the prospect's own site both make them "paying", but only
  the first was measured on this keyword — and a claim the prospect can falsify in one sentence
  costs the call. Absence of a source contributes NOTHING (unknown ≡ absent, never subtracts).
- **A name match between two records is ONE-DIRECTIONAL — the prospect's name inside the other's,
  never the reverse** (I-099, and `detect_ai_mention` before it). The reverse lets a shorter
  competitor name ("AAA Plumbing") match a longer prospect name ("AAA Plumbing Services") and
  fabricates a claim while deleting a real competitor. The kept direction fails toward a MISS.
- **A shared CLI default is not a default.** `--limit` defaulted to 20 for every subcommand and
  silently capped `scan-tech` at 20 of ~1,000 sites while exiting 0. Defaults belong to the COMMAND
  (`scan_tech_limit` / `pixel_probe_limit` / `legacy_limit`), and the safe value differs per command.
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
