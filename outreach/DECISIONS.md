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
