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

## The placeholder score is a view over coverage, not a row in `prospect_score` (2026-08-05)

The checklist calls for a placeholder score and the model's table is sitting right there. Using it
would have meant claiming a `model` from an enum with no honest value, an invented `lambda_shrink`,
and a `score_factors` that cannot satisfy its own replayability invariant.

The decisive argument is not tidiness. `v_prospect_ranked` already selects
`prospect_score where pass = 2 and model = 'value'`, so a placeholder in that table is not inert —
it is picked up as a fitted score by a query written before it existed, and the refit that replaces
it has no column to distinguish the two. A view has none of that reach and is removed in one line.

Recorded as a decision rather than an implementation note because the pull toward the existing
table will recur every time something needs a score before Phase 4 — and the answer is the same:
if the placeholder ever needs persisting, it gets a home that admits what it is.

*Consequence:* the placeholder gates on `snapshot_rollup`, the completion marker — not on
`scan_snapshot.complete` and not on "a snapshot exists". An incomplete snapshot has no coverage
rows, so gating on existence would score every prospect in that submarket at maximum deficit
because the scan failed. That is the measured-vs-found error again, in its fourth costume.

---

## 2026-08-06 — The UI triggers scans; the confirmation moves from config to a signed order (owner ruling; resolves I-072, supersedes §11a's default)

Owner ruling: the module gets a UI, and not a read-only one — it must start scans. §11a said a
trigger button "is an architectural change, and it needs deciding rather than assuming"; this is
that decision, made by the person entitled to make it. The recommendation on record (run the
first scan before adding a sixth unrun layer) was presented twice and overruled; the first scan
will now also exercise the trigger path it arrives through. That cost is accepted, not unnoticed.

**The constraint that shapes everything:** a button has no honest way to reach the deploy path.
The spend gate (§7.2) works because `OUTREACH_CONFIRM_SPEND` rides a deliberate deploy; no MCP
tool can create a fresh deployment for an existing service, platform-api must not run scan code
(it is the reader over this database, and the scan client lives in the outreach image), and
having the UI drive Railway's API would re-create the ~$0.11 incident with extra steps.

**So the confirmation changes carrier, not principle.** The gate's principle is: money moves only
on evidence the accidental path cannot supply. For config-driven runs that evidence is the
name-matched env token, unchanged. For UI-triggered runs it becomes a **`scan_request` row** — a
signed order carrying the exact submarket × keyword, the requesting AR Tools profile id, and a
consumed-on-execution lifecycle. An order is *stronger* evidence than the token: single-use,
named, attributed, and impossible for a replayed deploy, a leftover variable, or an unrelated
merge to manufacture. What it is weaker against is a compromised or careless admin account —
which is the same trust the token already places in whoever holds the Railway dashboard.

**The shape:**

- platform-api: `POST` creates an order (admin-gated, one active per submarket × keyword),
  `GET`s list orders/status/results. platform-api itself still cannot spend — it writes a row.
- outreach service: a new **`tick`** command = `collect` + drain **at most one** pending order.
  The frequent cron §11 already demanded for collection now runs `tick` — double duty, no new
  schedule. Click-to-scan latency is one cron interval; the UI says so instead of pretending the
  button is instant.
- `tick` is NOT in `PAID_COMMANDS`. Its spend is gated per-run by the order row. `collect` stays
  free and never drains — §8a's invariant and its test are untouched. `scan` keeps the env token
  for CLI/emergency use, exactly as today.
- The one-submarket ruling survives structurally: an order IS one submarket × one keyword, and
  the drain takes one per tick. A market sweep remains impossible from the UI in v1.
- `submit_scan` gains the `cost_ledger` write it never had (closes I-086), on both paths — a UI
  that spends money must show the ledger, and the sweep gate (`max_market_run_cost_cents`) is
  checked before the drain posts anything.

**Rejected:** draining from `collect` (makes the one command every doc promises is free into one
that can spend); platform-api executing scans (duplicates the client, splits the spend gate
across two services); triggering Railway deploys from the API (no supported path, and the config
snapshot semantics that already cost money twice).

---

## 2026-08-06 — Hand-picked leads ARE `outbound_scan` (owner ruling)

Asked while scoping the CRM board, because the docs reserved `outbound_scan` for Phase 3's emit
webhook and a human clicking "Send to CRM" on a scan-results row is neither automated nor
emitted. The owner's answer: **hand-picked leads count as outbound.**

What this settles: a lead promoted from a prospect carries `source = 'outbound_scan'` +
`prospect_id`, exactly like an emitted one will — it is factually a lead sourced from the scan,
and `source` records provenance, not automation. The `lead.unique (prospect_id, source)`
constraint therefore also dedupes hand-picks against future emits for the same prospect, which
is the correct collision: the emit path finding the lead already exists means a human got there
first, not an error.

What this deliberately does NOT settle: `outcome` rows. Phase 3's emit writes an `outcome` per
emitted prospect; a hand-picked lead has no emit event, so nothing writes its outcome row today.
`PHASE3-outcome-constraint.md`'s FK targets `lead (prospect_id, source)`, so outcomes can attach
to these leads retroactively when Phase 3 lands — whoever builds it must decide whether the
emit-time write also backfills outcomes for pre-existing hand-picked outbound leads, or the
model simply doesn't see them until they are re-emitted. Left to Phase 3, where the emit
machinery gives the question a concrete shape.

---

## 2026-08-07 — Phase 3 is sliced, the heatmap renderer ships first, no map background in v1

Phase 3 (reporting-layer-spec) is ~six discrete pieces: the heatmap renderer, the call hook, the
`outcome`/`touch` tables + emit webhook, the approval gate + audit PDF, signed-URL sharing/R2, and
client views/RLS. It ships as **separate reviewable draft PRs, renderer first**, rather than one
Phase-3 PR — matching how every prior phase here was merged, and letting each paid-data-dependent
piece land after the first scan makes its behaviour observable.

**Why the renderer first.** It is spec §4's "only genuinely new component" and the keystone the
audit PDF, the delta view and the client report all render through. It is also the one piece that
is fully **deterministic** and therefore golden-fixture testable with no live data, no provider
call and no money — so it is buildable and provable in parallel with the owner's first scan, and
is *ready* the instant that scan's rollup writes `prospect_coverage`. The emit webhook, `outcome`
table and approval gate all want real scanned prospects to be validated against, so they wait.

**No map background in v1.** Spec §4.5 makes a map background the DEFAULT for prospect-facing
renders, but the tile provider is an OPEN decision (spec §8 — the blocker is licensing, not cost),
and §4.5 itself requires tile-fetch failure to fall back to the no-background render. So the
no-background point layer is a correct shippable starting point, not a shortcut: the tile layer
slots in behind the same immutable geometry later without touching the point layer or the render
determinism. Internal/operator renders default to no background anyway (§4.5), so this half is
final regardless.

**Determinism is enforced, not hoped for.** The renderer has no `now()`, no element ids, no random
values, sorted point_seq iteration and fixed-precision coordinates (sign-of-zero normalised). A
unit test renders the same inputs twice and asserts byte-identical output and identical
`content_hash`; another asserts input reordering does not change the hash. `report_artifact` has a
unique index on `content_hash`, so re-rendering identical inputs is a no-op upsert — the spec §6
cache contract made structural.

The one spec gap hit — no colour band for a rank past position 20 — was resolved the
cheapest-to-reverse way (fold into "found, far down", never red) and logged as I-089 rather than
resolved in the spec. The deferred `score_run_id` FK is I-090.

---

## 2026-08-07 — Phase 3 slice 2: the comparison renderers, and how "improved" is decided

Slice 2 adds `heatmap_pair` (before/after side by side) and `heatmap_delta` (per-point change) —
reporting spec §4.3 — on the same deterministic, golden-fixture-tested footing as slice 1's single
heatmap. Three genuine choices, none of them in the spec verbatim:

**Absent (byte 0) is the worst rank, so it participates in the delta.** Rank is inverted (lower =
better) and "not found" is a real, meaningful outcome — the strongest pitch state. The classifier
maps absent to an effective rank of 1000 (larger than any real byte, 254), so `absent → ranking`
is an **improvement** (green) and `ranking → absent` is the sharpest **decline** (red). The one
exception the spec calls out explicitly is honoured: **absent in BOTH snapshots renders neutral,
never red** — "still not ranking" is not a decline. A pure `delta_band(before, after)` encodes all
of this and is hand-tested against a table reasoned from the inversion, not read off the code.

**The delta legend is directional words only — no numbers.** Spec §7a's trap: a numeric legend on
an inverted-rank view reads backwards to anyone who glances at it. The legend says "Rank improved /
Rank worsened / No change / No data" and a test asserts no digit appears in any delta legend label.
The delta view is also made visually distinct from a state heatmap (a tinted plot field + a dashed
frame) so the two are never confused when a page carries both.

**The renderer stayed byte-frozen while its drawing code was shared.** Slice 1's `render_heatmap`
output is already citable (its `content_hash` is the cache key), so the shared-primitive extraction
(`_draw_marks`/`_draw_legend`/`_draw_scale_bar`/`_projector`) that the pair and delta renderers now
reuse was proven byte-identical against reference hashes captured *before* the refactor — not merely
assumed from a green test suite. This is the lazy-split refactoring policy applied exactly: the
seam opened because the next feature (comparison renderers) landed in the file, and the frozen
output was protected empirically.

The guard mechanism is fuller than its current data (span enforced now; provider-boundary and
drift-suppression are seams awaiting a second provider and `prospect_delta`) — logged as I-091
rather than resolved by building those subsystems ahead of their phase.

---

## 2026-08-08 — Any-city scan onboarding: type "City + Business type", built in stages

The scan form only let an operator pick a PRE-SEEDED submarket from a dropdown (submarkets ship
from a market definition file). Owner request: type any city and scan it. Two findings shaped how
this is built.

**"Google-recognised submarkets" can't be sourced from Google.** Google resolves a place you name
but has no endpoint that LISTS a city's neighbourhoods. So sub-areas are OSM-enumerated (Overpass
`place=suburb|neighbourhood|…` nodes) and each is then VERIFIED against Google geocoding and kept
only if it resolves inside the city — every option shown is Google-recognised, the list just isn't
Google-sourced. This is the exact pipeline the Local SEO neighbourhood silo already rides; the
primitives (`maps_geocode.forward_geocode_places`, `place_is_within_city`, `overpass`) are reused,
not reinvented. Owner picked this over a Google-Places-Nearby-only list (patchy coverage). Owner
also fixed scope at ONE sub-area per scan (keeps the one-submarket first-run rule).

**A scan of a city that hasn't been INGESTED produces nothing.** `prospect_coverage` is
`grid_result` joined to `prospect` on place_id, and `prospect` rows come only from the paid
Outscraper `ingest` pass. So "scan a typed city" is really discover (ingest) → filter → scan —
the business type the operator types is exactly the ingest CATEGORY. That's why the form is "City +
Business type" and not just a place picker (I-092).

**Staged build (this is why the first PR is backend-only).** The geo READ layer ships first:
`services/outreach_geo.py` (resolve city + enumerate verified sub-areas, pure helpers unit-tested)
+ read-only routes (`GET /outreach/geo/resolve-city`, `/outreach/geo/subareas`, staff-gated,
geocoding-only — they cannot reach the ~$0.81 scan spend). The "City + Business type" FORM and the
discovery-execution (create market/submarket/keyword + run ingest→filter→scan on demand in the
outreach service) land together in the next slice, so the form's Queue button is never a dead end
that produces empty scans. The execution layer changes the outreach service's guarded spend/
execution model (a new paid job beyond the one-scan drain) and can't be tested from the build
sandbox, so it is deliberately verified live rather than merged blind.

Refactor rider: `place_is_within_city` moved from `local_seo_silo` (imports FastAPI) to
`maps_geocode` (pure), re-exported for existing callers — so the outreach geo layer reuses it
without importing a web-framework-bound module.

---

## 2026-08-08 — Any-city onboarding slice 2: the discover→filter→scan order + form

Slice 1 gave a read-only geo layer (resolve city + verified sub-areas). Slice 2 makes "City +
Business type → Go" actually run, and it required a genuinely new order type because a typed city
has never been ingested (I-092: a scan of it rolls up zero prospects).

**A SEPARATE `onboard_request` table, not a flag on `scan_request`.** `scan_request` authorizes one
thing — a scan of an already-ingested submarket — and its drain, its budget check, and its
one-active guard are all built around exactly that one paid step. An onboard order spends
differently: a variable Outscraper discovery pull PLUS a scan, across three stages. Bolting an
"ingest first" flag onto `scan_request` would bend its invariants around a second spend it was
never scoped for. A separate table + a separate drain (`onboard_queue`) keeps each order type's
guarantees intact; the claim/budget primitives are reused from `scan_queue`, not re-derived.

**Where each half runs.** platform-api owns the geo + row creation (resolve city, create-or-get
market/submarket/keyword — all free) and writes the signed order; the outreach service owns the
paid pipeline, because the Outscraper + scan clients live in its image. Same split, same reason, as
`scan_request` (a spend gate stops being one if both halves live in one service). The business type
the operator types is the Outscraper **category** AND the scan **keyword** — one input, both roles.

**The drain runs inside `tick`, staged, and fails asymmetrically.** `cmd_tick` now drains at most
one onboard order per heartbeat (after the quick scan drain, since discovery is multi-minute). The
order records which STAGE it reached; a budget refusal or the ingest cost-gate firing spends
nothing, an ingest/filter failure never reaches the scan (and records what discovery cost), and a
scan failure keeps its snapshot findable — `scan_queue`'s rule extended to a multi-step run. The
conditional claim means an onboard tick that runs past the next heartbeat cannot be
double-processed. One replica assumed (as everywhere in the outreach service).

**Create-or-get, never update.** Grid geometry is immutable once scanned, so a repeat pick of the
same city/sub-area reuses the existing rows (dedup by canonical Google name, scoped to parent)
rather than minting a second submarket with a drifted centre.

**Can't be tested from the build sandbox** (no Outscraper / Google / outreach DB), so the pure
logic — the staged drain's claim/budget/stage-failure decisions, the create-or-get dedup — is
unit-tested (`test_onboard_queue.py` 15 cases, `test_outreach_onboard.py` 6 cases), and the paid
execution is verified LIVE on the first real run (which is also the pipeline's first real scan).
Migration `20260808120000_onboard_request.sql`.

---

## 2026-08-08 — Any-city scan: a consumer SEARCH, not a GBP category; sub-area optional

Two owner refinements to the just-merged any-city scan, both making it more self-contained (and
explicitly NOT coupled to LeadOff — the outreach targeting stands on its own):

**The input is the search a customer would type, not a business category.** A GBP-category picker was
considered (and a source debated — DataForSEO live list vs bundled taxonomy) and rejected in favour
of a free-text CONSUMER SEARCH ("emergency plumber", "roof repair near me"). It's the natural input
for a geogrid tool — the scan measures who shows up when a customer searches that term, so the
businesses discovered are exactly the ones competing for it (sharper than a category). It also needs
no taxonomy to source. Mechanically this is what was already built: one string is both the Outscraper
discovery query AND the geogrid scan keyword; only the framing/labels changed (the `onboard_request.
category` column now holds that search term).

**The sub-area is optional.** "City → submarket if applicable → search" — a small city with no
distinct sub-areas, or a run you just want city-wide, picks "Whole city (center)" and the submarket
becomes the city-centre grid. `create_onboard_from_place(subarea=None)` builds the submarket from the
city; a NAMED sub-area still must carry coordinates (a partial pick is an error, not a whole-city
scan). Unit-tested (`test_outreach_onboard.py`: whole-city path, empty-dict path, partial-pick
refusal).

---

## 2026-08-08 — The call-hook justification is PURE deterministic assembly, not an LLM phrasing pass

The Phase 3 "phone-call hook generated from the prospect's own data" (HANDOFF §12 item 1; PRD §716;
reporting-layer-spec §4a "Call hooks are exempt"): before a caller dials a scanned prospect they
read a short, human-readable set of talking points — WHY the business is worth calling. Built as
`services/outreach_justification.py` (pure) + `services/outreach.prospect_justification` (I/O) +
`GET /outreach/prospects/{id}/justification` in platform-api, surfaced in `Outreach.tsx`'s coverage
table and the CRM lead drawer. Reads existing scan data only; spends nothing; writes nothing.

**THE DESIGN FORK (the one the task flagged): deterministic assembly vs an LLM phrasing pass
strictly grounded on the assembled facts. Chosen: PURE deterministic assembly.** Reasoning, in the
order it mattered:

1. **Cheapest to reverse — the deciding rule.** Pure assembly adds no dependency, key, cost, or
   non-determinism. An LLM phrasing pass can always be layered ON TOP later, grounded on the facts
   this module already assembles (the suite's "numbers-only, never invent" report narratives are
   exactly that shape). Deterministic-now → phrasing-later is strictly cheaper to reverse than
   LLM-now → strip-it-out-later, which is the test the session protocol sets.
2. **The invariant is "never invent a fact, a competitor, or a number" (CLAUDE.md; PRD §14
   "diagnose, not promise").** A deterministic assembler CANNOT fabricate — every sentence is a
   template over a measured number. An LLM pass, however tightly grounded, reopens that door and
   needs guarding shut again (verify-at-render, hallucination review). The whole reporting family
   is deterministic by requirement (reporting §2/§6 — a March render must regenerate in June); the
   hook inherits that for free.
3. **Replayability.** Each talking point carries the raw `facts` it was built from — the same
   discipline `score_factors` holds — so the claim is inspectable and reproducible from stored
   inputs, exactly like the heatmap's `content_hash`.

**Sub-decisions:**

- **The phrasing templates are code constants, not config.** The heatmap renderer's legend labels
  ("In the map pack (1–3)", …) are ALSO code constants — the accepted Phase 3 precedent. "Template
  MUST be config" (PRD §716) is honored in spirit: the sentences are filled from persisted scan
  data and never improvised at send time, which is what that MUST protects against. Promoting to
  config is a later cheap-to-reverse step if an A/B need arises.
- **The hook is a single element with the sentence composed from it (PRD §1335).** `hook_element`
  logs the primary driver (coverage — the strongest state pitch); `available_elements` records the
  full set it was chosen from (the §14a "available-but-passed" attribution a future emit manifest
  needs). A `delta` element would rank ABOVE coverage ("prefer a delta over a state", §716) — it is
  deliberately absent until a second scan exists, the same seam the heatmap delta guards leave open
  (I-091). The single-scan caveat says so.
- **It lives in platform-api, not the outreach api.** The outreach api is a batch job platform-api
  cannot call; the surface that needs the hook (the route + UI) is platform-api, which already reads
  the Outreacher DB. The one thing this costs is compass-directional geography, which needs the
  pinned geometry generator that must not be re-derived across the deploy boundary — deferred and
  logged as I-093 (the radial pattern from stored scalars ships now).
- **Competitor detail degrades, never fabricates.** "Who outranks you and where" reads the map pack
  from `grid_result` (bounded to `rank <= pack_size`), naming only competitors whose `place_id`
  resolves to a known business; a cold-dropped partition drops the competitor point and says so in a
  caveat (I-094), leaving coverage/reviews/gaps intact.

Pure logic unit-tested (`writer/platform-api/tests/test_outreach_justification.py`, 16 cases);
config knobs `outreach_call_hook_pack_size`/`_justification_max_competitors`/`_field_review_min_sample`.

---

## 2026-08-08 — Per-prospect reports: two faces over one document, signals staged, spend stays gated

Owner asked for two per-prospect report buttons: an internal stripped-down competitive read (organic
+ maps + LLM visibility, each vs top competitors) and a client-facing report. Built the **report
spine** (`services/outreach_report.py` pure + `services/outreach.prospect_report` I/O +
`GET /outreach/prospects/{id}/report` + `components/outreach/ProspectReport.tsx` — two buttons in the
coverage table and the CRM drawer, a modal with an Internal-brief / Client-facing-draft toggle and
print). The organic + LLM scan layers and the client-facing PDF+approval are staged as increments 2–4
(ISSUES I-095). Decisions made here:

- **Two faces, ONE document.** The internal brief and the client-facing draft render the SAME
  assembled facts with different copy, so they can never disagree — the same reason the justification
  and the report share the call-hook object verbatim.
- **Deterministic, same as the justification/heatmap.** No LLM, no clock; never a fabricated fact,
  competitor, or number. Signals feed from the same bounded scan reads.
- **A signal with no scan is an explicit `not_scanned` block, never an empty table.** Only the Maps
  geo-grid has a producer today; organic and LLM render "not scanned yet" with the reason. Showing
  "no organic competitors" for a scan that never ran would manufacture the exact false picture the
  module guards against — the I-076 lesson, applied to sections.
- **Spend stays gated (for the paid layers, increments 2–3).** platform-api cannot spend. Generating
  a report with FRESH organic/LLM data will place an admin-authorized scan order (the existing
  `scan_request`/`tick` mechanism), which the Railway job runs; the report assembles once it lands. No
  report button will ever fire a paid provider directly.
- **I-084 resolved (organic ↔ snapshot):** the organic SERP will attach to the maps `scan_snapshot`
  for that submarket×keyword as a single-location capture into `serp_result` (the natural join key),
  rather than a new snapshot type. Chosen now so increment 2 is built against a decided shape;
  cheapest-to-reverse (one location per keyword×submarket, the same unit the maps scan already keys).
- **The client-facing face is always a DRAFT until an approval slice exists.** "No prospect-facing
  asset without explicit human approval" is a hard invariant (CLAUDE.md; reporting §4a), so the
  client face carries `approved:false` + a draft banner and the print is an internal preview. The
  WeasyPrint PDF + approval gate + signed R2 URL is increment 4.

Pure builders unit-tested (`writer/platform-api/tests/test_outreach_report.py`, 6 cases).

---

## 2026-08-08 — Organic-SERP capture (report increment 2): one live call, attached to the maps snapshot

Increment 2 of the per-prospect report (ISSUES I-095): the "organic ranking for this keyword vs the
top competitors" signal. Built the producer + the read + the render.

- **One live call, not the queued grid.** Organic is ONE SERP per snapshot (`organic_scan.py` →
  `/v3/serp/google/organic/live/advanced`), so it uses the live endpoint — immediate, one billed
  request — rather than the 81-task queued lifecycle the maps grid needs. Gated like every paid
  command (`scan-organic` in `PAID_COMMANDS`); writes a `cost_ledger` row (stage `b2_organic`).
- **Attaches to the maps `scan_snapshot`** (I-084 decision): `scan-organic` targets the latest
  ROLLED-UP snapshot for a submarket×keyword (the one the report reads), via the same resolver the
  heatmap uses, and writes `serp_result` (engine `google_organic`, `payload` + `payload_summary`).
  So the organic and coverage reads come off one snapshot, keyed the natural way.
- **Endpoint shape MEASURED on first run, not asserted** — the `dataforseo_client.py` discipline. The
  path is added to the free `probe-dataforseo` set, `capture_organic` logs one full response, and
  `parse_organic_serp` RAISES on a task-level error rather than returning an empty SERP (an outage
  must never read as "nobody ranks"). The first real run proves the envelope, like the maps scan.
- **Idempotent per snapshot:** a re-run on a snapshot that already has an organic row is free and
  stores nothing.
- **The prospect's own organic rank** is read by matching their website's domain against the SERP's
  `domain` field, normalised identically on both sides (`domain_of` in each codebase). A prospect not
  in the captured depth reports `prospect_rank: None` (not ranking in the top N) — never a guessed
  position. Competitors are the top ranked domains, the prospect's own excluded.

Pure logic unit-tested both sides (`outreach/api/tests/test_organic_scan.py` 8 cases;
`writer/platform-api/tests/test_outreach_report.py` organic cases). Reuses `scan_depth` /
`dataforseo_*` config — no new knobs. **Still staged (I-095):** LLM visibility (increment 3, blocked
on `ai_region`) and the client-facing PDF + approval gate (increment 4).

---

## 2026-08-08 — AI-visibility scan (report increment 3): two engines, per-region, seeded ai_regions

Increment 3 of the per-prospect report (ISSUES I-095): the "AI / LLM visibility" signal — does an AI
assistant name this business when a customer asks about its keyword in its region. Owner rulings:
**only ChatGPT + Google AI Overview (AIO)**, and **yes, seed the region names** (from the I-073 LA
draft). Built the producer, the read, the render, and applied the migration live.

- **Two engines, both reusing proven pieces.** ChatGPT reuses the I-004 spike's OpenAI call +
  tolerant name parser (`ai_granularity.py`) — one definition of "the consumer question"; AIO reuses
  the organic DataForSEO path (`organic_scan.py`) and parses the `ai_overview` element's cited
  sources + text. Gated like every paid command (`scan-ai` in `PAID_COMMANDS`); a `cost_ledger` row
  per engine (`b3_ai_chatgpt` / `b3_ai_aio`).
- **Per (region × keyword), not per prospect.** The AI answer is the same for every prospect in a
  region, so the scan stores the answer (`ai_scan_result`: named_businesses / reference_domains /
  raw_excerpt / present) and the prospect-level "is THIS business named" is detected at report-read
  time. That is what keeps it cheap — a handful of regions × keywords × 2 engines, not one call per
  prospect.
- **`ai_region` is the coarse place-name geography (PRD §8b), NOT the submarket.** New table
  (migration `20260808140000`, applied live to Outreacher), seeded with the ELEVEN validated LA
  names from I-073 (7 cities + 3 LA suburbs + Hollywood as `neighbourhood`); the three WEAK names
  (Downtown/West/East LA) deliberately excluded — I-073 found them to be the "reads specific,
  returns metro" trap. A prospect maps to a region by its submarket NAME; `name_level` carries the
  I-004 recognition risk, and a `neighbourhood`-level region's report shows the "the AI may have
  answered for the metro" caveat.
- **Mention detection is conservative + never manufactures invisibility** (`detect_ai_mention`,
  pure): the prospect's normalised name inside a named business or the raw text, or its domain in the
  AIO references; name must be ≥4 chars to match on substring. A false NEGATIVE (named under a
  variant we missed) understates visibility — the safe direction — while a failed engine call is
  stored `present=False` with the error, never as "the AI doesn't know you".
- **AIO envelope MEASURED on first run** (the `dataforseo_client.py` discipline): `parse_aio` is
  tolerant and `capture_aio` logs one sample; no AI Overview parsed against this account before.

Pure logic unit-tested both sides (`outreach/api/tests/test_ai_visibility.py`;
`writer/platform-api/tests/test_outreach_report.py` detection + section cases). Config
`ai_visibility_chatgpt_model` / `_openai_cost_cents`. **All four report increments are now built**
(I-095): shell, organic, LLM. The client-facing PDF + approval gate (increment 4) remains — the
client face is still a print-preview DRAFT.

---

## 2026-08-08 — Client-facing PDF + approval gate (report increment 4 — the last one)

Increment 4 completes the per-prospect report (ISSUES I-095): the client-facing face becomes a real,
shareable **PDF**, generated ONLY behind an explicit human approval.

- **The approval gate is the module's hardest invariant** ("no prospect-facing asset without
  explicit human approval" — CLAUDE.md; reporting-layer-spec §4a). Implemented as: the client-PDF
  route is **admin-gated, and the click IS the approval**. Generating the PDF writes a
  **`report_approval`** row (migration `20260808160000`, applied live) naming the actor and the
  **content_hash of the exact bytes** approved (reporting §2 — a report shared in March regenerates
  identically in June; the approval records which render was sanctioned). `approved_by` is an AR
  Tools profile id with no cross-database FK (HANDOFF §2).
- **Server-side HTML → WeasyPrint, reusing the suite's `client_report.render_pdf`** (already in the
  platform-api image, so no Dockerfile change). `render_client_report_html` is a PURE builder of the
  SAME assembled facts the on-screen client face shows — client tone, honest `not_scanned` blocks
  (never an empty table), every value escaped, white-label agency footer, and NO draft watermark
  (it is generated only after approval).
- **Delivery is a direct download for v1** (`POST …/report/pdf` → `application/pdf` bytes; the
  frontend downloads the blob), not an R2 signed URL. Cheapest-to-reverse: it needs no new bucket or
  R2 creds in this context, and the admin downloads-and-sends. The R2 signed-URL delivery
  (reporting §5, 90-day expiry) is a documented follow-up (ISSUES I-095) — the approval + content_hash
  it would key on already exist.
- **Refuses an unmeasured area** — there is no honest client report when nothing has been scanned, so
  it raises rather than rendering an empty asset. The report's `client_facing` block flips from
  `draft` to `approved` (with who/when) once an approval is on record, so the UI banner reflects it.

Pure builder + approval-reflection unit-tested (`test_outreach_report.py`); the render + record flow
validated end-to-end with a mocked WeasyPrint. Config `outreach_report_agency_name`. **All four
report increments are now built** — the report is feature-complete; only the R2 delivery refinement
remains open under I-095.

---

## 2026-08-08 — Client report delivery: signed URL via Supabase Storage (not R2), the I-095 refinement

The last open item under I-095: reporting-layer-spec §5 wants the client-facing PDF delivered as a
SIGNED URL with an expiry (so a client gets a link, not an emailed file), and names Cloudflare R2.

**Built it on Supabase Storage instead of R2, deliberately.** The substance §5 asks for is "a signed
URL, no auth, ~90-day expiry"; a private Supabase Storage bucket delivers exactly that. The reasons
it wins over R2 here:
- **No new credentials to provision.** platform-api already holds the Outreacher project's
  service-role key; the outreach Railway service carries only Outscraper/DataForSEO/Supabase creds
  today (I-073), so R2 would be a net-new dependency + an owner-side setup step for the same outcome.
- **Cheapest to reverse.** All signing goes through one seam (`_sign_report_url`); swapping the
  storage backend to R2 later is a one-function change, and `report_approval.storage_path` +
  `content_hash` already record where the bytes are and which bytes they are.

Shape: `generate_client_report_pdf` uploads the rendered PDF to the private `outreach-reports` bucket
(migration `20260808180000`, applied live) at `{prospect_id}/{content_hash}.pdf` (content-hash keyed,
so identical inputs reuse one object — reporting §6), records the path on the approval row, and
returns a signed URL (TTL `outreach_report_url_ttl_days`=90). `POST …/report/pdf` now returns the
link (JSON) rather than the raw bytes; `GET …/report/pdf` re-signs the latest approval's stored PDF
so an expired link refreshes without re-approving (read-only, not admin-gated — approval already
happened). Storage is best-effort: a failure still records the approval, only the link is absent.
Frontend: the client face shows the shareable link (copy / open) + the expiry note.

**I-095 is now fully resolved** — the per-prospect report is complete end to end (shell, organic,
LLM, approved client PDF, signed-URL delivery).

---

## 2026-08-08 — Paid-placement PRESENCE (Slice A): parse it from the response we already pay for; persist in payload_summary

HANDOFF §12 item 3a, the owner's stated next build — the fourth competitive signal: is the business
(and are its competitors) BUYING Google Ads / Local Services Ads for its keyword. scoring-spec.md
rates it above every organic signal (LSA active +57, Google Ads + no organic/pack +46) because a
business paying to solve the visibility problem while still losing organically has proven budget AND
intent. Slice A is PRESENCE only (built); the money signal — spend magnitude + pixel/tag detection —
is Slice B, its own later build.

**The paid items ride the organic capture — no new paid call for Google Ads.** `scan-organic` already
stores the FULL DataForSEO SERP response in `serp_result.payload`, and that response carries the paid
items; the old parser discarded everything that was not `organic`/`ai_overview`. So `parse_organic_serp`
now also collects `type=="paid"` (Google Ads) and `type∈{local_services,…}` (LSA), and `summarize_serp`
emits a `paid` block in `payload_summary`. Deriving Google-Ads presence from data already on disk with
ZERO new spend is the cheapest possible reading, and it is exactly the discipline the module already
follows for the organic prospect-rank (parsed once, matched at read).

**LSA item type is unconfirmed and taken cheapest-to-reverse — logged as I-096, not resolved in specs.**
The exact DataForSEO type for Local Services Ads in THIS account's organic response is unmeasured (the
organic scan has never run). Rather than build a speculative NEW paid LSA call that might hit a wrong
envelope, Slice A parses LSA tolerantly from the already-captured response and records `seen_item_types`
(logged on first run + stored in the summary) so the shape is confirmable from the log. If the first
live run shows LSA needs its own endpoint, a gated `scan-lsa` call is the additive follow-up. Parsing
an existing field is free to reverse; a wrong paid call is not.

**Persistence: `serp_result.payload_summary.paid`, keyed to the snapshot — NO new column/table/migration.**
This mirrors the organic signal exactly: the per-snapshot advertiser lists persist in the summary, and
the per-prospect question ("is THIS business advertising") is DERIVED at read time by matching the
prospect's website domain (Ads) / name (LSA) against the stored lists — the same read-time match the
organic `prospect_rank` and the LLM mention use. That derivation (`outreach_report.derive_paid_signal`,
pure) feeds both the report's fourth "Paid placement" section AND the call-hook justification's
`ELEM_PAID` talking point ("rivals are paying for this search and you're not" — the §Buying-intent
pitch), so the two never disagree. The Phase-4 scorer reads the same per-snapshot summary + prospect to
compute its bins; the per-snapshot lists also support the future `ads_state_change` delta (diff two
summaries). A per-prospect table was rejected for the same reason the organic signal has none — the fact
is per-snapshot, the flag is a deterministic read-time match, and duplicating it per prospect invites
drift. Until the Phase-4 scorer exists the signal is STORED + SHOWN, not scored (HANDOFF §12 item 3a).

**Deterministic + fact-grounded, same as the three signals it joins.** Absence of ads is a FINDING
(`ads_present:false`), never a gap that manufactures a claim; a competitor is named only from a real
advertiser domain/name; the prospect's own ad presence excludes it from its own competitor list. The
paid talking point fires ONLY on the rivals-advertising-and-prospect-not gap — a prospect who IS
advertising is a scorer-owned signal, not a cold-call hook.

*Revisit:* Slice B (site-fetch money signal) and the Phase-4 scorer, which consume this. If the first
`scan-organic` run proves LSA needs a dedicated endpoint, add the gated `scan-lsa` command (I-096).

---

## 2026-08-08 — Paid-placement Slice B1 (site tech signals) + the §16a.1 spike; B2 gated behind a yield spike

Owner authorized proceeding on the Slice B design (2026-08-08): "build B1 now, gate B2 behind the yield
spike," run the §16a.1 pixel spike, persist the design doc. Built B1 + the spike instrument; deferred
B2. Full design: `docs/paid-placement-slice-b-design-v0_1.md`.

**B1 and B2 are separate builds because they are separate providers with opposite cost profiles.** B1
(tech/tag PRESENCE — Meta pixel, AW- conversion tag, GTM container, CallRail/Podium/Birdeye) comes from
a DIRECT HTTP fetch of the prospect's own site (PRD §B3 "own request, not a paid service") — FREE. B2
(spend MAGNITUDE) comes from DataForSEO Labs — PAID, and likely sparse for small local advertisers
(I-098). Bundling them would gate a free capability behind a paid one, or spend on a magnitude estimate
before proving it yields. So: `scan-tech` (free, NOT in PAID_COMMANDS — a test pins it) ships now;
`scan-adspend` is deferred behind the `probe-labs-paid` yield spike.

**`scan-tech` is free, so it is not spend-gated — same posture and same test as `collect`.** It makes
no paid provider call; gating it would make a routine detect refuse for want of a token. The §16a.1
pixel spike (`probe-pixel-field`) DOES bill (an Outscraper enrichment on a small sample) and IS gated.

**The measured-vs-found rule is structural in B1, the fourth time this correction has been made** (see
the 2026-08-05 coverage-denominator entry). A failed site fetch stores a `fetch_status`
(`unreachable`/`timeout`/`blocked`) with the signal booleans null — NEVER `absent`. Unknown ≡ absent
for the scorer (one-directional, never subtracts — PRD §B3), but the two must be stored distinctly so
the report can say "couldn't read the site" rather than "no ad tech". The platform-api reader enforces
it too: `_tech_ok` treats a non-'ok' row as no tech signal at all.

**The §16a.1 spike is isolated from the ingest path on purpose.** `outscraper_client.submit_maps_search`
carries a hard invariant — base-tier only, never populate `enrichment` — that protects the MASS ingest
from silently billing enrichment across thousands of places. A one-off enriched sample of ~8 places is
a different, deliberate, gated act, so `pixel_probe.fetch_enriched_sample` builds its OWN request rather
than bending that method. The pure heuristic (`scan_place_for_pixel`) never asserts the enrichment's
field name — it scans for pixel INDICATORS by key and value, because the field name is exactly what the
spike measures (measure-don't-infer). Likely outcome (pixel not in the base pull, or GTM-injected and
missed) reinforces the site-fetch B1 already built.

**The report/hook gained the strongest pitch the model has: "paying and losing."** B1's AW- tag (plus
Slice A's SERP paid / LSA) makes `prospect_is_paying` computable, and combined with poor coverage it is
the vendor-failing SHAPE — proven budget AND a visible problem (scoring-spec.md §Proven-spend /
§Buying-intent, the +66/+90 territory). It is folded into `derive_paid_signal` ADDITIVELY (Slice A's
SERP-derived facts keep their exact meaning; the competitor-gap stays SERP-only, so Slice A tests are
unchanged), gets its own `ELEM_PAYING` justification element that LEADS the spoken hook when it fires,
and is one-directional throughout. Persisted per-prospect in `prospect_tech_signal` (migration
`20260808200000`, applied live to Outreacher) — keyed to the prospect, not a snapshot, because the site
is the prospect's and does not change per scan (so it does NOT ride `serp_result`).

*Revisit:* the `probe-labs-paid` yield spike decides whether B2 (`scan-adspend`) is built; the §16a.1
spike decides whether `tech_follow_gtm` defaults on and whether the Outscraper pull can supply the Meta
half near-free (I-097).


---

## 2026-08-08 — Paid placement: what a signal may CLAIM is decided by which evidence produced it

Found by adversarially reviewing the Slice A/B code before it ran (ISSUES I-099). Two of the three
defects were the same shape: a derived boolean was true for more than one reason, and the sentence
built from it named only the most flattering one.

**A signal that can fire from several sources must carry WHICH one fired.** `prospect_is_paying`
was true for a SERP ad, an LSA, or an `AW-` conversion tag on the prospect's site — and the caller's
opener said "you're paying for Google Ads on ⟨keyword⟩" in all three cases. The first two were
measured on that keyword's own SERP. The third was measured on their website, proves only that
conversion tracking is installed, and is routinely left behind after a campaign stops. So the module
now carries `paying_evidence` (`serp_ad` | `lsa` | `conversion_tag`) alongside a narrow
`prospect_paying_this_keyword`, and every surface — the spoken hook, the internal brief, the
approval-gated client PDF — branches on it. The tag-only path ASKS ("are you paying for clicks your
competitors get free from the map pack?") rather than asserting. This is the fabrication invariant
applied one level deeper than "don't invent a competitor": *don't let a true-for-one-reason flag
license a sentence that names a different reason.*

**A two-sided name match fails in one safe direction and one unsafe one.** The LSA advertiser match
was bidirectional, so a SHORTER competitor name inside a LONGER prospect name ("AAA Plumbing" inside
"AAA Plumbing Services" — routine in the trades) both asserted an LSA the prospect does not run and
deleted a real competitor from the list. `detect_ai_mention` had already chosen the one-directional
rule for exactly this reason; the paid signal now matches it. The kept direction's failure is a MISS,
which understates spend — the direction that costs nothing to be wrong in.

**A shared CLI default is not a default, it is an accident waiting for a new command.** `--limit`
defaulted to 20 for every subcommand, so `scan-tech` — which wants every site — silently covered 20
of ~1,000 and exited 0. Defaults now belong to the COMMAND (`scan_tech_limit`, `pixel_probe_limit`,
`legacy_limit`), which is the same principle `resolve_command` already applies to the spend gate:
the safe value is what you get by omission, and "safe" differs per command (all sites for a free
scan, a small sample for one that bills). The parser is extracted as `build_parser()` so the
argparse-to-command seam is testable — the bug shipped because the pure logic was covered and that
seam was not.

*Consequence:* `likely_represented` no longer counts GTM. It is the only derived flag scoring
NEGATIVE (−21 Model A / −26 Model B), and GTM is a free tool on a large share of all sites, so
counting it penalised DIY operators for having a tag manager.

---

## 2026-08-09 — Phase 3 `outcome` + `touch`: DDL adopted verbatim; touch anchored on lead; app-owned rollup

The learning substrate (HANDOFF §12, scoring-spec §8 — the item with a closing window because
`outcome` cannot be backfilled). Migration `20260809170000_outcome_touch.sql`, applied live to
Outreacher and verified by `tests/outcome_touch_constraints.sql` (12 checks, all correct).

**`outcome` is adopted VERBATIM from `PHASE3-outcome-constraint.md`, not re-derived.** That DDL was
worked out and verified live against the real key on 2026-07-31, and the task instruction was to
adopt it. So the outbound-only rule stays STRUCTURAL: the composite FK targets
`lead(prospect_id, source)`, making an outcome on an inbound-with-a-prospect_id lead unrepresentable
(FK violation) and a reclassify-with-an-outcome refused through `on update cascade` — rather than a
trigger convention. The only additions over the doc's DDL are two non-modelling audit columns
(`created_at`/`updated_at` + an updated_at trigger); they touch no coefficient and were kept minimal
so the modelling shape is exactly the spec's.

**`touch` is anchored on `lead`, not `prospect`.** A touch happens against the CRM entity being
worked, `lead_activity.touch_id` lives on a lead's timeline, and an inbound/referral lead can be
contacted too — so `touch` must accept any lead. The outbound-only rule lives on `outcome` alone: a
touch on an inbound lead is real and recordable, it just never rolls up into an outcome. `id` is
`bigint generated always as identity` because Phase 1b shipped `lead_activity.touch_id bigint`
against this table's future existence. `channel` (phone|email) lives on the touch because phone and
email are measured with different offsets and never pooled (scoring-spec §8); the outcome has no
channel column (derivable from `sequence_version` / the touches).

**`outcome.touch_count` + `first_contacted_at` are an APP-OWNED rollup of `touch`, not a DB
trigger.** A trigger creating/maintaining the outcome would need `selection_reason` /
`sequence_version` / `touches_per_sequence_at_send` — all config-driven ("zero hardcoded params",
CLAUDE.md) — which SQL cannot read without hardcoding them. So the application recomputes the two
derived fields from the touch rows on every write (recompute-on-write, never an increment that can
drift). This mirrors the coverage-rollup philosophy: derive, don't drift. The cost is that a touch
inserted by raw SQL (not through platform-api) won't update the outcome — acceptable because
platform-api is the only writer (HANDOFF §2).

**`first_contacted_at` is set by the first TOUCH, not by emit.** `touch` is authoritative for "a
contact attempt happened" (CLAUDE.md invariant); emit only enqueues. A prospect emitted to the
queue but never dialed keeps `first_contacted_at` null — the honest state that lets the model tell
"queued" from "contacted". Logged as I-101 that the PRD's min-history / evidence-age emit gates are
deferred to the Phase-4 selector (v1 emit is manual + bootstrap-gated).

**`lead_activity.touch_id` gets its FK now** (`on delete set null`): deleting a touch nulls the
referencing call_note's pointer but never deletes the human commentary. 0 orphans verified live
before applying. This does NOT let `lead_activity` start recording sends — the
`lead_activity_touch_on_call_note_only` check (Phase 1b) still confines a `touch_id` to a
`call_note`, and `touch` remains the authoritative send record.

---

## 2026-08-09 — The emit path writes the outcome; a touch also creates it. NO bulk backfill of hand-picked leads (resolves the teed-up 2026-08-06 question)

DECISIONS 2026-08-06 ("Hand-picked leads ARE `outbound_scan`") left one question explicitly for
Phase 3: *whether the emit path also backfills outcomes for hand-picked `outbound_scan` leads that
already exist, or the model simply doesn't see them until they are re-emitted.* The emit machinery
now gives it a concrete shape, so it is decided.

**Decision: an `outcome` is created by whichever comes first — emit or the first touch — and both
are idempotent. There is NO bulk backfill that sweeps pre-existing hand-picked leads into
outcomes.** A hand-picked lead becomes modellable the moment it is actually CONTACTED (a `touch` is
recorded), not the moment it is promoted to the board.

**Why.** Promotion ("Send to CRM") is not contact. Writing an outcome — with a `first_contacted_at`
and a `selection_reason` — for a prospect nobody has called would inject fabricated contact events
into the exact substrate the Phase-4 model fits against, which is worse than the model not seeing
them. The whole reason `outcome` cannot be backfilled is that a contact event is unrecoverable after
the fact; the mirror of that is that a NON-contact must never be recorded as one. So:

- **Emit** (send to the external outreach queue) writes the `outcome` stub for the emitted prospect,
  reusing the existing hand-picked lead idempotently (via `promote_prospect`). `touch_count = 0`,
  `first_contacted_at = null` — queued, not yet contacted.
- **A touch** on any `outbound_scan` lead ensures the outcome exists (create-if-missing, config
  metadata + `selection_reason` default `manual`) and rolls up the touch. So a hand-picked lead that
  is manually dialed gets its outcome at the first call — captured from call one, which is the entire
  point of building this before dialing.
- Both paths never overwrite an existing outcome's `selection_reason` (idempotent).

**Reversibility (the deciding test).** If a bulk backfill is ever wanted, it is a purely additive
job over existing leads — nothing here forecloses it, and no data is lost by not doing it now
(a hand-picked lead's outcome is written the instant it is contacted). Backfilling now, by contrast,
would write contact events that never happened, which is not reversible without knowing which rows
were fabricated. So "create on first contact, no bulk backfill" is strictly the more reversible
reading. Recorded here; the alternative (bulk backfill at emit) remains open as an additive job.

---

## 2026-08-09 — The emit webhook: configurable POST, audit-ready queue, best-effort delivery, never triggers assets

PRD §C: emit MUST post an audit-ready QUEUE to a configurable webhook (n8n / Encharge), NOT
generated assets, and asset generation must stay behind the existing approval gate.

**One configurable URL, generic POST.** `outreach_emit_webhook_url` (default "" = the external queue
is not wired yet) + an optional `outreach_emit_webhook_token` bearer header. n8n and Encharge both
receive a plain JSON POST, so no provider branch is needed — the URL is where it points. `httpx`
(already a platform-api dep) does the POST with a bounded timeout.

**The payload is a deterministic, PURE builder** (`services/outreach_emit.py::build_emit_payload`),
reusing the same assembled facts the report/justification already produce: prospect identity,
channel, contacts, the placeholder score + empty `score_factors` (the Phase-4 model fills these —
labelled `placeholder` so it is never mistaken for a fitted score), `primary_pitch` (the
justification's call-hook sentence + element + talking points), `matched_case_study: null` (I-012),
`deltas: []` (single scan — needs ≥2, the same seam the heatmap delta leaves open), and evidence
references (snapshot id, submarket, scanned_at, geometry_version, coverage). Deterministic and
fact-grounded, the same discipline as every other outreach render.

**Asset generation is NOT triggered by emission.** The payload is a queue row, never a prospect-
facing asset; the approval-gated client PDF (`report_approval`) stays the only path to an asset. A
test pins that the emit payload carries no rendered asset and no PDF call.

**Delivery is best-effort; the DB write is the source of truth.** Order: write lead (idempotent) →
write outcome → POST the webhook. A POST failure leaves the outcome written and reports
`delivered:false` with the status/error for retry (re-emit is idempotent and retries the POST). This
honors the closing-window urgency — the outcome is captured even if the external queue hiccups —
without the double-send risk of POST-then-write. If the webhook URL is unset, emit still writes the
outcome and reports `delivered:false, reason:webhook_not_configured`; the `touch` path is the
independent, webhook-free capture of real contacts, so the substrate fills from call one regardless.

**Emit lives in platform-api and does not spend.** A webhook POST to the agency's own automation
tool is not a paid provider call — the "platform-api must not spend" invariant is about
Outscraper/DataForSEO. Emit is admin-gated (it queues a real business for outreach), matching the
scan-order routes. It records a `lead_activity` kind=`system` row (`event: emitted`) for an
append-only audit trail without persisting the re-derivable payload.

---

## 2026-08-09 — The emit webhook is a GENERIC optional integration; n8n/Encharge were only PRD examples (owner clarification)

Owner, on reviewing the Phase 3 build: *"We are not using n8n and I don't know what Encharge is."*
The PRD §C wording ("MUST emit via configurable webhook (n8n / Encharge)") named those two as
EXAMPLES of a downstream sender, and the build repeated the names in comments/docstrings as if they
were givens. They are not — nothing in the code depends on either.

**What is actually true, and now the framing:**
- `outreach_emit_webhook_url` POSTs plain JSON to ANY HTTP receiver, or nothing when empty. It is a
  generic, optional integration point (Zapier, Make, a custom endpoint — or none).
- **The primary capture path for a manual phone workflow needs no webhook at all.** Logging a call
  (the `touch` path) creates/rolls up the `outcome`, so the non-backfillable substrate fills from
  call one whether or not any external sender exists. Emit's webhook is purely for teams that DO run
  an automated outbound sender.
- Reworded the config comment, the Emit button tooltip, and this log so no artifact implies n8n or
  Encharge is required. No behaviour change — the code was always generic; only the framing was off.

*Reversible:* if the team later adopts an automation tool, set the URL (and optional token). If emit
itself is unwanted (pure manual dialling), the touch path stands alone and the Emit button can be
hidden with a one-line UI change — the outcome is still created at first touch.

---

## Phase 4 Stage 1 — the scoring model (2026-08-09)

### `prospect_score` / `score_run` / `conflict_check` are the PRD DDL, verbatim; the PK forces `channel` NOT NULL

START-HERE §3a names `docs/PRD-prospect-pipeline.md` as the owner of these three tables, and its DDL
is a superset of scoring-spec §8 (it adds `pass`, `channel`, `primary_pitch`, `evidence_age_days` on
`prospect_score` and `cycle_number` on `score_run`, which the reporting layer already reads). So the
PRD shape is the one built. The PRD makes `channel` part of the `prospect_score` primary key, which
in Postgres forces it NOT NULL — so Model B (close), whose coefficients are channel-independent, is
still STAMPED with the channel of the reply it composes into a `value` (close(phone) and close(email)
are distinct rows with identical points). That is deliberate: phone and email must never be ranked in
one list (spec §1), and carrying `channel` on every row is what enforces that at the read surface.

### `v_prospect_ranked` is a NEW view; the 2026-08-05 claim that it "already selects prospect_score
### where pass=2 and model='value'" was inaccurate and is corrected

The placeholder-score migration comment and the 2026-08-05 DECISIONS entry both referred to
`v_prospect_ranked` as an existing view. It never existed — verified live (`to_regclass` null) and by
grep (no migration creates it). The reporting spec's operator queue is a DIFFERENT view
(`v_prospect_queue`, §3.1, still unbuilt because it needs the enrichment/case_study tables). This
migration builds `v_prospect_ranked` for real, as the §10 acceptance surface ("rank order under all
three models side-by-side"). It does NOT hard-code `pass=2`: with no email enrichment yet, Stage 1
scores the phone track at pass 1, so pinning pass 2 would show an empty table. It reads the latest
score_run per market and pivots reply/close/value per prospect x channel x pass.

### Stage-1 live scope: PHONE track, PASS 1 only

The engine and golden fixtures cover both channels, but the score JOB writes the phone track at pass 1
(phone-first, pre-enrichment). Reasons: (1) the whole design is phone-first (HANDOFF); (2) email
reachability needs enrichment, which is Phase 5 — scoring an email track now would rank an unreachable
channel; (3) START-HERE Phase 4 requires "pass 1 excludes reachability rather than defaulting it", and
the phone reachability we DO have is `phone_type='unknown'` for every LA prospect, so it is correctly
excluded (not scored at a reference 0). Email lights up when enrichment lands, no code change beyond
passing `channels=('email',)` at pass 2.

### Offsets are pinned config; base rates are ALSO config (§1 requires it); a test binds them

scoring-spec §1 presents base rates and offsets together, with the offset derived from the base rate.
Deriving the offset at runtime (705.14 vs the fixtures' pinned 705.0) drifts F1/F7 probabilities to
the very edge of the 0.05pp golden tolerance. So the engine uses the PINNED offsets (705.0/579.3/625.1,
matching the fixtures exactly), and the base rates are ALSO config fields (§1 "MUST be config") with a
unit test asserting `derive_offset(base_rate)` rounds to the pinned offset within 0.2 — so replacing a
base rate per §9 without regenerating its offset fails loudly rather than silently miscalibrating.

### The coefficient registry IS the config; the points, not the displayed betas, are authoritative

"All coefficients from config, zero hardcoded betas" is satisfied structurally: the scalar knobs
(pdo/target/lambda/offsets/base rates) are `Settings` fields, and the ~40 elicited-prior point values
live in one documented registry (`scorecard_config.COEFFICIENTS`) loaded through the settings layer and
overridable per bin via `OUTREACH_SCORECARD_COEFFICIENTS_JSON`. Nothing in the scoring LOGIC hardcodes
a beta. The registry stores the spec's INTEGER points as authoritative (not `round(displayed_beta x
factor)`, which disagrees — ln(1.5)=0.4055 gives owner_operated +29 but round(0.41 x 72.13)=30, and the
golden fixtures were computed from the integer +29). `or`/`beta` are carried for the score_factors audit
trail only.

### Stage-2 recalibration is BUILT now, empty-safe (not stubbed)

Acceptance §10 requires it "runnable as a standalone job against outcome". It is built: a pure Fisher-
scoring fit of alpha+gamma on real reply outcomes (per channel, Thompson-subset guarded), and a
`recalibrate` CLI command. With zero contacted outcomes today it reports "insufficient" and writes
nothing — the correct empty-safe state, not a failure. It becomes useful as `outcome` rows accumulate.
`score_run` stores one alpha/gamma pair, so a calibrated run is single-channel (the phone-first reality);
per-channel calibration storage is a later migration when the email track is live (logged in ISSUES).

### The live-verification score run used minimal `score_factors` and was DELETED afterward

A full 83-prospect score run's faithful `score_factors` is ~170KB of SQL, which is expensive to route
through the MCP write path (the only path available: Railway OAuth redacts the service-role key, so
`run_score` cannot run locally, and triggering the production `score` command would disturb the cron
heartbeat unattended). So the live verification wrote a 4-prospect faithful sample (spanning severe-pain
/ franchise / high-coverage-incumbent / all-geogrid-bins), confirmed `v_prospect_ranked` pivots and
orders correctly (value 1415>1333>714>508; the franchise sinks to value decile 1; display_prob clamp
logic correct with calibration_alpha null), then DELETED the run — leaving the DB clean and the
placeholder intact as fallback. The full production ranking is one `score --market-name "Los Angeles,
CA, USA"` invocation away (see ISSUES for the onboard-market resolution). The model's correctness on the
full 83 prospects was demonstrated offline (top = low-coverage non-franchise; bottom = high-coverage +
franchises), and by 465 green tests including the 7 independent golden fixtures.

### Did NOT run the paid producers (scan-organic / scan-ai) this session

Authorized but deliberately not done: the async producers are built to run on the Railway job with its
credentials and egress, not from this sandbox; the free `scan-tech` is likewise a Railway-job producer.
The model already discriminates meaningfully on the signals we have (geogrid coverage + franchise +
review-count quartile), and the "measure-don't-infer / smallest-scope-first" discipline argues against a
first paid run through an unfamiliar path while the owner is away. Running them (scan-tech first, free)
to fill the buying-intent / organic-pain columns is the documented high-value next step; the extraction
wiring is already in place (unknown==absent), so a producer run lights those bins up with no code change.

---

## 2026-08-10 — Lead enrichment: order-driven, batchable, contact-aware, mass-ingest invariant untouched

Owner request: on-demand enrichment of a prospect (and a selection / all) with contact NAMES, PHONE
NUMBERS and EMAILS via Outscraper — one at a time and as a bulk "select all" action.

**The mass-ingest enrichment invariant is untouched, by construction.** `outscraper_client.submit_maps_search`
still hardcodes `enrichment=""` and gains no flag. Enrichment builds its OWN request in a new
`services/enrich_client.py::enrich_places`, generalizing the `pixel_probe.fetch_enriched_sample` model
(the proven, deliberately-off-the-ingest-path pattern for a billed enrichment call). Called BY place_id
(Outscraper resolves a place_id passed as the query to exactly that place), so a selection enriches
exactly the chosen leads. This was the whole shape of the request, so it was never in question — recorded
so a future reader does not "unify" the two paths.

**The order is the spend confirmation — same model as `scan_request`/`onboard_request`, NOT a platform-api
spend.** A UI click writes an `enrichment_request` row (migration `20260810120000`); the outreach job's
`tick` drains it and bills Outscraper. platform-api never spends. The alternative — platform-api calling
Outscraper directly — was rejected for the same reason it was rejected for scans: it splits the spend
path across two services and duplicates the client. The order carries the selection + the enricher set
frozen at authorization, and `est_cost_cents` doubles as the per-user daily budget ledger (no separate
spend table — mirrors the LeadOff pattern the request pointed at, but the order rows ARE the ledger).

**Batchable, so NOT the ≤1-order-per-tick cadence.** The scan drain takes at most one order per tick so
each scan's collection starts before the next scan spends. Enrichment is lightweight and one cheap request
covers a whole selection, so that reasoning does not apply: `enrich_queue.drain` processes up to
`enrich_orders_per_tick` (5) orders per heartbeat, each order the whole selection in one chunked pass. The
request explicitly warned against copying the heavy-scan cadence; this is the answer.

**Idempotent so a re-order is a cheap resume, not a re-bill.** A prospect already carrying a
`prospect_enrichment` row with status `enriched`/`no_contacts` is skipped (billed once, answer durable);
only `failed` is retried. Contacts are chunked and stored replace-on-place, so a crash marks the finished
chunks (skipped on re-order) and a re-enrich never duplicates contacts. This is what makes a stuck-`running`
order recoverable — re-place it and only the un-enriched prospects cost money.

**Contact-aware storage — one business → N contacts, `prospect` left pristine.** `prospect_contact`
(N children keyed on prospect_id + place_id), `prospect_enrichment` (per-prospect status + provenance +
the idempotency marker), `enrichment_request` (the order). The `prospect` table (owned verbatim by
PHASE-1-BRIEF §1) gains nothing, so coverage/scoring are unaffected. A `no_contacts` outcome is recorded
distinctly from a `failed` call — the first is billed-and-answered, the second retryable.

**Admin-gated placement (owner ruling 2026-08-10), staff reads.** Enrichment bills, so placing an order
matches the module's paid-order convention (`scan_request`/`onboard_request` are admin-gated — the click
IS the authorization) rather than LeadOff's staff+budget model. It is additionally budget-guarded per user.
Reads (estimate, status, contacts) are staff. Relaxing to staff later is a one-line dependency change.

**Measure-don't-infer: the field names are UNCONFIRMED and the parser asserts nothing.** No enriched pull
has run against this account, so the exact enrichment param value(s) and response field names are unknown.
`services/enrichment.py` reads the DOCUMENTED "Emails & Contacts" column shape defensively (both the nested
list-of-dicts and flat/numbered forms), stores each record's untouched fragment in `raw` for free
re-parsing against corrected aliases, and a `probe-enrich` command (PAID, env-gated) logs one full record
to confirm the shape before production is trusted — exactly the `probe-pixel-field` discipline. See ISSUES.

## 2026-08-10 — Report signal scans: run ORGANIC and AI per-prospect from the report UI

**The report already rendered organic + AI; only the geogrid could be TRIGGERED in-app.** The
per-prospect report (`writer/platform-api ProspectReport`) has always assembled four signals — maps,
organic, AI-visibility, paid — and their sections read `not_scanned` honestly until the paid scan
runs. But `scan-organic` and `scan-ai` were CLI-only, so every prospect nobody hand-ran showed those
two sections blank. Owner request (this session): let staff run organic + AI for each prospect from
the report. Built as two more signed-order queues on the existing `scan_request` rails.

**Same money-gate carrier, two new order tables.** `organic_scan_request` + `ai_scan_request`
(migration `20260810140000`): platform-api WRITES the order admin-only (the click is the spend
authorization, evidence the accidental deploy path cannot manufacture), the outreach `tick` DRAINS
and runs it (`organic_scan_queue` / `ai_scan_queue`, mirroring `scan_queue`). platform-api never
spends. ≤1 order per tick each (`organic_orders_per_tick`/`ai_orders_per_tick`, default 1) — the
geogrid cadence, not enrichment's batch drain — since each is a discrete paid capture and a first
run can surface a fault; raise the knob if a queue ever backs up.

**Two tables, not one polymorphic order (the onboard_request precedent).** Organic attaches to an
existing rolled-up `scan_snapshot` (resolved server-side from the prospect's report provenance, so
the capture lands on the EXACT snapshot the report reads); AI targets an `ai_region` × keyword.
Different targets, different invariants — keeping them apart means neither bends to fit the other.
Organic's one-active index is on `(snapshot_id, keyword_id)`, so a dozen prospects sharing a
submarket snapshot collapse to ONE billed capture; capture_organic is idempotent, so a re-order is a
free `done`. AI's is on `(ai_region_id, keyword_id)`; run_ai_scan is re-runnable (latest wins), so
its index only blocks a duplicate in-flight order, and a `done` requires ≥1 engine stored — `stored
== 0` fails the order (an outage must never be recorded as "the AI doesn't know this business").

**AI needs a human-seeded region, so the UI got a seed step — the I-073 invariant is intact.** The AI
scan runs at a coarse `ai_region` (a recognizable place name), NOT the fine submarket grid, and its
`name_level` is a human judgement the module forbids deriving. Only LA's regions were seeded, so a
typed any-city prospect had no region to target. Rather than auto-deriving a region (which would
break I-073) or leaving the AI button inert, `create_ai_scan_request` returns `ai_region_not_seeded`
when no region matches the prospect's submarket name, and the report UI opens a small seed modal
(`POST /outreach/ai-regions`, admin) where a human names the region — pre-filled to the prospect's
area so it MATCHES (the resolver joins region.name ilike submarket.name) — and picks its name_level.
Then it retries the order. The human still makes the recognition judgement; the tool just asks for it.

**Deliberately no per-user daily budget ledger (unlike enrichment).** Each run is ~1–3¢ and the
one-active index collapses many organic clicks in a submarket to one order, so the drain's
`max_market_run_cost_cents` gate + admin gating suffice. Enrichment bills per-contact, which is why
it carries a ledger; these do not.

## 2026-08-10 — Loss-framed, per-prospect "Why call?" hook (grounded LLM phrasing layered on the deterministic facts)

**The complaint:** the call hook read generic and identical for prospects in the same
submarket+keyword. Root cause (grounded in the code): `outreach_justification._hook` was one
template keyed on keyword+area+top-competitor+coverage-deficit — all shared across a submarket — and
led with coverage (the least per-prospect-distinctive fact). Owner also asked for **loss framing**
(consumers move on fear of loss).

**Two changes, deliberately separated.**

**(1) Deterministic side — loss-framed + lead with the distinctive fact.** `HOOK_PRIORITY` reordered
so the spoken hook LEADS with the most per-prospect-distinctive loss (paying-and-losing → a named
competitor taking the exact missing points → the business's own review deficit → then bare coverage,
which is shared across a submarket). `_hook` → `_compose_hook`, and every talking-point + headline
template rewritten from gain- to loss-framing ("every search for X is going to a competitor", not "a
gap you could close"). Output shape unchanged, so the report + existing tests are untouched except
the copy assertions. Two neighbours with the same coverage now diverge (one opens on its review
deficit, one on coverage).

**(2) Grounded LLM phrasing pass on top — the module docstring's anticipated extension.** A new
`services/outreach_call_hook.py` rewrites the deterministic hook into compelling, loss-framed,
per-prospect prose via `report_llm.run_forced_tool_sync` (the same grounded forced-tool transport the
maps/rank narratives use). This REVERSES the module's deterministic-by-default stance for the hook —
its docstring pre-authorizes exactly this ("an LLM phrasing pass can always be layered ON TOP later,
grounded on the facts THIS module already assembles"), so it is the planned path, not a new fork.

**Why this doesn't break "never invent a fact/competitor/number".** Three guards, in order of teeth:
- The model only RE-WORDS. It's handed the assembled facts; the caller keeps each talking point's
  `element`+`facts` and takes only the model's prose, so it can't add/drop/reorder a point or change a
  number-as-data.
- A deterministic **grounding guard** (`guard_output`, pure, unit-tested) rejects any output that
  slips a currency figure, a per-month/ROI number, or an estimated lead/job/sale/customer VOLUME
  through — precisely the fabrications fear-of-loss copy invites ("you're losing $8k/month", which is
  unprovable AND falsifiable in one sentence, PRD §9a.2). A regex can't be argued out of a verdict;
  the legitimate measured numbers (%, review counts, "top 3", points, miles) are deliberately not
  matched. Known limit: it targets the money/volume mode, not an invented competitor NAME (guarded by
  the prompt + the kept `element`/`facts`) — documented in-code.
- On any failure (no key, provider error, malformed response, guard rejection) the deterministic
  loss-framed hook (change 1) stands. A report never fails to render because phrasing was unavailable.

**Determinism/replayability is preserved at the CACHE, not the model.** `prospect_call_hook`
(migration `20260810160000`, applied live) stores the generated hook per (prospect, snapshot) keyed
by a SHA-256 `facts_fingerprint` over the deterministic facts (element + facts, NOT prose). A re-read
with a matching fingerprint returns the stored bytes (identical artifact, no second paid call —
reporting-spec §2/§6); a new scan changes a number → new fingerprint → regenerate. So the LLM runs
once per prospect×snapshot, and a report shared in March still regenerates identically in June.

**No per-report cost surprise, no frontend change.** One small cached call per prospect×snapshot,
default provider Anthropic (low volume, no fan-out 429 exposure like the maps report; flip
`outreach_call_hook_provider`). The justification's output shape is unchanged, so the report's
Call-hook section and the `/justification` panel both pick up the new hook with no UI change. Config:
`outreach_call_hook_llm_enabled` (default True) / `_provider` / `_model` / `_openai_model` /
`_max_tokens`. Pure logic (guard, fingerprint, prompt builder, lead-fact selection) unit-tested.

---

## 2026-08-10 — Category relevance: a three-bucket ingest gate (keep / review / drop)

**The problem, measured on live data.** A "plumbing contractor" onboard order for Inglewood pulled
135 GBPs; **~46% were not plumbing-service businesses** (apartment buildings, tool stores, painters,
HVAC firms, general contractors, and plumbing-SUPPLY warehouses), and about half of *those* survived
Stage A2 into the contactable set. Root cause: Google Maps category search fuzzy-matches adjacent
trades, and none of the six Phase-1 filter rules asked whether a listing is actually the searched
trade. The `category` was already parsed and stored on every prospect — it was simply never used to
filter.

**The decision.** Add a seventh filter rule, `category_relevant`, keyed on Google's own **primary**
category, with THREE outcomes rather than the usual two:

- primary category on the vertical's allow-list → **keep** (rule passes)
- primary off-list, but a **secondary** category matches → **review** (passes, but flagged; a human
  glances before contact — mirrors the franchise "flag, never exclude" posture)
- primary off-list, no secondary match → **drop** (rule fails, hard exclude)

**Why primary-not-any-subtype.** Measured: a Home Depot service desk lists "Plumber" among ten
subtypes, and an any-subtype match would auto-KEEP it — re-admitting the exact noise. Primary-category
matching is the precision point; secondaries feed only the review pile, which rescues genuinely
mislabeled plumbers (SLATER PLUMBING, primary "Contractor") without auto-keeping the generalists.

**Fail-open, everywhere, by this module's own rule** (a false exclusion is the one filter error with
no recovery path): the rule records NOT_EVALUATED and keeps the prospect when the gate is disabled,
when the vertical has no curated allow-list (`filter_category_relevance` map miss → `None`), or when
the listing carries no category at all. Enabling the feature for an un-curated vertical is a no-op,
not a mass exclusion.

**Human rulings win and are protected in the DB.** `category_status` ('unknown'/'relevant'/'review'/
'off_category'/'confirmed_relevant'/'confirmed_off') is re-derived each run, but a `confirmed_*`
ruling is preserved by extending the `prospect_preserve_decisions()` trigger (clause 4, symmetric with
the franchise clause) — same class as I-053/I-054, guarded in the database, not just at the call site.

**Retroactive clean is free.** `run_filter` re-derives from stored `raw` and upserts `filter_result`,
so switching this on and re-running re-buckets everything already pulled with **zero** Outscraper
spend — the module's "re-parsing raw is free, re-pulling is not" principle.

Config: `filter_category_relevance_enabled` (default True) + `filter_category_relevance` (ingest
category → accepted Google categories; seeded for plumbing only). Migration `20260810180000`.

**Deliberately deferred:** (1) the unbounded-`coordinates` geographic drift (a distinct, smaller
nearest-submarket distance gate); (2) curating allow-lists for verticals beyond plumbing — each new
vertical adds one map key. Both are additive and change the gate's inputs, never its mechanism.

### Addendum (same day) — distance gate folded in

The unbounded-`coordinates` drift noted as deferred above is now built as an eighth rule,
`within_area`. Outscraper's `coordinates` biases the search centre but does not bound it, so a
category pull returned a kitchen remodeler in Lompoc (~150 mi) for an Inglewood plumbing order. The
rule drops a listing whose location is further than `filter_max_distance_miles` (default **7 miles**,
owner ruling 2026-08-10) from its **assigned submarket centroid** — which, for the typed-city onboard
flow, IS the city centre (platform-api geocodes the typed city to that submarket). 7 miles keeps
results inside the city while still covering a business on its far side; the live Inglewood pull sat
entirely within 6.7 miles of centre. A market whose submarkets are spaced further apart may need a
looser cap, so it stays per-config.
Fail-open, like every rule: NOT_EVALUATED (kept) when disabled, when no centroid/cap is available, or
when the listing carries no coordinates (an unknown location is not a distant one). No migration — it
excludes via `filter_result` like the other hard gates; no new column. `filters` keeps its own
6-line haversine to stay dependency-free (a test pins it to `tiling.haversine_miles`). Config:
`filter_max_distance_enabled` (default True) / `filter_max_distance_miles` (7).
## 2026-08-10 — Always-on `tick-loop` worker (interactive orders drain in seconds, not on a cron)

**Complaint:** a UI-placed enrichment/scan order sat until the 15-minute cron picked it up — a
click-and-wait action felt hung. The order itself is fast (~5s once drained); the wait was entirely
the cron cadence.

**Why a cron can't fix it:** Railway's cron floor is **5 minutes**, so a cron can never be
interactive. Shortening 15→5 min (done as immediate relief) is the best a cron allows.

**Fix — the worker becomes a daemon.** New `tick-loop` command (`run_market.py::cmd_tick_loop`) runs
`cmd_tick` continuously with a short sleep (`tick_loop_interval_seconds`, default 8s), so a signed
order drains within seconds. It is the SAME tick the cron ran, so it inherits every safety property:
conditional claims (no double-spend), terminal order outcomes, free `collect`, and spend authorized
ONLY per signed order row — so `tick-loop` is deliberately NOT in `PAID_COMMANDS`, exactly like
`tick`, and an idle iteration spends nothing. Two robustness rules: a single bad iteration is logged
and swallowed (one transient error must not stop draining every client's orders), and SIGTERM/SIGINT
sets a stop flag so the loop exits cleanly AFTER the current tick (a deploy never severs a drain
mid-flight; the sleep is sliced so the stop is honored within ~¼s).

**Service config (cutover):** OUTREACH_COMMAND=`tick-loop`, `cronSchedule`=null (continuous),
`restartPolicyType`=`on_failure`. The last REPLACES the old `never`: `never` was correct when this
was a one-shot cron job; a daemon must self-heal from a crash (OOM/SIGKILL), and a clean SIGTERM exit
(returns 0) is deliberately NOT restarted (the new deployment takes over). `railway.toml` updated to
match so a future code deploy can't silently revert the policy. **Caveat recorded in railway.toml:**
do not repurpose this daemon service for a manual PAID one-shot (ingest/run) — under `on_failure` a
failed paid pull would restart and re-pull (the loop the old `never` guarded); run those via the
local CLI or an ephemeral job. The steady state here is tick-loop, whose restart just resumes
draining.

**Cost:** an always-on container (a few $/mo) vs a briefly-running cron — an accepted trade for
interactive latency (owner chose the always-on worker over the 5-min cron). No paid-call increase:
`collect` is free and drains only spend on authorized orders.

## 2026-08-11 — Whole-city onboards auto-seed a `city`-level AI region (sub-areas still go to the human seed modal)

**Friction:** AI-visibility scans resolve a prospect to an `ai_region` by NAME (its submarket name
`ilike` a seeded region name — `resolve_ai_region_for_prospect`). Onboarding a city
(`create_onboard_from_place`) created the market/submarket/keyword/order but NEVER an `ai_region`, so
every any-city AI scan hit `ai_region_not_seeded` until a human hand-seeded one from the modal. For
the common case that manual step has exactly one correct answer, so it was pure ceremony.

**Why one answer suffices for a whole city.** A whole-city onboard (no sub-area) names its submarket
after the city itself, and the operator picked a Google-resolved CITY — a locality by definition. The
four `name_level` choices collapse: `metro` makes a miss trivially dismissible (never seeded for a
pitch); `neighbourhood` is the silent-fallback trap and the only level with a downstream behavioural
consequence (the report caveat); `suburb` vs `city` render identically everywhere. So the whole-city
answer is always `city`, and it is never the one risky level.

**Fix.** `create_onboard_from_place` now calls `_auto_seed_city_ai_region` on the whole-city path
only (`picked_subarea` is captured before `sub_name` is reassigned to the city name). It reuses
`create_ai_region` (idempotent on `(market_id, name)`, non-destructive on conflict) and is
best-effort — a seed failure is logged and swallowed, never failing the onboard order it rides on.

**Not a breach of "name_level is a human judgement, never derived" (I-073 / I-004).** I-073's filter
exists to judge an AMBIGUOUS SUB-AREA NAME from self-naming evidence. A whole city is the opposite:
I-073 itself calls a real Google locality "close to a formality" / "very likely to survive a
recognition test" (Inglewood sits in its strong `city` list). We carry forward the KNOWN level of the
operator's explicit input; we derive nothing from scan data. A PICKED SUB-AREA — where suburb-vs-
`neighbourhood` recognition IS the judgement and the silent-fallback risk lives — is deliberately left
to the manual seed modal, untouched.

**Scope.** platform-api `services/outreach.py` only; no migration, no new config, no change to the
outreach drain or the manual `create_ai_region` route. Tests in `tests/test_outreach_onboard.py`
(auto-seed on whole-city, no-seed on sub-area, seed failure never fails the order).

---

## 2026-08-14 — `scan-tech` runs automatically in `tick` (free, idempotent, bounded)

Owner ruling: the free site-tech scan (paid-placement Slice B1) should run on its own each cycle
rather than as a manual `scan-tech` per market, and the already-completed Inglewood run's prospects
should get covered too. Added `scan_tech.run_tech_backlog`, drained by `cmd_tick` after the enrich
drain.

**Why it belongs in `tick`, unlike the manual command.** `cmd_scan_tech` takes a market-definition
FILE and scans that market. The any-city onboard path (Inglewood, LA-emergency-plumber) creates its
market dynamically and has no file, so the manual command cannot target those markets at all. A
DB-driven backlog drain has no such limit: it finds every prospect with a website and no CURRENT
tech signal, across all markets, and fetches them. That single mechanism covers each new run's
survivors the cycle after they land AND backfills any pre-existing market — Inglewood included — with
no operator step, which is exactly what was asked for.

**Free, so it drains like `collect`, not like a signed order.** `scan-tech` makes no paid provider
call (own HTTP GET — DECISIONS 2026-08-08 B1), so it is not in PAID_COMMANDS and needs no order row
or env token. It rides `tick` the same way `collect` does. A tech-fetch failure (a site blocking a
bot is routine) is best-effort and deliberately does NOT change the tick exit code — only a failed
paid ORDER does.

**Idempotent + bounded, so a perpetual cron cannot churn or run away.** `pick_backlog` (pure,
unit-tested) skips any prospect already carrying a current signal, so a drained backlog costs two
reads and stores nothing on later ticks. `tech_scan_per_tick` (default 100 ≈ one market's survivors)
bounds one heartbeat's fetches — worst case ~100/`tech_scan_concurrency` × timeout — so a large
market can't monopolize a tick or overrun the cron interval; 0 disables the drain. This preserves
the measured-vs-found discipline unchanged (a failed fetch still stores a `fetch_status`, never
`absent`) — the store path is the same `_scan_prospects` core the manual command now shares.

**Refresh cadence over fetch-once.** `tech_refresh_days` (default 45 ≈ three scan cycles, ~the
`max_delta_span_days` window) re-fetches a prospect's site once its latest signal ages past the
window, so the vendor-failing pairing (tech present + a fresh coverage delta) stays honest when a
business installs CallRail after we first looked — without re-hammering every site every 15-day
cycle. `tech_refresh_days = 0` reverts to fetch-once. Re-fetching costs nothing in dollars, only
politeness/wall-clock, so the light cadence is the conservative-honest default; a one-line config
change moves it either way.

**Scale assumption, stated.** The drain reads all website-carrying prospects and all current
tech-signal ids per tick, then diffs in Python (the `enrich_queue._already_enriched` precedent). At
the current portfolio size (hundreds–low thousands) that is two cheap paginated reads. If the
prospect table grows large enough that a full read per tick matters, replace the diff with a
NOT-EXISTS view / RPC — cheapest-to-reverse, so deferred until it bites.

**Scope.** Outreacher `api/` only: `config.py` (two settings), `scan_tech.py` (extract
`_scan_prospects`; add `pick_backlog` + `run_tech_backlog`), `run_market.py` (`cmd_tick` drain +
output block), `tests/test_scan_tech.py`. No migration — `prospect_tech_signal` already exists and
the write path is unchanged.

**Addendum (same day, adversarial self-review).** Two corrections after tracing the drain against
the always-on worker:

- **Throttle — the drain runs on the ~8s `tick-loop`, not the 15-min cron.** The paragraph above
  said "two cheap reads per tick"; under `cmd_tick_loop` (`tick_loop_interval_seconds`=8) that is
  ~two portfolio reads every 8s forever, and a real backlog's synchronous site-fetch batch (up to
  `tech_scan_per_tick`/`tech_scan_concurrency` × `tech_fetch_timeout_seconds`) blocks the next
  heartbeat — the one that drains newly-placed enrich/scan orders. So the drain is now throttled by
  the pure `scan_tech.backlog_due(last, now, tech_scan_min_interval_seconds)` (default 300s), keyed
  off a monotonic timestamp held in a `run_market` module global: a fresh cron process (state None)
  always runs it, the daemon runs it at most every ~5 min. `tech_scan_per_tick` was also lowered
  100→50 to halve the worst-case iteration block (~75s at 50/8/12). A throttled heartbeat emits
  `"tech": {"skipped": "throttled"}`.
- **Scoped signal read.** `_signaled_prospect_ids` now takes the candidate prospect ids and queries
  `prospect_tech_signal` with a chunked `.in_` (+ the `fetched_at` cutoff) — the
  `enrich_queue._already_enriched` precedent — so the read is bounded by the candidate set, not the
  whole signal history. This also closes the fetch-once (`tech_refresh_days=0`) path's unfiltered
  full-history read.

## 2026-08-26 — Site name-scrape: a FREE owner/manager fallback when Outscraper returns no name

**Decision.** Add an optional, user-triggered producer that scans a prospect's OWN website for the
owner/manager NAME when Outscraper enrichment couldn't get one (status `no_contacts`, or contacts
carrying an email/phone but no person). FREE — an own HTTP GET, the exact posture as `scan-tech`
(PRD §B3 "own request, not a paid service") — so it is NOT in `PAID_COMMANDS`, places no billed
order, and is STAFF-gated (not admin + budget-guarded, the enrichment bar): there is no spend to
authorize, matching `promote`/`touch` (commitments, not spend).

**Shape (mirrors the two proven siblings, no new architecture).**
- `api/services/name_extract.py` — PURE, role-anchored + schema.org extractor (the crux). A name is
  taken ONLY when tied to an explicit ownership/management role (`owner`/`founder`/`president`/…) or
  carried by JSON-LD (`founder`/`employee` with a matching `jobTitle`). Conservative by design: a
  bare Title-Case phrase with no role is nothing; the business name / nav chrome / trade words are
  rejected; the business-name check is ONE-DIRECTIONAL (I-099). Evidence is kept for replay.
- `api/services/name_scrape.py` — the producer: reuses `scan_tech.fetch_page` / `normalize_site_url`
  (one definition of "how we fetch a prospect's site") and does a BOUNDED same-host crawl —
  homepage + a few likely pages (about/team/contact/meet), capped by `name_scrape_max_pages` —
  because owners are rarely on the homepage. Measured-vs-found: a failed homepage fetch is
  `unreachable`, never "no owner named".
- `api/services/name_scrape_queue.py` — the drain (sibling to `enrich_queue`, minus the money): a
  `name_scrape_request` order, conditional claim, idempotent skip of `found`/`no_names` (retry
  `unreachable`/`failed`), chunked for crash isolation, batchable (several orders/tick). Store
  replaces ONLY the prospect's `source='site_scrape'` contacts — never the Outscraper ones (the two
  producers are independent). Wired into `cmd_tick` after the enrich drain; also a free `scan-names`
  CLI (`run_name_scrape_market`) for ops/backfill.
- Migration `20260826120000_name_scrape.sql` — `name_scrape_request` (no cost/budget columns, unlike
  enrichment) + `prospect_name_scrape` (per-prospect marker, `found|no_names|unreachable|failed`,
  keeping the measured-vs-found distinction). Found names land in the EXISTING `prospect_contact`
  with `source='site_scrape'` (no schema change there). Applied live to Outreacher.
- platform-api: `create/list/detail/cancel_name_scrape_request` (staff-gated routes
  `/outreach/prospects/{id}/scrape-names`, `/outreach/name-scrape`), the contacts reads now carry
  `name_scrape` status + each contact's `source`. Frontend: `useNameScrape` + a per-row "Scan site
  for names" fallback button (shown when the prospect has a website and no name is known yet), a free
  bulk `NameScrapeBar`, and a "from website" provenance badge on site-scraped names.

**Why a separate marker table, not reuse `prospect_enrichment`.** The two producers must be
independent — an enriched prospect can still be name-scraped and vice versa — and merging their
status would corrupt each drain's idempotent skip. Same reasoning as `prospect_tech_signal` sitting
apart from `prospect_enrichment`.

**Why user-triggered, not an auto-backlog.** The ask was to give the team the OPTION (owner request).
Unlike `scan-tech`'s auto-backlog, this does not run on every prospect each tick — it only drains
placed orders. An auto-backlog "scrape everyone who enrichment left nameless" is a clean follow-up on
the same machinery if wanted, but was deliberately not built.

**Config.** `api/config.py`: `name_scrape_max_pages` (5), `_max_names` (8),
`_fetch_timeout_seconds` (12), `_max_page_bytes`, `_concurrency`/`_chunk_size` (6),
`_orders_per_tick` (5), `_max_places_per_order` (200). platform-api:
`outreach_name_scrape_max_places_per_order` (200; no cost/budget keys — it is free).

**Unvalidated.** The extractor's PRECISION is unmeasured against real sites (I-114) — it is tuned to
fail toward a miss, but a caller must still verify a scraped name (hence the "from website" badge and
that these names carry no verified email/phone, unlike Outscraper contacts).

## 2026-08-26 — Name-scrape adversarial-review fixes (loose-form precision, wall-time budget, SSRF)

An adversarial re-read of the site name-scrape produced five fixes:

- **Loose-byline precision.** The punctuation-free `<role> <Name>` form fabricated a person from any
  page merely mentioning a president/CEO of another entity ("President Joe Biden" → "Joe Biden",
  "CEO Tim Cook"). `President`/`President & CEO`/`CEO`/`Principal` were removed from `_STRONG_ROLES`
  — they still extract on every PUNCTUATED byline ("Jane Doe, President", "President: …", "our
  President Jane"), only the bare loose form is withheld. Owner/Founder/Proprietor keep it.
- **`extract_names` truly never-raises.** A pathologically deep JSON-LD block could raise
  `RecursionError` from `json.loads`/the node walk, escaping the narrow `except (ValueError,
  TypeError)`. Added `_JSONLD_MAX_DEPTH` to `_iter_json_nodes` + caught `RecursionError` at parse.
- **Per-tick wall-time budget (`name_scrape_per_tick`, default 60).** Unlike enrichment (one provider
  call per place), a scrape does up to `name_scrape_max_pages` sequential fetches per prospect, so a
  200-prospect order could block the tick loop for many minutes. The drain now bounds prospects
  FETCHED per tick across and WITHIN orders: an order larger than the remaining budget is scraped up
  to it and left PENDING to resume next tick — the marker-based idempotent skip means a resume
  re-scrapes only the un-done prospects (no loss, no repeat). Order counters are the CUMULATIVE
  marker tally (`_order_marker_tally`), so a resumed order still reports its whole self.
- **SSRF guard (`name_scrape.is_public_host`).** The scrape reuses `scan_tech.fetch_page`
  (`follow_redirects=True`), so a malicious prospect site could redirect the fetch to an internal
  host (e.g. 169.254.169.254). The guard blocks localhost + IP-literal private/loopback/link-local/
  reserved hosts BEFORE fetching AND on the post-fetch `final_url` (a same-host page 301-ing to an
  internal address has its body discarded). Self-contained in `name_scrape` — `scan_tech` is
  untouched. DNS-rebinding (a hostname resolving to a private IP) is explicitly out of scope (I-116).
- **Frontend: staff-gate + error surfacing + dead-code removal.** The per-row "Scan site for names"
  button is gated on `isStaff` (the route is `require_staff`) and now surfaces a placement error
  instead of a silent 403. Removed dead backfill code in `merge_names`.

## 2026-08-26 — Web-search owner name: the PAID third-rung fallback (a guarded LLM exception)

**Decision.** Add a third owner/manager-name fallback below Outscraper enrichment and the free site
scrape: when both come up empty, the team can PAY for a web search that looks the owner up (news,
directories, licensing records, LinkedIn). OpenAI Responses API + `web_search` tool over httpx
(reuses `OUTREACH_OPENAI_API_KEY`; no `openai` SDK dependency), grounded on the business's own
name + address + category + website so the model resolves THIS business, not a namesake elsewhere.

**This is a deliberate, GUARDED exception to the "deterministic, never an LLM guess, never fabricate"
report ruling (2026-08-08).** A web search for "who owns X" is the single most fabrication-prone
thing the module does, so the guard is the strictest of any producer:
- **Require-citation (owner ruling).** A name is kept ONLY when the search returns a real SOURCE URL
  that names the person; an uncited name is DROPPED (`name_search.parse_search_answer`). The model is
  prompted for strict JSON `{found, name, title, source_url}` and told never to guess.
- **Same plausibility guard as the site scrape.** The kept name must pass
  `name_extract.is_plausible_name` (business-name/stopword rejection) — one definition of "is this a
  real person, not the business".
- **Surfaced as lowest-trust.** Stored `source='web_search'` with the citation in `raw`; the UI
  badges it "from web search — verify" as a link to the source, and it carries no verified
  email/phone. The report/scoring layers must continue to treat only the deterministic signals as
  fact — a web-searched name is a caller aid, never a measured fact.

**PAID, so it mirrors enrichment, not the free site scrape.** Signed `name_search_request` order
(admin-gated + per-user daily budget guard + `cost_ledger` write + free preflight estimate); the
`tick` drains it (`name_search_queue.py`, one OpenAI call per prospect, per-prospect isolation,
idempotent skip). Config on the outreach service: `name_search_model` (gpt-5.4),
`name_search_web_search_tool`, `_cost_cents`, `_chunk_size`, `_orders_per_tick`,
`_max_places_per_order`, `_max_names`, `_request_timeout_seconds`; on PLATFORM:
`outreach_name_search_cost_cents`/`_daily_budget_usd`/`_max_places_per_order`.

**Placement gate.** The paid order refuses (`nothing_to_search`) any prospect that already has a name
from ANY source or was already searched, so a bulk "search all" only bills the genuinely nameless.
The UI offers the web-search rung only after the site scrape came up empty (or there is no site to
scan), and only to admins.

Migration `20260826140000_name_search.sql` (`name_search_request` + `prospect_name_search`) applied
live to Outreacher. Names land in the existing `prospect_contact` (`source='web_search'`).
Unvalidated like every other name source (I-114 applies): calibrate the model/prompt from real
`prospect_name_search.raw` after the first live runs; the require-citation guard is the floor.
