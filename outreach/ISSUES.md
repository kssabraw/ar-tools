# ISSUES.md — Outreach Pipeline

Known problems, open questions, and unvalidated assumptions. Append; do not delete resolved
entries — mark them RESOLVED with the date and what changed.

---

## OPEN — blocks build

### I-001 · Email sending vendor undecided
**Severity: blocks Phase 5. Calendar lead time.**
GetResponse is likely disqualified: its anti-spam policy prohibits non-opt-in addresses,
screening is automated and opaque, and suspension can be permanent — taking the list with it.
Outscraper-derived GBP emails fit exactly the profile their import screening targets. Cold B2B
email is legal under CAN-SPAM; the restriction is contractual, not legal. Purpose-built cold
outreach tooling sending through owned mailboxes is the lower-risk path.
**Action:** decide vendor, then start domain warming (3–4 weeks, cannot be compressed).

### I-002 · Sending domain not warmed
**Severity: blocks Phase 5. 3–4 weeks calendar.**
Start in parallel with Phase 1, not after Phase 4.

### I-037 · `LEAD_INTAKE_SECRET` unset; the intake endpoint has never been invoked
**Severity: blocks inbound capture.** Account action.
The `lead-intake` edge function is deployed and fails closed (`503 not_configured`) until the
secret is set in the dashboard. It has also never been called once — the build sandbox's network
policy blocks egress to the project host — so the deployed path is unverified end to end.
*Note:* under the suite-module ruling this function is a candidate for retirement — inbound could
arrive through a platform-api route instead, which would put it behind the same auth and logging
as everything else. Not decided; the function works and costs nothing to keep for now.

## OPEN — verification spikes

### I-003 · Outscraper pixel field unverified (~1h)
Unknown whether Meta pixel arrives in base or enrichment tier, and whether GTM-injected pixels
are detected. If GTM injection is largely missed, the site-fetch container parse is promoted from
false-negative check to required step, and the money-signal cost model changes.
**Blocks:** final cost modelling for money coefficients. See PRD §16a.1.

### I-004 · AI prompt granularity untested (~20m)
Which place-name level returns scale-appropriate businesses. Too coarse and the absence claim is
trivially dismissed; too fine and the model silently falls back to metro while you believe you
asked a specific question. See PRD §16a.2.

### I-005 · Map tile licensing unchecked (~30m)
Whether embedding a rendered tile in a client-facing PDF constitutes redistribution, and what
attribution must appear on the image. Attribution affects heatmap layout, so this must resolve
before the renderer is built. See PRD §16a.3.

## OPEN — spec inconsistencies found, not yet resolved

### I-006 · No-pain incumbents are not excluded, only mildly penalised
**Found while computing golden fixtures.**
The original concept said "exclude no-pain incumbents." The scorecard does not exclude them — it
applies −50 for coverage >80%, which strong reachability (+66) and GBP quality (+34) more than
offset. Golden fixture `F3_ceiling_incumbent` scores **525.5**, slightly *above* the mid-tier
prospect `F2_mid_email` at **525.0**.

In practice this may be harmless: at 50 starts per cycle out of 400+ qualified, a 525 never
reaches the shortlist. But the ceiling is softer than the concept described, and the score is
not communicating what it appears to.

**Options:** (a) accept — capacity filters them anyway; (b) add a hard gate excluding prospects
with no pain on any of the three pitches; (c) make the geogrid ceiling penalty larger than the
maximum reachability bonus.
**Recommend:** (a) at launch, revisit if incumbents appear in shortlists.

### I-007 · Golden fixtures cover Model A only
Models B and C have no fixtures. Lower risk — Model C is currently `p_reply × p_close` and Model
B is not used for ranking at launch — but the same silent-failure mode applies once they are.

## OPEN — unvalidated assumptions

### I-008 · Every scoring coefficient is an elicited estimate
No part of the model has been tested against a single reply. Rank order is a strong prior, not a
prediction, until ~100 prospects have been contacted.

### I-009 · Base reply rates are guesses
Email 5.5%, phone 25%. Phone is the weaker of the two and is observable first, since cycle one is
phone-only during domain warming. Overwrite with observed data; do not tune coefficients around
them.

### I-010 · Declining-velocity sign (+19) may be backwards
Argued that a business watching lead flow dry up is receptive. The opposite — dying business, no
budget — is equally plausible. Carries a wide prior (σ ≈ 1.0) so modest evidence will move it,
sign flip included. First isolate-test candidate.

### I-011 · Vendor-failing (+79) is the largest coefficient and has never fired
Requires two scan cycles before it can activate. Unvalidated at launch.

## OPEN — deferred by design

### I-014 · CRM scope is leads only, by decision
Expanded to cover inbound, referral, and manual leads (`lead.source`). Client management after
`won` remains out of scope. **The constraint that must not bend:** `outcome` stays strictly
outbound-sourced, or coefficients get fit on a population where half the leads never went through
scoring. Business reporting reads `lead.stage`; model fitting reads `outcome`.
*Revisit only if scope creeps toward renewals, upsells, or account health — at which point buying
beats building.*

### I-012 · Case-study coefficients inactive
AR holds no case studies in the target verticals. Top two bins marked `unavailable`; they
activate automatically as case studies are documented. Check whether WheelHouse IT's multi-market
local SEO work qualifies for the adjacent-vertical bin (+24).

### I-013 · Reply capture is manual
Adequate at ~5 replies/month. Build IMAP polling at ~30/month. `replied_at` is the field the
entire model is fit against, so a logging gap here costs more than anywhere else.

### I-038 · Phase 1's live `suppression` does not match `crm-layer-spec.md` §3
**Found while patching it for Phase 1b.**
Spec §3 defines `suppression` with separate `email` and `phone` columns plus `prospect_id`,
`reason`, `source`, and unique indexes on `lower(email)` and `phone`. The live Phase 1 table is
`(id, scope, value, created_at)` — a generic scope/value pair, no reason, no source, no unique
index. Phase 1b patched the live shape additively rather than recreating it, on the grounds that
Phase 1 is closed and its emit path will write the shape it knows.
Consequence: the spec's §6 views and §4 rules are written against columns that do not exist.
**Options:** (a) treat the live scope/value shape as authoritative and amend the spec;
(b) migrate to the spec's shape while the table is empty. **Recommend (a)** — scope/value
generalises to `place_id` suppression, which the spec's fixed columns cannot express.

### I-039 · `crm-layer-spec.md` §3 indexes a column that does not exist
`create index on lead_activity (prospect_id, occurred_at desc)` — `lead_activity` has no
`prospect_id` in its own DDL; it reaches prospects through `lead_id`. Minor, but it will fail if
applied verbatim. Logged rather than silently corrected, per the session protocol.
---

## RESOLVED

> **Numbering note.** Phase 1b's issues were first filed as I-015…I-019, which collided with
> Phase 1's own I-015…I-036 — the two tracks ran in parallel branches and both appended to this
> file from the same I-014 base. Phase 1b's have been renumbered into I-037+ and the resolved ones
> moved here. If you are chasing a reference to "I-017" written before 2026-07-31, it means the
> CRM schema divergence, now **R-012**.

### R-011 · The CRM needed Supabase auth users that were never going to exist
*Resolved 2026-07-31 by the suite-module ruling.* Phase 1b assumed staff would hold `auth.users`
accounts in the Outreacher project, because Retool was to connect directly with per-user JWTs.
`lead.owner_id` and `lead_activity.actor_id` had foreign keys to that table, and it held zero
rows — so leads could not be assigned to anybody.

Making the pipeline an AR Tools module dissolved the problem rather than solving it: platform-api
is now the only client, it holds the service role, and staff identities live in AR-Internal-Tools.
The FKs are dropped (they referenced a pool that will stay permanently empty) and those columns
now carry the **suite's** profile id, validated in platform-api. Nobody needs an Outreacher login.

### R-012 · Phase 1b's applied schema diverged from `crm-layer-spec.md` §3
*Resolved 2026-07-31 by migration `20260731190000_lead_crm_spec_reconcile.sql`, verified by 17
checks in `tests/lead_crm_rls.sql`.* Filed as I-017 before the renumbering above.

Phase 1b was built from a plan derived from the spec; the spec itself arrived afterwards. What was
corrected, while `lead` still held zero rows:

- **`source` could not record a `manual` lead** — the phase's primary use case. The old check held
  `('outbound_scan','inbound','referral')`; `'inbound'` was not a spec token at all and `manual`
  and `partner` were missing. Now the spec's six. `'outbound_scan'` was already exact and is
  unchanged, which is the one that mattered — Phase 3's `outcome` check compares that literal.
- **`lost_reason` was absent entirely**, with `lost_to` and the DB-enforced `lost_requires_reason`.
  §5 calls it the highest-value field in the layer and notes it is unrecoverable after the moment
  of loss. Modelled as a CHECK rather than a lookup table, deliberately unlike `stage`: stages are
  presentation and get edited, lost reasons are joined to scoring coefficients and adding one
  silently changes what a refit means.
- **`next_action` / `next_action_due` were absent**, so `v_overdue_actions` — which §10 designates
  the forcing function for manual reply capture — could not exist. Both added and the view built.
- **The stage vocabulary reintroduced `qualified`**, which §8a deliberately collapsed into
  `in_conversation`; and `disqualified`, which is a lost *reason*, not a stage. Both removed.
- `stage_changed_at`, `outbound_requires_prospect`, `non_prospect_needs_identity` added;
  `business_name`/`notes` renamed to the spec's `company_name`/`notes_intake`; `lead_activity`
  gained real `from_stage`/`to_stage` columns instead of burying them in `metadata`, so the
  acceptance criterion is checkable by query.
- **A straight §4 violation removed:** the migration had granted DELETE on `suppression` and
  shipped a delete policy, against "suppression records MUST NOT be deleted, ever". The invented
  `expires_at` went with it — a time-limited suppression is a soft delete of a record the spec
  treats as permanent.

Three divergences were **kept deliberately**: `lead_stage` stays a lookup table (the board needs
`sort_order` and `is_terminal`, neither of which survives in an enum) with the spec's values;
`actor_id` stays a uuid rather than the spec's `actor text`; and `unique (prospect_id, source)`
stays *alongside* the spec's plain unique, because the spec's key alone cannot support the
composite FK that makes Phase 3's outbound-only rule structural.

### R-007 · Phase 1b's grants removed nothing
*Resolved 2026-07-31 during Phase 1b verification.* Supabase's default privileges already grant
ALL on new `public` tables to `anon` and `authenticated`, so the migration's
`grant select, insert on lead_activity` was purely additive — it read like a restriction while
leaving UPDATE, DELETE and TRUNCATE in place. Append-only was therefore resting entirely on the
absence of an update policy, and an UPDATE with no matching policy silently affects zero rows
rather than erroring: a "save note" button would have reported success and changed nothing.
Separately, TRUNCATE is not subject to RLS at all. Fixed by revoking before granting; recorded as
a standing rule in `DECISIONS.md`. Row data was never at risk — RLS held the row-level line
throughout. The defect was that the wrong outcome was silent rather than loud.

### R-008 · Phase 1b's trigger functions were reachable as RPC endpoints
*Resolved 2026-07-31.* All three are `SECURITY DEFINER` — they write `lead_activity` on behalf of
a caller with no rights there — and living in `public` made them callable at
`/rest/v1/rpc/lead_flag_suppressed` and siblings by `anon` and `authenticated`. Invoking a trigger
function directly errors out, so it was not exploitable, but that is a weak thing to rely on for a
definer-rights function. `execute` revoked; `search_path` pinned on the fourth. Found by the
Supabase security advisor, not by the verification script — the two catch different classes of
problem, and both are worth running.

### R-009 · `now()` cannot appear in an index predicate
*Resolved 2026-07-31.* The intended partial index over live suppression rows was rejected — index
predicates must be immutable. Liveness is filtered at query time instead; the unique
`(scope, value)` index serves the lookup.

### R-010 · Phase 1b's `source` vocabulary was a guess
*Resolved 2026-07-31 when the specs were supplied.* Built without access to `crm-layer-spec.md`,
Phase 1b assumed `'inbound'` and `'referral'` alongside the known-exact `'outbound_scan'`. §3
names the real enum: `outbound_scan, inbound_form, inbound_call, referral, manual, partner`. The
guess was wrong, and the correction is tracked as part of **I-017**.


### R-006 · Phase 1 specified a geogrid placeholder score before any grid data exists
*Resolved while extracting the Phase 1 brief.* `START-HERE.md` and PRD §17 both put "placeholder
score = raw geogrid coverage deficit" in the ingest+filter phase, but geogrid data does not exist
until the scan phase. Phase 1 now writes no scores at all; the placeholder moved to Phase 2.

### R-001 · `grid_result` defined twice with conflicting schemas
*Resolved during consistency audit.* PRD carried an unpartitioned version with lat/lng; storage
spec carried the partitioned version without. PRD copy now marked context-only, storage spec is
owner. Would have caused an implementer to build the wrong table.

### R-002 · Storage projections sized for 12 market-verticals, not 50
*Resolved during consistency audit.* Every volume figure was understated ~4×. Corrected: ~64M
rows/year, ~2 GB steady state, and the Pro ceiling arrives in year one rather than year three —
making partitioning a Phase 2 prerequisite rather than a later optimisation.

### R-003 · Franchise coefficient could never fire
*Resolved.* Hard exclusion at the filter meant franchises were never scored, so the −87 penalty
was dead. Changed to flag-for-review.

### R-004 · `touch` and `lead_activity` duplicated send records
*Resolved.* `touch` is authoritative; `email_sent` and `call` removed as activity kinds.

### R-005 · `ai_name` collapsed two distinct geographies
*Resolved.* `ai_region` separated from `submarket`; multiple submarkets may share one region.

---

## OPEN — found during the Phase 1 build (2026-07-31)

### I-015 · `phone_type` is unobtainable in Phase 1 — brief self-contradiction
**RESOLVED by decision, kept for the record.** Brief §2 says "MUST capture `phone_type` where
available" and also "MUST request base tier only … do not enable [enrichments]". Carrier/type
comes from `phones_enricher_service`, which IS an enrichment. Both cannot hold.
*Resolution:* keep the column, always write `'unknown'`. Revisit at Phase 5 with the enrichment.

### I-016 · Review recency needs a second billed endpoint
Review timestamps are not in the base pull; they need `GET /maps/reviews-v3`.
*Resolution:* deferred to Phase 5 and reimplemented as relative VELOCITY rather than an absolute
9-month window — see DECISIONS.md. Sub-issue found while implementing: `filter_result.passed` is
`not null boolean`, so there is no "not evaluated" state. Handled with
`passed = true, observed_value = 'not_evaluated'` rather than omitting the row (silently absent)
or writing `passed = false` (a lie that would inflate every exclusion count).

### I-017 · "Overlapping radii" is not expressible against the Outscraper API
`coordinates` sets a search CENTRE; there is no radius parameter. A tile is therefore one query
per (category x submarket centroid), and the overlap between adjacent tiles is real but implicit.
**Consequence:** coverage completeness is not guaranteed by construction. The only observable
proxy is the tile overlap rate — if adjacent tiles return disjoint sets, the tiling is too sparse
and the market has holes. `tiling.DedupeStats.overlap_rate` and the per-tile counts exist to make
that visible; the §6 DoD query surfaces the returned-vs-deduped gap.
**Action:** check the overlap rate on the first real pull before treating the market as covered.

### I-018 · Outscraper base-response field names are unverified
outscraper.com and the api-docs SPA are Cloudflare-403 from the build environment. Endpoint paths
and REQUEST parameters were verified against the official outscraper-python SDK v6.0.4
(2026-06-11); the RESPONSE schema is not declared there. Only `place_id`, `name`, `phone` and
`site` (NOT `website`) are confirmed, from the SDK's own example.
*Mitigation:* `services/parser.py` is an alias map over stored raw, so re-parsing an entire market
against corrected aliases costs nothing and needs no re-pull. `parser.unmapped_fields()` logs
provider keys no alias claims.
**Action:** pin `FIELD_ALIASES` against the first real 20-row pull. Until then, treat
`business_status` in particular as assumed — the closed-listing gate depends on it.

### I-019 · `IF NOT EXISTS` is not a merge for `suppression`
The coordination note ("whichever migration runs second uses IF NOT EXISTS") does not make the
two shapes agree — it silently keeps whichever ran FIRST and no-ops the other, in whichever
direction. If the CRM spec's `suppression` differs from the Phase 1 placeholder, one of them is
wrong and neither migration will say so.
*Mitigation:* `services/suppression.py` reads defensively across candidate value columns and logs
loudly when rows exist but no recognised column does. **This fails OPEN, which is correct in
Phase 1 only** — the table is empty by definition and nobody is contacted. From Phase 5, where
suppression gates real spend and real sends, a load failure must become a hard error.
**Action for the Phase 1b session:** reconcile the two shapes explicitly with `ALTER TABLE`.

### I-020 · Franchise pattern list is a placeholder
No spec carries a chain-name list. `config.DEFAULT_FRANCHISE_PATTERNS` is a seed that has never
been checked against a real market pull. Low risk by construction — a match only flags, and
nobody is contacted in Phase 1 — but the flag is only as useful as the list.
**Action:** owner to supply/approve a real list per vertical.

### I-021 · `prospect.submarket_id` assignment was unspecified
Resolved as nearest submarket centroid rather than discovering tile, for determinism. See
DECISIONS.md.

### I-022 · "Real reported cost" is not available from the API
Brief §4 requires the ledger to record real cost, not estimates; §5 requires reconciliation
within 5%. The API does not appear to return a per-request cost.
*Resolution:* ledger stores `units x configured rate`; reconcile manually against the dashboard
once per cycle. The 5% criterion is relaxed, not met.
**Action:** set `OUTREACH_OUTSCRAPER_COST_PER_1000_PLACES_CENTS` from the real plan before any
production run — the abort gate is exactly as honest as that number. Placeholder is 200c/1000.

### I-023 · `keyword` is created but unused in Phase 1
Keywords drive Phase 2 scanning. Creating and populating it now is correct; nothing reads it.
Recorded so it does not read as an omission.

### I-024 · "Persist raw before parsing" is not literally achievable against `prospect.raw`
`prospect.raw` is `not null` on a row whose `place_id` and `name` are also `not null` — so
extracting those two fields is unavoidable before the row can exist. Implemented as: `raw` holds
the untouched provider dict, only `place_id`/`name` are read before insert, every other column is
derived from the stored copy. An optional on-disk landing (`raw_landing_dir`) writes the full
archive body before anything reads it, as a hedge against a crash inside Outscraper's 2-hour
retention window.
**Action:** revisit when R2 lands in Phase 2 — the landing belongs in object storage.

### I-025 · Grid point count (89) does not match the stated geometry (5-mile radius, 1-mile spacing)
`README.md` and the concept notes describe an "89-point geogrid" over a "5-mile-radius scan area
with 1-mile spacing". A 1-mile lattice bounded by a 5-mile radius contains **81** points, which is
also exactly a 9x9 square grid. 89 matches neither the inscribed-circle count nor any square
lattice.
**Why it matters now rather than later:** Phase 2 pins grid geometry into a versioned function
and persists its parameters per snapshot, and geometry is immutable once scanning begins. If the
intended shape is 9x9=81, or a 5-mile radius with a different spacing, or 89 points from some
other construction, that must be settled BEFORE the first scan. Afterwards it cannot be corrected
without invalidating every snapshot taken.
**No Phase 1 impact** — Phase 1 uses submarket centroids for tiling only and never touches radius
or spacing. Raised now because it is free to fix today and expensive in six weeks.
**Action:** confirm the intended point count and construction before Phase 2 builds the geometry
function.

### I-026 · Franchise pattern list can be bootstrapped from the first pull
No hand-written chain list exists (I-020) and the owner does not have one. A name appearing at
three or more distinct `place_id`s inside one market is almost certainly a chain, so the first
real pull can propose the list rather than requiring it up front. Proposed, not built — it would
be an addition to the existing rule, still flag-only, never an exclusion.
**Action:** run the repetition query after the first ingest and seed
`OUTREACH_FRANCHISE_PATTERNS` from what it surfaces, then keep the list in config.

### I-027 · The build sandbox cannot reach Outscraper or the Supabase REST endpoint
**Severity: blocks running Phase 1 from this environment. Does not block the code.**
The remote execution environment's network policy rejects CONNECT to all three Outscraper hosts
(`api.app.outscraper.com`, `.cloud`, `api.outscraper.net`) and to
`fkwhgvcggvsricuinuqy.supabase.co`. Confirmed via the agent proxy's own failure log
(`connect_rejected`, "gateway answered 403 to CONNECT"). The Supabase MCP is unaffected because
it uses a different authorised channel, which is why the migration and seed succeeded.
**Consequence:** the calibration pull could not run, so I-018 (response field names) and I-022
(real billing rate) remain open, and the ingest has never executed against the live API.
**Two ways forward:** (a) widen the environment's network policy to allow those hosts; or
(b) run `api.scripts.calibrate` and `run_market ingest` from the Railway service, where the
egress is unrestricted and the env vars belong anyway.

### I-028 · Host failover never triggered on a proxy rejection — FIXED
Found while hitting I-027. `httpx.ProxyError` is not a subclass of `httpx.ConnectError`, so the
client's failover loop did not catch it and gave up on the first host instead of trying the other
two. An egress proxy refusing CONNECT is exactly the case failover exists for.
*Fixed:* `outscraper_client.FAILOVER_ERRORS` now covers ConnectError, ConnectTimeout and
ProxyError. ReadTimeout is deliberately excluded — a slow response is the host working, not
failing. Regression-tested.

**I-027 update (2026-07-31):** re-tested after the calibration request; the egress policy still
rejects all three Outscraper hosts. `/root/.ccr/README.md` classifies a 403 from the gateway as
an organisation policy denial and directs that it be reported rather than retried or routed
around, so this is not a transient failure to work through. Added
`api/scripts/calibrate_standalone.py` — stdlib only, no repo or dependencies needed — so the pull
can be run from any host with egress and the output pasted back.

### I-029 · CORRECTION — `/maps/search-v3` is live, and the brief was right
**I previously recorded that the Phase 1 brief was stale for naming `/maps/search-v3`. That was
wrong, and the error is worth keeping visible.** I inferred "stale" from the vendor's current SDK
(v6.0.4) using `POST /google-maps-search`, and treated a newer client as proof the older path was
gone. It is not: `writer/platform-api/services/gbp_service.py` calls
`GET /maps/search-v3` with this same API key, in production, today.

Both endpoints exist. The client now supports both and DEFAULTS to `/maps/search-v3`, because
running-in-production evidence against this exact account beats a newer SDK.
`outscraper_search_endpoint` switches it. Request shape for each is regression-tested against a
mock transport.

*Method note:* the SDK's newer endpoint takes a JSON body with real booleans; `/maps/search-v3`
takes query params with booleans as lowercase STRINGS (production sends `"async": "false"`).

**Lesson for the rest of this build:** the AR Tools repo is itself a source of verified provider
behaviour and should be consulted before the vendor docs. It integrates Outscraper, DataForSEO
and several others against these accounts already.

### I-018 update · Response field names largely CONFIRMED, one gap remains
`gbp_service.py` resolves live maps responses using: `place_id or google_id` · `name` ·
`full_address or address` · `phone` · `site or website` · `category or type` then `subtypes`
(comma-joined string) · `rating` · `reviews` (the COUNT — `reviews_data` is the inline review
list and must never be read as a count) · `latitude/lat` · `longitude/lng` · `working_hours` ·
`location_link` · `area_service`. `parser.FIELD_ALIASES` now follows that ordering, and the
envelope (`data` as an array-of-arrays) is confirmed too.

**STILL OPEN: `business_status`.** No code in this estate reads it, so nothing has observed
whether Outscraper returns it, under what name, or with what values — and it is the only input to
the closed-listing gate, the first hard filter. `filters.evaluate` already treats an absent or
unrecognised status as `not_evaluated` rather than "closed", so the unknown cannot silently
exclude live businesses; the risk is the opposite one, that the gate never fires at all.
**Action:** confirm from the first real pull. If `business_status` is absent from the base tier,
the closed gate needs a different source and the brief's filter table needs revisiting.

**I-027 correction (2026-07-31):** I framed this as the egress policy rejecting Outscraper
specifically. It is broader and more mundane than that — the session is running at the **Trusted**
network access level, so everything outside the default package-manager allowlist is refused.
Measured from inside the session: `pypi.org` → 200 (on the default list), `example.com` → 403
(not on it, and obviously not blocked for security reasons). Same 403 for
`api.app.outscraper.com`, `fkwhgvcggvsricuinuqy.supabase.co` and `api.dataforseo.com`.

Two consequences:
1. **`api.dataforseo.com` is blocked too**, so this is not an Outscraper problem — Phase 2's
   entire scan layer (geogrid, organic SERP, AI surfaces) hits the same wall. Whatever resolves
   this now also unblocks Phase 2.
2. **Network access level is fixed at VM start.** A running session keeps the level it booted
   with, so changing the environment does not affect a session already in flight; a NEW session
   is required. Check with `curl -o /dev/null -w '%{http_code}' https://example.com` — 200 means
   the wider policy is live, 403 means the session is still on Trusted.

### I-030 · `outreach/supabase/` shadowed the installed `supabase` package — FIXED
The migrations directory was named `supabase/`, and once `/outreach` is on `sys.path` (which the
CLI does deliberately, and which the container's WORKDIR makes automatic) Python resolved
`from supabase import Client` to that directory as a namespace package rather than the installed
library. It fails as `cannot import name 'Client' from 'supabase' (unknown location)` — a message
that reads like a version problem rather than a name collision.
*Fixed:* renamed to `outreach/migrations/`, plus a `.dockerignore` that keeps migrations out of
the runtime image entirely (they are applied out-of-band, never by the job). Deliberately diverges
from the `writer/supabase/migrations` convention, which is safe only because nothing there ever
puts that directory on `sys.path`.

### I-031 · Railway `redeploy` re-runs the OLD deployment's config, not the current one
Changing `startCommand` and calling redeploy silently re-ran the previous start command — twice,
looking identical each time. `redeploy` replays a specific deployment; only a fresh deployment
picks up config changes.
*Consequence for this service:* the run mode must be driven by the `OUTREACH_COMMAND` variable
through one entrypoint (`run_market.py`), not by overriding the start command per run. `calibrate`
was added as a subcommand for exactly this reason.

### I-032 · Tile queries resolved to the WRONG STATE — found by the first live pull
**The most valuable thing the calibration produced.** A live pull for `plumber, Downtown Los
Angeles` (no coordinates, no region qualifier) returned businesses in **Jersey City, New Jersey**
— the first result was "City Plumbing & Drain Service, 290 Webster Ave, Jersey City, NJ", at
lat 40.75 / lng -74.04.

Outscraper resolves an ambiguous place name against its own server location. Most submarket names
are ambiguous nationally — Torrance, Whittier, Burbank, Hollywood and Pasadena all exist in
several states. **The failure mode is the dangerous kind:** a market full of the wrong state's
businesses is perfectly well-formed, parses at 100%, passes every filter, and is completely
worthless. Nothing downstream would have flagged it.

*Fixed:* geography is now pinned twice. `coordinates` biases the search centre (the ingest always
sent these; the calibration did not, which is why it drifted), and a new required-in-practice
`region` field on the market definition is appended to every tile query — `plumber, Downtown Los
Angeles, CA, USA`. `validate_definition` flags a market with no region. Regression-tested,
including the degenerate no-submarket path, which is the one most likely to be hit by accident.

**Lesson:** the calibration was only useful because it exercised the real request path. A
smoke test that differs from production in one parameter validates the wrong thing — the first
version of this one omitted coordinates and would have "passed" while proving nothing.

### I-018 RESOLVED (2026-07-31) · Response field names confirmed against a live pull
20/20 places parsed. Every alias resolved: `place_id` via `place_id`, `name`, `category` via
`category`, `address` via `address`, `phone`, `website` via `website`, `rating`, `review_count`
via `reviews`, `lat` via `latitude`, `lng` via `longitude`.

**`business_status` IS returned** — populated 20/20, value `OPERATIONAL` — which closes the open
half of this issue. The closed-listing gate has a real input and will fire. 49 provider keys come
back in total; the unmapped ones are all genuinely unused in Phase 1 (`about`, `area_service`,
`cid`, `h3`, `photos_count`, `reviews_per_score`, `verified`, `working_hours`, …).

Note `subtypes` and `type` are both populated, and `category` is present too — the alias order
taken from `gbp_service` (category → type → subtypes) resolved correctly on the first attempt.

**I-032 VERIFIED FIXED (2026-07-31).** Re-ran the same calibration with the fix in place:
`GET /maps/search-v3?...&query=plumber%2C+Downtown+Los+Angeles%2C+CA%2C+USA&coordinates=34.0407%2C-118.2468`
→ first result **"Alliance United Plumber Los Angeles", 1035 S Los Angeles St, Los Angeles, CA
90015**, lat 34.0390 / lng -118.2570 — roughly a mile from the submarket centroid. 20/20 parsed,
`business_status` OPERATIONAL 20/20, `phone` populated 20/20 (19/20 in the New Jersey run).

**I-027 RESOLVED (2026-07-31).** Superseded by the Railway service. The sandbox's egress
restriction no longer blocks anything: the pipeline runs where it will live anyway, with
unrestricted egress and the credentials already on the platform. The `calibrate_standalone.py`
script is kept — it is still the fastest way to sanity-check the provider from any machine.

### I-033 · Outscraper billing rate still unmeasured
Two calibration pulls have run (20 places each, 40 total). The API returns no per-request cost,
so the rate must come from the dashboard: divide the charge for those two requests by 40 and
multiply by 1000 to get `OUTREACH_OUTSCRAPER_COST_PER_1000_PLACES_CENTS`.
Until then the abort gate runs on the 200c/1000 placeholder. At 14 tiles x 400 places the
worst-case projection is $11.20 against a $50 ceiling, so the gate has ample headroom even if the
placeholder is wrong by 4x — but it should be set from measurement before the portfolio scales.

### I-034 · Railway reports a CRASHED job as deployment status SUCCESS
**Observed, not theorised.** With `restartPolicyType = NEVER`, the `filter` run died with an
unhandled `RuntimeError` (missing credential) and the deployment still showed **SUCCESS**, and
posted a green commit status to the PR.

**This is a live trap for an unattended cron job.** From cycle two onward nobody watches these
runs, and a failed ingest that reports green is indistinguishable from a healthy one — the market
would simply stop updating while the dashboard said everything was fine.

*Partial mitigation:* `run_market.main` now prints a terminal marker on every exit path —
`OUTREACH_RESULT status=ok|failed command=<cmd> exit=<n>` — including from the exception handler,
so it survives any failure mode. The deployment status is NOT a success signal; this line is, and
it is greppable from the logs.

**Still needed (Phase 2, with the scheduler):** something that actually reads that marker and
alerts. A log line nobody greps is only marginally better than a green tick nobody questions.
Options: Railway webhook on deploy, or the job posting its own result somewhere durable —
`cost_ledger` already gets a row per stage, so a `run_log` table is the cheap version.

### I-035 · The first real ingest lost 12 tiles of PAID work — FIXED
Deployment `923ef997` ran the real LA ingest: seeded, passed the cost gate, and pulled 12 of 14
tiles sequentially over ~4 minutes. At 09:09:54, mid-poll on the Torrance tile, the container
stopped. No traceback, no `OUTREACH_RESULT` marker, memory at 54 MB (no OOM), no superseding
deployment, no platform maintenance notice. The signature — abrupt silence with no Python-level
error — is an external SIGTERM, whose default handling kills the process immediately and prints
nothing.

**The termination cost nothing by itself. The DESIGN cost twelve tiles.** Every place was
buffered in memory and written in one bulk insert after the last tile, so an interruption at 12/14
discarded 12 tiles of paid pulls and left `prospect` empty. The brief's own principle —
"re-parsing from stored raw is free, re-pulling is not" — was applied per RUN when it needed to be
applied per TILE.

*Fixed, three ways:*
1. **Per-tile persistence.** Each tile's places are upserted the moment they land, with a
   `cost_ledger` row per tile so an interrupted run cannot under-report spend either. An
   interruption now costs the tile in flight, not the ones already bought.
2. **Bounded concurrency** (`outscraper_tile_concurrency`, default 4). Shrinks the window from
   ~5 minutes of wall time to ~90 seconds. Modest by default — this is a courtesy limit on a paid
   third-party API, not a throughput contest.
3. **SIGTERM handler** printing `OUTREACH_RESULT status=failed reason=terminated signal=15`, so
   an external kill is self-evident rather than silent.

Regression-tested: incremental writes, one failing tile not discarding the rest, cross-tile dedup
writing once, and the cost gate still firing before any client is opened.

**Root cause of the termination itself is NOT established** — only its signature. Candidates:
a Railway runtime limit for a container that binds no port, or platform-side reaping of a job
whose deployment already reported SUCCESS. Worth pinning down before the semi-monthly schedule is
set, because a recurring silent kill at ~4 minutes would cap how large a market can be ingested in
one run. The mitigations above make it survivable either way.

### I-036 · PostgREST silently truncated the filter at 1000 rows — FIXED
`run_filter` read prospects with an unbounded `select()`. PostgREST caps that at **1000 rows** and
returns the truncated set with no error, no header and nothing a caller could notice. Both LA
filter runs therefore reported `evaluated: 1000` against 1388 prospects, leaving **215 prospects
never filtered** — and the definition-of-done question "how many survived" would have undercounted
by that much, confidently and invisibly.

*Fixed:* `services/paging.fetch_all` reads page by page until a short page arrives, and every read
that grows with the portfolio now goes through it — prospects, submarkets, and **suppression**
especially, where a truncated read would silently contact people who asked not to be contacted.
`build_query` is a callable because supabase-py builders are stateful: reusing one compounds
`.range()` calls instead of replacing them, which pages wrongly in a way that also looks fine.

Regression-tested including the exact-multiple-of-page-size boundary, where a full first page must
provoke a second request.

### I-035 CORRECTED (2026-07-31) · The first run did NOT lose its work
I recorded I-035 as "the first real ingest lost 12 tiles of paid work". **That was wrong.** The
`cost_ledger` shows deployment `923ef997` wrote its ingest row at 09:10:59 (1399 places) and its
filter row at 09:11:01. It completed normally, roughly 70 seconds after the last log line I could
retrieve.

The mistake was diagnosing from a log stream that lags the container, treating "no new logs" as
"process dead", and not re-checking the database after the point where the old code would have
written. The Railway agent's "exited at 09:09:54" was inferred from the same lagging stream and
carried the same error. **Two sources agreeing is not corroboration when both read the same
instrument.**

The direct cost of that misdiagnosis: a `git push` while `OUTREACH_COMMAND=run` was still set
auto-deployed and fired a SECOND full paid ingest (1408 places, ~2.8x the placeholder rate) that
nobody asked for — the exact footgun documented in the Dockerfile comment, walked into anyway.

*What stands from I-035:* per-tile persistence, bounded concurrency and the SIGTERM marker are all
still right, and per-tile persistence is what makes the ledger legible enough to have caught this.
They were built on a false premise and remain worth keeping.
*What to change:* `OUTREACH_COMMAND` must be returned to `filter` IMMEDIATELY after any paid run,
not at the end of the working session. Better still, a paid run should require a token the deploy
path cannot supply on its own — a follow-up worth doing before the cron schedule is set.

---

## Linter state (2026-07-31)

The Supabase security advisor reports **no warnings** on this project — only ten INFO
`rls_enabled_no_policy` notices, which now include `lead`, `lead_activity`, `lead_stage` and
`suppression`. That is the intended posture under the suite-module ruling: RLS on, no policies,
reachable only by the service role platform-api holds. Do not "fix" them by adding policies.

An earlier revision of this file recorded six `rls_policy_always_true` warnings as permanent and
expected. That was true of the Retool access model and stopped being true when those policies were
dropped.
## Phase 2 foundations + suite router (2026-08-01)

### I-025 RESOLVED · Grid point count settled at 81
The specs did carry the answer; it was in the document nobody had cross-read against the count.
`reporting-layer-spec.md` §4.1 defines the generator explicitly — square lattice over the bounding
box, row-major from the NW corner, clipped to `distance <= radius_miles` — and that construction
contains **81** points at a 5-mile radius with 1-mile spacing.

Every alternative was computed, not assumed: hexagonal lattice **91**, concentric 8-point rings
**41**, unclipped 11×11 box **121**. Nothing yields 89, and the PRD hedges it as "~89" precisely
because it was an estimate. Implemented in `api/services/geometry.py` (version `v1`, 18 tests);
`README.md`, PRD §8b and the storage spec's volume arithmetic corrected with markers, not silently.

**CONFIRMED BY THE OWNER 2026-08-01.** Previously recorded here as decided-by-me pending
confirmation; that caveat is now discharged. The owner questioned the count (reasonably — see the
note below), the arithmetic and the cost lever were both put in front of them, and the ruling is
**keep 81**. Geometry is now fixed and freezes at the first scan.

*The question worth keeping, because it will be asked again:* "5-mile radius, one point per mile —
isn't that 25?" No: a 5-mile radius is 10 miles ACROSS, so a row holds 11 points (5 west + centre
+ 5 east), the bounding box is 11 x 11 = 121, and the clip leaves 81. 25 would need ~1.67-mile
spacing; a 5x5 box at 2.5-mile spacing clips to 13, not 25.

### I-040 · The lead audit trail had no actor under the module ruling — FIXED
`lead_log_changes` writes the stage-change and reassignment rows with `actor_id := auth.uid()`.
That was correct when the CRM was reached directly with a per-user Supabase JWT. Under the module
ruling platform-api holds the **service role** and is the only client, and `auth.uid()` is NULL for
the service role — so every stage change and every reassignment would have been logged
anonymously. The trail would exist, be append-only, be correct in every other respect, and be
unable to say who did anything.

Not caught by PR #534's 17 checks because `lead` held zero rows and no client existed; it only
becomes observable the moment something writes. **This is the general shape to watch for in the
rest of the module port:** the Retool-era schema assumed an end-user JWT, and anything else that
reads `auth.uid()` or `auth.jwt()` is now reading a null.

*Fixed:* migration `20260801110000` adds `lead.updated_by` (the mutation-side twin of the existing
`created_by`) and the trigger takes `coalesce(auth.uid(), new.updated_by)` — that order, because a
genuine end-user JWT, if one ever reaches this database again, is stronger evidence than a column
the caller populated itself. `services/outreach.update_lead` sets it on every update, not only on
stage changes.

### I-041 · 113 of the 925 LA survivors were never measured against the review-count bar
Surfaced immediately by the new `outreach_market_summary` per-rule split. `review_count_min`
reports 842 passed / 433 failed / **113 not_evaluated** — and all 113 are prospects where
Outscraper returned no `review_count` at all (verified: `count(*) filter (where review_count is
null)` = 113 = the not_evaluated row count).

The filter is behaving correctly — a rule that could not run cannot have failed, so it writes
`passed = true, observed_value = 'not_evaluated'` (I-016) — and Phase 1 contacts nobody, so
nothing is harmed today. But HANDOFF §2's per-rule table reports only the 433 failures, so the
113 are invisible in the numbers everyone is reading, and they are counted as survivors.

**Why it matters at Phase 5, not now:** those 113 would be enriched and contacted on a
qualification that was never checked. Roughly 12% of the shortlist pool.
**Action:** decide whether an unmeasurable review count should qualify. Options: (a) leave as-is
and accept the 12%; (b) treat missing review data as a soft exclusion pending enrichment; (c) let
the Phase 5 review-VELOCITY rule resolve it, since that pull returns the counts anyway — probably
the cheapest, since it needs no decision now beyond remembering to look.

### I-042 · The coverage rollup is specified but not implemented
`prospect_coverage` exists (storage spec §4 owns it) and `drop_cold_partitions` enforces its
presence, but `rollup_coverage()` is deliberately unwritten — `rank_vector` ordering depends on
the geometry generator and on land masking (`grid_point_status`, PRD-owned, absent), and a rollup
written before those exist would emit vectors that render every historical heatmap against the
wrong coordinates while looking healthy.

Consequence: **the retention job currently drops nothing but empty partitions**, by design. That
is the correct fail-closed posture and costs nothing while there is no scan data, but it must not
be mistaken for "retention is done". It is not done until the rollup is written and reconciled.
**Action:** build with the scan writer, in the same phase as land masking. `centroid_dist_at_loss`
must survive it (storage spec §4) even though it is derived.

### I-043 · `serp_result` payload offload to R2 is not built
The table carries `payload_path` / `payload_summary` per storage spec §6 and is partitioned, but
nothing migrates payloads to R2 and nothing monitors migration lag. `payload_path IS NULL` means
*not yet migrated*, never *absent* — a reader that treats null as missing data is wrong, and
CLAUDE.md lists that specific mistake as a plausible-looking action that is wrong.
**Action:** Phase 2's scan layer, alongside the R2 landing that ISSUES I-024 also wants.

### I-044 · `grid_result.scan_month` is not enforced against its snapshot
It is denormalized from `scan_snapshot.scanned_at`, and nothing forces the two to agree: a CHECK
cannot reference another table, and a per-row trigger on a table taking ~58M rows a year is not
worth its cost. A writer that computes the month from `now()` instead of the snapshot will split
one snapshot across two partitions — and the retention job's per-snapshot reconciliation would
then compare a partial count against a full one and blame the ROLLUP, sending the reader to debug
entirely the wrong component.
*Mitigation:* `verify_grid_result_months()` reports mismatches, and is cheap enough to run monthly.
**Action:** the scan writer MUST derive `scan_month` from the snapshot it is writing under, never
from the clock. Call it out in that PR.

---

## I-040 sweep + I-041 evidence (2026-08-01)

### I-040 sweep · Two failure modes, swept separately
Grepping `auth.uid()` uniformly would have conflated two things that fail differently, so the
Outreacher schema was swept as two lists.

**List A — expressions that RUN under the service role and receive null.** Column defaults,
generated-column expressions, CHECK constraints, view definitions, trigger bodies, and any
function reading `auth.uid()` / `auth.jwt()` / `auth.role()` / `current_setting('request.jwt…')`.
These produce the anonymous-actor pattern.

| Object | Kind | Reads | Status |
|---|---|---|---|
| `lead_log_changes` | trigger fn on `lead` | `auth.uid()` | **FIXED** — `coalesce(auth.uid(), new.updated_by)` |

**That is the entire list.** Zero column defaults, zero generated columns, zero CHECK constraints,
zero views, zero non-trigger functions, and zero `request.jwt` readers anywhere in `public`. The
other three triggers on `lead` (`lead_flag_suppressed`, `lead_log_suppressed`,
`lead_touch_updated_at`) reference no caller identity at all. `lead_log_changes` still *appears*
in the sweep because it still prefers `auth.uid()` when one is present — which is intended.

**List B — RLS policies.** Not evaluated at all under the service role: bypassed silently, and
therefore never a source of the anonymous-actor pattern.

**Zero policies exist in `public`.** The category is empty, which is the intended posture (RLS
enabled, no policies, no grants to anon/authenticated) rather than an absence to be fixed.

*Conclusion:* the port carries exactly one instance of this defect and it is fixed. The sweep is
worth re-running after any migration that adds a trigger or a default, since only List A can
regress.

### I-041 UPDATE · Population evidence gathered; Google spot-check NOT done
**Do not act on this yet — one input is still missing, and it is the one that decides the answer.**

**What the existing data already settles (free, whole population, no sampling):**

| Fact | Value |
|---|---|
| Prospects with `review_count is null` | 113 |
| …where the provider key `reviews` is PRESENT and explicitly JSON-null | **113 / 113** |
| …where `rating` is ALSO null | **105** |
| …where `rating` is populated but the count is null | **8** |
| Prospects anywhere in the market with `review_count = 0` | **0** |
| Prospects with counts of 1 / 2 / 3–5 / 6–9 | 118 / 70 / 129 / 116 |
| Prospects with a count but no rating | **0** |

Two readings follow, and they split the 113:

1. **This is not an alias or parsing gap.** The key is present on every one of the 113 and its
   value is null. `parser.FIELD_ALIASES` resolved correctly; there is nothing to re-parse.
2. **Outscraper appears to encode zero as null.** It reports counts down to 1 freely (118 rows)
   but emits `0` literally never, across 1,388 listings. Combined with 105 of the 113 also having
   a null rating — and a rating being an average *of reviews* — the 105 look like genuinely
   zero-review listings, which is precisely what the `>= 10` rule exists to catch.
3. **The 8 with a rating and no count are a real gap.** A 4.6-star rating cannot coexist with zero
   reviews, and every other rated prospect in the market carries a count. Those 8 are genuinely
   unknown, not genuinely zero.

**What is still missing: the direct Google Maps check.** It could not be run from the build
session — Google returns 403 to every route available here (Maps place URL,
`search.google.com/local/reviews`, and Google search), and raw egress is still blocked at the
Trusted network level (I-027). Search-engine snippets do not carry a Google review count. This is
an environment limitation, not a finding; **treat the reading above as strong circumstantial
evidence, not as the confirmation that was asked for.**

Ten place_ids are queued for that check the moment a session or machine with egress is available:
`ChIJ85sqYl65woAR0YobClIKhls`, `ChIJVVVVFfO7woAReGLHX8ivBxg`, `ChIJ64hlhLebwoAROhhNnojNZdo`,
`ChIJ40_30pDHwoARtA82xZQcoKo`, `ChIJbY6g6-GdwoARNlyGXEJituc`, `ChIJVVVVVdCkwoARv8EiT_bvoa0`,
`ChIJl5tHxGfJwoAReMBp7CpysXw`, `ChIJ9xXATQDHwoAR_sAcRRd0hrs`, `ChIJv6eS5sDBwoARkLhYDvw6DbQ`,
`ChIJB_aokmC5568ROqlq4J0YYPY` — plus **all 8** of the rating-but-no-count rows, which matter more
per listing than any of the 105 (`select … from prospect where review_count is null and
raw->>'rating' is not null`). Open as
`https://www.google.com/maps/place/?q=place_id:<id>`. The question is only: does the listing show
a review count, and is it zero or non-zero?

*(Aside worth noting for I-020/I-026: three of the ten carry `ChIJVVVVV…`-prefixed place_ids, a
Google pattern associated with weak/auto-generated listings.)*

### I-045 · Backfill review counts from the Phase 2 geogrid — free, from data already paid for
**Binding obligation on the scan writer, not a Phase 5 enrichment.**

DataForSEO Maps responses carry the review count per result, on the same item that carries the
`place_id` — so any of the 113 that appears at any grid point on any keyword resolves for **zero
additional spend**, from a response already being bought.

Field path **verified against this estate's production code**, not vendor docs (the I-029 lesson):
`item["rating"]["votes_count"]`, with `item["rating"]["value"]` as the rating and
`item["place_id"]` as the join key. Confirmed in `writer/platform-api/services/maps_dataforseo.py`
(`_business_from_item`) and `services/dataforseo_rank.py` (`local_pack` parsing). Both item shapes
carry `place_id` and `rating.votes_count` together, so the join needs nothing extra.

**The scan writer MUST** capture `rating.votes_count` per result and update
`prospect.review_count` (and `rating`) where the current value is null and the place_id matches,
then re-evaluate the affected `filter_result` rows.

**How many of the 113 this resolves is not yet knowable** — it depends on which of them appear in
a local pack, which no data answers until the first scan runs. It is reported after cycle one, by
comparing the count of `review_count is null` before and after. Listings with genuinely zero
reviews will mostly *not* appear in a pack, so a low resolution rate is itself evidence for
reading 2 above rather than a failure of the backfill.

### I-046 · Phase 5 precondition — unresolved filter evaluations gate SPEND, not the filter
**Recorded now so it is not rediscovered at the moment money is committed.**

A prospect whose filter evaluation is unresolved — any `filter_result` row with
`observed_value = 'not_evaluated'` on a rule that is enabled — **MUST NOT be enriched or
contacted.** It may pass through ingestion, scanning, scoring and audit generation unchanged.

This is deliberately the same shape as the franchise flag: the prospect proceeds through the
pipeline and is blocked before spend, rather than being excluded at the filter. The reasoning is
also the same — excluding at the filter permanently discards a prospect on the strength of a fact
nobody has established, whereas gating at the spend costs only a deferral, and by Phase 5 the
geogrid backfill (I-045) will have resolved most of them anyway.

Note the gate keys on `observed_value = 'not_evaluated'` for an ENABLED rule. A rule disabled by
config (`review_recency`, deferred by decision) writes the same sentinel and must NOT gate spend —
otherwise every prospect in the portfolio is blocked, since `review_recency` writes
`not_evaluated` for all of them.

### I-047 · Repointing the job at `main` sharpened the paid-run footgun — RESOLVED
**Severity: this is the one open item that can cost real money without anyone deciding to spend it.**

The `outreach` Railway service was repointed from the merged `claude/phase-1-outscraper-ingestion-llje34` to `main` on 2026-08-01, which was correct — a service deploying from a dead branch is a confusing thing to debug. But **"Auto deploys when pushed to GitHub" is still enabled**, and that setting means something very different now.

| | tracked branch | pushes to it | deploys of this job |
|---|---|---|---|
| before | a merged feature branch | none, ever | effectively never |
| after | `main` | several a day | **several a day** |

At `OUTREACH_COMMAND=filter` each such deploy is free — a filter re-run over 1,388 prospects and a $0 `cost_ledger` row. The exposure is I-035's footgun, which now has a far wider trigger: if the command is set to `run` or `ingest` for a deliberate run and not put back within minutes, **the next merge to `main` by anyone, on any unrelated PR, fires a paid ingest.** The duplicate LA ingest happened when the trigger was a push to a branch only that work touched; the trigger is now the whole repository's merge traffic.

**RESOLVED 2026-08-01** — auto-deploy is disabled on the service. Merges to `main` no longer deploy or run this job; it runs only on a deliberate Deploy click. The branch connection is retained, so the source repoint stands.

*What this does NOT resolve.* Disabling auto-deploy removed the trigger that had just widened from one dormant branch to the whole repo's merge traffic. Two paths remain, and the second is scheduled to arrive:
1. A **manual Deploy while `OUTREACH_COMMAND` is `run` or `ingest`** still spends money — and it is the same click used for a legitimate free `filter` run, so the two are indistinguishable at the moment of clicking.
2. **Setting a `cronSchedule`** — the stated plan once the first real ingest is validated — re-arms it twice: a Railway cron service runs its start command on every deploy *and* on schedule (`railway.toml`).

So §7.2's requirement is untouched and now has a deadline: a paid run must need something the deploy path cannot supply on its own (`--confirm`, a date-stamped token, or a last-ingest-was-≥N-days-ago check) **before any cron schedule is set**.

### I-048 · Railway's config API disagrees with the dashboard after a staged change — resolved, recorded
Changing the source branch reported "applied — staged for deployment" while `get-service-config` continued to report the **old** branch. Neither was wrong: the change was staged, and that API reports the currently-deployed config. The dashboard showed `main` immediately and settled it.

Recorded because the natural next move on an apparently-failed infra write is to retry it, and retrying a write you cannot confirm is how one change becomes two. When two instruments disagree, find a third (§6.3, §6.11).

### I-049 · The Railway agent's persistent memory carries two false facts about this service
It wrote itself a project memory during the repoint. Two entries are wrong and will be repeated confidently if anyone consults it:

1. **Start command** recorded as `python -m api.scripts.calibrate "plumber, Downtown Los Angeles, CA" 20`. That is a stale one-off calibration command; the real one is the `run_market` entrypoint driven by `OUTREACH_COMMAND`.
2. **The Phase 1 run** recorded as exiting silently with "**NO OUTREACH_RESULT marker**" — the original I-035 diagnosis, which is **debunked**. The run completed normally at 09:11:01 and the log stream lagged. That misdiagnosis is what caused the duplicate paid ingest.

Low stakes and not worth chasing, but a second source repeating a debunked failure story is exactly how a corrected mistake gets un-corrected.

### I-041 UPDATE (2026-08-01, second pass) · The 8 checked, the 105 NOT verifiable from here

**The 8 (null count + numeric rating) — all eight checked. Verdict: provider gaps, not zeros.**

| Business | Our rating | External finding | Google-specific? |
|---|---|---|---|
| **Mejia Rooter** | 5.0 | **"5.0 on Google Reviews based on 3 reviews"** | **yes** |
| DARROW Heating & Air | 4.6 | "4.6 stars from 13 reviews"; Birdeye 15 | ambiguous |
| Mobile Vet, Glendale | 4.3 | 4.3 / 84 reviews — Yelp | no |
| Troutwine Plumbing | 4.4 | Birdeye 24, Yelp 58, "108 online" | no |
| A.S. Photography | 5.0 | Yelp 44 | no |
| PHCC Greater LA | 4.8 | Facebook 6, 86% recommend | no |
| USA Business Insurance | 4.8 | Yelp + own-site, no count | no |
| J & D HVAC, Silver Lake | 3.0 | not found anywhere | no |

Only one yielded an explicitly-Google count, but **all eight are real, established businesses with
review presence somewhere** — none resembles a new zero-review listing. They stay NULL and route
to I-045.

**APPLIED: Mejia Rooter `review_count = 3`** (owner ruling). 3 < 10, so it now FAILS
`review_count_min` and is excluded. **Survivors 925 → 924.** The lesson generalises: resolving the
8 can REMOVE survivors, not merely fill blanks.

**The 105 (null count + null rating) — the spot-check could not be run.**
Every route is closed from the build session: WebFetch 403s on Google *and* on third-party mirrors
(Birdeye); raw egress is blocked at the Trusted network level (I-027, re-tested and unchanged);
all three Outscraper hosts are unreachable. WebSearch works but returns synthesized third-party
aggregates, and the question requires proving a **negative** — a listing with 0 Google reviews and
one with 3 produce identical empty results. Three were tried (Fast Leak Detection, Global Plumbing
& Fire, Sunstate Plumbing); all returned no count, which is consistent with zero and equally
consistent with three.

**The owner's mechanical argument, which was under-credited first time round:** a rating is an
average, so zero reviews cannot produce one; null+null is therefore internally coherent, and the
105:8 ratio points the same way. The counter is narrower than first stated — H2 does *not* need a
second unobserved failure mode, because a single one (the review block failing to parse) would
null both fields together. That makes the 8 the stranger shape, not the 105. Both hypotheses need
a mechanism; H1 is the more economical, and that is why ground truth is worth buying rather than
reasoning about further.

**Corrected survivor arithmetic** — the premise that the rule drops ~105 is wrong: **only 89 of
the 105 are currently surviving** (the other 16 already fail another rule).

| | count | pass rate |
|---|---|---|
| Survivors now (Mejia applied) | **924** | 66.6% |
| If the flag were set on all 105 | 835 | 60.2% |

### I-050 · Re-asking Outscraper is not independent of the hypothesis it would test
**Bounds what the approved ~$0.10 can buy, so it is recorded before the money is spent.**

The question is whether *Outscraper* encodes "no reviews" as null. Asking Outscraper again cannot
answer it: if the null comes from its parser failing to read the review block, it fails identically
on the second pull, and the answer returns null either way. **The ambiguous value is also the
expected value.**

A detail pull is still worth running, because of the *sub-objects* rather than the count field:
`reviews_per_score` (the star histogram) and `reviews_data` (inline reviews). Neither can exist
without reviews, so either one contradicts "zero" on a listing whose count is null.
`review_verify.classify_lookup` is built around that and treats an all-zero histogram as a
rendered empty widget rather than as evidence.

**The genuinely independent check is a different vendor.** DataForSEO returns `rating.votes_count`
on the same item as `place_id` (verified in `platform-api/services/maps_dataforseo.py`), and that
credential does not exist on the outreach service (HANDOFF §8.2). If the Outscraper pass comes back
mostly `ambiguous`, the next step is DataForSEO, **not more Outscraper pulls.**

### I-051 · `review_count_inferred_zero` shipped, deliberately unset
Migration `20260801130000`, applied live. A boolean on `prospect`, wired into
`filters.evaluate(..., inferred_zero=)` and read from the column by `pipeline.run_filter`.

`review_count` stays NULL on these rows **forever**. Writing 0 would launder an inference about a
vendor convention into a measurement of a business: afterwards a real 0, a genuine zero-review
listing and a guess would read identically, and withdrawing the inference would mean working out
which zeroes had been ours. A DB constraint (`inferred_zero_requires_null_count`) makes the two
mutually exclusive, and `filter_result.observed_value` records `"0 (inferred)"` so the audit trail
says the exclusion rests on an inference.

**Zero rows are flagged and behaviour is unchanged.** The flag is applied by hand, once, on
evidence — `verify-reviews` reports and never acts.

**To spend the approved ~$0.10** (needs egress, so from the Railway service or any machine with
credentials — auto-deploy is off, so this is a deliberate Deploy):

```
OUTREACH_COMMAND=verify-reviews        # then Deploy; returns to `filter` afterwards
# or locally:
python -m api.scripts.run_market verify-reviews markets/los-angeles-plumbing.json --limit 20
```

Read-only apart from a `cost_ledger` row, cost-gated before any client is opened, and it prints
`by_verdict` / `counts_found` / a recommendation. **A single `has_reviews` in the sample withholds
the flag** — it would be written across every future market pull, so one false zero here is a
systematic error there.

### I-052 · Disabling auto-deploy PINS the service to its last-built commit — found by a failed run
**This is a direct consequence of the I-047 mitigation and was not anticipated when it was
recommended.** "Auto deploys when pushed to GitHub" does not only stop deploys on push; it stops
Railway *tracking* new commits at all. The service stays pinned to the last commit it built, and a
variable change redeploys **that snapshot** rather than fetching the connected branch's HEAD.

Observed: with the source correctly set to `main` (dashboard-confirmed) and `verify-reviews` merged
to `main`, setting `OUTREACH_COMMAND=verify-reviews` deployed commit `7f9430b` from
`claude/phase-1-outscraper-ingestion-llje34` — the old branch — and failed with
`invalid choice: 'verify-reviews'`. **Nothing was spent**: argparse rejects before any client is
opened.

So the repoint is real in config and **inert in practice** until something explicitly deploys a
newer commit. To run new code: deploy the latest commit from the Railway dashboard (the service's
Deploy control offers it when undeployed commits exist), or re-enable auto-deploy briefly and turn
it back off.

*Do not "fix" this by leaving auto-deploy on.* The pinning is the safety property working: this
service spends money, and a job that only ever runs code someone deliberately deployed is the
posture I-047 was asking for. The cost is one extra click, paid at the moment of running.

**Two things the same failure settled for free:**
- The build log loads `outreach/Dockerfile`, so `railway.toml` **is** read and the DOCKERFILE
  builder is in effect. The `RAILPACK` value reported by the config API is the stale pre-override
  field, not what builds. Closes the ambiguity noted in HANDOFF §1.
- Deployment status came back **SUCCESS** on a job that errored — I-034 observed live a second
  time — and **no `OUTREACH_RESULT` marker printed**, because argparse exits before `main()` can
  emit one. The marker does not cover bad-argument failures, which is precisely the shape an
  unattended cron misconfiguration would take.

### I-053 · A verified review count did not survive a filter re-run — FIXED
**Found while checking the retry path, not by a test.** `pipeline.run_filter` re-parses `place`
from stored `raw` on every run and passes THAT to `filters.evaluate`. The `prospect.review_count`
column was selected but never handed to the filter. Mejia Rooter's manually-confirmed count of 3 —
an owner ruling — lives only in the column, because `raw.reviews` is still null and always will be.

**The next routine `filter` run would therefore have scored it `not_evaluated` and silently
returned it to the survivor set**, reverting the ruling with nothing anywhere reporting it. Same
family as I-035 and I-036: correct-looking output, quietly wrong, no signal.

*Fixed:* `evaluate(..., review_count_override=)`, threaded from the COLUMN by `run_filter`. An
externally-obtained count — a manual verification, or the Phase 2 geogrid backfill (I-045) — beats
a re-parse of the provider payload, in both directions. Three regression tests, including the
exact Mejia shape (raw null, column 3, must exclude).

This also makes I-045 land correctly when it arrives: the backfill writes the column, and the
filter now reads it.

### I-054 · CLASS AUDIT — human decisions overwritten by re-derivation
**Prompted by the observation that I-035, I-036 and I-053 are three instances of one pattern:** a
decision is stored in a column, and some later code path re-derives that value from source and
overwrites or ignores it. Nothing errors. The revert surfaces weeks later as "why did that number
move". Fixing instances does not catch the fourth, so every column that can hold a human decision
was audited against every path that writes it.

| Column | Holds a decision? | Re-derived by | Risk | Status |
|---|---|---|---|---|
| `prospect.franchise_status` (`confirmed_*`) | reviewer read the listing | `run_filter`'s unconditional `update({franchise_status: 'flagged'})` | **CONFIRMED** | **FIXED** |
| `prospect.review_count` (verified) | manual or geogrid | `run_filter` re-parses raw **and** the ingest upsert rewrites from payload | **CONFIRMED, two paths** | **FIXED** |
| `prospect.review_count_inferred_zero` | inference about a vendor convention (I-051) | nothing today | latent | guarded preemptively |
| `prospect.latest_review_at` | Phase 5 review recency | ingest upsert writes `None` unconditionally | **latent, will bite at Phase 5** | flagged below |
| `prospect.submarket_id` | not today | ingest recomputes nearest-centroid | none now | documented, unguarded — see below |
| `submarket` geometry | yes | `seed` | already guarded | `check_geometry_change` — the existing precedent |
| `lead.stage` / `owner_id` / `lost_reason` / `next_action` | all human | nothing re-derives | none | safe by construction |
| `lead.suppressed_at` / `suppression_reason` | trigger-set | `BEFORE INSERT` only, never on update | none | safe |
| `suppression` rows | human | nothing; no delete path exists | none | safe |
| `conflict_check.decision`, `audit_approval.state` | future | not built | future | flag at build time |

**`franchise_status` was the worst of them and had not been noticed.** `run_filter` updated every
pattern-matching prospect to `flagged` unconditionally, so a reviewer's `confirmed_independent`
was reset on the next routine run — and `confirmed_franchise`, a *stronger* statement than
flagged, was silently downgraded. The code carried a comment saying "never writes
`confirmed_franchise` — confirmation is a human act", which shows the author considered not
*writing* a confirmation and not that the same update *destroys* one.

**`review_count` had a second revert path** beyond the one fixed in I-053: the ingest upsert
(`on_conflict = place_id`) rewrites it from the payload on every re-ingest. A call-site fix in
`run_filter` alone would have left that open — which is the argument for guarding the class.

*Fixed structurally, in the database.* `prospect_preserve_decisions()` (`BEFORE UPDATE`, migration
`20260801140000`) preserves a verified `review_count`, a `confirmed_*` franchise ruling, and the
inferred-zero flag, **regardless of which code path writes** — the ingest, the filter, a future
backfill, or a hand-written UPDATE at 2am. Provenance comes from a new
`prospect.review_count_source` (`provider` | `verified` | `geogrid`); a write that does not claim
better provenance cannot overwrite a value that has it, and one that does (the I-045 backfill)
still can. A human can always revise their own ruling. Six live guard checks pass.

Plus the call-site half, so intent is legible where it is enforced: `run_filter` skips confirmed
rows, and `filters.evaluate(..., franchise_decision=)` makes the *verdict* honour the ruling in
both directions rather than contradicting the stored status on every run.

**`latest_review_at` is the fourth instance, found by this audit before it could bite.** The ingest
writes `None` unconditionally, so once Phase 5 populates review recency, a re-ingest will null it.
Not guarded now because nothing writes it yet and a guard on a column with no writer is untestable.
**Action for the Phase 5 session:** add it to `prospect_preserve_decisions()` in the same migration
that starts writing it.

**`submarket_id` is deliberately unguarded.** It is recomputed on every re-ingest, but
nearest-centroid is deterministic and depends only on geometry, which is immutable once scanned
(DECISIONS.md) — so a re-ingest reproduces the same value rather than reverting anything. It joins
this class the moment a human can reassign a prospect by hand, and no such path exists. Recorded so
the absence is a decision rather than an oversight.

### I-052 UPDATE · Fixed — the job now says which code it is, and bad invocations report
**The build banner.** Line one of every run is now
`OUTREACH_BUILD sha=<12> branch=<b> commands=<list>`. The SHA is baked at image build from
`RAILWAY_GIT_COMMIT_SHA` (Dockerfile `ARG`) with a runtime env fallback. **The command list is the
half that always works** — a SHA can read `unknown` if the platform does not expose its git vars,
but the subcommands come from the running code, so a stale image is self-evident either way. The
container that failed I-052 would have shown a list without `verify-reviews` on line one, instead
of announcing itself by rejecting an argument several seconds later.

**I-034 closed properly.** `parse_args()` is now inside the try. Argparse raises `SystemExit`,
which derives from `BaseException` and not `Exception`, so a handler guarding only `Exception`
never fired for exactly the failure an unattended misconfiguration produces — a wrong
`OUTREACH_COMMAND`. Note the process *did* exit non-zero all along; the missing half was the
marker, and Railway's SUCCESS badge is unaffected either way, which is why the marker is the
signal and the badge is not. `--help` still exits 0 and is not reported as a failure, or whoever
greps these markers learns to ignore them. Four subprocess regression tests, including the exact
`verify-reviewz` shape.

### I-055 · Task-state persistence has no table, and the PRD data model has no place for one
Raised by the `tasks_ready` ruling (DECISIONS.md, 2026-08-01), which makes durable task state a
hard requirement rather than an implementation detail: **an un-persisted task id is a paid task
that can never be collected**, and no amount of later reconciliation recovers it.

Nothing in the PRD's schema holds one. `scan_snapshot` is per submarket × keyword × cycle and is
written when results EXIST; a submitted-but-uncollected DataForSEO task has no row anywhere. At
81 points × 10 submarkets × 3 keywords that is ~2,430 in-flight ids per market-vertical per cycle.

**Needs a `scan_task` table** (or equivalent) before the scan layer is built, carrying at minimum:
the DataForSEO task id, the snapshot/submarket/keyword/point it belongs to, `submitted_at`,
`collected_at`, and a status. The submission run writes it; the collector marks it; the ~5-day
alert and the 3-day fallback both read it.

**Two things it must support that are easy to miss:**
- The 30-day retrievable-by-id window is longer than the 3-day ready-list window, so the table has
  to survive well past the point where `tasks_ready` stops mentioning a task.
- It is the only place that can answer "did we pay for a result we never collected", which is the
  question the cost reconciliation (I-022) will eventually need.

### I-056 · The collector needs a SECOND Railway schedule, and the cadence is a trap
The `outreach` service currently has no cron schedule at all. The ruling requires **two**
independent cadences on what is one service:

| Run | Cadence | Cost |
|---|---|---|
| submission (scan) | semi-monthly, 15 days | **paid** — `task_post` |
| collection | hourly or daily | **free** — `tasks_ready` and `task_get` do not bill |

**The trap:** a collector running on the scan cadence lets every task age off the ready list
between runs, silently demoting the normal path to the id-fallback path. That still works, which
is precisely why nobody would notice — the same shape as I-035/I-036/I-053, where the wrong
behaviour produces plausible output.

Railway gives one `cronSchedule` per service, so this needs either a second service sharing the
image (with `OUTREACH_COMMAND=collect`) or an external tick. **Decide before the scan layer is
built**, because the collector's existence changes what the submission run is allowed to assume:
it must NOT wait for its own results.

Note also that auto-deploy is off (I-047) and a Railway cron service runs its start command on
every deploy — so whichever way this is wired, deploying it will fire one immediate run. Free for
the collector; not free if the two ever share a command.

### I-057 · DataForSEO wired as the independent check for I-041
`api/services/dataforseo_client.py` + `verify-reviews --provider dataforseo` (now the **default**).

Endpoint and request shape taken from this estate rather than the vendor docs — the I-029 lesson.
`platform-api/services/gbp_service.py` has called `POST /v3/business_data/google/reviews/live`
with `{"place_id": ...}` and HTTP basic auth against this same account, in production, for months.

**It is a better instrument than a count field.** It takes a `place_id` and returns the review
objects *plus* `reviews_count`, so "does this listing have reviews" is answered by the presence of
reviews rather than by re-reading a number that may be null for the very reason under
investigation. And a DataForSEO `reviews_count` of **0** is a positive assertion of zero — exactly
what Outscraper never emits across 1,388 prospects, and the single most valuable answer the run
can return.

Four verdicts, and the third is the one that matters most:
`count > 0` or items present → `has_reviews` · `count == 0` → `zero` · `count is None` →
**`ambiguous`, never `zero`** (rounding a second silence down would let absence of evidence argue
for the conclusion under test) · lookup failed → `error`.

`--provider outscraper` is kept, because the COMPARISON is the result: two vendors agreeing on a
null is evidence, one vendor repeating itself is not (I-050).

Credentials are Railway reference variables (`${{PLATFORM.DATAFORSEO_LOGIN}}`), so no secret was
copied and a rotation propagates. Cost is a configured per-request rate
(`dataforseo_cost_per_request_cents`, default 1c) — like the Outscraper rate it is not reported
back by the API, so the abort gate is exactly as honest as that number (same caveat as I-022).

### I-058 · The build banner's BRANCH label is stale on Railway — SHA is the signal
The first deployment of main's HEAD printed
`OUTREACH_BUILD sha=b8a0e3295661 branch=claude/phase-1-outscraper-ingestion-llje34`. The SHA was
correct; the branch was the stale connected branch Railway still had on file. Since the whole
point of the banner is to make a wrong build obvious, a wrong-looking branch beside a right SHA is
exactly the kind of thing that would send someone chasing the wrong problem. Noted in the code:
**the SHA and the command list are the signals; the branch is context.**

### I-053 VERIFIED IN PRODUCTION (2026-08-01)
The free `filter` run on deployment `601e1c23` confirmed the `review_count_override` fix against
live data: **survived 925 → 924**, `review_count_min` failures **433 → 434**. Mejia Rooter's
manually-verified count of 3 survived a full filter re-run and kept it excluded — the exact silent
revert that prompted the class audit, now proven fixed where it counts rather than only in tests.
