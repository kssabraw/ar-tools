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

### I-004 · AI prompt granularity untested — INSTRUMENT BUILT, not yet run (~20m)
Which place-name level returns scale-appropriate businesses. Too coarse and the absence claim is
trivially dismissed; too fine and the model silently falls back to metro while you believe you
asked a specific question. See PRD §16a.2.

**Built 2026-08-04:** `api/services/ai_granularity.py` (pure analysis + one OpenAI call) and the
`probe-ai-granularity` command. Nine chat completions — three place names × three samples — with
the prompt identical across levels except the place name, temperature 0 so repeats measure the
model's stability rather than sampling noise we introduced, and a summary reporting cross-level
Jaccard overlap, within-level stability, and error/empty counts kept separate.

The key is `OUTREACH_OPENAI_API_KEY = ${{PLATFORM.OPENAI_API_KEY}}` — a Railway *reference*, so no
secret is copied and a rotation propagates. The unblocking that was pending in I-073 is done.

**Three things this deliberately does not do.** It does not pick the granularity — that is a human
call recorded in `ai_region.name_level`, and the output says so in the payload rather than only in
a docstring, because the payload is what gets pasted into an issue. It does not default the three
place names; I-073's free evidence run already narrowed which LA names are worth testing, and
choosing among them is a judgement about the market. And it does not treat a failed call as an
empty answer — an outage must not read as "the model does not know this place".

**To run:** it is in `PAID_COMMANDS` despite costing well under a cent, so it needs
`OUTREACH_CONFIRM_SPEND=probe-ai-granularity` alongside `OUTREACH_COMMAND` and
`OUTREACH_ARGS="--metro 'Los Angeles' --suburb 'Woodland Hills' --neighbourhood 'Hollywood'"`,
then a fresh Deploy (a redeploy replays the old config snapshot). Hollywood is the right fine
name to test: I-073 found it commercially real (13 self-named businesses) but addressed
"Los Angeles" by Google — exactly the silent-fallback case.

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

**CONFIRMED STILL UNBUILT — 2026-08-25, after four completed live scans** (LA, Whittier,
Inglewood, Van Nuys — all 81/81, rolled up). The scan writer does NOT yet do any of the above:
`maps_scan.GridRow`/`parse_grid_result` keep only `place_id` + `rank`, `grid_result` has no review
column, and the `votes_count` the response carries is dropped. Direct evidence:
`review_inferred_zero_audit` = 0 rows, `contradicted` = 0, `review_count_inferred_zero` still set
on **105** prospects — unchanged across four scans covering real plumbers. So HANDOFF §9's
promise that "the geo-grid scan will audit the flag" cannot fire until this obligation is
implemented; §9 now carries a correction marker pointing here. This is the canonical home for the
gap (found independently while verifying the scans and reconciled to I-045 on merge — do NOT open
a duplicate). Cheapest close if the review signal is never actually needed by scoring: withdraw
§9's expectation rather than build the capture — decide when Phase 4 scoring first reads review
counts as a feature.

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

### I-059 · `reviews/live` does not exist, and platform-api has been swallowing the 404
**Measured, not inferred.** The free `probe-dataforseo` command posted a deliberately-invalid task
to seven candidate paths against these credentials (a rejected task is not billed, so discovery
cost nothing):

| path | HTTP | task status | exists |
|---|---|---|---|
| `/v3/business_data/google/reviews/live` | **404** | — | no |
| `/v3/business_data/google/reviews/live/advanced` | 404 | — | no |
| `/v3/business_data/google/reviews/task_post` | 200 | 40503 | **yes** |
| `/v3/business_data/google/my_business_info/live` | 200 | 40501 *"Invalid Field: 'keyword'."* | **yes** |
| `/v3/business_data/google/my_business_info/live/advanced` | 404 | — | no |
| `/v3/business_data/google/my_business_info/task_post` | 200 | 40503 | **yes** |
| `/v3/serp/google/maps/live/advanced` | 200 | 40503 | **yes** |

**Two findings.**

*Mine.* I-057 above asserted `reviews/live` was "production-proven against this account" because
`platform-api/services/gbp_service.py` calls it in production. It is called there. It also 404s. I
confirmed the endpoint was CALLED and claimed it WORKED — which is the shallow version of the
I-029 lesson I was citing while doing it. Twenty lookups failed; **no money was spent**, because
DataForSEO bills on task acceptance. The corrected instrument is `my_business_info/live`, whose
own 40501 named the field it wanted.

*A live suite defect, outside this pipeline.* `gbp_service._fetch_reviews` wraps the call in
`except httpx.HTTPError: return []`. `httpx.HTTPStatusError` subclasses `HTTPError`, so the 404 is
caught and returned as "this business has no reviews". **GBP review enrichment has been silently
returning nothing for as long as that endpoint has been gone**, with no error surfaced anywhere.
Not fixed here — it is in `writer/platform-api`, a different service on a different database, and
it wants its own change with its own verification. Raised for the owner.

The value form inside `keyword` is still unmeasured, so `build_lookup_bodies` tries three rungs
(`place_id:<id>` → name+coordinate → name+country) and keeps whichever the account accepts. A
name-search rung can answer about a *neighbouring* business, so `place_id_matches` is checked and
a mismatch classifies **ambiguous**, never as evidence — a true review count for the wrong listing
is worse than no answer, because it looks exactly like an answer.

### I-060 · Seventeen log lines printed their message and dropped their content
`run_market.py` configured `format="%(levelname)s %(name)s %(message)s"`, which renders nothing
from `extra=`. Every call site in `api/` puts its payload there: the `place_id` and error of a
failed lookup, the row count behind the I-036 truncation guard, the projected spend before a paid
run, the host in "outscraper host unreachable, failing over". All of it was being written and none
of it printed — and because the sentences themselves read fine, the logs looked healthy.

Fixed at the formatter (`_ExtraFormatter`), not at the call sites: the call sites are correct,
this is a rendering bug, and a fix at the formatter also covers lines not yet written.

### I-061 · DataForSEO returned NO review count for any of the 20 — I-041 still open
First real DataForSEO run (deployment `b8297c77`, commit `225d061`, 2026-08-01):
`{"error": 4, "ambiguous": 16}`, `counts_found: []`, recommendation **INCONCLUSIVE**.

The `place_id:<id>` keyword form works — every successful lookup reports `form: "place_id"` and
the returned `place_id` matched the one asked about, so no name-search fallback was used and no
result is about the wrong business. Cost was `0.0054` per task, ~$0.11 for the run.

**Of the 16 that completed, not one returned a review count.** No explicit zero, no positive
count. DataForSEO found each business (`Top Sewer Hollywood`, `California Rooter & Plumbing`,
`Sloane Plumbing & Heating`, …) and reported no `votes_count`.

**This is not evidence for the flag, and the temptation to read it as such is the exact failure
mode this module exists to avoid.** Two readings produce identical output:

1. Both providers omit the count when a listing genuinely has no reviews. → the flag is correct.
2. `my_business_info` does not carry review counts, or we are asking it wrongly. → the flag would
   be applied to 105 prospects on a measurement error.

Nothing observed so far distinguishes them, so `classify_dataforseo` returns AMBIGUOUS and the
verifier writes nothing. **`review_count_inferred_zero` remains unset. The 105 stay NULL.**

**The control group settles it, and is cheap.** `verify-reviews --group control` samples
prospects whose review count is already KNOWN. If the same call returns a `votes_count` for
those, the silence on the 105 is the provider asserting zero. If it returns nothing for those
either, this endpoint does not measure what we are asking it and no volume of further lookups
against it will ever mean anything. ~5 lookups, **~$0.03**. Awaiting approval — the previous
approval was for a specific 20-lookup run, which has now happened.

Three defects the run exposed, all fixed in `0cbe246`:

* **4 of 20 timed out.** `my_business_info/live` is a live endpoint (~19s typical, long tail) and
  was running under the 60s Outscraper timeout. It has its own 180s budget now. A timeout here is
  not merely a lost answer — DataForSEO has already run the query, so it is a lookup paid for and
  discarded.
* **Those 4 logged `error: ''`.** httpx timeout exceptions carry an empty message. Errors are
  typed now (`ReadTimeout: ...`).
* **The sample log truncated at 2000 chars and cut off `rating`**, which sits after `latitude` in
  the item's field order — so the one field the question turns on was the one field not logged,
  and "the provider said null", "the provider said nothing" and "the parser missed it" were
  indistinguishable. `rating_evidence()` now logs `rating` / `rating_distribution` /
  `has_rating_key` verbatim, for every lookup.

### I-062 · The I-059 suite defect is fixed — and it was two consumers, not one
I-059 found that `platform-api` calls `POST /v3/business_data/google/reviews/live`, that the path
404s, and that `except httpx.HTTPError: return []` turns the 404 into "this business has no
reviews". It was raised for the owner as one live defect in `gbp_service`. Fixed now, and the
audit found **a second consumer with the same dead endpoint and the same swallow**:

`services/review_analytics.py` — the whole Tier-B review-intelligence feature (review volume,
velocity, rating distribution, recent negatives, client vs competitor comparison) — imported the
endpoint constant *from* `gbp_service` and wrapped it in the identical handler. Its `_store()`
no-ops on an empty list, so nothing was ever written; `analyze_reviews([])` then returned
`count: 0`, `velocity_per_month: 0.0`, `recent_negatives: 0`, and `detect_review_gap` found no gap.

**This is the worse of the two.** `gbp_service` degrades to Outscraper's inline `reviews_data`, so
it has had real review text all along. `review_analytics` had no fallback, and every one of its
headline outputs has zero as a *legitimate* value — so the failure did not present as an outage,
it presented as a confident measurement of a client with no reviews.

The fix, in `writer/platform-api`:

* **`services/dataforseo_reviews.py`** (new) — the corrected instrument, with the probe-confirmed
  paths from I-059 and the dead one named-but-unused so nobody re-derives the discovery. A failed
  lookup **raises `ReviewFetchError`**; only the provider may assert zero. Task-level errors
  inside a 200 raise too — `raise_for_status()` never sees those.
* **`gbp_service`** — the DataForSEO leg is removed, not repointed. The endpoint that exists for
  review *text* is the queued `task_post`→`task_get` lifecycle, and this runs inside a
  synchronous user-facing details fetch. It uses the Outscraper inline reviews it has effectively
  been using for months, now stated rather than accidental.
* **`review_analytics`** — uses the queued lifecycle (it is a background job; it can wait) and
  reports `failures` per place. "No reviews in this market" and "we could not ask" are separate
  answers again.

**What is verified and what is not.** The error semantics are unit-tested (14 tests, and the
error tests are the point — a 404, a transport error, a task-level error and absent credentials
must all raise rather than return `[]`). The `task_post`/`task_get` *result envelope* is parsed
tolerantly but has **not** been confirmed against a live paid task — the probe established that
the lifecycle exists, not what it returns for these credentials. That is exactly why the failure
path was fixed first: if the shape is wrong, the next call raises and says so, instead of quietly
meaning "no reviews" for another few months. One paid task closes it.

### I-063 · The spend guard was procedure-safe, so it failed — now it is fail-safe
A `redeploy` fired `verify-reviews` with none of its intended flags and spent **~$0.11** on the
20-lookup `both_null` default, a group already measured in I-061. The approved run was
`--group control --limit 5`, ~$0.03. Nothing was corrupted — the run completed `status=ok`,
20/20 ambiguous, and it did incidentally retire the I-061 timeouts (0 errors this time, against
4 before) — but it is money spent on a question already asked.

**Three causes, and only the third is worth fixing.**

*The proximate one.* `redeploy` replays the old deployment's config snapshot (§6.1), which
predated `OUTREACH_ARGS`, so the container ran the bare default. Documented, and not read first.

*The discoverability one.* HANDOFF §6.1 described this exact trap. HANDOFF is only read by someone
who thinks to open it. The Railway traps now also live in repo-root **`CLAUDE.md` → "Railway
deploy traps"**, which auto-loads every session.

*The real one.* `OUTREACH_COMMAND` held a **paid** command as its resting state, in a service
where any deploy runs whatever is set. The mitigation for that was a sentence in a runbook —
"set it back to `filter` immediately after any paid run" (§160/§306). That procedure was followed
and it still misfired, because a procedure cannot protect the window between setting the variable
and the deploy that reads it, and cannot protect a snapshot replayed from before the window.

**The fix: the safe state is the default, and spending carries intent.**

* Absent, empty or whitespace `OUTREACH_COMMAND` resolves to `filter` (`resolve_command`).
* Every paid command additionally requires `OUTREACH_CONFIRM_SPEND` to equal **that command's own
  name** (`spend_denial`), checked before the handler and before any credential is touched.
* `probe-dataforseo` stays free and ungated until `--sample-place-id` makes it bill, which is
  passed as an explicit override rather than encoded in the paid set.

The token names the command deliberately. A boolean (`CONFIRM_SPEND=true`) authorizes whatever
happens to be set, which is this incident exactly. A token that must equal the command means a
**replayed or half-updated config cannot spend**: the leftover confirmation names a different
command than the one about to run, and the run refuses. The two variables also fail safe
independently — change the command and forget the token → refused; leave a token behind and the
command reverts to `filter` → nothing paid to authorize.

The banner now carries both, so line one says what a run is about to do:

    OUTREACH_BUILD sha=… branch=… command=verify-reviews PAID confirm=(unset) commands=…

A refusal exits non-zero through the existing marker path (`OUTREACH_RESULT status=failed`), so a
job that declined to work is as visible as one that crashed — silence would make it look like a
run with nothing to do. 20 tests, including the replayed-stale-token case and an end-to-end check
that the refusal happens before the provider is ever contacted.

### I-064 · I-063 blamed the wrong cause: the startCommand override has no slot for OUTREACH_ARGS
**Correcting my own diagnosis.** I-063 attributed the ~$0.11 misfire to `redeploy` replaying a
stale config snapshot (§6.1). That is a real trap, but it is **not what happened here**, and the
service config says so plainly:

    startCommand  sh -c "exec python -m api.scripts.run_market
                         ${OUTREACH_COMMAND:-filter} ${OUTREACH_MARKET:-…}"

**No `${OUTREACH_ARGS}`.** The Dockerfile CMD gained the slot in "Give the runner a slot for
flags"; this **service-level dashboard override**, which Railway applies over the image CMD, never
did. `railway.toml` sets no startCommand, so there was nothing to override it back. Every flag ever
put in `OUTREACH_ARGS` has been dropped before argparse saw it — the variable has never worked on
this service.

*What disproves the snapshot theory.* The 03:40 run **executed `verify-reviews`**. That value came
from `OUTREACH_COMMAND`, which had been set at 02:05 with `skipDeploys=true` — i.e. AFTER the
deployment being replayed. A replayed variable snapshot would have run `filter`. So variables were
read live; only the arguments went missing, and they went missing in the start command.

This is a more dangerous failure than the one I recorded, because it is **silent and total**: a
dropped flag does not error, it just leaves the CLI on its defaults. `--group control --limit 5`
became "the 20-lookup both_null default" with nothing in the log marking the difference, and the
same override would have dropped those flags on a *fresh* deploy too. The fix belongs in config,
not procedure: the override now carries `${OUTREACH_ARGS:-}`.

*What I-063 still gets right:* a paid command as a service's resting state is a loaded default,
and `spend_denial` remains the correct guard. It would not have prevented THIS run — the token
would have matched `verify-reviews`, which is genuinely what was intended — but it does prevent
the leftover-value case, which is a different and equally live risk. Both fixes stand.

*Standing corollary:* **`get-service-config` before believing the Dockerfile.** The same endpoint
also reports a stale `builder` (`RAILPACK` while `railway.toml`'s `DOCKERFILE` is what builds,
I-052), so it is authoritative for the start command and corroborated-only for the builder.

### I-065 · The service still tracks the dead branch, so a Deploy click builds 2026-08-01 code
The approved control run was deployed and **failed without spending anything**:

    run_market.py: error: argument command: invalid choice: 'verify-reviews'
                   (choose from 'seed', 'ingest', 'filter', 'run', 'calibrate')

The container held **`7f9430b`** — "Handoff document for the next session", the HEAD of
`claude/phase-1-outscraper-ingestion-llje34`, which predates `verify-reviews` entirely. This is
I-052 recurring, and the reason is in the service config: `source.branch` is **still the dead
merged branch**. HANDOFF §290 listed repointing it to `main` as a pending cleanup; it was never
done, so a Deploy click faithfully builds that branch's HEAD.

No `OUTREACH_BUILD` banner and no `OUTREACH_RESULT` marker appear in the run's logs — both
postdate `7f9430b` — so it failed exactly the way I-052 describes: silently, behind a green
SUCCESS badge. The banner cannot warn you about a commit old enough to predate the banner.

**Unblocking the control run needs a dashboard action**: repoint `source.branch` to `main`. The
Railway MCP `update-service` explicitly does not handle source changes, so this cannot be done
from a session. Once repointed, a Deploy picks up `59abd4a` (the spend gate) and the corrected
start command together, and the banner will read
`command=verify-reviews PAID confirm=verify-reviews` before it spends.

### I-066 · The control group ran: the instrument is VALID, and I-064's fix is proven
Deployment `73f2ea06`, commit `a7a206d` (main), 2026-08-03. **5 of 5 control lookups returned a
review count.** ~$0.027.

| business | count | rating |
|---|---|---|
| CastleWorks Water Heaters | 232 | 4.8 |
| Kerrygold Plumbing, Inc. | 30 | 5.0 |
| Derek's Plumbing & Water Heater Repair | 7 | 5.0 |
| Noble Plumber's Experts | 3 | 5.0 |
| Maximum Plumbing | **1** | 5.0 |

All `form: "place_id"`, all `error: null`, `OUTREACH_RESULT status=ok exit=0`. The run's own
verdict: *"INSTRUMENT VALID — 5 of 5 completed lookups returned a count for a listing known to
have reviews. A missing count on the 105 is therefore the provider declining to report."*

**Maximum Plumbing is the row that carries the argument.** A single review is reported as
`votes_count: 1`, so the instrument resolves all the way down to one. A listing with *any*
reviews would have produced a number.

**What this settles for I-041, stated exactly.** The 20/20 silence on `both_null` is no longer
uninterpretable: it is not a broken endpoint, a wrong keyword form, or a parser miss, because the
same call on the same day against the same account returned counts for five listings. Two
independent vendors now decline to report a count for those prospects.

**What it does NOT settle.** Neither vendor ever emits an explicit `0`. DataForSEO reports absence
as a null `rating` (`has_rating_key: True`, value None), not as `votes_count: 0`, so "zero
reviews" remains an *inference from corroborated absence* rather than a provider assertion. The
I-057 verdict rules are unchanged and still correct: `count is None` classifies **ambiguous, never
zero**, so nothing was written and `review_count_inferred_zero` stays unset.

**The open decision is a human one:** whether corroborated absence from two independent vendors is
sufficient to set `review_count_inferred_zero` on the 105. The evidence for it is now as good as
this method can make it; the remaining gap is that no source will ever say "0" out loud. Recorded
here rather than acted on, per the class audit — a judgement of this kind must not be re-derived
by whoever next reads the table.

**Also proven here: the I-064 fix.** Line one read
`command=verify-reviews PAID confirm=verify-reviews`, and the run reported
`{'places': 5, 'group': 'control'}` — the flags reached argparse for the first time on this
service. The repointed source (`branch=main`) also retired the stale-branch label from I-058: the
banner now reports the branch it actually built.

### I-067 · `review_count_inferred_zero` APPLIED to the 105 — owner decision, 2026-08-03
Applied live to the Outreacher project. **105 rows flagged, `review_count` left NULL on every
one.** Verified after: 105 flagged, 0 flagged rows carrying a count, 0 carrying a rating, and the
7 rating-without-count provider gaps untouched (that set is 7, not the original 8, because Mejia
Rooter now carries its corrected count of 3 — I-053).

*The reasoning, per the owner:* the evidence will not improve by waiting. No source will ever
affirmatively report zero — that is the vendor convention under test — so holding the inference
open means it never resolves. Rating-is-an-average is **mechanical**, counts-down-to-1-but-never-0
is **distributional**, and two vendors corroborate absence with 20/20 silence and no timeouts
(I-066). The flag exists precisely so the inference is visible and reversible rather than certain.

**Migrations:** `20260803210100_set_inferred_zero_la.sql` guards on `count = 105` and raises
rather than applying if the set has moved — a human decision must not silently widen its own
scope when a re-ingest changes the underlying rows.

**The falsification mechanism ships with it.** `20260803210000_inferred_zero_audit.sql` adds
`review_inferred_zero_audit` + a BEFORE UPDATE trigger: when a real count lands on a flagged row,
it records the row (`verdict: contradicted | confirmed`), `raise warning`s to the server log, and
clears the flag so the measurement wins. The `inferred_zero_requires_null_count` CHECK would
otherwise have made that write ERROR — loud, but the wrong loud, aborting the backfill instead of
recording what was learned.

Trigger ordering is load-bearing: `prospect_audit_inferred_zero` sorts before
`prospect_preserve_decisions`, whose preservation branch is guarded on `new.review_count is null`
and therefore correctly declines to re-set a flag cleared alongside a real count.

*Verified live* by simulating the geo-grid backfill inside a rolled-back transaction:
`audit_rows=1 verdict=contradicted flag_after=f count_after=4`, and the audit table confirmed
empty afterwards. The geo-grid resolving these from `rating.votes_count` is now the audit of this
decision, exactly as intended — and it cannot happen silently.

### I-068 · The task_get envelope is verified by the first real run, not by a synthetic test
Owner ruling, 2026-08-03: **do not build a separate verification.** Fail-loud is the right
posture, and a synthetic test can only confirm the shape that was assumed — which is the same
error as I-057 (asserting an endpoint worked because it was called) in a different costume.

The remaining risk is cost, not correctness: DataForSEO bills on **task acceptance**, so an
unparseable envelope would previously have cost one billed `task_post` per place — up to 9 per
client, every one failing identically to rediscover the same fact.

`review_analytics.fetch_and_store` now **aborts on a failure that precedes any success**
(`_ShapeUnproven`, surfaced as `aborted` in the job result). A failure before anything has worked
is almost certainly systemic — dead endpoint, rejected credential, unparseable envelope — and
those fail the same way for every remaining place. Once ONE lookup succeeds the contract is proved
for that run, and later failures skip-and-continue as per-place problems (a delisted listing, a
transient timeout). So a wrong envelope costs **one task, not a run**, and the fix is verified by
the next real run rather than by a test that assumes the answer. Unit-tested three ways
(`tests/test_review_analytics.py`).

### I-069 · A PARTIALLY-written rollup passes the retention guards — found while planning Phase 2
`drop_cold_partitions` (migration `20260801120000`) guards a partition on two things: that every
snapshot in it has *some* row in `prospect_coverage`, and that `max(points_present)` per snapshot
does not exceed the distinct `point_seq` count in the raw partition.

Neither catches a rollup that covered **some prospects and not others**. The first is
`not exists (... where pc.snapshot_id = s.snapshot_id)` — presence of any row for the snapshot
satisfies it. The second compares point counts, so a prospect missing from the rollup entirely
leaves `max(points_present) <= raw_points` true. A rollup that died halfway through a snapshot
therefore reads as complete, and the raw partition it was verifying against gets dropped.

**This is the exact failure the rollup was supposed to be verified against**, and it matters most
here because the loss is silent and unrecoverable: the prospects that were missed lose their
`rank_vector`, so their historical heatmap cannot be rendered and the omission is invisible
afterwards — the snapshot looks rolled up.

Not fixed here (Phase 2 planning, no code). Two candidate fixes, cheapest-to-reverse first:
1. Make the rollup atomic per snapshot and record its own completion (`scan_snapshot.rolled_up_at`
   or a `rollup_run` row), then have the guard require that marker rather than infer completeness
   from row presence. A marker written in the same transaction as the last row cannot be half true.
2. Additionally reconcile *prospect counts*: every prospect with at least one `grid_result` row in
   the snapshot must have a `prospect_coverage` row. Strictly stronger than the point-count check
   and cheap, since both sides are already grouped by `snapshot_id`.

Both are worth having: (1) prevents the partial write, (2) detects one that happened anyway.

### I-070 · `scan_snapshot` is described as immutable and append-only, and nothing enforces it
START-HERE §4 Phase 2 requires "`scan_snapshot` immutable, append-only". The table exists with the
right columns; there is **no trigger, rule or grant** stopping an UPDATE or DELETE.

The repo already treats this class structurally rather than by convention — `prospect_preserve_decisions`
exists precisely because "nothing currently writes this" was judged an insufficient guarantee for a
human decision. A snapshot is the anchor every historical coverage figure is computed against, so a
silent UPDATE to `expected_points` or `geometry_version` would re-interpret history rather than
corrupt it visibly.

Deferred to the Phase 2 build, not fixed now. Note the fix is not "revoke UPDATE" alone: the
completeness flag has to be set at some point, so the guard must permit the write that finalizes a
snapshot and refuse everything after — or the flag must be computed at insert.

### I-071 · The 98% completeness threshold lives in a SQL comment, not in config
`scan_snapshot.complete` carries the comment `-- actual/expected >= completeness_threshold (0.98)`.
`api/config.py` has no `completeness_threshold`; its only scan-related value is `scan_interval_days`.

This collides with a standing invariant — *"All coefficients load from config. Zero hardcoded βs,
ever."* 0.98 is exactly such a coefficient: it decides which snapshots are excluded from scoring,
so it changes results. Right now it is documented in a place no code reads, which is the worst of
both worlds — it looks specified and is unenforced (nothing computes `complete` at all yet).

To settle in the Phase 2 build: add `completeness_threshold: float = 0.98` to `api/config.py`, have
the snapshot writer compute `complete` from it, and make every scoring consumer filter on
`complete`. Logged rather than fixed because the writer it belongs to does not exist yet.

### I-072 · There is no UI plan — only an architecture ruling and a read surface
Raised while planning Phase 2, because Phase 2 produces nothing visible and the UI keeps being
"next".

**What exists:** the suite-module ruling (the UI is suite SPA pages over platform-api, Retool
dropped — HANDOFF §2), a **built and verified read surface** (`routers/outreach.py`, 14 routes
covering markets, submarkets, prospects, leads, activities, suppressions), and
`reporting-layer-spec.md` §3, which specifies *which views must exist* in three tiers — operator
(§3.1), analysis (§3.2), client (§3.3).

**What does not exist:** any frontend code, page, route or design. `frontend/src/pages/LeadOff.tsx`
is a **different module** (the suite's pre-client market-intelligence tool) and is not this
pipeline. START-HERE's Phase 1b guidance was actively wrong until 2026-08-03 — it still told the
reader to build a Retool board and *not* to build a React app, which is the reverse of the ruling.
Now struck with a marker.

**Why it is worth a decision rather than a default.** 1,388 prospects and 925 survivors are sitting
in the database with no way to look at them except SQL, and the read surface they need was
finished and then never consumed. Meanwhile HANDOFF §1 has listed Suite UI as "now the next build"
across several sessions that each built something else.

**The tension to resolve deliberately:**
- The CRM/prospect board is buildable **today** — data and API both exist, no dependency on
  scanning.
- The high-value surfaces — coverage, heatmap, delta — need scan data (Phase 2) and the renderer
  (Phase 3). Building the UI shell now means building the interesting half twice.
- `reporting-layer-spec.md` §7a already ruled *PDF first, dashboard later* for CLIENT reporting.
  That ruling does not cover the OPERATOR views, which is the gap this issue is about.

**Not a blocker for Phase 2.** Recorded so the next session chooses rather than inherits. If the
answer is "operator board now", it is a self-contained piece of work against an API that is
already tested; if it is "after Phase 3", that should be written down so it stops resurfacing.

### I-069 RESOLVED (2026-08-03) — and the fix caught two further errors on the way in
`snapshot_rollup` + `finalize_snapshot_rollup()` + a replaced GUARD 1 in `drop_cold_partitions`.
Migration `20260803230000`, applied live.

**The mechanism.** The rollup transaction calls `finalize_snapshot_rollup(snapshot_id)` as its
last statement. That function re-derives the counts from the data — it does not trust what the
caller believes it wrote — and RAISES on a mismatch, which aborts the transaction so a partial
rollup leaves neither a marker nor partial rows. GUARD 1 now requires the marker instead of the
presence of coverage rows, so completeness is a recorded fact rather than an inference.

The marker lives in its own append-only table rather than as `scan_snapshot.rollup_completed_at`,
which keeps `scan_snapshot` write-once (I-070) instead of building the first exception into the
table this project most needs to trust.

**Two errors caught while verifying, both mine, both of the same kind — reasoning from a partial
read instead of the source:**

1. *A reconstructed function that silently deleted the relocation logic.* The first draft rebuilt
   `drop_cold_partitions` from memory after reading fragments of it. The real function uses `$$`
   not `$function$`, takes `p_hot_window_days` not `p_hot_days` (which alone would have failed —
   Postgres refuses to rename a parameter in CREATE OR REPLACE), and **relocates cited/client
   survivors into `grid_result_retained` with per-snapshot verification before dropping**. The
   reconstruction had none of the relocation. It would have destroyed exactly the rows §3.3/§3.4
   exist to preserve. Replaced with surgical text replacement against the real body.
2. *A reconciliation that would have made every partition permanently undroppable.* The finalizer
   first compared `count(distinct grid_result.place_id)` against `count(*) from
   prospect_coverage`. But grid_result holds the top ~20 businesses at each of 81 points (~1,620
   rows/snapshot, storage spec §1) and most are **not prospects** — they are whoever ranked.
   `prospect_coverage` is one row per PROSPECT. The comparison would have raised forever. Fixed
   by joining through `prospect.place_id`.

**Verified live** in rolled-back transactions, both directions: a snapshot with two prospects and
one non-prospect business, rolled up for only one prospect, raises *"2 prospects present in
grid_result, 1 in prospect_coverage"* and writes no marker; rolled up for both, it writes
`prospect_count=2`. The non-prospect business was correctly ignored in both, which is what proves
the join. Database left clean afterwards (all scan tables 0, the 105 flags intact).

`point_count` on the marker is deliberately NOT joined through prospect — it records points
scanned. Counting only points where a prospect appeared would record a number that reads like
coverage and is not.

### I-073 · `ai_region` candidates for LA, with the free evidence run — 3 of 14 names look wrong
PRD §16a.2 notes a validation that costs nothing and is already in our data: *"check whether
businesses in the Outscraper pull name themselves after the place — several plumbers with 'Los
Feliz' in their business name or address means the name is commercially real."* Run against all
1,388 LA prospects:

| candidate | self-named | `city` field | verdict |
|---|---|---|---|
| Van Nuys | 5 | **90** | strong |
| Burbank | 11 | **84** | strong |
| Long Beach | 18 | **79** | strong |
| Torrance | 13 | **76** | strong |
| Pasadena | 13 | **57** | strong |
| Whittier | 9 | **48** | strong |
| Woodland Hills | 8 | **44** | strong |
| Inglewood | 3 | **38** | strong |
| Northridge | 6 | **35** | strong |
| Santa Monica | 4 | **34** | strong |
| Hollywood | 13 | 4 | **see below** |
| East Los Angeles | 0 | 4 | **weak** |
| West Los Angeles | 2 | **0** | **not a locality here** |
| Downtown Los Angeles | 0 | **0** | **not a locality here** |

**Ten are unambiguous** — a real `city` value on 34–90 prospects each, plus businesses named after
them. Those are `name_level = 'suburb'` or `'city'` and are very likely to survive a recognition
test.

**Hollywood is the interesting one.** 13 businesses name themselves after it, but only 4 sit in a
`city` of "Hollywood" — while 44 addresses mention it. That gap is almost certainly **street
names** (Hollywood Blvd), not locality. So the address-mention count is a confounded signal and
should not be used on its own; the `city` field and the self-naming count are the honest ones.
Hollywood is a real *neighbourhood* whose businesses are addressed "Los Angeles" — exactly the
`name_level = 'neighbourhood'` case, and exactly where I-004's "model silently falls back to
metro" risk lives.

**Three look wrong as AI regions.** `Downtown Los Angeles` and `West Los Angeles` have **zero**
prospects with that `city` and near-zero self-naming; `East Los Angeles` has 4. Google does not
treat the first two as localities in this data, so asking an engine about them is the case the
spike is designed to catch: a name that reads specific and returns metro-scale answers.

**What this does and does not settle.** It is a *commercial-reality* filter, not the recognition
test. It cannot tell you what an engine returns — only which names are worth spending the
recognition test on. It costs nothing and it has already halved the risky set: the paid test
matters most for Hollywood and the three weak names, and is close to a formality for the other ten.

**Still blocked:** the recognition test itself (I-004) needs one engine key. None exists in the
sandbox, and the `outreach` Railway service carries only Outscraper, DataForSEO and Supabase
credentials.

---

## The coverage rollup (2026-08-05)

Everything below was found while building `rollup_snapshot_coverage()` (migration
`20260805120000`). Six are ambiguities in the specs, resolved the cheapest-to-reverse way and
recorded here rather than silently in the specs, per CLAUDE.md §6. Two are structural consequences
of the completion contract that the next reader will otherwise meet as a surprise.

### I-074 · Land masking's second null criterion is not computable from stored data
PRD §9a.1 defines a point as `null` for a scan "if it returns zero results, **or if the nearest
result exceeds `2 x grid_spacing_miles` from the point**". The second half cannot be evaluated:
`grid_result` deliberately stores no coordinates (storage spec §5 — they regenerate from the
snapshot's geometry), and `maps_scan.parse_grid_result` keeps only `place_id` and `rank`, so
nothing anywhere records where a returned business actually is. Most results are not prospects, so
`prospect.lat/lng` does not cover it either — the *nearest* result is usually somebody we have
never heard of.

The distinction matters: the second criterion catches a point where the provider answered with
businesses from miles away, which is a different failure from an empty pack and arguably the more
common one over water.

**Implemented:** the zero-results criterion only. **Forward fix:** capture the nearest result's
distance at collect time — one number per point, computed from `items[0].latitude/longitude`
against the grid point we already hold — onto `scan_task`. That is a scan-layer change and the
scan layer has never run, so it was deliberately not made here: the first live run should prove
the response envelope before anything new is read out of it.

### I-075 · Two ways a snapshot can pin its partition forever, both fail-closed
`drop_cold_partitions` requires a `snapshot_rollup` marker for **every** snapshot in a partition.
Two snapshots can never get one:

- **Incomplete snapshots.** PRD §9a.3 requires they be excluded from rollup, and the rollup
  enforces that. So a snapshot that never reaches 98% completeness blocks its month indefinitely.
- **Snapshots matching no prospects.** `finalize_snapshot_rollup()` raises when the grid contains
  no known prospect, so the marker cannot be written. Unlikely at 81 points x ~20 results, but
  possible in a submarket where every prospect has churned.

Both retain a partition that will never drop — disk, forever, for one snapshot. That is the right
direction to fail (the alternative is dropping evidence that was never verified), and it is not
free. **Not fixed:** the fix is a "rolled up as excluded" marker variant, which means deciding what
`prospect_count` means for a snapshot that legitimately has none — a schema question for whoever
owns retention next, not something to decide inside a rollup. Watch `storage_retention_log` for
`retained` rows whose reason names the same partition month after month.

### I-076 · A prospect present at zero grid points gets no coverage row at all
Forced, not chosen. `finalize_snapshot_rollup()` compares `count(*)` in `prospect_coverage` against
`count(distinct prospect.id)` joined to `grid_result` with `<>`, so writing a row for a prospect who
appears nowhere raises exactly as hard as omitting one who appears.

The consequence is the wrong way round from what anyone would want: **the prospect with the worst
possible coverage — invisible at every point — is the one with no row.** Whatever reads coverage
next (the placeholder score, the audit, the heatmap) MUST treat a missing row for a scanned
submarket as **zero coverage**, never as "not measured". Reading it as unknown would exclude the
most painful prospects from scoring, which is precisely backwards for a pipeline whose entire pitch
is coverage deficit.

### I-077 · `grid_result` can hold duplicate rows, by design, and nothing constrains them
There is no unique index on `(snapshot_id, point_seq, place_id)`. `_collect_one` writes the rows
and *then* marks the task `collected` — deliberately, because a crash between them re-collects
something free rather than losing something paid (DECISIONS.md) — so a crash in that window leaves
a point's rows written twice after the retry.

The rollup deduplicates with `min(rank)` per `(prospect, point)`, so `points_present` is correct
today. Nothing else that reads `grid_result` knows to. **Not fixed here:** a unique index would
turn the retry into an insert failure and lose the paid result, and `on conflict do nothing` on the
insert is the better shape — but that is a change to the collector's write path, which has never
run. Revisit after the first live scan.

### I-078 · `scan_snapshot` has no `center`, though the storage spec says coordinates derive from it
Storage spec §5: "Store the generator parameters (already in `scan_snapshot`)" and coordinates
regenerate from `scan_snapshot.{center, grid_radius_miles, grid_spacing_miles}` plus `point_seq`.
The built table has the two distances and **no centre** — the centre lives on `submarket`, which is
immutable only by enforcement (`seeding.check_geometry_change`) rather than by storage.

The rollup is unaffected and deliberately stays that way: point *distances* come from
`steps x spacing` and are centre-independent, so nothing in the rollup reads a mutable column, and
`centroid_dist_at_loss` cannot be rewritten by a corrected centre. **Phase 3 is affected.** The
heatmap needs real lat/lng, so it will read `submarket.center_*` — and a submarket whose centre is
ever corrected would re-render every historical heatmap against coordinates that were never
scanned, which is the exact failure `geometry_version` exists to prevent, arriving through the one
door the pin does not cover. **Action:** copy the centre onto `scan_snapshot` before the first
heatmap renders, not after.

### I-079 · `snapshot_rollup.point_count` counts what was FOUND, not what was measured
`finalize_snapshot_rollup()` sets it from `count(distinct point_seq)` over `grid_result` — points
that returned at least one business. Its own comment calls it "distinct grid points captured",
which reads like coverage and is not: a snapshot with 81 points scanned and results at 60 records
`point_count = 60`.

This is the same measured-vs-found confusion corrected twice already (DECISIONS.md `actual_points`;
I-069 itself). **Deliberately not changed** — the marker is a merged contract and the number is
still the right one for its actual job, which is reconciling against the raw partition at drop
time. Recorded so nobody reads it as a coverage statistic. The measured number is
`scan_snapshot.actual_points`; the live one is `prospect_coverage.live_points`.

### I-080 · `centroid_dist_at_loss` has no formula anywhere
Storage spec §4 gives it a comment ("miles from pin where they drop out") and §11's acceptance
criteria require it to survive rollup; the reporting spec exposes it in `v_client_coverage_history`
and the PRD refers to an "invisible past N miles" line. No document defines how to compute it.

**Implemented:** the distance of the **nearest live point at which the prospect is absent**, and
null when they hold every live point. It is deterministic, needs no assumption about the shape of
the decay, and on a normally-decaying grid it is the radius at which they drop out.

**The alternative reading**, which "invisible past N miles" arguably fits better, is the smallest
distance beyond which they are absent at *every* live point — a genuine outer boundary rather than
a first gap. The two agree when coverage decays monotonically and diverge when a prospect holds an
isolated far point. Cheapest to reverse: both are recomputable from `rank_vector` plus geometry, so
switching later is a backfill, not a rescan. **Pick one deliberately before it appears in a
prospect-facing claim**, because the two numbers can differ by miles and only one of them will
match what the heatmap looks like.

### I-081 · "3 consecutive null scans" — per snapshot, with the counter shared across keywords
PRD §9a.1 says a point is masked "after 3 consecutive null scans" without saying what a scan is.
One market cycle produces one snapshot per keyword per submarket, so "3 scans" could mean 3 cycles
or 3 snapshots.

**Implemented:** per snapshot, with one counter per `(submarket, point_seq)` shared by every
keyword. That reading turns out to be the safe one rather than merely the literal one: because the
counter is shared, a point that returns results for **any** keyword resets it, so the only points
that ever reach 3 are those returning nothing for everything — which is what "this point is over
water" actually means. A per-keyword counter would mask a point that is simply a dead zone for one
service.

**The wrinkle:** within a single cycle the three snapshots roll up in arbitrary order, so a point
crossing the threshold mid-cycle is masked for the keywords rolled up after it and not for those
before. Same cycle, two denominators. It is small, self-consistent per snapshot (`live_points` is
stored contemporaneously), and cheaper to accept than to serialise rollups per cycle. Worth knowing
before someone reads two keywords' coverage side by side and finds them incomparable.

---

## The placeholder score and the snapshot centre (2026-08-05)

### I-082 · The placeholder score is a VIEW, not a `prospect_score` row
START-HERE §4 Phase 2 asks for a "placeholder score = raw geogrid coverage deficit (one SQL
expression)". The obvious home is `prospect_score`, and it is the wrong one.

That table is the Phase 4 MODEL's, and its shape says so: `model in ('reply','close','value')`,
`pass in (1,2)`, a `channel`, a `predicted_prob`, a `decile`, and a mandatory `score_run` carrying
`model_version`, `lambda_shrink` and calibration constants. A coverage deficit has none of those.
Writing it there would mean picking a `model` value from an enum with no slot for "this is not a
model", inventing a `lambda_shrink` for a run that fits nothing, and satisfying a `score_factors`
column whose stated invariant (CLAUDE.md) is that points plus offset reproduce the score exactly.

Each is a small lie, and they compound in the one place this project cannot afford them. The
reporting layer **already** reads `prospect_score where pass = 2 and model = 'value'`
(`v_prospect_ranked`, reporting spec §3.1), so a placeholder wearing a model's clothes would be
picked up as a fitted score by a query written months before it existed — and Phase 4's refit would
have no column to tell the two apart. Phase 1 was verified on the criterion "`prospect_score` was
never written"; keeping that true is worth more than the convenience.

**Implemented:** `v_prospect_placeholder_score`, a view over `prospect_coverage`. It stores
nothing, cannot pollute the modelling substrate, is literally the one SQL expression the checklist
asks for, and Phase 4 replaces it by dropping it. **If a later phase needs the placeholder
persisted** — to join scores to outcomes before the real model exists — that is a decision to take
deliberately, and it needs its own table or a `model` value that admits what it is. Do not reach
for `prospect_score` because it is there.

### I-078 RESOLVED (2026-08-05) · The snapshot now records its own centre
`scan_snapshot.center_lat` / `center_lng` added (migration `20260805140000`, applied live) and
written by `submit_scan` from the same locals passed to the geometry generator, so the recorded
centre is provably the one used rather than one that merely matches today.

**Nullable deliberately.** NOT NULL would let a stale writer fail a snapshot insert on a
bookkeeping column, and the fail-safe direction on a path about to spend money is "the scan
proceeds and the gap is visible". Tighten to NOT NULL once the first real scan proves the writer
populates it.

Done now rather than later because the window was closing: the table is empty, so this was an
ALTER with nothing to backfill. After the first snapshot it becomes a backfill that reads today's
submarket centre and asserts it was the centre used at scan time — exactly the unverifiable claim
the column exists to make unnecessary. What stood between the pipeline and that first snapshot was
a Railway deploy.

---

## Found while preparing the first scan (2026-08-06)

Five findings, none of them fixed. All were discovered by reading the paths the first run is
about to execute, rather than by running anything.

### I-083 · The first snapshot is the likeliest one to be incomplete, and that pins its partition
A dated instance of I-075 rather than a new mechanism, logged separately because it has a
foreseeable trigger date and I-075 does not.

`drop_cold_partitions` requires a `snapshot_rollup` marker for **every** snapshot in a partition,
and an incomplete snapshot (below `scan_completeness_threshold`, 0.98) is excluded from rollup and
therefore can never get one. The first live run is the single snapshot most likely to fall below
that bar: it is the first time the submission path, the ready list and the fallback-by-id path
have ever run against a real provider, and 2 uncollected points out of 81 is already 97.5%.

If that happens, the `2026_08` `grid_result` partition is retained forever. The cost is bounded
and small — one partition holding ~1,620 rows — and the direction is the right one to fail in
(the alternative is dropping evidence nobody verified). It is recorded because the consequence is
**permanent and silent**: nothing alerts, and the partition simply never appears in a drop log.

**Not fixed.** The fix is I-075's — a "rolled up as excluded" marker variant — and it requires
deciding what `prospect_count` means for a snapshot that legitimately has none. That is a schema
question for whoever owns retention, not something to settle inside a scan runbook. **Watch for
it** with check 7 of `queries/first-scan-verify.sql`, which prints the consequence beside the
ratio rather than leaving it to be inferred from `complete`.

### I-084 · How `serp_result` attaches to a grid-shaped `scan_snapshot` is undefined
**Blocks the design of the organic SERP layer (HANDOFF §8.1 item 2d).**

`serp_result.snapshot_id` is `NOT NULL`, and PRD §B1 requires one immutable `scan_snapshot` per
submarket × keyword × cycle. So the organic layer does not get its own snapshot type — it must
attach to the same row the geogrid writes. But every completeness column on that row is
grid-shaped: `expected_points`, `actual_points`, `point_count`, and a `complete` flag computed by
`scan_runner._maybe_finalize` purely from collected grid tasks.

Three questions follow, and no document answers any of them:

- **Who creates the snapshot** when an organic pull runs and a geogrid does not, given that
  `expected_points` is `NOT NULL` and means nothing for a SERP pull?
- **Does a missing or failed organic pull make the snapshot incomplete?** Today it cannot —
  `complete` sees only grid tasks — so a snapshot can read complete while carrying no SERP result
  at all. If that is intended it should be stated, because "complete" then means "complete for
  the geogrid" in a column named for the snapshot.
- **Does the organic pull have to wait for finalization**, or can it write against a snapshot
  still collecting? The rollup's guarantees are transactional per snapshot; nothing scopes them
  to a channel.

**Not resolved here, deliberately.** Every answer is a claim about a lifecycle that has executed
zero times. Cheapest to reverse is to decide it after the first run has shown what that lifecycle
actually does, which is also the argument for running the scan before building 2d.

### I-085 · I-071 has drifted — the completeness threshold IS in config now
I-071 records that the 0.98 threshold "lives in a SQL comment, not in config". That is no longer
true of the first half: `api/config.py:187` carries `scan_completeness_threshold: float = 0.98`,
and `scan_runner._maybe_finalize` reads it through `maps_scan.is_complete`. It landed with the
geogrid build (#557) without I-071 being updated.

**What remains open is the second half**, and it is the half that matters for results: *"make
every scoring consumer filter on `complete`."* Nothing scores yet, so nothing filters yet. The
placeholder score reaches `complete` only indirectly — `v_prospect_placeholder_score` joins
`snapshot_rollup`, and the rollup refuses incomplete snapshots, so the filter is real but is
enforced one layer away and by a different table. That works and is worth knowing about before
someone adds a consumer that reads `prospect_coverage` directly and inherits no such guard.

Logged rather than edited into I-071 so the drift itself stays visible: an issue that quietly
half-fixes is harder to notice than one that stays open.

### I-086 · The geogrid scan spends money and writes no `cost_ledger` row
**The only paid path in the system with no ledger entry.** `pipeline.py` (Outscraper ingest) and
`review_verify.py` both write one; `scan_runner.py` writes none — the string `cost_ledger` does
not appear in it. `dataforseo_cost_per_request_cents` exists in config (1¢) and nothing reads it
for the scan.

Two consequences, and the second is the larger one:

- **Spend is invisible in-system.** The first run's cost exists only in the DataForSEO dashboard,
  which is exactly the position §7.1 describes for Outscraper — a placeholder rate that was never
  reconciled because nothing forced the comparison.
- **The budget ceiling does not cover scans.** `max_market_run_cost_cents` (5000) is enforced by
  `cost.py`'s pre-flight gate, and `cmd_scan` does not call it. Immaterial at 81 tasks; not
  immaterial for the market sweep that HANDOFF §8a says comes after this run proves the envelope.
  The gate should exist before the command that needs it, not after.

**Not fixed.** It is a change to the paid write path, immediately before a paid run, and it is the
owner's call whether to take it now (a best-effort insert in `review_verify.py`'s style, which
logs on failure and cannot abort a scan) or after. Check 14 of `queries/first-scan-verify.sql`
prints this as a defect rather than a pass so it is not read as "no cost, therefore free".

### I-087 · `recovered_by_tag` is a counter in a log line, not durable state
HANDOFF's post-run instruction says to check "whether any row is sitting on `recovered_by_tag`".
There is no such row and no such column: it is a field on `scan_runner`'s in-memory `report`
(line 70), incremented at line 331, and printed once in the `collect` command's JSON output.

That makes it the least durable signal in the system and one of the most important. The tag is
the recovery key that closes the one window ordering cannot cover — a request the provider
accepted and billed whose response never reached us (§8.0a). If it fires, the fact lives only in
a Railway log line, and this project already knows that the log stream lags (§6.3) and that
nothing greps `OUTREACH_RESULT` (I-034). Nor is it reconstructible afterwards: a task recovered
by tag is `collected` like any other, so no query can tell the two apart.

**Not fixed** — it is a change to the collector's write path, and the same reasoning applies as
I-086. A durable version is a boolean on `scan_task` set where the counter increments. **For the
first run, capture the `collect` output** rather than relying on being able to read it later.

### I-088 · Auto-deploy on push appears to be BACK ON, contrary to §7.2
Found 2026-08-06 while checking what a manual Deploy had run. The `outreach` service's five most
recent deployments track commits merging to `main` — `01a6d42` (#570), `c1d7273` (#569) and
`0883911` (#573), the last two unrelated to this module — at 00:52:01, 00:52:19 and 01:52:28.
That is the signature of deploy-on-push, and HANDOFF §7.2 records auto-deploy as **disabled on
2026-08-01**.

Not confirmed from the API: `get-service-config` does not expose an auto-deploy field, so this is
inference from the deployment pattern and needs a dashboard read (Settings → Source). It is
recorded as suspected rather than established for exactly the reason I-065 exists — *a config
change recorded in a document is not a config change* — and this is the same claim failing the
same way, from the other direction.

**Why it matters more than it did in §7.2.** That section reasoned about deploy-on-push while the
command was `filter`: free but noisy. Two things have changed. The runbook (§11b) now asks an
operator to set `OUTREACH_COMMAND=scan` with a matching confirm token, and **any merge by anyone,
on any unrelated PR, would then fire a paid scan** — not once, but on every merge until the pair
is cleared. And the planned hourly `collect` cron adds a third trigger path. Three ways to start
this job, two of which nobody watching the service would attribute to themselves.

**Evidence it has not cost anything yet:** every `cost_ledger` row on 2026-08-06 is
`a2_filter / internal / 0 cents`, and `scan_snapshot`, `scan_task` and `grid_result` are all still
empty. The re-runs are free filter passes that upsert over the same 1,388 prospects —
`filter_result` is unchanged at 8,328.

**Action before the first scan, not after:** confirm the setting in the dashboard and disable it if
it is on. The spend gate (§7.2) bounds the damage to commands carrying a matching token, which is
precisely the state the runbook asks you to create — so the gate does not cover this case.

**Also unresolved:** the deployments at 01:46:57 and 01:52:38 wrote no `cost_ledger` row at all,
where the 00:52 pair did. Their deploy logs come back empty through the API, so what command they
ran is not knowable from here — consistent with a crash (§6.2 reports one as SUCCESS), with a
`collect` run finding nothing to do, or with a refused command. Named rather than guessed at.

### I-072 RESOLVED (2026-08-06) — owner ruling: UI now, and it must TRIGGER scans, not only read
The question this issue held open — operator board now vs after Phase 3 — was answered by the
owner, and answered wider than asked: "we need a UI to start this, not just read the reports."
That overturns §11a's working position (a trigger button "gets its own decision") by making that
decision. The on-record recommendation (first scan before a sixth unrun layer, HANDOFF §8.1 2c)
was raised twice and overruled twice; the first scan will now arrive through the trigger path it
proves. Recorded, not relitigated.

**v1 scope:** one suite-level page (like LeadOff — pre-client, not client-scoped): pick a
submarket × keyword → confirm → scan queued; live status (order state, task progress x/81,
snapshot completeness); results tables (coverage + placeholder score) once rolled up. The
**heatmap stays Phase 3** — building the renderer now is the "interesting half twice" cost the
original issue named, and nothing in this ruling requires it.

**The mechanism — how a button spends money without gutting §7.2 — is in DECISIONS.md** (the
confirmation moves from config to a signed order row). Summary: the UI writes a `scan_request`
row through platform-api (admin-gated); the outreach service gains a `tick` command = `collect` +
drain at most one pending order; the frequent cron §11 already required now runs `tick` and does
double duty. `collect` itself stays free and never drains — the §8a invariant and its test are
untouched. Closing I-086 (cost_ledger on scans) rides this build, because a UI that spends money
must show what it spent.

**What this does NOT remove:** the one-time Railway setup (the cron running `tick`) and the I-088
auto-deploy question. A webpage cannot wake a server on a schedule; the engine still has to exist.

---

### I-089 (open, low) — the heatmap colour scale has no band for a rank past 20
Reporting spec §4.2 defines four rank bands — `1–3` green, `4–10` yellow, `11–20` orange, `0` red
(not found) — and `255` grey (dead). It says nothing about a byte in **21–254**. That byte is a
genuine encoding: `coverage_rollup` stores each point's `rank_absolute` as the byte, and while
`scan_depth = 20` today (so the provider returns at most 20 results and ranks never exceed 20), the
depth is config-tunable and a deeper scan would produce ranks past 20.

**Interpretation chosen (cheapest to reverse, per CLAUDE.md session protocol #6):** the renderer
(`api/services/heatmap.band_for_byte`) folds 11–254 into the single `far_down` band. The load-
bearing property is that a found ranking, however deep, is **never** coloured red — conflating
"ranked #40" with "not ranking at all" is exactly the overstatement §4.2 warns a prospect can
catch. The legend reads "Found, far down (11+)" rather than "11–20" so it stays honest if the depth
is ever raised.

**If 11–20 vs 21+ ever needs to be visually split**, it is a new band plus a `GENERATOR_VERSION`
bump — never a silent recolour of history, since a cached March artifact must keep rendering the
way it was cited. Unreachable at the current depth, so no action needed now; recorded so the
decision is visible if `scan_depth` changes.

---

### I-090 (open, low) — `report_artifact.score_run_id` has no foreign key yet
Reporting spec §2 defines `score_run_id uuid references score_run(id)`. `score_run` is the Phase 4
model's table (START-HERE §3a) and does not exist, so migration `20260807130000_report_artifact.sql`
creates `score_run_id` as a nullable, **unconstrained** uuid. A heatmap needs no score run, so
nothing is lost today.

**Adopt when Phase 4 lands `score_run`:** add the FK in the same migration that creates the table —
`alter table report_artifact add constraint report_artifact_score_run_fk foreign key
(score_run_id) references score_run(id)`. Check for orphans first (there will be none until a
renderer starts writing the column). Same shape as the `lead_activity.touch_id` FK deferral in
PHASE3-outcome-constraint.md §2 — a column waiting for the table it points at.

---

### I-091 (open, low) — the delta guard's provider-boundary and drift-suppression halves are seams awaiting their data
Reporting spec §4.3 requires a delta heatmap to refuse to render across three conditions: a
**provider boundary**, a **span** wider than `max_delta_span_days`, and where **drift suppression**
fired (PRD §9a.2). `heatmap.assert_delta_renderable` implements all three, but only the span guard
is sourced from live data today:

- **Span** — fully enforced. Both snapshots carry `scanned_at`; `max_delta_span_days` (default 45)
  is now in config. This guard is real now.
- **Provider boundary** — the mechanism exists (`provider_before != provider_after`), but
  `scan_snapshot` carries no provider column and DataForSEO is the only provider, so it is
  vacuously satisfied. `build_delta_inputs` defaults both providers to `"dataforseo"`. When a
  second provider is ever added, store it per snapshot and pass it through — the guard then bites
  with no renderer change.
- **Drift suppression** — `build_delta_inputs` takes an explicit `drift_suppressed: bool`,
  defaulting False, because `prospect_delta` (the table that would source it, PRD §9a.2) does not
  exist yet — the `coverage_rollup` migration notes this at its own tail. Building the drift
  subsystem now would be pulling Phase-later work forward (session protocol §3); the renderer is
  built as its correct *consumer* instead, with the seam documented here.

**Adopt when:** a second SERP provider lands (wire the provider column) and/or `prospect_delta` +
drift suppression are built (pass the real flag). Neither is a renderer change — both are one-line
call-site edits in `build_delta_inputs`. Until then the delta is honest: it refuses on span, and
the other two conditions cannot occur.

---

### I-092 (open, by design) — a scan of a non-ingested city yields empty coverage; discovery must precede the scan
`prospect_coverage` is produced by `finalize_snapshot_rollup()` joining `grid_result` to
`prospect` on `place_id` (migration `20260805120000`). `prospect` rows are written ONLY by the
paid Outscraper `ingest` pass (`cmd_ingest` → `pipeline.run_ingest`, driven by a market's
`categories` + submarket tiles). So scanning a submarket whose city was never ingested captures a
grid but rolls up ZERO prospect coverage — a successful-but-empty result, and exactly the
"manufactured total invisibility" the I-076 invariant warns against if misread.

**Consequence for the any-city scan form (DECISIONS 2026-08-08):** "type a city and scan it" is not
a scan-only action — it is discover (ingest, paid) → filter → scan. The business type the operator
types IS the ingest category, which is why the form is "City + Business type". The geo read layer
(built) resolves the city + its sub-areas; the discovery-execution layer (next slice) must run
ingest+filter for the city BEFORE the scan, or reuse an already-ingested city's prospects. Not a
bug — the pipeline order — recorded so the execution slice is built with it front of mind and no
one wires a "scan a fresh city" button that silently returns nothing.

---

### I-093 (open, by design) — the call hook's geography is RADIAL, not compass-directional

The call-hook justification (DECISIONS 2026-08-08) describes the geographic pattern of a prospect's
invisibility from the coverage scalars the rollup already stores — coverage %, absent-point count,
`centroid_dist_at_loss` ("holds close to home, falls off beyond ~N miles"), rank depth. That is a
RADIAL read: near vs far, which "parts" of the service area in the concentric sense.

The richer read the task named — "which parts they don't rank in, derived from `rank_vector` + the
snapshot's stored geometry" in the COMPASS sense (weakest to the north/east) — is **deferred**,
because it needs each point's (dx, dy) offset, which comes only from the pinned geometry generator
(`api/services/geometry.generate_points`). That generator lives in the outreach api, which
platform-api (where the hook is assembled) cannot import across the deploy boundary. Re-deriving the
lattice in platform-api is exactly the "second definition of geometry" the version registry exists
to prevent (CLAUDE.md) — a byte decode of the vector is geometry-free and safe; a point→coordinate
mapping is not.

**Cheapest-to-reverse reading chosen:** ship the radial pattern now (no geometry, honors the
boundary), defer the compass decomposition. Two clean ways to add it later, neither a rewrite of the
hook: (a) vendor `geometry.py` byte-identical into platform-api with a sync-guard test — the
established suite pattern for cross-boundary duplication (`agent_docs/`, the voice_card vendoring) —
so there is no drifting second *definition*, only a test-enforced copy; or (b) have the rollup store
a small per-prospect directional summary (octant weakest-quadrant) alongside coverage, which the hook
then reads as a scalar. (b) is cleaner but touches the rollup, so it waits for a rollup-touching
build. Neither is worth pulling forward before the hook has been used on a real call.

### I-094 (open, by design) — the hook's competitor detail needs a HOT `grid_result` partition

"Who outranks you and where" reads the map pack from `grid_result` (bounded to `rank <= pack_size`).
`grid_result` is partitioned by month and cold-dropped after the hot window (~90 days,
`drop_cold_partitions`), while `prospect_coverage` persists indefinitely — which is exactly why the
heatmap renderer reads ONLY coverage, so it renders forever (reporting §4).

The hook deliberately diverges: it reads `grid_result` because competitor IDENTITY (place_id → name)
lives nowhere else, and the hook is a call-prep artifact generated soon after a scan, when the
partition is hot. When the partition has been dropped, `_fetch_pack_rows` degrades: the competitor
talking point is omitted and a caveat says "the raw ranking data has aged out", while coverage,
geography, reviews and gaps — all from the persistent coverage row + the prospect — still stand. So
a hook built from a cold scan is thinner, never wrong, and never fabricated.

**Adopt a durable form when:** competitor identity needs to survive the partition drop. The clean
option is for the rollup (or a later phase) to persist the top-N pack holders' `place_id`s per
prospect alongside coverage — a handful of ids, negligible storage — so the hook reads them from a
permanent row. Not built now: it touches the rollup, and the hot-window read covers the actual
use (dialing a fresh shortlist).

---

### I-095 (open, staged) — the report's organic + LLM sections, and the client-facing PDF, are staged builds

The per-prospect report (DECISIONS 2026-08-08) ships its spine now — identity + the Maps
rankings-vs-competitors table + the call hook, in an internal brief and a client-facing draft. Three
pieces are deliberately staged, because each is a real build (two of them paid, one blocked), and the
report renders them as explicit `not_scanned` blocks until they land — never an empty table:

- **Organic-SERP scan (increment 2) — BUILT 2026-08-08.** A new producer in the outreach Railway job:
  a DataForSEO organic SERP for the prospect's keyword+location, the prospect's rank + top
  competitors, written to `serp_result` against the maps `scan_snapshot` (I-084 resolved — single
  location per keyword×submarket). Authorized through the `scan_request`/`tick` order mechanism, not a
  platform-api call. Then `outreach_report.build_report`'s `organic` section fills from it.

- **LLM-visibility scan (increment 3) — BUILT 2026-08-08.** Blocked on `ai_region` names (§7.4 — a human
  "which place names does an LLM recognise" task; a candidate LA list is drafted in I-073) and an
  engine choice (the suite AI-visibility uses six; a prospect scan likely wants a cheap subset —
  DataForSEO's Google AI Overview/AI Mode needs no per-engine key, plus optionally ChatGPT). Same
  order-gated spend path. Fills the report's `llm` section.

- **Client-facing PDF + approval gate (increment 4) — BUILT 2026-08-08.** Signed-URL delivery built on Supabase Storage (DECISIONS 2026-08-08 — R2's substance, no new creds). **I-095 fully resolved.** Today the client face is a print-preview DRAFT
  marked `approved:false`. Turning it into a sendable asset needs the Phase 3 audit path: WeasyPrint
  render + signed R2 URL + the explicit-approval gate (reporting §4a; the no-unapproved-asset
  invariant). Build order: after the data layers, so the PDF has all three signals to show.

None is a restructure of the report — each fills a section shape that exists now. Build order
2 → 3 → 4; increment 3 needs the two human inputs above before it starts.

---

### I-096 (open, cheapest-to-reverse reading taken) — the LSA / Google-Guaranteed item type is unconfirmed against this account's organic response

Paid-placement PRESENCE (HANDOFF §12 item 3a, Slice A) is parsed from the organic SERP response
`scan-organic` already captures — no new paid call. Two item types feed it:

- **Google Ads** — DataForSEO's `type == "paid"`. High confidence (it is the standard label), and
  the parse is tolerant (domain recovered from the ad URL when `domain` is absent).
- **Local Services Ads ("Google Guaranteed")** — parsed from `type ∈ {local_services,
  google_local_services, local_service_ads}` in the SAME response.

**The ambiguity:** whether LSA actually rides the organic `/serp/google/organic/live/advanced`
response for THIS account, and under which exact item type, is UNMEASURED — the organic scan has
never run (I-095), so there is no stored sample to read. The spec is explicit that this is a
measure-don't-infer point ("confirm its item type against a live response before parsing").

**The reading taken (cheapest to reverse, per the session protocol):** parse LSA from the
already-captured organic response with a tolerant type set, and DO NOT add a speculative new paid
LSA call in Slice A. Two guards make the reading recoverable:

- `parse_organic_serp` records every distinct top-level item `type` it saw (`seen_item_types`), and
  `capture_organic` logs it plus the paid/LSA counts on the first run, so the exact envelope is
  confirmable from the log (and from `serp_result.payload_summary.paid.seen_item_types`) rather than
  a second paid run.
- Presence-absent is a finding, not a gap — `ads_present:false`/`lsa_present:false` never
  manufacture a claim, so a wrong LSA type reads as "no LSA detected" (understates, the safe
  direction), never a fabricated advertiser.

**Resolve after the first `scan-organic` run:** read `seen_item_types` from the log / stored summary.
If LSA does NOT appear in the organic response for local-service queries, the follow-up is a
dedicated `/v3/serp/google/local_services/live/advanced` capture — its own PAID, token/order-gated
command (`scan-lsa`), a `cost_ledger` row, and the path added to the free probe set first. Parsing an
existing field costs nothing and adds no paid call; a speculative new paid call on a wrong envelope
is what this reading avoids.

---

### I-099 (RESOLVED, same session) — three defects found by adversarial review of the Slice A/B code

Reviewed the paid-placement code adversarially before it ran and found three real defects, each
reproduced with a concrete input before fixing. Recorded because two of them are the SAME class of
mistake this module keeps meeting, in a new place.

1. **`scan-tech` scanned 20 of ~1,000 sites and exited 0.** `--limit` had a SHARED argparse default
   of 20, inherited by a command that wants "all". A full-market run reported `considered: 20` and
   looked clean — the "reports clean because it did almost nothing" failure, again. Fixed by giving
   the flag NO shared default and naming a per-command default (`scan_tech_limit` → all,
   `pixel_probe_limit` → 8 because it spends, `legacy_limit` → the previous 20). The parser was
   extracted as `build_parser()` so tests exercise the real wiring; the gap was that pure logic was
   covered and the argparse-to-command seam was not.
2. **A bidirectional LSA name match fabricated a claim.** `name in prospect_norm` let a SHORTER
   competitor name inside a LONGER prospect name read as the prospect — "AAA Plumbing" (a distinct
   business) inside "AAA Plumbing Services". It asserted an LSA the prospect does not run AND
   deleted a real competitor. Fixed to one-directional (prospect-name-in-advertiser), which is the
   rule `detect_ai_mention` already used and which fails toward understating.
3. **An `AW-` tag on the SITE produced the spoken line "you're paying for Google Ads on ⟨keyword⟩".**
   The tag proves conversion tracking is installed, not that they bid on that term — and tags
   routinely outlive the campaigns that placed them, so the claim is falsifiable on the call. Fixed
   by splitting `prospect_paying_this_keyword` (measured on this SERP) from the broad
   `prospect_is_paying`, and carrying `paying_evidence` (`serp_ad`/`lsa`/`conversion_tag`) so the
   hook, the report and the client PDF each say only what was observed. The tag-only wording now
   ASKS about spend instead of asserting it.

Also fixed in the same pass: `likely_represented` counted GTM (near-universal, and the only derived
flag that scores NEGATIVE) — now 2+ vendor tags; the pixel spike discarded already-billed results on
any mid-loop failure (`httpx.ReadTimeout` is not in `FAILOVER_ERRORS`, so it propagated) — now
per-query isolation with the errors reported beside the results; no credential pre-flight on the
spike (`missing_outscraper_vars` added); a page-size cap + bounded problem list on the site fetch;
the report's duplicate cross-region reads (a per-request memo); and the `deficit >= 50` literal moved
to config. Every fix carries a regression test.

---

### I-097 (open, cheap follow-ups) — Slice B1 tech-scan: survivor filtering + GTM-follow default

Slice B1 (`scan-tech`, `services/scan_tech.py`) fetches every prospect-with-a-website in a market and
stores `prospect_tech_signal`. Two deliberate simplifications, each a cheap follow-up, neither wrong:

- **Scans all prospects with a website, not only filter survivors.** PRD §B3 says "survivors only".
  Narrowing to filter survivors needs the filter verdict joined in; a wasted FREE fetch on an excluded
  prospect is slightly wasteful, never wrong (the row is per-prospect and read only for a prospect the
  report is about). Follow-up: join `filter_result`/exclusion into the query.
- **GTM container follow is OFF by default** (`tech_follow_gtm=False`). A GTM container can inject a
  pixel the inline scan misses (I-003 / §16a.1). The seam is built (`looks_gtm_only` + `merge_signals`,
  unit-tested), gated behind the flag until the §16a.1 spike measures the miss rate. Flip the flag if
  the spike shows inline scanning misses GTM-injected pixels.

Also: `scan-tech` is a manual per-market command today — it is NOT yet on the `tick` cron or a
`scan_request`/order path (Slice A's producers aren't either). Wiring it into the cadence is a
follow-up once the first run proves the fetch behaves against real sites.

---

### I-098 (open, gates Slice B2) — DataForSEO Labs ad-spend yield is unproven for small local advertisers

Slice B2 (ad-spend MAGNITUDE, the >$2k / $500–2k bands) is designed against DataForSEO Labs domain
paid metrics (`domain_rank_overview` — `estimated_paid_traffic_cost` / `count`), added to the free
`probe-dataforseo` set so endpoint EXISTENCE is confirmable free. **That probe does NOT establish
entitlement**: an account without Labs can answer HTTP 200 with a task-level access error, and the
probe's `exists` flag is HTTP-200-only — read `task_message` rather than the `exists` list. **B2 is deferred
behind a yield spike** (owner ruling 2026-08-08: build B1 now, gate B2) for one reason: Labs paid data
is keyword-SERP-derived, so a two-truck local operator bidding on hyper-local terms — and running LSA,
which Labs does not index as paid search at all — very often returns `paid.count = 0`. That is exactly
the population this pipeline targets, so the band is likely SPARSE for our prospects.

**Resolve before building `scan-adspend`:** a `probe-labs-paid` sample over ~20 small local prospects,
measuring how many return a non-zero paid estimate. If near-zero, defer B2 and rely on the PRESENCE
signals (Slice A + B1); a documented fallback (the scanned keyword's CPC as a spend FLOOR — "some spend
vs none", insufficient for the >$2k band) is the cheaper alternative. Design: `docs/paid-placement-slice-b-design-v0_1.md`.

---

## Phase 3 — outcome + touch + emit (2026-08-09)

### I-100 · `PHASE3-outcome-constraint.md` §3 points at a `_phase3_probe` that never existed
**Doc-vs-code drift, resolved cheapest-to-reverse.** §3 of `PHASE3-outcome-constraint.md` says
"`outreach/tests/lead_crm_rls.sql` cases 1–3 currently run against a throwaway `_phase3_probe`
table standing in for `outcome`. Delete the probe and point them at the real table." No such probe
exists anywhere in the repo — `grep -rn _phase3_probe` matches only that one doc line — and
`lead_crm_rls.sql` cases 1–3 test the lead SOURCE vocabulary, not `outcome`. The probe was
presumably a scratch table used live during the 2026-07-31 verification (the doc records that run)
and never committed.
**What was done instead of "deleting the probe":** `lead_crm_rls.sql` is left untouched (its cases
1–3 are about `source`, still correct), and the real `outcome`/`touch` constraints get their OWN
new script `tests/outcome_touch_constraints.sql` (12 checks, self-cleaning, run live 2026-08-09 —
all `(correct)`), following the `lead_crm_rls.sql` pattern the task pointed at. Adding a script is
more reversible than editing a working one to chase a table that isn't there.

### I-101 · Emit-time cadence + evidence-age gates (PRD §183/§198) are NOT enforced in v1 emit
**Deferred to the Phase-4 selection layer, deliberately.** PRD §C-adjacent rules say a prospect
MUST NOT be emitted unless its submarket has ≥ `min_history_cycles` (2) snapshots (§198) and its
backing evidence is younger than `max_evidence_age_days` (§183). v1 emit does NOT check these; it
requires only that the prospect has a rolled-up snapshot (`prospect_justification.measured`), which
under `bootstrap_share = 1.0` (DECISIONS — cycle one runs on a single snapshot) is the correct
bootstrap bar. The min-history and evidence-age gates are selection-policy concerns that belong with
the Phase-4 scorer/selector (where `selection_reason` becomes `thompson`), not with a manual v1
emit. Recorded so it is not mistaken for an omission. **Action:** enforce both gates in the Phase-4
selection job; until then emit is manual and bootstrap-gated.

### I-102 · `selection_reason` carries a third value, `manual`, in the pre-Phase-4 era
scoring-spec §7 names the enum `{thompson, random_control}`, but both presuppose a model to select
from or to hold out against — neither exists before Phase 4. Labelling a hand-picked pre-model
contact `random_control` would poison the one unbiased baseline that bucket exists to measure. So
the application allowlist is `{thompson, random_control, manual}`, default `manual`. The `outcome`
DDL leaves `selection_reason` unconstrained text (as adopted from PHASE3-outcome-constraint.md), so
this needs no migration and the vocabulary can tighten later. **Action at Phase 4:** the selector
writes `thompson` / `random_control`; `manual` remains only for hand-picked contacts, and refits
must treat the three buckets distinctly (they already must exclude `thompson`-only — §7).

---

## Phase 4 Stage 1 findings (2026-08-09)

### I-103 · Geogrid "steep decay from pin" qualifier is not evaluated — coverage<20 always maps to the `_steep` bin
scoring-spec §Geogrid-pain names the strongest pain bin "Coverage <20% + steep decay from pin" (+57),
but there is NO non-steep <20 bin to fall to. Requiring a reliable per-pin decay computation (from
`centroid_dist_at_loss`) to gate the pipeline's PRIMARY discriminator would zero out the strongest
signal in the market whenever the decay read was ambiguous. So `score_features._geogrid_bin` maps any
coverage below the low threshold to `geogrid_lt20_steep` unconditionally. **Cheapest-to-reverse
reading** (CLAUDE.md §protocol): the decay refinement lands with a trustworthy per-pin measurement;
until then the +57 bin fires on coverage alone. `centroid_dist_at_loss` is carried on FeatureInputs so
the refinement needs no new capture.

### I-104 · GBP strong/weak bins are dormant — Stage 1 captures rating only, not photos/categories
scoring-spec §GBP-gate's `gbp_strong` (+34) requires "rating >= 4.0, photos, categories set" and
`gbp_weak` (-26) is a rebuild-level deficiency — neither reducible to rating alone. Stage 1 does not
capture photos/categories, so GBP scores at the `adequate` reference (0) for every prospect with a
rating, and strong/weak never fire. This is honest (a feature with no variance cannot discriminate —
the §7a logic), not a bug. A future GBP-detail enrichment (photos/categories from the Outscraper/DfS
pull) lights them up with no coefficient change. `score_gbp_strong_rating` config is kept for then.

### I-105 · The scanned market has no definition file, so the `score`/`recalibrate` CLI needs `--market-name`
The measured LA market is "Los Angeles, CA, USA" (`9238e737…`, created by the any-city ONBOARD path),
NOT the seeded "Los Angeles, CA — Plumbing" (`markets/los-angeles-plumbing.json`, which has zero
coverage). The `score`/`recalibrate` commands resolve the market by the definition file's `name`, so
they would target the empty seeded market. **Fixed:** a `--market-name` override on both commands
(the positional definition file is still required by argparse, but its name is overridden). The
production run is `score <any-file> --market-name "Los Angeles, CA, USA"`. A cleaner fix (resolve
onboard markets without a file) is deferred — onboard markets are created dynamically and a broader
market-resolution rework is out of Stage-1 scope.

### I-106 · `score_run` stores ONE calibration alpha/gamma, but calibration is per-channel
scoring-spec §1 forbids pooling phone and email, and §6 Stage 2 fits calibration per channel — but the
PRD `score_run` DDL carries a single `calibration_alpha`/`calibration_gamma` pair. So `recalibrate`
writes a calibrated run only when EXACTLY ONE channel clears the outcome floor (the phone-first reality:
phone is observable first, §1). A run where BOTH channels fit has nowhere to store both and is reported
as a problem, writing no calibrated run. **Action when the email track goes live:** a migration adding
per-channel calibration storage (e.g. a `score_run_calibration(score_run_id, channel, alpha, gamma)`
child table), then `run_score` reads the pair per channel. Not needed until email + ~30 email outcomes
exist, which is many months out.

### I-107 · `phone_type` is 'unknown' for every ingested prospect — phone reachability is dormant
Every LA prospect carries `phone_type='unknown'` (the base pull does not classify the line), so the
phone-track reachability bins (direct-owner +50 / listed 0 / gatekept -37) never fire and reachability
is correctly EXCLUDED from the phone reply score (START-HERE Phase 4: "pass 1 excludes reachability
rather than defaulting it"). This is honest but means the phone reply score currently has no
reachability contribution for anyone. When the ingest/enrichment classifies `phone_type` (or an owner-
name signal appears), the bins fire with no code change. Not a defect — a dormant signal awaiting data.

### I-108 · Reporting/platform-api still reads the placeholder, not `v_prospect_ranked` — reader NOT repointed
`writer/platform-api/services/outreach.py::placeholder_scores` reads `v_prospect_placeholder_score`,
and the frontend prospect list ranks by it. Phase 4 built the fitted `v_prospect_ranked` and
subordinated the placeholder (view comment), but did NOT repoint the platform-api reader/frontend to
prefer real scores when a score_run exists — that is a separate change with frontend regression surface,
deliberately deprioritized this session (owner away, high bar on user-facing change). **Action:** repoint
`placeholder_scores` (or add a ranked-scores endpoint) to read `v_prospect_ranked` where a score_run
exists, falling back to the placeholder otherwise; then the UI reflects the fitted ranking. Until then
the placeholder still drives the list even after a `score` run populates the fitted tables.

---

## Lead enrichment (2026-08-10)

### I-117 FIXED (2026-08-27) · Re-enrich WIPED a prospect's site_scrape / web_search name contacts (unscoped delete)
`enrich_queue._store_prospect`'s replace-on-place did
`prospect_contact.delete().eq("prospect_id", …)` with **no source scope**, so re-enriching a prospect
deleted ALL its contacts — including the free **site_scrape** and paid **web_search** NAME fallbacks,
which are independent producers. Caught live: a market-wide `leads_n_contacts` re-run on the LA
emergency-plumber market dropped site_scrape from 14 named prospects → 1 and web_search 3 → 0. The
`name_scrape_queue` correctly scopes its own delete to `source='site_scrape'`; the enrich drain didn't.
**Fixed:** scoped the delete to `enrichment.CONTACT_SOURCE` ('outscraper') — a re-enrich now replaces
only Outscraper contacts and leaves the name fallbacks intact. New `CONTACT_SOURCE` constant is the
single source of truth (used by `contact_rows` too). Regression test
`test_enrich_queue.test_re_enrich_preserves_site_scrape_and_web_search_contacts`. **Merged + deployed**
(#767 → `main`, live on the outreach service). **VERIFIED (2026-08-27):** after deploy the wiped names
were restored on the LA (`Los Angeles, CA, USA`) market — site_scrape re-scraped **1 → 20** contacts
(free `name_scrape_request`) and web_search re-searched **0 → 3** (paid `name_search_request`, ~9¢:
Cesar Fashen Jr. / Edgar A. Samayoa / Alex Preciado — the third drifted from the pre-wipe "Jason
Hanleybrown, CEO" to the SoCal regional manager, an accepted more-local result; web search is
non-deterministic). The surviving `prospect_name_scrape` / `prospect_name_search` markers held the
names through the wipe, which is what made a free/cheap restore possible. **Cleanup DONE — issue fully
resolved.**

### I-118 FIXED (2026-08-27) · A large enrichment order exceeds the 5-min cron window and gets stuck `running`
The market-wide `leads_n_contacts` order (118 places) ran ~4 min writing 101 markers, then the cron
container was terminated at the `*/5` boundary (~00:29→00:30), leaving 17 places unprocessed and the
order stuck `status='running'` with no recovery (the enrich drain claims only `pending` orders, and
there is no stale-order reaper for `enrichment_request`). Unlike `name_scrape`, the **enrich drain has
no per-tick place budget**, so one big order can't bound itself to the cron window or resume across
ticks. **Fixed** (mirrors `name_scrape`): (1) a per-tick PLACE budget `enrich_per_tick` (40) — the
drain enriches at most that many places per tick across all orders; an order with more is enriched up
to it and left PENDING to resume next tick (the idempotent marker skip re-bills only the un-done
places), so no tick can overrun the cron window; `process_order` now returns
`(report, billed, finished)` and the order's counters are the CUMULATIVE marker tally
(`_order_marker_tally`) so a multi-tick order still reports its whole self; cost_ledger writes one row
per billing tick. (2) `recover_stuck_orders` resets a `running` order older than
`enrich_stuck_order_minutes` (20) back to `pending` (conditional-on-still-running so it can't stomp a
live tick), called first in `drain` — the recovery half. Unit-tested (`test_enrich_queue`: resume
across ticks, whole-tick budget bound, stuck recovery, recent-order-not-recovered). Separate from
I-117 (data loss). The stuck 2026-08-27 order was cancelled by hand before the fix. **Merged +
deployed** (#769 → `main`, live on the outreach service). **VERIFIED IN PRODUCTION (2026-08-27):** the
same failure mode was re-run cleanly — the 17 places the killed order had stranded were re-enriched as
one `enrichment_request` that drained in **71 s within a single tick** (started 01:25:05, finished
01:26:16, 0 failed), well inside the `*/5` cron window, with no stuck `running` order. **Fully
resolved.**

### I-119 FIXED (2026-08-27) · The I-118 cron-window fix, ported to the PAID name_search drain
`name_search_queue` (the paid `web_search` owner/manager-name fallback, OpenAI gpt-5.4) had the SAME
latent I-118 vulnerability the enrich drain did: **no per-tick place budget and no stuck-order reaper**.
A web search is ~4 s/place, so a large `name_search_request` (dozens of places) drained as one order
could exceed the `*/5` cron window and get its container killed mid-run — stranding the order `running`
with no recovery. Surfaced while closing the LA generic-name gap (an ~83-place sweep would have tripped
it). **Fixed by porting the I-118 pattern verbatim** (mirrors `enrich_queue`): (1) per-tick PLACE budget
`name_search_per_tick` (24) — the drain searches at most that many places per tick across all orders; an
order with more is searched up to it and left PENDING to resume next tick (the idempotent marker skip
re-bills only the un-done places), so no tick overruns the window; `process_order` now returns
`(report, billed, finished)` and the order's counters are the CUMULATIVE marker tally
(`_order_marker_tally`, scoped by `name_search_request_id`) so a multi-tick order reports its whole self;
`cost_ledger` writes one row per billing tick. (2) `recover_stuck_orders` resets a `running` order older
than `name_search_stuck_order_minutes` (20) back to `pending` (conditional-on-still-running), called
first in `drain`. Unit-tested (`test_name_search_queue`: resume across ticks, whole-tick budget bound,
stuck recovery, recent-order-not-recovered — 14 pass; full suite 665). **Remaining sibling gap
(not fixed here, lower priority):** `name_scrape_queue` (the FREE site-scrape fallback) already HAS the
per-tick budget (`name_scrape_per_tick`) but still lacks the `recover_stuck_orders` reaper — a hard kill
(SIGKILL before its budget's work finishes) would strand a `running` order with no auto-recovery. It
wastes no money (free), only blocks that one order, so it's a cheap follow-up: port the same reaper.

### I-109 RESOLVED (2026-08-26) · TWO stacked bugs — sync mode AND the wrong enricher slug; fixed to async + `leads_n_contacts`
Enrichment was broken two ways at once, which is why every prior single-cause theory (wrong validator
set, parser aliases) only half-explained it:

1. **Sync mode** returned the base listing before the enrichers ran (see the update below) → fixed to
   async submit+poll (`enrich_client._enrich_one`, merged in #756).
2. **Wrong enricher slug.** Even async, `domains_service` (+ validators) returned no contacts. The
   owner's Outscraper **dashboard export** for the CSV that DID have people revealed the real slug:
   **`enrichments: ["leads_n_contacts"]`** — Outscraper's "Leads & Contacts" enricher (emails / phones /
   socials / domain + decision-maker `full_name`·`first_name`·`last_name`·`title` where they exist).
   `domains_service` is a bare website scraper; it was never the right one.

**Validated live (2026-08-26).** Re-enriched 5 LA plumbers that were email-null / business-name-only
under `domains_service`; under `leads_n_contacts` (async) all 5 returned real emails
(info@mlplumbing.net, fast24plumbing@gmail.com, …) plus domain + company socials, and the raw now
carries the full contact column set. Person names came back empty for these five specifically — the
raw `first_name`/`last_name`/`title` are genuinely null (not a parser miss): they are small
owner-operated businesses with no Apollo/ZoomInfo decision-maker record, so `leads_n_contacts` fell
back to their scraped site emails. A business WITH a decision-maker record (the hearing-aid stores in
the source CSV) populates the person fields — that is the whole point of the enricher.

**Fix shipped:** default `enrich_enrichments` → `["leads_n_contacts"]` (outreach api) and
`outreach_enrich_enrichments` → `"leads_n_contacts"` (platform-api). The public `/maps/search-v3`
endpoint accepts the slug on our async place_id call (no `/tasks` endpoint or category-search shape
needed). **Remaining:** cost per record for `leads_n_contacts` is unconfirmed (the placeholder
`enrich_cost_per_place_cents`=5 stands; the export carried `est:10` — likely pricier than a base pull),
tracked under I-111.

### I-109 UPDATE (2026-08-26) · ROOT CAUSE FOUND — enrichment was called SYNCHRONOUSLY, which returns the base listing with NO enrichers run; fixed to async submit+poll
The "Enrich just restates the business name" complaint traced to a fundamental integration bug, not a
wrong enricher set or a parser alias. `enrich_client._enrich_one` called `/maps/search-v3` with
`async=false`, and **Outscraper runs enrichments asynchronously** — a synchronous call returns the base
Maps record BEFORE the enrichers finish, so the response carries no `emails`, no scraped contacts, no
person fields at all, only `name_for_emails` (the business name). The parser then correctly fell back to
that business name. Every LA-plumber "contact" was this fallback over an un-enriched record, and a live
inspection confirmed the stored `raw` for those rows is a pure Maps record (no `emails`/`website_title`).

Confirmed by two `probe-enrich` runs (2026-08-26, owner-authorized, ~one billed record each, cron reverted
after each): (1) `company_insights_service` → firmographics only (employees/founded_year), no people;
(2) **our production set `domains_service,emails_validator_service,phones_enricher_service` against
Enhanced Hearing Center** — a business KNOWN to have LinkedIn/Apollo contact data (owner "Rex McGee" in a
real Outscraper dashboard export) — STILL returned a bare Maps record with `with_email:0` and
`full_name`=the business name. So sync mode yields nothing whatever the enricher set or the business.

**Fixed:** `_enrich_one` now submits `async=true` and polls the archive with `fetch_result` to completion
(the same submit/poll pair the mass ingest uses — the only path that returns the enrichers' output). New
`enrich_poll_timeout_seconds` (300s) is a per-place ceiling so one stuck-Pending place fails on its own
instead of hanging the tick for the mass-ingest 1h timeout. `fetch_result` gained an optional
`poll_timeout`. `submit_maps_search`'s `enrichment=""` base-tier invariant is untouched. Unit-tested in
`tests/test_enrich_client.py` (submit carries `async=true`, polls past Pending, tags by place_id,
per-place isolation). **Validate on a live re-enrich** before trusting output — the async path is the
proven fix for "returns nothing", but whether `domains_service` alone surfaces the Apollo/ZoomInfo *people*
(vs. site-scraped emails only) is the remaining field-shape question below; add the people-enricher slug
once a live async run shows what comes back.

### I-109 UPDATE (2026-08-10) · The enricher SET was wrong — corrected against a real response; domains_service field shape still to confirm
The first live enrichment ran (order drained in 5s, 1 contact) and produced the evidence the probe was
meant to: the response carried `name_for_emails` + the base listing `phone` + `website`, but **ZERO
email fields** (`emails` key absent). Root cause: the default set requested the POST-PROCESSORS
(`emails_validator_service`, `phones_enricher_service`) WITHOUT the scraper that actually finds emails.
That scraper is **`domains_service`** (the repo's own contact-pull convention — `pixel_probe` /
`run_market --enrichment` default), which reads the business's website and returns emails + contact names
+ phones for the validators to enrich. Fixed: the default enricher set is now
`domains_service,emails_validator_service,phones_enricher_service` (both configs).
**Still open:** the exact FIELD SHAPE `domains_service` returns is not yet seen against this account, so
the parser stays defensive and the stored `raw` is the recovery path — inspect the next real enrichment
and adjust `enrichment.py` aliases if the emails/contacts land under unexpected keys. Not fully closed
until a `domains_service` run is confirmed to yield real emails/people.

### I-109 · Outscraper enrichment param value(s) + response field names UNCONFIRMED — run `probe-enrich` first
**Severity: blocks trusting production enrichment OUTPUT; does not block the code.**
No enriched pull has ever run against this account, so — exactly like I-018 for the base pull and I-003
for the pixel field — the exact `enrichment` param VALUE(S) (the guess is
`emails_validator_service,phones_enricher_service`, config `enrich_enrichments` /
`outreach_enrich_enrichments`) and the RESPONSE field names are unverified. `services/enrichment.py`
reads the documented "Emails & Contacts" column shape (both nested and flat forms) DEFENSIVELY and asserts
nothing; every record's untouched fragment is stored in `prospect_contact.raw` / `prospect_enrichment.raw`,
so a corrected alias re-parses stored data for free (no re-pull).
**Action (owner-authorized, one billed call):** deploy + run `probe-enrich` with
`OUTREACH_CONFIRM_SPEND=probe-enrich` on one place (`--place-id` or the market's first prospect). It prints
the parsed summary and LOGS the full record (`enrich sample record`). Read the log, confirm the enricher
set + field paths, adjust `enrichment.py`'s aliases if they differ, and (if needed) re-parse via a small
backfill over stored `raw`. Until then, treat parsed contact fields as provisional.

### I-110 · A stuck-`running` enrichment order is not auto-resumed
Like `scan_request`/`onboard_request`, a container death mid-drain leaves an `enrichment_request` at
`running` with no reaper (the outreach service is a cron, not an async_jobs worker). Correctness is
protected by idempotency — a NEW order over the same prospects skips the ones already enriched (no re-bill)
— but the stuck row itself is not retried by the machine, matching the module's "terminal failure, human
re-places" philosophy. A re-order is the cheap resume. If enrichment volume grows enough that this bites,
add an owner-id + heartbeat claim (the same upgrade the scan drains would need for >1 replica).

### I-111 · Enrichment billing rate is a placeholder, in TWO places that must stay in sync
`enrich_cost_per_place_cents` (outreach job — drives the `cost_ledger` write) and
`outreach_enrich_cost_per_place_cents` (platform-api — drives the free preflight estimate + the per-user
daily budget guard) are both `5`, a GUESS. Outscraper returns no per-request cost, so like every rate here
the ledger is `units × rate` reconciled manually against the dashboard (I-022). **Action:** set BOTH from
the real plan before a production run, and keep them equal — the budget guard is exactly as honest as the
platform-api value, and the ledger as honest as the outreach one.

### I-112 · Enrichment daily-budget guard has a benign check-then-insert race
`create_enrichment_request` reads a user's spend-today and inserts without a lock, so two concurrent
orders by the same admin (a double-click, or a per-row Enrich fired alongside a bulk order) can both
pass the guard and land slightly over `outreach_enrich_daily_budget_usd`. Bounded by one extra order's
estimate; identical shape to LeadOff's `check_budget`. **Left as-is** — soft guard, single admin,
cheap enrichment; a DB-side atomic check isn't worth the complexity at this volume. Revisit if
enrichment ever runs unattended or multi-user.

### I-113 · An order's progress counters undercount when a selected prospect is deleted before the drain
If a `prospect` in an `enrichment_request`'s selection is deleted between placement and drain, it is
excluded from `to_enrich`, so the order's `enriched_count + skipped_count + failed_count` (the
`progress.done`) is less than `requested_count`. **Cosmetic only** — the order still resolves to
`done` and the UI batch completes (useResumableBatch keys on the order STATUS, not the counts), so
nothing hangs. Left as-is; if a precise reconciliation is ever wanted, add a `vanished_count`.

### I-114 · Site name-scrape extraction PRECISION is unvalidated against real sites
`name_extract.extract_names` is conservative by construction — role-anchored (a name only counts tied
to an explicit `owner`/`founder`/`president`/… role or schema.org `founder`/`employee` with a matching
`jobTitle`), with nav-chrome / trade-word / business-name (one-directional, I-099) rejection and a
Title-Case 2–3-token name shape. It is tuned to FAIL TOWARD A MISS. But it has been tested only against
hand-written golden fixtures (`tests/test_name_extract.py`), never against a corpus of real small-business
sites, so its true precision/recall is unknown. A scraped name is therefore surfaced with a "from website"
badge and carries NO verified email/phone (unlike an Outscraper contact) — a caller must verify it before
using it on a call. **Action:** once the first real `scan-names` / `name_scrape_request` runs land, sample
the `prospect_name_scrape.raw` evidence against the live sites and tune the role vocabulary / patterns from
what it missed or over-matched (the `raw` evidence makes this a re-read, not a re-fetch). Recall is the
likelier weakness (a site that names the owner only in an image, a PDF, or JS-rendered content is a miss).

**UPDATE — first live run (2026-08-26).** Ran `name_scrape_request` over all 84 website-carrying
prospects of the LA emergency-plumber market (`9238e737…`): 14 found / 20 names / 15 unreachable, and the
paid `name_search_request` over 5 no-website prospects: 3 cited names / 2 correctly dropped (~15¢). The high-
confidence JSON-LD names are clean (8 at 82–100: *Roy Riddle, Founder* / *Jay Morton, Founder* / *Shane
Lucas, Founder* …), which confirms the extractor's precision on the structured-data path. Two live over-match
cases on the *text* path (both landed in the medium band, so the confidence layer contained them — but the
extractor did not reject either):

  1. **A PLACE NAME matched as a person.** "Los Angeles" was extracted as a "Founder" (A-1 Total Service
     Plumbing, `source_kind=text`, conf 62). The Title-Case 2–3-token shape + role-anchor accepts a
     multi-token toponym because it is neither a business token nor a stopword. Cheapest fix: add a small
     curated place-name / toponym stoplist to `is_plausible_name` (the market's own city + common US
     locality words), OR reject a candidate that is entirely city/region tokens the way the business-name
     guard already rejects business tokens (one-directional, I-099). Do NOT reach for NER — it reintroduces
     the fabrication surface the whole module avoids.

  2. **A non-owner "Manager" from a mis-ingested prospect.** "Carol P. Parks, General Manager"
     (emergency.lacity.gov) and "Aril Aril, Office Manager" (a SERVPRO franchise) were named because a city
     emergency-management office and a restoration franchise were ingested as "emergency plumber" prospects
     in the FIRST place. The scraper did its job; this is a prospect-INGEST precision question (the filter
     upstream of the fallback), not an extractor defect — logged here only because the live run surfaced it.
     Track under the ingest/filter work, not I-114's tuning.

Recall (the predicted likelier weakness) held up: the 15 `unreachable` sites are the recall ceiling for now,
not extraction misses on reachable pages. Web-search soft-match note: *Fast Water Heater → "Jason
Hanleybrown, CEO"* cited to a national chain's blog page — a local listing attributed to the national brand's
officer; the blended confidence correctly ranked it lowest (51) and the "verify" framing is exactly for this.

### I-115 · Name-scrape `unreachable`/`failed` are retried on every re-order (no backoff)
The drain treats `found`/`no_names` as durable (never re-scraped) but `unreachable`/`failed` as retryable,
so a re-placed order re-fetches a site that was down. That is the intended semantics (a site up now that was
down before), but there is no per-prospect backoff or attempt cap — repeatedly re-ordering a selection that
includes a permanently-dead domain re-fetches it each time. FREE (own HTTP GET, no spend), so this is only
wasted work, not wasted money, and it is bounded by `name_scrape_max_places_per_order` per order. **Left
as-is** — cheapest-to-reverse; add an `attempts` counter + a stale-retry cutoff on `prospect_name_scrape`
if a dead-domain re-fetch loop ever shows up in practice.

### I-116 · Name-scrape SSRF guard does not cover DNS-rebinding
`name_scrape.is_public_host` blocks localhost + IP-LITERAL private/loopback/link-local/reserved hosts
before fetching and on the post-redirect `final_url`, which stops the common metadata-endpoint /
localhost vectors. It does NOT resolve hostnames, so a domain whose DNS resolves to a private IP (a
rebinding attack) is not caught — resolving in-process would add latency + a TOCTOU gap and is out of
scope for a best-effort site fetch. Same residual applies to `scan_tech`'s homepage fetch (shared
`fetch_page`, `follow_redirects=True`). **Left as-is** — the prospect sites are agency-chosen targets,
not arbitrary attacker input; revisit with an egress allowlist / resolving guard if the fetch surface
ever widens to untrusted submissions.
