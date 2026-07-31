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

---

## RESOLVED

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

**Still reversible, and only until the first scan.** Every `submarket.last_scanned_at` is null, so
the geometry can still change freely today. Raised with the owner and implemented on the
spec-literal reading in the absence of a contrary instruction — recorded here as decided-by-me,
not as confirmed.

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
