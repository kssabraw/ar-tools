# HANDOFF — Outreach Pipeline

**Read this first, then `CLAUDE.md` → `START-HERE.md` → `ISSUES.md` → `DECISIONS.md`.**

Status as of 2026-07-31:

- **Phase 1 (ingest + filter) is COMPLETE, verified against a real market, and MERGED to `main`** (#528, squashed as `67f235b`).
- **Phase 1b (lead CRM) is COMPLETE and applied live.** PR [#534](https://github.com/kssabraw/ar-tools/pull/534) is open, draft, green, rebased onto Phase 1.
- **Phase 2 has not been started.** Do not start it without being asked, and read §8 first — it is blocked on credentials that do not exist yet.

**The biggest thing that changed today is architectural: this is now an AR Tools suite module, not a standalone tool.** See §2. It supersedes parts of what Phase 1 recorded, and reading Phase 1's decisions without it will mislead you.

---

## 1. What exists right now

| Thing | Where | State |
|---|---|---|
| Code | `outreach/` in `kssabraw/ar-tools` | Phase 1 on `main`; Phase 1b on `claude/lead-crm-foundation-mb1k9g` |
| Phase 1 PR | [#528](https://github.com/kssabraw/ar-tools/pull/528) | **merged** 2026-07-31 |
| Phase 1b PR | [#534](https://github.com/kssabraw/ar-tools/pull/534) | open, draft, CI green, 9 files |
| Database | Supabase project **Outreacher**, ref `fkwhgvcggvsricuinuqy` | Phase 1 + Phase 1b applied; LA ingested and filtered |
| Job runner | Railway service **outreach**, id `928c84bc-d7ca-416a-bd61-39e91cc64872` in project `ar-tools` (`2c718e53-…`) | no cron schedule; **repoint its source at `main`** now that #528 is merged |
| platform-api integration | not built | §8.1 — this is the next build |
| Suite UI | not built | nothing in `frontend/` |

**This is a SEPARATE Supabase project from AR-Internal-Tools.** Do not point outreach code at the suite's database, and do not put outreach migrations in `writer/supabase/migrations/`.

Live row counts: `prospect` 1,388 · `filter_result` 8,328 · `submarket` 14 · `keyword` 5 · `market` 1 · `cost_ledger` 19 · `lead` 0 · `lead_activity` 0 · `lead_stage` 7 · `suppression` 0.

### Railway service configuration

```
source           kssabraw/ar-tools @ claude/phase-1-outscraper-ingestion-llje34   ← STALE, move to main
rootDirectory    /outreach
railwayConfigFile  outreach/railway.toml   ← repo-root-relative, NOT relative to rootDirectory
builder          DOCKERFILE (from railway.toml)
restartPolicy    NEVER                     ← this is a job; ALWAYS would re-run the paid ingest in a loop
cronSchedule     (none yet)
startCommand     sh -c "exec python -m api.scripts.run_market ${OUTREACH_COMMAND:-filter} ${OUTREACH_MARKET:-markets/los-angeles-plumbing.json}"
```

Variables set: `OUTREACH_SUPABASE_URL`, `OUTREACH_SUPABASE_SERVICE_ROLE_KEY`, `OUTREACH_OUTSCRAPER_API_KEY`, `OUTREACH_COMMAND` (currently `filter`), `OUTREACH_MARKET`.

**There is no DataForSEO credential on this service.** Phase 2 cannot run without one — see §8.2.

> The Outscraper key and the Supabase service-role key were pasted into a chat transcript during the Phase 1 build. Rotating both is cheap and worth doing.

---

## 2. THE RULING THAT CHANGES HOW YOU READ EVERYTHING ELSE

**The outreach pipeline is an AR Tools suite module** (owner ruling, 2026-07-31). Recorded in `DECISIONS.md`.

It **amends, without withdrawing,** Phase 1's decision that the code lives in this repo while the database is a separate Supabase project. The storage half of that reasoning stands — ~64M `grid_result` rows a year would eat the suite project's headroom, and the storage spec sized partitioning for a dedicated project.

What was wrong was the *inference*. Phase 1 recorded a consequence: *"a separate project means a separate `auth.users` pool… do not expect SSO with existing AR Tools users."* That let a decision about where the **data** lives decide where the **application** lives. Those are separable.

**So: the database stays in Outreacher; the API and UI move into `platform-api` and the suite SPA.**

This dissolves the SSO cost rather than paying it. platform-api holds the Outreacher service-role key and is the **only** client, so staff authenticate against the suite exactly as for every other module and never need an Outreacher account.

### What follows from it — do not undo these by accident

- **Retool is dropped.** So is the per-user RLS model built for it. §8a of the CRM spec says to write per-owner policies at launch; that instruction was aimed at a direct database connection which no longer exists. The policies are **removed**, not left permissive-and-tightened-later — a policy on a table nothing reaches through PostgREST is an access model that looks load-bearing and is not.
- **Access is service-role only**: RLS enabled, zero policies, no grants to `anon`/`authenticated`. Same posture as every other table in the estate.
- **Authorization belongs in platform-api**, beside the suite's existing role checks.
- **Identity columns have no foreign keys.** `lead.owner_id`, `lead_activity.actor_id`, `lead.created_by` carry the **AR Tools** profile id from AR-Internal-Tools. Postgres cannot enforce that across databases. Dropping the FKs loses real integrity; the alternative was a column pointing at a pool that will stay permanently empty.
- **No cross-database joins.** A won lead becomes an AR Tools client through an API call, not a foreign key. Worth knowing before designing a report that assumes otherwise.
- **Anything telling you to create Supabase auth users for this project is out of date** (`ISSUES.md` R-011).

---

## 3. The Los Angeles result (real, verified)

Market `Los Angeles, CA — Plumbing`, 14 submarkets, category `plumber`.

| | |
|---|---|
| Listings returned (billed) | 2,807 across 15 tile-pulls |
| Prospects after `place_id` dedup | **1,388** |
| Tile overlap rate | 14.7% |
| Cost recorded | $5.68 — **at the placeholder rate, see §7.1** |
| Survived the filter | **925** |
| Excluded | 463 |
| Flagged as possible franchise | 22 (all still in play — flag never excludes) |

Failures per rule: `review_count_min` 433 · `has_phone` 46 · `not_franchise` 22 · `business_status_open` 14 · `not_suppressed` 0 · `review_recency` 1,388 `not_evaluated`.

Every acceptance criterion in `docs/PHASE-1-BRIEF.md` §5 is met. Verified independently: 30 prospects failed more than one rule with every rule logged (not first-match-only); all 1,388 are in California (one distinct state); every prospect has a submarket; `prospect_score` was never written.

**2,807 listings cost roughly double what one clean run costs** — two full ingests ran (see §6.4). A single LA run is ~1,400 places.

---

## 4. Running it

```bash
# tests — no network, no database
cd outreach && python -m pytest api/tests -q      # 85 passing

# locally (needs OUTREACH_* env vars and network egress to Outscraper + Supabase)
python -m api.scripts.run_market seed      markets/los-angeles-plumbing.json
python -m api.scripts.run_market calibrate markets/los-angeles-plumbing.json   # 1 tile, ~20 places
python -m api.scripts.run_market ingest    markets/los-angeles-plumbing.json   # PAID
python -m api.scripts.run_market filter    markets/los-angeles-plumbing.json   # free
python -m api.scripts.run_market run       markets/los-angeles-plumbing.json   # seed+ingest+filter
```

On Railway, the run mode is `OUTREACH_COMMAND`. **Only `ingest` and `run` spend money.**

Success is the log line `OUTREACH_RESULT status=ok command=<cmd> exit=0`. **The Railway deployment status is NOT a success signal** — see §6.2.

Definition-of-done SQL: `queries/phase1-dod.sql`. Adding a market: copy `markets/EXAMPLE-kansas-city-plumbing.json`, fill it in, `seed`. Idempotent.

**The CRM verification script** is `tests/lead_crm_rls.sql` — paste into the Supabase SQL editor for Outreacher, or run through the MCP `execute_sql` tool. 17 checks, self-cleaning fixtures, every line prints `(correct)` or `(WRONG)`.

---

## 5. Phase 1b — the lead CRM

Applied live and verified. Detail in `PHASE1B-STATUS.md`; the reasoning is in `DECISIONS.md` and `ISSUES.md` R-011/R-012.

| Object | Notes |
|---|---|
| `lead` | spec §3 shape: six-value `source`, seven-stage workflow, `lost_reason` + `lost_to`, `next_action`/`next_action_due`, `stage_changed_at` |
| `lead_activity` | append-only commentary; real `from_stage`/`to_stage` columns; `touch_id` carried **without** its FK until Phase 3 creates `touch` |
| `lead_stage` | lookup table carrying the spec's seven stages, plus `sort_order`/`is_terminal` for the board |
| `suppression` | Phase 1's table, patched additively. **No delete path** — spec §4 says these records are never deleted |
| `lead_inbox`, `lead_detail`, `v_overdue_actions` | `security_invoker` views |
| `lead-intake` edge function | deployed, fails closed until `LEAD_INTAKE_SECRET` is set (§7.5) |

### Read the two migrations in order

`20260731150000_lead_crm.sql` then `20260731190000_lead_crm_spec_reconcile.sql`. The first is **deliberately left wrong** with comments explaining each mistake; the second corrects them. That history is the point — see §6.11.

### Invariants specific to this layer

- **`outcome` is outbound-only, and it is Phase 3's table.** Phase 1b creates neither `outcome` nor `touch`. It ships `lead.unique (prospect_id, source)` as the FK target that makes the rule structural rather than a trigger convention — because a *promoted inbound lead also carries a `prospect_id`*, so keying on prospect alone cannot distinguish them. Full DDL for Phase 3 in `PHASE3-outcome-constraint.md`. Verified live against the real key with a throwaway probe table.
- **Suppression flags, never rejects.** Matching lives in a `BEFORE INSERT` trigger so no write path can skip it, and a match sets `suppressed_at` rather than refusing the row. Discarding an inbound lead because a stale suppression matched is unrecoverable; a flagged row is visible and reversible.
- **`lead_activity` is human commentary only.** `touch` is authoritative for "a contact attempt happened". There is no `email_sent` or `call` kind; a call writes a `touch` and a `call_note` referencing it.

---

## 6. Traps — every one of these cost real time or money here

### 6.1 Railway `redeploy` replays the OLD deployment's config
Changing `startCommand` and calling redeploy silently re-runs the *previous* command. Twice, and it looked identical each time. Only a **fresh deployment** picks up config changes. This is why run mode is driven by `OUTREACH_COMMAND` through one entrypoint.

### 6.2 Railway reports a CRASHED job as deployment status SUCCESS
With `restartPolicy: NEVER`, a job that dies on an unhandled exception still shows SUCCESS and posts a green commit status to the PR. Trust `OUTREACH_RESULT`, not the badge.

### 6.3 The Railway log stream LAGS the container — do not diagnose from it
A run was concluded dead at 09:09:54 because logs stopped. It completed at 09:11:01. The Railway agent agreed with that diagnosis **because it was reading the same lagging stream** — that is not corroboration. **Check `cost_ledger` and `prospect` in the database**; those are written synchronously and are ground truth.

### 6.4 …and that misdiagnosis caused a duplicate paid ingest
Pushing the "fix" auto-deployed while `OUTREACH_COMMAND=run` was still set, firing a second full pull nobody asked for — about half the $5.68. **Set `OUTREACH_COMMAND` back to `filter` immediately after any paid run.** See §7.2.

### 6.5 PostgREST silently caps an unbounded `select()` at 1000 rows
No error, no header, nothing a caller notices. `run_filter` read 1,000 of 1,388 prospects and left 215 unfiltered; "how many survived" would have undercounted, confidently. **Every read that grows with the portfolio must go through `services/paging.fetch_all`.** Its argument is a *callable* — supabase-py builders are stateful, and reusing one compounds `.range()` instead of replacing it, which pages wrongly in a way that also looks fine.

### 6.6 A directory named `supabase/` shadows the installed `supabase` package
Migrations live in `outreach/migrations/`, not `outreach/supabase/`. Once `/outreach` is on `sys.path`, Python resolves `from supabase import Client` to the directory and fails as `cannot import name 'Client' from 'supabase' (unknown location)`, which reads like a version problem.

### 6.7 Tile geography must be pinned TWICE
A pull for `plumber, Downtown Los Angeles` with no coordinates and no region returned businesses in **Jersey City, New Jersey**. Both the `coordinates` bias *and* the `region` qualifier are required. The failure mode is the dangerous kind: a market full of the wrong state's businesses parses at 100%, passes every filter, and is worthless.

### 6.8 The AR Tools repo is a source of verified provider behaviour
`writer/platform-api/services/gbp_service.py` has been calling Outscraper with this same API key in production for months. **Check the repo before the vendor docs.**

### 6.9 Outscraper returns errors as HTTP 2xx
`{"error": true, "errorMessage": ...}` in the body with a 200 status. Status-code-only handling swallows them.

### 6.10 Railway's `railwayConfigFile` resolves against the REPO ROOT
Not against `rootDirectory`. Getting it wrong means the config is never read and the builder silently falls back to Railpack. It must be `outreach/railway.toml`.

### 6.11 Building from a plan *derived from* a spec is not building from the spec
Phase 1b's schema was built from a plan written against `crm-layer-spec.md` without the spec in context. Four vocabularies were guessed, and the worst — `source` — could not record a `manual` lead, which is the entire reason the CRM track runs in parallel with Phase 1. **If a spec exists, open it.** Corrected in `ISSUES.md` R-012.

### 6.12 Supabase grants ALL to `anon` and `authenticated` by default — REVOKE FIRST
A bare `grant select, insert` on a new `public` table **adds nothing and removes nothing**. It reads like a restriction while leaving UPDATE, DELETE and TRUNCATE in place. Two consequences, both live for a while here:
- **An UPDATE with no matching RLS policy is not an error — it silently affects zero rows.** Append-only on `lead_activity` was resting on the absence of a policy, so a "save note" button would have reported success and changed nothing. A silent wrong outcome is worse than a refusal.
- **TRUNCATE is not subject to RLS at all.** No policy can stop a role that holds it; only the grant can.

### 6.13 `SECURITY DEFINER` functions in `public` are callable as RPC
All three CRM trigger functions were reachable at `/rest/v1/rpc/<name>` by `anon`. Invoking a trigger function directly errors, so it was not exploitable — but that is a weak thing to rely on for a definer-rights function. **Revoke `execute`.** Found by the Supabase security advisor, *not* by the verification script: the two catch different classes of problem, so run both.

### 6.14 `now()` is TRANSACTION time — it will fake a test failure
Comparing `stage_changed_at` to `created_at` inside one transaction shows no movement whether the trigger fired or not, because both resolve to the same transaction timestamp. That false failure is exactly what invites someone to "fix" a working trigger. Backdate the column first, then act. Same reason `now()` is illegal in an index predicate (it is not immutable) — filter liveness at query time instead.

### 6.15 Two branches appending to the same `ISSUES.md` collide silently
Phase 1 and Phase 1b ran in parallel and both appended from the same `I-014` base. Both defined `I-015`…`I-019`, differently. Nothing in git flags it — the files merge cleanly and you end up with two `I-017`s. Phase 1b's were renumbered to **I-037+**. If you see a pre-2026-07-31 reference to "I-017", it means the CRM schema divergence, now **R-012**.

---

## 7. What is NOT done

### 7.1 The Outscraper billing rate is still a placeholder — do this first
`outscraper_cost_per_1000_places_cents` is **200¢/1000, a guess**. Every cost figure above and the `max_market_run_cost_cents` abort gate are only as honest as that number. 2,807 places have been pulled; divide the Outscraper dashboard charge for 2026-07-31 by 2,807, multiply by 1000, set the variable. (`ISSUES` I-033.)

### 7.2 A paid run should need more than a variable
`OUTREACH_COMMAND=run` plus deploy-on-push means **any push to the tracked branch fires a paid ingest**. This actually happened (§6.4). Before any cron schedule is set, gate paid runs behind something the deploy path cannot supply on its own.

### 7.3 Grid geometry ambiguity — free now, frozen forever after the first scan
`ISSUES` I-025: the specs describe an **89-point** geogrid at 1-mile spacing over a 5-mile radius. A 1-mile lattice in a 5-mile radius holds **81** (exactly 9×9). 89 matches neither. No Phase 1 impact, but **Phase 2 pins geometry and it becomes immutable**, and the 14 LA submarket centroids are freely editable only until then. **Settle this before the first scan.**

### 7.4 `ai_region` does not exist
Not as a table, not as data. AI checks run per `ai_region`, which is a *different and coarser* geography than `submarket` — several submarkets share one region. Drafting the names is a Phase 0 manual task that was never done, and it needs human judgement about which place names an LLM actually recognises. Blocked on §8.2.

### 7.5 Smaller open items
- **I-037** — `LEAD_INTAKE_SECRET` unset; the intake function fails closed and has **never been invoked**. Under §2 it is also a candidate for retirement in favour of a platform-api route.
- **I-038** — Phase 1's live `suppression` (`id, scope, value, created_at`) does not match spec §3 (separate `email`/`phone` columns). Recommendation: amend the spec — scope/value generalises to `place_id` suppression, which fixed columns cannot express.
- **I-039** — spec §3 indexes `lead_activity (prospect_id, …)`, a column that does not exist in its own DDL. Logged rather than silently corrected, per the session protocol.
- **I-034** — nothing reads `OUTREACH_RESULT` yet. A log line nobody greps ≈ a green tick nobody questions.
- **I-020/I-026** — franchise pattern list is an unvalidated seed. 22 matched in LA. Improvable from data: a name at ≥3 distinct `place_id`s in one market is almost certainly a chain.
- **I-024** — the raw landing dir is on-disk and opt-in; it belongs in R2 in Phase 2.

---

## 8. What to do next

### 8.1 Unblocked, and the highest-regret thing to defer
1. **The platform-api `outreach` router.** A project-scoped Supabase client — the `services/leadoff_db.py` / vendored-fanout pattern, extended to a second Supabase **project** rather than a second schema, which is new ground in this codebase. Then suite SPA pages. Nothing in `frontend/` exists.
2. **Phase 2 storage foundations.** `grid_result` partitioning and the retention jobs, per `docs/storage-retention-spec.md` — which **owns** that table (the PRD's copy is context only). The spec is emphatic that this must exist *before cycle two writes data*; retrofitting partitioning onto a multi-gigabyte table is materially harder than building it first. Zero spend, no credentials needed.
3. **The pinned, versioned grid-geometry function.** Pure math, unit-testable, no network. Settle §7.3 first.

### 8.2 Blocked on a human
- **DataForSEO credentials on the `outreach` Railway service.** It is the sole provider for geogrid, organic SERP and AI Overview. The service holds only `OUTREACH_OUTSCRAPER_API_KEY`. Also needs a **public callback URL** — the spec requires postback, not polling, and this is a command worker with no domain.
- **`ai_region` names for LA** (§7.4). A candidate list can be drafted from the 14 submarkets for a human to correct.
- **Two verification spikes, ~80 minutes total.** `I-004` AI prompt granularity (~20m) decides the `ai_region` grain — too fine and the model silently falls back to metro while you believe you asked a specific question. `I-003` Outscraper pixel field (~1h) decides whether the site-fetch parse is optional or required, which changes the money-signal cost model.
- **Spend approval.** ~$3–6 per market-vertical per cycle, guarded at `max_market_run_cost_cents` 5000 — a gate that is only as honest as §7.1.

### 8.3 Do not
- Start Phase 2 scanning before §7.3 is settled and partitioning exists.
- Add RLS policies to the CRM tables to silence the advisor's `rls_enabled_no_policy` INFO notices. That is the intended posture (§2).
- Point outreach code at AR-Internal-Tools, or file an outreach migration under `writer/supabase/migrations/`.
- Trigger a paid Outscraper or DataForSEO run without being asked. `OUTREACH_COMMAND` must stay `filter`.

---

## 9. Layout

```
outreach/
├── HANDOFF.md                 this file
├── CLAUDE.md                  session protocol + invariants
├── START-HERE.md              build phases, table ownership, config reference
├── DECISIONS.md               settled decisions WITH reasoning — read before proposing changes
├── ISSUES.md                  open problems, corrections, unvalidated assumptions
├── PHASE1B-STATUS.md          the CRM layer: what exists, access model, what is left
├── PHASE3-outcome-constraint.md   the DDL Phase 3 must adopt for outbound-only `outcome`
├── docs/                      the six specs (PRD is Phase 2+; the Phase 1 brief is self-contained)
├── markets/                   one JSON per market-vertical; EXAMPLE-* is the template
├── migrations/                SQL, applied out-of-band via the Supabase MCP — never by the job
├── functions/lead-intake/     Supabase edge function (inbound leads)
├── queries/                   phase1-dod.sql
├── tests/
│   ├── lead_crm_rls.sql       17-check CRM verification (run in the SQL editor)
│   └── fixtures/              golden scorecard fixtures — Phase 4, hand-computed, never regenerate
├── Dockerfile · railway.toml  the Railway job image and its restart policy
└── api/
    ├── config.py              every tunable; nothing hardcoded
    ├── db.py                  Supabase client (service role)
    ├── services/              outscraper_client, parser, tiling, filters, suppression,
    │                          cost, paging, seeding, pipeline
    ├── scripts/               run_market (the entrypoint), calibrate, calibrate_standalone
    └── tests/                 85 tests, no network or database
```
