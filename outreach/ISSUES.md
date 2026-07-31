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
