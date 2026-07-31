# DECISIONS.md — Outreach Pipeline

Settled decisions with reasoning. **Read before proposing architectural changes.** Most things
that look open are closed. Append new entries; never edit or delete old ones.

Format: decision, reasoning, and what would need to change to revisit it.

---

## Scope and portfolio

**Portfolio: 5 verticals × 10 cities = 50 market-verticals.**
Chosen over 8 × 12 on case-study compounding, not cost — under the selection model, cost is
nearly independent of portfolio size. Concentration accumulates comparable-market proof faster,
and that proof is the largest positive coefficient in Model A once it exists.
*Revisit:* ~month 9, when slot inventory runs low.

**No scan tiering. Deep-scan the whole portfolio.**
A two-tier deep/shallow model was specified and rejected. At 100 prospect starts/month with
`slot_depth_max` = 5, 50 market-verticals is ~300 slots ≈ 900 attempts ≈ nine months of
inventory — not the multi-year backlog that would justify rationing scan depth.
*Revisit:* past ~100 market-verticals with flat contact volume.

**v1 stops at identify + score + audit + emit.** No sending, no dialing, no rendering beyond the
heatmap and PDF. Sending is a sibling module reached via webhook.

## Providers

**DataForSEO is the sole scan provider — geogrid, organic, AI surfaces.**
Governing reason is capability, not price: the pipeline needs the full pack (~20 results) at
every grid point, which is what lets one grid score an entire submarket. Per-business geogrid
tools cannot do market-wide scoring at any price. Not abstracted behind a provider interface;
entity resolution depends on `place_id` from a consistent source.
*Revisit:* see `docs/dataforseo-dependency-note.md`. Any change must be parallel-run, never cut
over — a hard switch would manufacture portfolio-wide false deltas on day one.

**Supabase for the database.** Railway, Neon, Timescale Cloud, and ClickHouse were considered.
MCP and Claude Code integration is a first-order factor under agent-driven development, not a
soft preference. 64M rows/year is not a scale problem with partitioning. Bundled RLS is needed
for client history.

**Cloudflare R2 for blobs**, not Supabase Storage. No egress fees; Cloudflare already in stack.

## Cadence and evidence

**Semi-monthly (15-day) scan interval, uniform across layers.**
Mixed per-layer cadence was evaluated and rejected: comparable cost, but it adds cadence state
that must be reasoned about on every scheduler change. Accepted inefficiency — the LLM layer at
24×/year buys extra samples but effectively no change detection, ~$16–48/yr of low-value spend
traded for one cron instead of two.

**`min_history_cycles` = 2** (30-day window before a market is workable). One geogrid is a single
sample of a system that genuinely fluctuates, and coverage is the dominant scoring input.

**`bootstrap_share` = 1.0.** Cycle one runs unrestricted on single-snapshot evidence because it
coincides with the phone-only ramp — free per prospect, and it calibrates the weakest number in
the spec (phone base rate). Bootstrap outcomes are excluded from *effect* estimates but included
in *base-rate* calibration as a conservative floor.

**Deltas compare current vs the mean of the prior two snapshots.** A 15-day consecutive
comparison is too noisy; the mean gives a ~30-day effective window with two samples of noise
reduction. Contact eligibility is 2 snapshots; delta *claims* require 3.

## Selection and scoring

**`monthly_prospect_starts` = 100, `touches_per_sequence` = 5.**
Config unit is prospect starts, not touches — "100 contacts a month" is ambiguous by a factor of
five. Tuning down is free; tuning up is one-way, because a contacted prospect who ignores a weak
pitch is unavailable for 6–12 months.

**`slot_depth_max` = 5.** Close to a wash against depth 3 on expected slots filled (2.3 vs 2.4);
the real trade is coverage breadth versus market depth.

**MMR λ = 0.5 at launch, scheduled to 0.6 then 0.8.** Diversification is insurance against the
model being wrong, which is worth most when it is entirely unvalidated. Gated on refit
milestones, never elapsed time.

**`λ_shrink` = 0.5, and it is not a ranking parameter.** Uniform multiplier, therefore a
monotonic transform — rank order is mathematically unchanged. Stage 2 recalibration exists to
correct it. Do not tune it to improve results.

**Flat pricing; Model C value layer inert.** At a 1.67× retainer spread, expected-revenue ranking
has nothing to optimise. Operative ranking is `p_reply × p_close`. R and T machinery retained
unused as constants.
*Revisit:* ~month 9, if AR decides to price larger prospects higher.

**Per-channel Model A base rates.** Email 5.5% (offset 705.0), phone 25% (offset 579.3). These
measure different events, not the same event at different rates — refits must be per-channel or
carry channel as an explicit level.

**Franchise pattern matches flag for review, never exclude.** A false positive is a permanently
lost prospect. This also makes the −87 franchise coefficient meaningful; under hard exclusion it
could never fire.

**`likely_represented` keeps its −21 penalty.** Vendor-failing suppresses it in the case that
matters; what remains is prospects whose agency is not visibly failing, who genuinely are harder
to reach and close.

## Channels

**Channel split ramps 100/0 → 50/50 → 30/70**, gated on `email_track_ready` (vendor compliance,
SPF/DKIM/DMARC, warming complete, inbox placement verified). Never on elapsed time.

**Phone track ships first** despite carrying 30% of steady-state volume. It needs no enrichment,
costs nothing per prospect, and exercises the whole pipeline on real conversations before any
per-record spend.

**A prospect is never active in both tracks simultaneously.** Confounds measurement, poor
recipient experience. Sequential fallback is permitted and counts as one sequence.

## Storage

**Partition `grid_result` by month; retention via DROP PARTITION, survivors relocated.**
Composite partition key was rejected — cleaner at drop time, but adds a column to every query
touching the table forever.

**90-day hot window**, scheduled to drop to 45 once rollup logic is validated. The hot window is
~1.9 GB of the ~2 GB steady state and exists purely as insurance against rollup logic changing.

**Staged blob offload.** Payloads land in Postgres and migrate to R2 on schedule. Direct-to-R2
couples scan success to object-store availability.

**Drop lat/lng from `grid_result`.** Derivable from snapshot geometry plus `point_seq`.

## Reporting and CRM

**Asset generation is approval-gated.** Never triggered by cycle completion or emission.
Send-time LLM verification and evidence randomization both occur at generation.

**Prospect URL expiry 30 days**, deliberately aligned with `max_evidence_age_days` — the link
dies exactly when the evidence behind it would no longer be emittable.

**Client reporting: PDF now, dashboard later.** Client views and RLS policies are built now
regardless, so the dashboard is a UI layer over a tested read surface.

**CRM owner is an `auth.users` reference.** Per-owner RLS policies written at launch however
permissive — retrofitting RLS onto live tables is where disclosure bugs come from.

**Pipeline stages collapsed:** `qualified` + `proposal` → `in_conversation`. Substages, if ever
needed, become activity rows — never enum additions.

**Nurture re-entry is manual only.** Automatic risks re-contacting someone who already declined.

---

## Phase 1 build decisions (2026-07-31)

**Code lives at `outreach/` in the `kssabraw/ar-tools` repo; database is a SEPARATE Supabase
project.** The storage profile (~2 GB steady, ~550 MB/yr) would eat the shared AR Tools project's
headroom, and the two systems share no tables. Placed at the repo root rather than under
`writer/` because `writer/` is the AR Tools suite backend against the AR-Internal-Tools project —
a migration dropped into `writer/supabase/migrations/` by muscle memory would hit the wrong
database. Trivially movable if that reads as clutter.
*Known cost:* a separate project means a separate `auth.users` pool, which `lead.owner_id`
depends on. For a small team that is a handful of accounts, but do not expect SSO with existing
AR Tools users.

**Review recency (the 9-month rule) is DEFERRED to Phase 5, not paid for in Phase 1.**
Review timestamps are not in the Outscraper base pull; they need a separately billed
`/maps/reviews-v3` call. Two reasons to defer, the second being the stronger one:
1. Phase 1 contacts nobody. A blunt filter costs nothing when no enrichment or outreach follows
   it — dormant businesses just sit in the table. The filter only starts mattering at Phase 5,
   when it gates spending.
2. By then there will be multiple listing pulls, which means review VELOCITY is computable — the
   relative mode the brief itself calls "more correct" but deferred for want of history. A
   commercial plumber can be busy and profitable with near-zero consumer review flow, so an
   absolute 9-month window would exclude exactly the wrong businesses. Deferring buys the better
   rule for free.
The rule stays in config, disabled, and still writes an honest `filter_result` row
(`passed = true`, `observed_value = 'not_evaluated'`) so the audit trail is explicit rather than
silently absent.
*Revisit:* Phase 5, implemented as velocity rather than an absolute window.

**`suppression` is created empty by the Phase 1 migration.** A `to_regclass()` guard is uglier
than four columns, and it means the Phase 1 check is a real query rather than something
retrofitted later. It stays owned by `docs/crm-layer-spec.md` (Phase 1b).
*Coordination:* whichever migration runs second must use `IF NOT EXISTS`. Note this is NOT a
merge — `IF NOT EXISTS` silently keeps whichever shape was created first and no-ops the other.
If the CRM spec's shape differs, reconcile it explicitly with `ALTER TABLE`.
`services/suppression.py` reads the table defensively and degrades to an empty index if the
columns are not what it expects, which is safe in Phase 1 only.

**`cost_ledger` stores `units x configured rate`, not provider-reported cost.** Brief §4 asks for
"real reported cost" and §5 for 5% dashboard reconciliation; the Outscraper API does not appear
to return a per-request cost, so that is unmeetable as written. Relaxed to manual reconciliation
against the dashboard once per cycle rather than building something elaborate to chase an
unachievable check. This makes `outscraper_cost_per_1000_places_cents` load-bearing — the abort
gate is exactly as honest as that number.

**`phone_type` is always `'unknown'` in Phase 1.** Carrier/type comes from Outscraper's
`phones_enricher_service`, an enrichment, which the brief's own "base tier only" rule puts in
Phase 5. The brief contradicted itself; the column stays, the signal does not exist yet.

**`prospect.submarket_id` is assigned by nearest submarket centroid, not by discovering tile.**
Tile order is an implementation detail — a place returned by three overlapping tiles would
otherwise get whichever was polled first, and re-running the ingest could reassign it.
Nearest-centroid is deterministic and depends only on geometry, which is immutable.

**Franchise matching is non-exclusionary by construction, not by convention.** The rule is
declared outside `NON_EXCLUSIONARY_RULES` in `services/filters.py` and the exclusion verdict is
derived from that set, so no caller can turn a flag into an exclusion by adding a branch.

**Markets are defined in checked-in JSON, not hardcoded.** `outreach/markets/<slug>.json` per
market-vertical, applied idempotently by `services/seeding.py` via
`python -m api.scripts.run_market seed`. Adding the tenth city is the same act as adding the
first, and definitions are reviewable in a diff. The pipeline was already multi-market — every
table keys on `market_id` — but there was no repeatable way to DEFINE one, which made it look
like a single-market tool.

**The geometry immutability invariant is enforced in code, not just documented.**
`seeding.check_geometry_change` refuses any centre/radius/spacing change to a submarket with
`last_scanned_at` set, and there is deliberately NO override flag that unlocks a scanned one —
the correct move is a new submarket, which starts its own history, rather than an edit that
silently orphans prior snapshots. Changing an UNSCANNED submarket is permitted but requires an
explicit `--allow-geometry-change`, so it cannot happen by accident during a routine re-seed.
Names are always editable.

**`categories` and `keyword` are kept separate in the market definition** even though the strings
often coincide. Categories drive the Stage A1 Outscraper listing pull; keywords drive Phase 2
SERP and geogrid scanning. Conflating them costs nothing today and would be painful to unpick
once both are in use.

**Los Angeles x Plumber is the first market-vertical.** One category, per the brief's definition
of a market-vertical ("one business category in one city"). 14 submarkets at a 5-mile radius over
the LA basin — the city plus inner metro (San Fernando Valley, San Gabriel Valley, South Bay,
Long Beach). Every submarket has a neighbour within 10 miles, so with 5-mile radii the whole set
overlaps, which is the only coverage insurance available given I-017. Deliberately NOT all of LA
County (4,751 sq mi); the covered area is what a local SEO client would plausibly serve. If that
proves too narrow, add submarkets rather than widening radii — radius is grid geometry and
freezes at the first scan, whereas a new submarket starts its own clean history.
*Still editable:* nothing has been scanned, so these centroids can move freely until Phase 2.

**Default to `GET /maps/search-v3`, with `POST /google-maps-search` available via config.**
Both endpoints are live. The first is proven against THIS Outscraper account by platform-api's
`gbp_service`, which has used it in production for months; the second is what the vendor's
current SDK uses but is unproven here. With no way to test either from the build sandbox
(I-027), running-in-production evidence against the same account and key is the stronger signal.
Reversing is a one-line config change and both request shapes are regression-tested.
*This reverses my earlier "the brief is stale" claim — see ISSUES I-029.*

**Consult the AR Tools repo before vendor docs for provider behaviour.** It already integrates
Outscraper, DataForSEO, Google and others against these accounts, so it carries verified
request shapes and response field names that no amount of documentation reading would have
settled — and in this case contradicted a conclusion I had drawn from the vendor's own SDK.
