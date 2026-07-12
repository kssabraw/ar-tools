# LeadOff — Feedback-Loop Calibration Surface (Plan v1.0)

**Status:** DESIGN — Phase 0 (instrumentation) specified for review; **no code
written, no scoring weight changes**. Owner review gates implementation.
**Depends on:** the Create-Client-from-market handoff (#339) — the capture
seam — and the outcome-bearing modules (organic + maps rank trackers, GBP
enrichment, campaign goals).
**Companion docs:** `leadoff-prd-v1_0.md` (module), scanner methodology at
`docs/reference/leadoff-scanner/` (where the weights live on the desktop
side), `docs/sops/LeadOff_Market_Intelligence_SOP.md` (usage rules).

## 1. The idea (and the discipline)

LeadOff makes **falsifiable predictions** per market. When the agency actually
builds in a market, reality grades the model: the review bar was or wasn't
~36, the field was or wasn't winnable at 0.45, the leads did or didn't
approximate 47/mo. Captured systematically, those prediction↔outcome pairs
become the calibration surface no competitor can copy — the moat is the
*engagement history*, not the formula.

The discipline, per the working agreements: **there is no outcome data yet**,
so tuning anything now is guaranteed overfitting on N≈0. The first job is
purely archival — freeze what LeadOff asserted at decision time, join it to
realized outcomes as they accrue, and report error read-only. Weights move in
Phase 1, behind a hard minimum-N gate, as human-approved proposals.

## 2. Prediction schema — what LeadOff asserts, captured where

### 2.1 The capture seam

`POST /leadoff/create-client` is the moment a market pick becomes a real
engagement — the only point where "LeadOff said X" and "we acted on it" are
simultaneously true. Today the endpoint reads the full market brief and
writes a **lossy prose** campaign goal ("~36 reviews… ~20 true RD"). Phase 0
adds a **lossless, immutable** `leadoff_predictions` row alongside it (the
goal stays — it's the human-facing yardstick; the prediction row is the
machine-facing one).

Tryouts (`leadoff_tryouts`) are NOT predictions: no engagement follows most
of them. If a client is later created from a tried-out city (off-board), the
handoff captures whatever vector exists at that moment; tryout-only rows are
never joined to outcomes.

### 2.2 The table (public schema — app-owned, like `leadoff_tryouts`)

```sql
create table leadoff_predictions (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients(id) on delete cascade,
  city_id        bigint not null,
  category_id    text not null,
  category       text not null,
  city_name      text not null,
  state_code     text not null,
  as_of          text,             -- board vintage ("2026-07") — which scan asserted this
  assumptions    jsonb not null,   -- {capture, lead_tier, lead_value_used}
  predicted      jsonb not null,   -- §2.3 vector, verbatim board numbers
  competitors    jsonb not null,   -- frozen top-5 at selection (name/domain/rating/review_count/rank_position)
  enrichment     jsonb,            -- rd_min/rd_med/momentum/vel_matched/growth_yoy/growth_yoy_ss/peak_months if scouted
  model_version  jsonb not null,   -- §5.2: the constants in force (rankability weights, veto thresholds, percentile ref vintage)
  created_by     uuid references profiles(id),
  created_at     timestamptz not null default now()
);
-- one prediction per engagement; a client re-created for a second market is a second row
create unique index uq_leadoff_predictions_client_market
  on leadoff_predictions (client_id, city_id, category_id);
```

**Immutable by convention**: no UPDATE path. Corrections are new engagements.

### 2.3 The predicted vector (all verbatim from the board row at capture)

| Field | Meaning | Falsifiable by |
|---|---|---|
| `rev_win` | reviews to beat the #3 incumbent (static bar at selection) | §3.1 |
| `rankab` | 0–1 win-likelihood | §3.2 |
| `xdem` | regressed monthly demand | §3.3 (weak) |
| `est_leads_mo` / `exp_leads_mo` | leads at capture% / × rankab | §3.3 |
| `value_mo` / `exp_val` | $ if ranked / expected $ | §3.3 (derived) |
| `grade` / `build` | national percentile + vetoes | §3.4 (cohort-level) |
| `roi` | exp_val ÷ rev_win | derived — not independently scored |
| `rating`, `namekw`, `exact_open`, `luck`, `conf`, `v3`, `population` | context for later slicing (e.g., "were low-conf predictions worse?") | not directly |

The `competitors` freeze matters as much as the vector: `rev_win`'s outcome
needs *which business was #3 and its review count on selection day*, because
the field moves (that's the whole `momentum` point).

## 3. Outcome-source mapping — what proves or refutes each metric

All joins are per `client_id`, computed by a periodic read-only job (§4). A
metric with no available source records `null` + a `coverage` reason — the
report is honest about what it cannot yet see.

### 3.1 `rev_win` → GBP review trajectory (AVAILABLE TODAY)

- **Client side:** `clients.gbp` review count, refreshed by the existing GBP
  fetch path; snapshot per outcome check.
- **Bar side:** two readings — (a) the *frozen* bar (predicted `rev_win` vs
  the frozen #3's count) and (b) the *live* bar (the current #3 among the
  frozen top-5, via `competitor_gbp_profiles` — the handoff already seeds the
  top-5 into `client_competitors`, and competitor-intel captures their GBP
  profiles). Both are recorded: (a) scores LeadOff's *estimate*, (b) scores
  the *plan's sufficiency* (did the field move faster than `rev_win` assumed
  — the momentum question).
- **Outcome fields:** `client_reviews`, `frozen_bar`, `live_bar`,
  `bar_cleared` (bool), `months_elapsed`.

### 3.2 `rankab` → the rank trackers (AVAILABLE, one instrumentation gap)

- **Maps (primary — LeadOff scores the pack):** latest `maps_scans` /
  `maps_scan_results` for the category keyword → top-3 pin share +
  `average_rank`. "Ranked" for calibration = pack presence above a threshold
  (proposal: ≥25% top-3 pin share, aligned with how the maps module reads a
  contender) at horizons 3/6/12 months.
- **Organic (secondary):** `rank_status.compute_keyword_summary` for
  "&lt;category&gt; &lt;city&gt;" among `tracked_keywords` → position ≤10 at the same
  horizons.
- **The gap (OWNER RULING 2026-07-12: keyword tracking stays manual):** the
  handoff does NOT auto-track the market keyword — the team adds tracked
  keywords deliberately, and rankability outcomes exist only where they did.
  The join matches any tracked keyword containing the category (and the city
  when present), uses whatever maps scans exist, and reports "no tracked
  keyword" / "no maps scan yet" as explicit coverage reasons rather than
  silently skipping — the calibration report shows how much of the surface
  is actually measurable.
- **Outcome fields:** `maps_top3_share`, `maps_avg_rank`, `organic_position`,
  `ranked_maps` / `ranked_organic` (bools per horizon).

### 3.3 `exp_leads` / `exp_val` → actual leads (THE HARD GAP — no automatic feed)

Candidly: **the app has no lead feed.** Nothing in the suite observes calls,
form fills, or booked jobs. Until one exists, `exp_leads`/`exp_val` outcomes
are null and the capture assumption is untunable. How it can arrive, in
order of realism:

1. **Manual monthly entry (Phase 0 ships the field, not the discipline):**
   `leadoff_outcome_checks` accepts an operator-entered `actual_leads_mo`
   (a small PATCH endpoint + a field on the Campaign Goals page). Cheap,
   honest, and it works the day someone types a number — but it depends on a
   human habit, so the error report must show entry coverage, not pretend.
2. **GBP performance metrics as a proxy** (calls + direction requests +
   website clicks): the ingestion module exists but is **dormant** pending
   Business Profile API quota (`gbp_metrics_enabled=false`). When it lands,
   `gbp_metrics` becomes an automatic lower-bound proxy for lead volume —
   labeled `leads_source="gbp_proxy"`, never conflated with counted leads.
3. **Future integrations** (CallRail / form webhooks / the PRD's
   "jobs-close-rate dial"): out of scope here; the schema reserves
   `leads_source` so they slot in without migration.

`exp_val` is derived (leads × lead_value × rankab): it is scored only when
its inputs are, and `lead_value` itself (the CSV assumption) is flagged as
untestable until real revenue-per-lead data exists — that is a *business*
input, not a scraped one.

### 3.4 `grade`/`build` → cohort-level only

A grade isn't falsified by one engagement. It's scored across engagements:
do A-grade markets outperform C-grade markets on realized rank/reviews/leads?
This is a Phase 1 report (needs N), computed from the same rows — nothing
extra to capture.

## 4. Phase 0 — instrument (what gets built after this doc is approved)

### 4.1 Capture (at the existing seam, additive)

- `leadoff_predictions` insert inside `/leadoff/create-client` (best-effort,
  same policy as competitor/goal seeding: never fails the client).
- No keyword auto-tracking (owner ruling — see §3.2).
- Migration: `leadoff_predictions` + `leadoff_outcome_checks` (below). Both
  **public schema** — nothing added to `market_scanner` (the scanner's
  toolchain is unaffected; coordination note §6).

### 4.2 Outcome join (read-only, periodic)

```sql
create table leadoff_outcome_checks (
  id             uuid primary key default gen_random_uuid(),
  prediction_id  uuid not null references leadoff_predictions(id) on delete cascade,
  checked_at     timestamptz not null default now(),
  months_elapsed numeric(5,1) not null,
  outcome        jsonb not null,   -- §3 fields, nulls + coverage reasons included
  errors         jsonb not null,   -- per-metric signed error where computable
  actual_leads_mo numeric,         -- manual entry (§3.3 path 1), null until typed
  leads_source   text              -- 'manual' | 'gbp_proxy' | future
);
```

- A monthly `leadoff_calibration_check` job (shared scheduler tick, DB-reads
  only — **$0, no paid calls**) appends one check row per prediction.
  Append-only: the trajectory is the data (a market that ranked at month 9
  after "rankab 0.45" is a different datum than one that never did).
- `GET /leadoff/calibration` — the read-only error report: per-metric
  coverage (how many predictions have a scorable outcome), error
  distributions where N permits, and per-engagement drill-down. Surfaced
  as numbers first; UI later if wanted.

### 4.3 Explicitly NOT in Phase 0

No weight changes, no capture-rate suggestions, no grade adjustments, no
automated anything that feeds back into scoring. The report may *show* that
`rankab` ran hot; nothing acts on it.

## 5. Phase 1 — calibrate (later, gated)

### 5.1 The gate (overfitting guard)

- **N ≥ 15 engagements** with ≥ 6 months tenure AND a scorable outcome for
  the specific metric being tuned (per-metric gates — `rev_win` will qualify
  long before `exp_leads` does).
- Per-category adjustments additionally need **N ≥ 5 in-category**; below
  that only global constants are candidates.
- Time-split holdout (oldest 2/3 fit, newest 1/3 validate) — with N this
  small, anything fancier is theater; the honest guard is the N gate itself.

### 5.2 What can be tuned, and what cannot

Tunable (existing constants, adjusted in place — from `report.py` /
`check_city.py` and their app ports):

- rankability weights `0.75/0.25` and scale constants `/50`, `/5`
- capture default `0.10` (global first; per-category behind the N≥5 gate)
- veto thresholds (`<5 leads/mo`, `rankab <0.15`)
- xdemand blend `0.75/0.25` (only if demand outcomes ever become scorable)

**Not tunable — the no-frankenscore rule holds:** dollars decide (`exp_val`),
percentile contextualizes (`build`), v3 compares within category. Calibration
sharpens the *inputs* to those three; it never blends them into a new score.

### 5.3 Process (proposes, never executes)

The tuner emits a **proposal** (old constant, new constant, fit evidence,
holdout error) for human approval — same posture as the strategist. On
approval the constant changes **in both toolchains in one coordinated
release** (app: `leadoff.py`/`leadoff_actions.py`; desktop: `report.py`/
`check_city.py`), and `model_version` (§2.2) stamps every prediction with
the constants that made it — so post-change predictions are never scored
against pre-change assumptions. A future single-source
`market_scanner.scoring_params` table can replace the dual-edit, but that is
a Phase 1 decision, not Phase 0 scope.

## 6. Coordination (cross-repo / cross-session)

- **No `market_scanner` tables are added or altered by this plan** — all
  Phase 0 state is app-side public schema. The scanner toolchain needs no
  change for Phase 0.
- Phase 1 weight changes ARE a shared contract (same class as the
  `demand_trend` / `biz_key` contracts): dual-edit until `scoring_params`
  exists, stamped via `model_version`.
- **Memory-file note (desktop side):** mirror into
  `market-opportunity-scanner.md`: "Calibration Phase 0 lives app-side
  (`leadoff_predictions` / `leadoff_outcome_checks`, public schema — no
  market_scanner changes). Weight constants are now a coordinated contract;
  do not tune report.py/check_city.py constants unilaterally — see
  ar-tools docs/modules/leadoff-calibration-plan-v1_0.md §5.3." (Written
  here because the cloud session cannot edit the desktop memory file.)

## 7. Owner rulings (2026-07-12 — design approved, Phase 0 unblocked)

1. **Keyword tracking stays MANUAL** — no auto-track at handoff. Rankability
   outcomes exist only where the team tracked the keyword; the report shows
   that coverage explicitly (§3.2 updated).
2. **Manual lead entry lives on the Campaign Goals page**, next to the
   LeadOff-targets goal the handoff writes.
3. **Maps "ranked" bar = ≥50% top-3 pin share** — count it only when the
   pack is substantially won.
4. **Horizons: 3 / 6 / 12 months.**
