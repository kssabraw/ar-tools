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

---

## The outreach pipeline is an AR Tools module (owner ruling, 2026-07-31)

**Amends the Phase 1 build decision, which is not withdrawn.** That decision said the code lives
in the `kssabraw/ar-tools` repo while the database stays a SEPARATE Supabase project, and it
recorded a cost: *"a separate project means a separate `auth.users` pool… do not expect SSO with
existing AR Tools users."* The storage half of that reasoning stands — outreach's ~2 GB steady
state and ~64M `grid_result` rows a year would eat the suite project's headroom, and the storage
spec sized partitioning for a dedicated project.

What was wrong was the inference, not the decision. A decision about where the *data* lives got
allowed to determine where the *application* lives, and those are separable.

**So: the database stays here; the API and UI move into the suite.** platform-api gains an
`outreach` router backed by a project-scoped Supabase client, and the suite SPA gains the pages.
There is precedent for reading a foreign data source this way — LeadOff reads the
`market_scanner` schema through `services/leadoff_db.py`, and the Fanout backend is vendored and
mounted under a path prefix — though both of those stay inside one Supabase project, and this is
the first reach into a second.

**This dissolves the SSO cost rather than paying it.** platform-api holds the Outreacher service
role and is the only client, so staff authenticate against the suite exactly as they do for every
other module and never need an Outreacher account. That is why the identity FKs are dropped: they
pointed at a `auth.users` pool that will now stay permanently empty (ISSUES.md R-011).

**Consequences that follow, and are not optional:**

- **Retool is dropped**, and with it the per-user RLS model built for it. §8a's instruction to
  write per-owner policies at launch was aimed at a direct database connection; there is no longer
  one. The policies are removed rather than left in place, because a permissive policy on a table
  nothing reaches through PostgREST is not "safe, tighten later" — it is an access model that
  looks load-bearing and is not. RLS stays enabled with zero policies, which is the posture of
  every other table in the estate.
- **Authorization moves up** into platform-api, beside the suite's existing role checks.
- **No cross-database joins.** A won lead becomes an AR Tools client through an API call, not a
  foreign key. Worth knowing before someone designs a report that assumes otherwise.

*Revisit:* if outreach ever needs to join prospects to suite clients in SQL rather than in
application code, or if the storage argument stops holding.

## Implementation — Phase 1b (2026-07-31)

**The CRM tables carry real RLS policies. Every other table in the estate carries none.**
Not drift. The rest of the estate sits behind a service that holds the service role and does its
own auth, so a policy there would be unreachable code. The CRM tables are read **directly by a
low-code UI over PostgREST** — when the client is the database's own REST layer, the database has
to be the thing that says no. The trap this guards against: a Retool *Postgres* resource
connecting as `postgres`/`service_role` bypasses RLS entirely, leaving every policy sitting in the
schema looking correct and doing nothing. That failure is invisible in a schema diff. The
connection MUST therefore be a **Supabase/REST resource with per-user JWTs** — load-bearing, not a
preference. Policies start permissive per §8a.

*Superseded the same day by the suite-module ruling above.* Retool never connected, so the
policies were dropped rather than tightened, and the six `rls_policy_always_true` warnings this
entry once predicted would be permanent are gone with them. The entry is kept because the trap it
describes is real and independent of Retool: a Postgres-type connection authenticating as
`postgres` or `service_role` bypasses RLS entirely, leaving every policy in place and enforcing
nothing. That will apply again the next time anything is pointed straight at a Supabase database.

**`outcome`'s outbound-only rule is keyed on `(prospect_id, source)`, not on `prospect` alone.**
Phase 1b ships `lead.unique (prospect_id, source)` as the FK target and hands the enforcing DDL
to Phase 3 (`PHASE3-outcome-constraint.md`); it creates neither `outcome` nor `touch`. Keying on
prospect alone — the §10 shape — leaves the rule as a convention a trigger remembers, because a
**promoted inbound lead also carries a `prospect_id`**, so nothing in the schema would object to
an outcome attached to one. Since `lead.prospect_id` is already unique the composite costs
nothing and makes the violation unrepresentable. Verified live against the real key with a
throwaway probe table: outbound accepted, inbound-with-a-prospect_id rejected by FK, and
reclassifying a lead that already has an outcome blocked through `on update cascade` — that last
being the back door a plain FK would leave open.

**Revoke before granting on any table PostgREST can reach.**
Supabase's default privileges already grant ALL on new `public` tables to `anon` and
`authenticated`, so a bare `grant select, insert` adds nothing and removes nothing — it reads
like a restriction while leaving UPDATE, DELETE and TRUNCATE in place. Two consequences, both
caught in verification: append-only on `lead_activity` was resting on the *absence* of an update
policy, and an UPDATE with no matching policy is not an error but a silent zero-row no-op; and
TRUNCATE is not subject to RLS at all, so no policy can stop a role that holds it. The failure
mode is a silent wrong outcome rather than a refusal, which is the kind that survives review.
## Phase 2 foundations + suite router (2026-08-01)

**The grid holds 81 points. "89" was an arithmetic estimate, not a design.**
`reporting-layer-spec.md` §4.1 is the only document that defines the generator, and it is
unambiguous: *"Square lattice covering the bounding box, row-major from NW corner, clipped to
distance <= radius_miles from centre."* At a 5-mile radius and 1-mile spacing that construction
contains exactly **81** points — by row from the north, 1, 7, 9, 9, 9, 11, 9, 9, 9, 7, 1.

The alternatives were computed rather than assumed: a hexagonal lattice at the same spacing gives
**91** (and π·25·2/√3 = 90.7 is the likeliest origin of a remembered "89"), concentric 8-point
rings give **41**, the unclipped 11×11 bounding box gives **121**. Nothing produces 89. The PRD
itself hedges it as "~89"; only `README.md` stated it flatly.

The deciding argument is that **the count is not a parameter.** It is an output of (radius,
spacing, lattice, clip), and the specs fix all four. Choosing 89 would have meant changing one of
the four to hit a number, which is backwards. Hexagonal is the one genuinely defensible
alternative — it covers a disc more evenly — but adopting it would contradict the spec that owns
`point_seq` ordering, and ordering is the property the whole storage model rests on.
*Revisit:* only before the first scan. `submarket.last_scanned_at` is null everywhere today, so
this is still free; it stops being free the first time a geogrid runs. Raised with the owner and
implemented on the spec-literal reading in the absence of a contrary instruction — flagged rather
than assumed settled.

**The geometry generator is a version REGISTRY, not a version string.**
`_GENERATORS = {"v1": ...}` keeps every shipped generator callable forever, and an unknown
version raises instead of falling back to the current one. A bare version constant that labels
whatever the code currently does is not a pin: change the ordering, bump the label, and every
historical `rank_vector` is decoded against coordinates that were never used to collect it —
silently, with the heatmap still rendering and every number still plausible. Falling back on an
unknown version would produce a picture instead of an error, which is strictly worse than
crashing.

**The clip measures flat mile offsets, not great-circle distance.**
The coordinates come from the spec's flat 69-miles-per-degree approximation, so the flat offsets
*are* the distances that approximation implies. A more accurate distance would disagree with the
lattice that produced it and could flip a borderline point — and a flipped point does not merely
change the count, it renumbers every `point_seq` after it. Reproducible beats accurate here.
This grid is unusually exposed to that: the 3-4-5 Pythagorean triple puts **12 of the 81 points
exactly on the boundary**, so a strict `<` would shave 15% off the grid rather than one point.

**No DEFAULT partition on `grid_result` / `serp_result`.**
A default partition never loses a row, which reads as the safe choice. It has a long-fuse trap:
once a month's rows land in it, that month's partition can never be attached until every one of
them is moved out — surfacing months later, on a table too large to reorganise casually. Without
one, an insert for an uncovered month raises immediately. The trade follows the storage spec's own
governing principle: `grid_result` is the *replaceable* data, recoverable by rescan for cents,
whereas an un-attachable partition is not recoverable without a maintenance window.
`create_month_partitions()` runs two months ahead and is idempotent, so a writer can also call it
defensively before a batch.

**`serp_result` is partitioned now, `prospect_coverage` is populated later.**
Both are empty and neither has a writer, so the "build it before cycle two" rule is satisfiable
either way — but the two are not symmetric. Partitioning `serp_result` costs three lines today
and a table rebuild later, so it was done. The coverage ROLLUP is the opposite: `rank_vector`
ordering depends on the geometry generator and on land masking that does not exist yet, and a
rollup written blind would emit vectors that render every historical heatmap against the wrong
coordinates while looking entirely healthy. `prospect_coverage` is created (the storage spec owns
it) and `rollup_coverage()` is deliberately not written. `drop_cold_partitions` refuses to drop
any partition whose snapshots lack a rollup, so the absence fails closed and costs nothing until
there is something to drop.

**`drop_cold_partitions` fails closed on every table that does not exist yet.**
`audit_asset` (§3.3 citation guard) and `slot` (§3.4 client guard) arrive in later phases. Each is
checked with `to_regclass(...) is null` explicitly, logging a sentence, rather than being allowed
to raise or — far worse — being skipped as "not applicable yet". Until those tables exist the job
drops nothing at all, which is correct: retaining a partition too long costs disk, dropping one
whose citation table did not exist yet costs a dispatched claim with no evidence behind it.

**The suite router reaches a second PROJECT, which is new here.**
`services/leadoff_db.py` was the stated pattern, but it scopes a client to a second SCHEMA inside
the same project. Outreach needs a second URL and a second service-role key, so
`services/outreach_db.py` diverges: no `ClientOptions(schema=...)`, and an explicit
`outreach_configured()` predicate so an unprovisioned deployment answers `503
outreach_not_configured` instead of failing inside the first query. Env vars are deliberately
named `OUTREACH_SUPABASE_URL` / `OUTREACH_SUPABASE_SERVICE_ROLE_KEY` — identical to what the
outreach Railway job already uses, carrying identical values.

**Aggregation for the suite happens in Postgres, not in platform-api.**
`v_prospect_status` and `outreach_market_summary()` were added to the Outreacher project rather
than computing the funnel in Python. Two reasons, the second stronger: storage spec §9 requires
it, and PostgREST silently caps an unbounded `select()` at 1,000 rows — with 8,328 `filter_result`
rows already present, a Python-side funnel would have been wrong on day one in exactly the way
ISSUES I-036 describes, reporting a confident undercount with no error anywhere.

**The per-rule summary reports `not_evaluated` as a third number, not folded into `passed`.**
`filter_result.passed` is `not null boolean`, so a rule that did not run says so through
`observed_value` (I-016). Reporting two numbers instead of three would state that all 1,388 LA
businesses have a recent review when not one was checked. It immediately earned this: the live
summary shows **113 prospects whose review count was never evaluated** because Outscraper returned
none — invisible in a pass/fail pair, and 113 of the 925 "survivors" (ISSUES I-041).

**Stage-change activity rows stay trigger-owned; the API supplies the actor.**
Under the module ruling platform-api connects with the service role, so the `lead_log_changes`
trigger's `auth.uid()` is always NULL and the audit trail would have been anonymous (I-040). The
fix adds `lead.updated_by` and has the trigger prefer it. Moving the activity write into
platform-api instead — now that it is the only writer — was rejected: the trigger is what makes
the audit trail structural rather than conventional, so a stage corrected by hand in SQL still
gets logged. Losing that to gain an actor id is a bad trade when a column buys both. The router
therefore never writes `stage_change` rows, and refuses them over the API, so one event can never
produce two rows in an append-only table.

---

## Grid geometry confirmed: 81 points (owner ruling, 2026-08-01)

**`grid_radius_miles` = 5, `grid_spacing_miles` = 1, 81 points per submarket × keyword.** This
supersedes the "decided from the specs, awaiting confirmation" status recorded earlier the same
day. It is now a ruling, and it freezes at the first scan.

**The count was challenged on arithmetic first** — "5-mile radius, one point per mile, isn't that
25?" It is not, and the reasoning is worth keeping because the mistake is a natural one: a 5-mile
*radius* spans 10 miles, so a row holds **11** points (5 west + centre + 5 east), the bounding box
is 11 × 11 = 121, and clipping to the circle leaves 81. 25 would require ~1.67-mile spacing; a 5×5
box at 2.5-mile spacing clips to 13, because the corners of a square fall outside the inscribed
circle.

**Then on cost, which is the substantive version of the question.** The point count is an output
of radius and spacing, both per-submarket config, so it is a real lever: 81 → 49 at 1.25-mile
spacing, 25 at 1.67, 21 at 2. Across the 50-market portfolio that is 2.92M DataForSEO tasks a year
versus 756k. Declined, for three reasons:

1. **81 is not an overrun — it is the budgeted figure.** The specs costed the geogrid at ~89
   points, so 81 is marginally *cheaper* than the estimate already sitting behind
   `max_market_run_cost_cents` = 5000 and the ~$3–6 per market-vertical per cycle figure. Nothing
   about this number is a surprise to the cost model.
2. **Coarser spacing degrades the product, not just the resolution.** `centroid_dist_at_loss` and
   the "invisible past N miles" claim (PRD §9a) are derived from *where on the grid* a business
   drops out. At 2-mile spacing there are ~2 usable rings, and that claim degrades from a distance
   into a direction — which is the single most persuasive line the audit produces.
3. **If cost ever binds, the right lever is elsewhere.** Fewer keywords or fewer submarkets per
   market scale spend linearly without damaging the signal each individual scan yields. Cutting
   points makes every scan worth less; cutting scans makes fewer scans.

*Revisit:* not for an existing submarket, ever — geometry is immutable and an edit orphans every
prior snapshot. A future market-vertical could in principle be seeded at different spacing, but
mixing geometries across the portfolio would make coverage percentages non-comparable between
markets, which is worse than the cost it saves.

---

## DataForSEO task collection: `tasks_ready` polling, not postback (owner ruling, 2026-08-01)

**Corrects the PRD.** §B2 said "MUST batch task submission (up to 100 per POST) and use
postback/pingback, not polling." That was over-specified, and the correction matters because the
original wording made the outreach service's *shape* look negotiable when it is not.

**Postback does not remove the need for `tasks_ready`.** A callback that does not receive a
response within 10 seconds is transferred to the Tasks Ready list anyway, so a collector is
required as reconciliation whichever mechanism is chosen. Postback therefore *adds* a mechanism
rather than replacing one — and the added mechanism is the expensive kind: it would force a cron
job into being a service with a public domain and a live receiver, listening around the clock for
callbacks that arrive twice a month. All of that to still need the collector.

**The service stays a cron job.** No public domain, no receiver, no shape change. It gains a
second schedule, not a second nature.

Shape, as ruled:

1. **Submission run** — `task_post` batched at 100/POST; every returned task id persisted
   immediately with `status = 'submitted'`, before anything else happens.
2. **Collector run on its own frequent tick** (hourly or daily) — `GET tasks_ready`, `task_get`
   each, store, mark collected, **loop**: the list caps at 1000 and will not reveal the rest until
   the current batch is collected.
3. **Fallback by id** — an id uncollected after ~3 days has aged off the ready list, but results
   are retained 30 days and remain retrievable directly.
4. **Alert** past ~5 days uncollected.

**The cadence constraint is the load-bearing part.** The collector must run far more often than
the 15-day scan cadence. A collector on the scan schedule would let every task age off the ready
list between runs, silently converting the normal path into the fallback path — which still works,
which is exactly why it would go unnoticed.

`tasks_ready` is free; only `task_post` bills. So collection frequency costs nothing, and there is
no reason to be sparing with it.

*Revisit:* only if DataForSEO changes the ready-list retention or the 1000-entry cap. Note that
adopting postback later would be additive and would not let the collector be removed.

**Credentials added the same day** as Railway reference variables —
`OUTREACH_DATAFORSEO_LOGIN = ${{PLATFORM.DATAFORSEO_LOGIN}}`, same for the password. References
rather than copies for two reasons: the secrets never pass through a chat transcript (the
Outscraper and Supabase keys did, and are flagged for rotation), and a rotation on PLATFORM
propagates automatically. Nothing is wired to them yet.

## `actual_points` counts points SCANNED, never grid rows written (2026-08-04)

The completeness gate (PRD §9a.3) compares `actual_points` to `expected_points` and excludes a
snapshot below 98% from scoring. The obvious implementation — count the distinct `point_seq`
values that produced `grid_result` rows — is wrong, and wrong in a way that gets worse the more
honest the market is.

A grid point can legitimately return an empty pack. Some sit over water, some over a stretch with
no business of that category, some over an industrial block. **"Nobody ranks here" is a finding,
and frequently the strongest one in the whole grid** — it is the shape of the coverage deficit the
entire pitch is built on. Counting rows classifies every one of those as a missing measurement, so
a submarket with real dead zones reads as a failed scan *every cycle*, is excluded from scoring
forever, and the exclusion looks like a provider problem.

So the count comes from `scan_task.status = 'collected'`, which records that a point was measured
regardless of what the measurement found. There is deliberately no `empty` status: an empty answer
is a collected answer.

This is the same correction the rollup's completion marker needed on 2026-08-03 (ISSUES I-069),
where the guard compared distinct prospect ids against coverage rows and would have raised forever
because most businesses in a grid are not prospects. Twice now the mistake has been counting *what
was found* where the question was *what was measured*. Recorded as a decision rather than a bug fix
because the next reader will meet it a third time.

## The `task_post` tag is a recovery key, not a debug label (2026-08-04)

The suite's `maps_dataforseo.py` sends a tag and explicitly treats it as a convenience: it aligns
responses positionally and only *logs* a tag mismatch. That is sound there, because that code polls
task ids it holds, and its tags are not unique across keywords.

Here the tag is `<snapshot_id>:<point_seq>`, it is unique, and it is load-bearing for two things
positional alignment cannot do:

1. **Matching a `task_post` response.** Nothing in the provider's contract guarantees response
   ordering. Using the tag removes the assumption rather than checking it.
2. **Recovering a paid task whose id we never stored.** The dangerous window is a request the
   provider accepted — and billed for — whose response never reached us. Rows are written before
   the post so that window is as small as possible, but it cannot be closed from our side. The tag
   closes it from theirs: the provider echoes it on `tasks_ready`, so the collector can reattach
   the result to its point without ever having known the id.

The difference in posture follows from the difference in mechanism. The suite polls ids it holds,
so a lost id is one lost pin. This collector discovers work from an account-wide list, which is
exactly what makes recovery-by-tag possible — and therefore worth designing for rather than
treating as a log line.

*Consequence:* the tag format is now part of the wire contract. Changing it orphans any task in
flight, which is a real cost for ~3 days after any submission.

## The coverage rollup is ONE SQL function, and geometry arrives as a parameter (2026-08-05)

Two decisions, taken together because each forces the other.

**One transaction, therefore one plpgsql function.** The requirement is that `rank_vector` is
written in the same transaction as the summary statistics, and that a rollup producing summaries
without vectors FAILS rather than partially succeeding (owner instruction, 2026-08-03). A vector
written later, or in the wrong `point_seq` order, renders every historical heatmap against
coordinates that were never used to collect it — silently, with the picture still drawing and every
number still plausible.

PostgREST gives one transaction per call. So the obvious Python shape — insert the coverage rows,
then call `finalize_snapshot_rollup()` — cannot hold both halves together: the rows commit, the
finalizer raises, and the partial rollup survives as exactly the thing I-069 was built to catch.
Everything therefore happens inside `rollup_snapshot_coverage()`, whose last statement is the
finalizer. This also satisfies storage spec §9, which requires coverage aggregation to run in
Postgres rather than by pulling ~1,600 rows per snapshot into the application.

**Geometry is passed in, not re-derived in SQL.** The rollup needs a distance per `point_seq` for
`centroid_dist_at_loss` and needs to know how long a vector is. Both are properties of the lattice,
which lives in `api/services/geometry.py` as a version REGISTRY — and that module's own docstring
explains why a second derivation is dangerous: two implementations eventually disagree about a
boundary point, and a point flipping in or out renumbers every `point_seq` after it.

Re-implementing the lattice in SQL would create that second definition. Persisting distances into a
table would create a cache that can go stale against a version bump. So the caller regenerates
through the registry — using the snapshot's STORED `geometry_version`, never the default — and
passes `[{"seq": n, "dist": miles}, ...]`; the function validates that it covers `0..expected-1`
exactly and that the version matches the snapshot, and refuses otherwise.

*Consequence, and it is a real one:* storage spec §7 asks for a daily `rollup_coverage` **pg_cron**
job, and that is now unbuildable — pg_cron cannot call the Python generator. See the next entry.

## The rollup rides the collector's tick rather than taking a third schedule (2026-08-05)

Given the above, the rollup must run from the Railway job. The choice was a THIRD cron schedule or
attaching it to an existing one.

HANDOFF §11 already records that the collector's second schedule is the one most likely to be
skipped and the most expensive to skip. A third would be worse, and its failure mode is quiet: no
rollup means no completion markers, which means the retention job drops nothing, which means the
storage ceiling this whole policy exists to avoid arrives on schedule while every run reports clean.

So `collect` rolls up the snapshots it has just finalized — the only moment new work exists — and
`rollup` also stands alone for backfill and for re-running one snapshot after fixing it. The
integration is guarded and reported, never raised: collection is the paid work being rescued, and a
rollup failure must not cost a collected task. `--no-rollup` exists for isolating a collection
problem, not for routine use.

`rollup` is FREE and must stay out of `PAID_COMMANDS` — same reasoning as `collect` (HANDOFF §8a).
Spend-gating it would make every routine deploy's tick refuse for want of a confirmation token, and
the backlog would stop draining silently. There is a test asserting this.

## The coverage denominator counts points MEASURED — the third time (2026-08-05)

`live_points` reads `scan_task.status = 'collected'` intersected with `grid_point_status.land`. It
does not read `grid_result`, which can only record what was found.

Three consequences, each the opposite of a plausible alternative:

- A point that returned an **empty pack** stays in the denominator. It was measured; "nobody ranks
  here" is a finding, and usually the strongest one in the grid.
- A point whose task **never collected** leaves the denominator entirely. It is not an absence
  anybody observed, and counting it as one manufactures pain out of a provider failure.
- A **masked** point leaves the denominator but stays in the geometry and in the vector as `255`,
  because the renderer must draw dead differently from not-found. Conflating them overstates pain
  in the direction a prospect can catch.

This is the same correction as `actual_points` (2026-08-04) and as I-069's completion marker
(2026-08-03). Recorded a third time because it has now been the wrong answer three times in three
different places, and the next place it comes up will be the placeholder score.
