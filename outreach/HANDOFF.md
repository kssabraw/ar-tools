# HANDOFF — Outreach Pipeline

**Read this first, then `CLAUDE.md` → `START-HERE.md` → `ISSUES.md` → `DECISIONS.md`.**

Status as of 2026-08-05:

- **Phase 1 (ingest + filter) is COMPLETE, verified against a real market, and MERGED to `main`** (#528, squashed as `67f235b`).
- **Phase 1b (lead CRM) is COMPLETE, applied live, and MERGED to `main`** (#534, squashed as `452a726`).
- **The platform-api `outreach` router, Phase 2 storage/partitioning and the pinned grid-geometry generator are MERGED** (#538, squashed as `a7acc05`). Migrations applied live.
- **I-041 is RESOLVED BY DECISION.** `review_count_inferred_zero` is set on **105 prospects**, `review_count` left NULL, with a trigger that records any future contradiction. See §9.
- **Paid runs are now gated in code, not by procedure** (§7.2, closed). `OUTREACH_COMMAND` resolves to `filter` when absent, and every paid command additionally requires `OUTREACH_CONFIRM_SPEND` to equal its own name.
- **I-069 is RESOLVED (#554, `b6700999`).** A partial rollup can no longer pass verification: `finalize_snapshot_rollup()` raises inside the rollup transaction and the retention guard requires its marker. Applied live and verified in both directions. See ISSUES I-069.
- **The LA `ai_region` candidates are drafted (I-073)** from evidence already in the data — 10 of 14 submarket names are unambiguous localities, 3 are not. No engine calls were needed. See ISSUES I-073.
- **The maps geogrid client + `tasks_ready` collector is BUILT and MERGED (#557, `29914108`).** Migration `20260804120000_scan_task.sql` applied live. Two commands — `scan` (paid, one submarket × one keyword) and `collect` (free, never spend-gated). See §8.1a for what it does and §11 for the two things standing between it and real rows.
- **The I-004 spike instrument is BUILT and MERGED (#556, `ccb7e912`)** — `probe-ai-granularity`, nine OpenAI calls, three place names × three samples. **It has not been run.** The key is set as a Railway reference; the run needs a Deploy plus `OUTREACH_CONFIRM_SPEND=probe-ai-granularity`.
- **The `prospect_coverage` rollup is BUILT and MERGED (#559, `d802dbf`; migration `20260805120000`, applied live, 18/18 live checks passing).** Land masking (`grid_point_status`) and dead-point exclusion land with it, because both change the coverage DENOMINATOR. One plpgsql function per snapshot ending in `finalize_snapshot_rollup()`, so `rank_vector` cannot be separated from the numbers it belongs to. A free `rollup` command, and `collect` now rolls up what it finalizes. See §8.0b.
- **The placeholder score is BUILT and MERGED (#561, `902be5f`)** — `v_prospect_placeholder_score` (migration `20260805150000`), a view over `prospect_coverage`. Deliberately NOT a `prospect_score` row: that table is the Phase 4 model's and `v_prospect_ranked` already reads it as a fitted score (ISSUES I-082). **I-078 is RESOLVED** — `scan_snapshot` now records its own grid centre, which had to land before the first snapshot rather than after.
- **The first scan is PREPARED, not run** (2026-08-06). Live Railway config read and recorded, the target picked (`Van Nuys` × `plumber`, with reasoning), the runbook written and the post-run read built as `queries/first-scan-verify.sql` — 14 checks, every statement executed against the live schema so it parses. **See §11b.** The three things it waits on are still the three in §11, and all three are the owner's. Five findings came out of reading the paths the run is about to execute: **I-083** (the first snapshot is the likeliest to be incomplete, which pins its partition forever), **I-084** (how `serp_result` attaches to a grid-shaped `scan_snapshot` — this blocks 2d's design), **I-085** (I-071 has half-fixed itself), **I-086** (**the geogrid spends money and writes no `cost_ledger` row, and the budget ceiling does not cover scans**) and **I-087** (`recovered_by_tag` exists only in a log line). None are fixed.
- **NOTHING HAS BEEN SCANNED.** The scan layer now has a producer, a consumer, and no data: `scan_snapshot`, `scan_task`, `grid_result`, `prospect_coverage`, `grid_point_status` are all empty. `OUTREACH_COMMAND` is `filter` and both spend variables are empty. **What is missing is no longer code — it is a deploy, a confirm token, and a second cron schedule** (§11).

**Two things changed on 2026-08-03 that will mislead you if you read the older sections first.** The spend gate above supersedes the "set it back to `filter` afterwards" procedure this file used to rely on (§7.2), and the Railway configuration recorded in §1 was found to be **stale in two ways that each cost money** — read `get-service-config`, not this file, for live values.

**The biggest structural thing remains architectural: this is an AR Tools suite module, not a standalone tool.** See §2. It supersedes parts of what Phase 1 recorded, and reading Phase 1's decisions without it will mislead you.

---

## 1. What exists right now

| Thing | Where | State |
|---|---|---|
| Code | `outreach/` in `kssabraw/ar-tools` | all merged to `main` — Phase 1, 1b, Phase 2 foundations (#538), I-069 (#554) |
| Phase 1 PR | [#528](https://github.com/kssabraw/ar-tools/pull/528) | **merged** 2026-07-31 |
| Phase 1b PR | [#534](https://github.com/kssabraw/ar-tools/pull/534) | **merged** 2026-07-31 as `452a726` |
| Phase 2 foundations PR | [#538](https://github.com/kssabraw/ar-tools/pull/538) | **merged** as `a7acc05` |
| Database | Supabase project **Outreacher**, ref `fkwhgvcggvsricuinuqy` | Phase 1 + 1b + Phase 2 storage applied; LA ingested and filtered |
| Job runner | Railway service **outreach**, id `928c84bc-d7ca-416a-bd61-39e91cc64872` in project `ar-tools` (`2c718e53-73c8-4de8-bef8-7136f06b6ead`) | no cron schedule; auto-deploy-on-push DISABLED (2026-08-01); source **actually** on `main` since 2026-08-03 (the 2026-08-01 repoint did not stick — I-065). Runs only on a manual Deploy |
| platform-api integration | `routers/outreach.py` + `services/outreach{,_db}.py` | **built** — 14 routes, read-only over the pipeline, read/write over the CRM |
| Suite UI | not built | nothing in `frontend/`. NOT the next build, and **not a prerequisite for scanning** (§11a) — see ISSUES I-072, which asks for a decision rather than a default |
| Grid geometry | `api/services/geometry.py` | **built**, version `v1`, **81 points** (I-025 resolved) |
| Geogrid scan client | `api/services/maps_scan.py` (pure) + `scan_runner.py` (I/O) | **built** (#557) — `task_post` batching, `tasks_ready` collection, finalization. Never run |
| Scan bookkeeping | `scan_task` table, migration `20260804120000` | **applied live**, empty |
| Coverage rollup | `rollup_snapshot_coverage()` + `grid_point_status`, migration `20260805120000`; `api/services/coverage_rollup.py` | **applied live**, verified by `tests/coverage_rollup.sql` (18 checks). Never run against real data — there is none |
| Placeholder score | `v_prospect_placeholder_score`, migration `20260805150000` | **applied live**. A view; `prospect_score` stays empty until Phase 4 (I-082) |
| I-004 spike | `api/services/ai_granularity.py` + `probe-ai-granularity` | **built** (#556), **never run** — needs a Deploy + confirm token |
| First-scan runbook + read | `HANDOFF.md` §11b · `queries/first-scan-verify.sql` | **prepared 2026-08-06**, never executed. The scan itself still waits on the three owner-side steps in §11 |

**This is a SEPARATE Supabase project from AR-Internal-Tools.** Do not point outreach code at the suite's database, and do not put outreach migrations in `writer/supabase/migrations/`.

Live row counts (2026-08-04, unchanged 2026-08-05): `prospect` 1,388 (**105 carrying `review_count_inferred_zero`**, §9) · `filter_result` 8,328 · `submarket` 14 · `keyword` 5 · `market` 1 · `cost_ledger` 33 · `storage_retention_log` 8 · `lead` 0 · `lead_stage` 7 · `suppression` 0 · `review_inferred_zero_audit` 0 · **`scan_snapshot` 0 · `scan_task` 0 · `grid_result` 0 · `prospect_coverage` 0 · `snapshot_rollup` 0 · `grid_point_status` 0** — the scan layer now has a producer and has still produced nothing. Those two facts are easy to conflate and §11 exists to keep them apart.

### Railway service configuration

```
source           kssabraw/ar-tools @ main   ← ACTUALLY repointed 2026-08-03. The 2026-08-01
                                             repoint did not stick: the service still tracked the
                                             merged phase-1 branch and a Deploy built its HEAD
                                             (I-065). Verify with get-service-config, not here.
rootDirectory    /outreach
railwayConfigFile  outreach/railway.toml   ← repo-root-relative, NOT relative to rootDirectory
builder          DOCKERFILE (from railway.toml)
restartPolicy    NEVER                     ← this is a job; ALWAYS would re-run the paid ingest in a loop
cronSchedule     (none yet)
startCommand     sh -c "exec python -m api.scripts.run_market ${OUTREACH_COMMAND:-filter} ${OUTREACH_MARKET:-markets/los-angeles-plumbing.json} ${OUTREACH_ARGS:-}"
                 ← ${OUTREACH_ARGS:-} added 2026-08-03. Its absence silently dropped every flag
                   ever set in OUTREACH_ARGS and cost ~$0.11 (I-064).
```

Variables set: `OUTREACH_SUPABASE_URL`, `OUTREACH_SUPABASE_SERVICE_ROLE_KEY`, `OUTREACH_OUTSCRAPER_API_KEY`, `OUTREACH_COMMAND` (currently `filter`), `OUTREACH_MARKET`, `OUTREACH_ARGS` (empty), `OUTREACH_CONFIRM_SPEND` (empty), and DataForSEO credentials as Railway reference variables.

**This block is a snapshot and has been wrong twice.** Both the source branch and the start command above were stale in ways that cost money. Read `get-service-config` and `list-variables` for the live values; see repo-root `CLAUDE.md` → "Railway: read the live config, do not infer it".

~~**There is no DataForSEO credential on this service.**~~ **Set 2026-08-01** as Railway reference variables, and **exercised for real 2026-08-03** — the `verify-reviews` control run completed against `my_business_info/live` (I-066). ~~The Phase 2 *scan* client is still not built.~~ **Built 2026-08-04 (#557); never run.** `OUTREACH_OPENAI_API_KEY` was added the same day as a reference to `${{PLATFORM.OPENAI_API_KEY}}` for the I-004 spike.

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
cd outreach && python -m pytest api/tests -q      # 276 passing

# locally (needs OUTREACH_* env vars and network egress to Outscraper + Supabase)
python -m api.scripts.run_market seed      markets/los-angeles-plumbing.json
python -m api.scripts.run_market calibrate markets/los-angeles-plumbing.json   # 1 tile, ~20 places
python -m api.scripts.run_market ingest    markets/los-angeles-plumbing.json   # PAID
python -m api.scripts.run_market filter    markets/los-angeles-plumbing.json   # free
python -m api.scripts.run_market run       markets/los-angeles-plumbing.json   # seed+ingest+filter
python -m api.scripts.run_market collect   markets/los-angeles-plumbing.json   # free — and rolls up
python -m api.scripts.run_market rollup    markets/los-angeles-plumbing.json   # free — backlog only
python -m api.scripts.run_market rollup    markets/los-angeles-plumbing.json --verify   # writes nothing
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

> **The Railway-specific ones now live in repo-root `CLAUDE.md` → "Railway: read the live config, do not infer it", which auto-loads every session.** Read that first. Its framing matters and is not cosmetic: on 2026-08-03 a plausible explanation *from this very section* was believed instead of measured, and cost ~$0.11 (I-064). The traps below are evidence that this environment's config diverges from what the repo implies — never a substitute for reading the live config.

### 6.1 Railway `redeploy` replays the OLD deployment's config
Changing `startCommand` and calling redeploy silently re-runs the *previous* command. Twice, and it looked identical each time. Only a **fresh deployment** picks up config changes. This is why run mode is driven by `OUTREACH_COMMAND` through one entrypoint.

Then a third time, and it cost money: a `verify-reviews --group control --limit 5` intent was set on the service, `redeploy` replayed the snapshot from before those variables existed, and the run executed the bare `verify-reviews` default — 20 lookups, ~$0.11, against a group that had already been measured. **This section existed and was not read first.** That is a discoverability failure rather than a discipline one, so the Railway-specific traps (this one, the auto-deploy pinning, `update-service` not handling source changes) now live in the repo-root **`CLAUDE.md` → "Railway: read the live config, do not infer it"**, which auto-loads every session. Note the framing changed deliberately: the trap list itself turned out to be the hazard — a plausible remembered explanation displaced a one-call measurement (I-064) — so CLAUDE.md now leads with *read the live config* and treats the traps as evidence that config diverges, not as a list to reason from. Keep this section; treat CLAUDE.md as the copy that gets read.

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

### 6.11 Railway's service-config API reports the DEPLOYED config, not the staged one
Changing the source branch through the Railway agent returned "applied — staged for deployment", and reading the config back through `get-service-config` still showed the **old** branch. Both were telling the truth about different things: the change was staged, and the API reports what is currently deployed. The dashboard (Settings → Source) showed the new branch immediately and is the tiebreak.

Worth knowing before someone concludes a write silently failed and applies it a second time. Same family as §6.3 — when two instruments disagree, find a third rather than trusting the more convenient one.

---

### 6.12 After a squash merge, RESTART the branch — do not keep committing on it
Hit twice in one session, both times as a merge conflict that looked like someone else had touched
the files. Nobody had.

A squash merge replays your commits onto `main` as ONE NEW commit with a different SHA. The branch
still holds the originals. Keep committing on it and the branch now contains the same content
twice — once as your commits, once as main's squash — and the next merge conflicts on every file
both sides touched. `ISSUES.md` and `HANDOFF.md` are the usual casualties because every change
appends to them.

The fix is mechanical and takes ten seconds:

```
git fetch origin main
git checkout -B <branch> origin/main
git cherry-pick <only the commits made SINCE the merge>
git push --force-with-lease
```

Cherry-picking applies cleanly because main already carries the earlier content — the conflict was
never a real disagreement, only two spellings of the same change. Verify with
`git log --oneline origin/main..HEAD`: it should list only work that has never been merged.

---

## 7. What is NOT done

### 7.1 The Outscraper billing rate is still a placeholder — do this first
`outscraper_cost_per_1000_places_cents` is **200¢/1000, a guess**. Every cost figure above and the `max_market_run_cost_cents` abort gate are only as honest as that number. 2,807 places have been pulled; divide the Outscraper dashboard charge for 2026-07-31 by 2,807, multiply by 1000, set the variable. (`ISSUES` I-033.)

### 7.2 A paid run should need more than a variable — AND THE BLAST RADIUS JUST GREW
`OUTREACH_COMMAND=run` plus deploy-on-push means **any push to the tracked branch fires a paid ingest**. This actually happened (§6.4). Before any cron schedule is set, gate paid runs behind something the deploy path cannot supply on its own.

**Repointing the source to `main` on 2026-08-01 made this materially worse, and the mitigation was not applied.** While the service tracked a dead feature branch, nothing ever pushed to it and the footgun was close to theoretical. Tracking `main` in a repo that merges several PRs a day means **every unrelated merge now deploys and runs this job.** At `OUTREACH_COMMAND=filter` that is free but noisy — a filter re-run over 1,388 prospects and a $0 ledger row per merge. If the command is ever set to `run` or `ingest` and not put back within minutes, the next merge by anyone, on any unrelated PR, spends money.

**DONE 2026-08-01: "Auto deploys when pushed to GitHub" is disabled.** Merges to `main` no longer deploy or run this job; it runs only on a deliberate Deploy click. The branch connection stays, so Railway still knows where to pull from.

**That narrows the trigger. It does not close this item.** Two ways the risk returns, both foreseeable:
- **A manual Deploy while `OUTREACH_COMMAND` is `run` or `ingest`** still spends money — now the likeliest remaining path, because it is the same click used for a legitimate free `filter` run.
- **Setting a `cronSchedule`**, which is the plan once the first real ingest is validated, re-arms it twice over: a Railway cron service runs its start command **on every deploy as well as on schedule** (noted in `railway.toml`). Whatever gates paid runs must exist *before* that schedule is set, not after.

**CLOSED 2026-08-03 — the token exists.** `spend_denial` (`api/scripts/run_market.py`) implements exactly what this item asked for, and it was built because the procedural version failed: a `redeploy` ran `verify-reviews` and spent ~$0.11 that nobody approved, *after* the "set it back to `filter`" procedure had been followed (I-063, I-064).

- Absent, empty or whitespace `OUTREACH_COMMAND` resolves to `filter` (`resolve_command`). The safe command is what you get by omission.
- Every paid command (`ingest`, `run`, `calibrate`, `verify-reviews`) additionally requires **`OUTREACH_CONFIRM_SPEND` to equal that command's own name**, checked before the handler and before any credential is opened. `probe-dataforseo` is free and ungated until `--sample-place-id` makes it bill.
- The token names the command *deliberately*. A boolean would authorize whatever happens to be set, which is this incident exactly. A name-matched token means a replayed or half-updated config cannot spend: the leftover confirmation names a different command than the one about to run.
- The two variables fail safe independently — change the command and forget the token → refused; leave a token behind and the command reverts to `filter` → nothing paid to authorize.
- Line one of every run now reads `command=… PAID confirm=…` beside the SHA, and a refusal exits non-zero through the `OUTREACH_RESULT` marker.

**This is what must be in place before a `cronSchedule` is set**, per the paragraph above. It now is. Setting the schedule no longer re-arms the footgun on its own, because a scheduled deploy carries no confirmation token.

### 7.3 Grid geometry — SETTLED at 81, confirmed by the owner 2026-08-01
`ISSUES` I-025 is closed. `reporting-layer-spec.md` §4.1 is the only document that *defines* the generator — "square lattice covering the bounding box, row-major from NW corner, clipped to distance <= radius_miles" — and that construction holds exactly **81** points. Every alternative was computed rather than assumed: hexagonal **91** (π·25·2/√3 = 90.7, the likeliest origin of a remembered "89"), concentric rings **41**, unclipped 11×11 box **121**. Nothing produces 89, and the PRD hedges it as "~89" because it was an estimate.

Built as `api/services/geometry.py` version `v1`; `README.md`, PRD §8b and the storage spec's volume arithmetic corrected with markers rather than silently.

**Confirmed by the owner on 2026-08-01, with the cost lever considered and declined.** This is no longer an inference from the specs — it is a ruling. Treat `radius 5 / spacing 1 / 81 points` as fixed, and see DECISIONS.md for why coarser spacing was rejected as a cost lever.

**The recurring confusion, recorded so it is not relitigated:** a 5-mile *radius* is 10 miles across, so a 1-mile lattice has **11** points per row (5 west + centre + 5 east), not 5. 11 x 11 = 121 in the bounding box, 81 after clipping. "25" comes from reading the 5 as a side length rather than a radius; it would need ~1.67-mile spacing, and a 5x5 box at 2.5-mile spacing clips to 13, not 25.

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

### 8.0 Done on 2026-08-01 — all three former §8.1 items (PR #538)

**The platform-api `outreach` router.** `routers/outreach.py` + `services/outreach.py` + `services/outreach_db.py`, 24 unit tests. The project-scoped client turned out to be the one real divergence from `leadoff_db.py`: that scopes to a second SCHEMA, this reaches a second **PROJECT**, so `ClientOptions(schema=…)` buys nothing and it needs its own URL, its own key, and an `outreach_configured()` predicate so an unprovisioned deploy answers `503 outreach_not_configured` instead of failing inside the first query. **Nothing in it can spend money** — ingestion stays on the Railway job.

Funnel aggregation runs in Postgres (`v_prospect_status`, `outreach_market_summary()`, migration `20260801100000`) — storage spec §9 requires it, and with 8,328 `filter_result` rows a Python-side funnel would have hit PostgREST's silent 1,000-row cap on day one (§6.5). Verified live against LA: 1,388 / 925 survived / 463 excluded / 22 flagged, matching §3 exactly.

**Phase 2 storage foundations** (migration `20260801120000`, applied live). `scan_snapshot`, `grid_result` (partitioned by month, no lat/lng), `serp_result` (partitioned identically), `grid_result_retained`, `prospect_coverage`, `grid_result_all`, `storage_retention_log`, `create_month_partitions()`, `verify_grid_result_months()`, `drop_cold_partitions()`, and two `pg_cron` schedules. Verified by `tests/storage_partitioning.sql` — **14 checks, run live, all passing** (a pass reports `ERROR: ROLLBACK — 14 checks passed`).

**No default partition**, deliberately: it never loses a row, but once a month's rows land in it that month's partition can never be attached, which surfaces months later on a huge table. The retention job **fails closed on everything it cannot verify**, including `audit_asset` and `slot`, which do not exist yet — so today it drops nothing but empty partitions. Correct, and not the same as finished.

**The pinned grid-geometry generator** — see §7.3. 81 points, version `v1`, 18 tests with hand-derived expectations.

**A defect fixed on the way (I-040).** `lead_log_changes` stamped `actor_id := auth.uid()`, which is NULL for the service role, so under §2 every stage change would have been logged anonymously. `lead.updated_by` added; the trigger prefers it. **The sweep for others came back clean:** one instance total. Swept as two lists, because the failure modes differ — expressions that RUN and receive null (defaults, generated columns, CHECKs, views, trigger bodies, `request.jwt` readers) versus RLS policies, which are bypassed silently and never evaluated. Zero of the former beyond `lead_log_changes`; zero policies exist at all. Re-run after any migration that adds a trigger or a default; only the first list can regress.

**And one found, not fixed (I-041).** `review_count_min` is 842 passed / 433 failed / **113 not evaluated** — Outscraper returned no review count for those 113 and they sit inside the 925 "survivors". Population evidence splits them: `review_count = 0` never occurs anywhere in 1,388 rows while counts of 1/2/3–5/6–9 occur 118/70/129/116 times, so null reads as the provider's encoding of zero; 105 of the 113 also have a null rating (consistent with genuinely zero reviews), and **8 have a rating but no count**, which cannot both be true and are genuinely unknown. The direct Google Maps spot-check **could not be run** — Google 403s every route and egress is blocked (I-027) — so this is strong circumstantial evidence, not confirmation. Ten place_ids plus all 8 anomalies are queued in `ISSUES`.

### 8.0a Done on 2026-08-04 — the geogrid producer (#557) and the I-004 instrument (#556)

**The maps geogrid client + `tasks_ready` collector.** `api/services/maps_scan.py` (pure: task bodies, `task_post`/`tasks_ready`/`task_get` parsing, completeness) + `api/services/scan_runner.py` (submission, collection, finalization) + the `scan_task` bookkeeping table. 42 tests; the suite is at **247**.

The endpoint is QUEUED — `task_post` bills and returns an id, the result is fetched later — so almost every decision is about **ordering**, each chosen so an interruption loses at most one point and always in the cheap direction:

- **`scan_task` rows are written `pending` BEFORE the post.** The naive order has a window where money is spent and no record exists. A row still `pending` afterwards just means "not yet posted": reposting an unposted point costs one point, losing a posted one costs the batch.
- **The tag is a recovery key, not a debug label.** `<snapshot_id>:<point_seq>`, echoed on `tasks_ready`, closes the one window ordering cannot: a request the provider accepted and billed whose response never reached us. This DIVERGES from the suite's `maps_dataforseo.py`, where the tag is explicitly a convenience and alignment is positional — sound there, because that code polls ids it holds. See DECISIONS.md.
- **Grid rows are written before the task is marked collected.** A crash between them re-collects something free to re-collect; the reverse finalizes a snapshot with a hole nothing downstream can detect.
- **`actual_points` counts points SCANNED, never rows written.** A point over water returns an empty pack, and "nobody ranks here" is a finding. Counting rows would mark a submarket's real dead zones as scan failures and exclude it from scoring every cycle — the same correction I-069 needed. DECISIONS.md records it because the mistake has now been made twice.
- **`tasks_ready` RAISES on a shape it cannot read** rather than returning `[]`. Nothing here has ever called that endpoint; an unreadable response reading as "nothing ready" would end the collector's loop, mark the run clean, and leave paid tasks to age off.
- **The month guard.** Collection lands hours or days after submission, so `scan_month` from the clock is right in every test and wrong twice a year (I-044). `assert_snapshot_month()` checks it per snapshot at finalization — one query, not a per-row trigger on a 58M-row/year table — and refuses rather than repairs.

**The I-004 spike instrument** (#556): `probe-ai-granularity`, nine OpenAI calls at temperature 0, three place names × three samples, reporting cross-level overlap, within-level stability, and error/empty counts kept separate. It gathers evidence and deliberately does **not** pick the granularity — that is a human decision recorded in `ai_region.name_level`, and the output says so in the payload rather than only in a docstring. The three place names are required rather than defaulted; I-073's free evidence run already narrowed which LA names are worth testing.

### 8.0b Done on 2026-08-05 — the `prospect_coverage` rollup, land masking, dead-point exclusion

Checklist §4 Phase 2, ISSUES I-042. Migration `20260805120000` applied live;
`api/services/coverage_rollup.py`; 29 new unit tests (suite at **276**) plus an 18-check live
script, `tests/coverage_rollup.sql`, which passes.

**It is one plpgsql function because it has to be.** `rank_vector` must be written in the same
transaction as the summary statistics — a rollup producing coverage percentages without vectors
must FAIL rather than partially succeed, because a vector written later or in the wrong
`point_seq` order renders every historical heatmap against coordinates that were never used to
collect it, with the picture still drawing. PostgREST gives one transaction per call, so a Python
loop that inserted rows and then called `finalize_snapshot_rollup()` physically cannot hold both
halves together. `rollup_snapshot_coverage()` does the whole snapshot and calls the finalizer as
its LAST statement; the finalizer re-derives its counts and raises on a mismatch, aborting
everything. There is a unit test asserting nothing follows that call.

**Geometry arrives as a parameter.** The caller regenerates points through the pinned registry
using the snapshot's **stored** `geometry_version` — never the default — and passes
`[{"seq", "dist"}]`; the function refuses a payload that does not cover `0..expected-1` exactly, or
whose version disagrees with the snapshot. Re-deriving the lattice in SQL would create the second
definition of point membership that `geometry.py` exists to prevent. Distances are
centre-independent, so the rollup never reads the mutable `submarket.center_*` (ISSUES I-078 —
Phase 3's heatmap will, and should not).

**The denominator counts what was MEASURED.** `live_points` = `scan_task.status = 'collected'`
intersected with `grid_point_status.land`. An empty pack stays in (it was measured; "nobody ranks
here" is a finding). An uncollected task leaves entirely (nobody observed that absence). A masked
point leaves the denominator but stays in the vector as `255`, because dead must render
differently from not-found. Third time this correction has been needed — see DECISIONS.md.

**Land masking self-calibrates** (PRD §9a.1): N consecutive null scans mask a point, any non-null
result reactivates it, the counter is shared across keywords, and the whole update happens inside
the rollup's transaction so `live_points` is contemporaneous with the claims made from it. `N` is
`land_mask_null_scans` in config, not a literal in the SQL.

**Cadence:** `collect` now rolls up the snapshots it finalizes — guarded, reported, never raised,
because collection is the paid work being rescued. `rollup` also stands alone for backfill and
`rollup --verify` recomputes every statistic from the stored vectors (storage spec §12). Both are
FREE and must stay out of `PAID_COMMANDS`. Storage spec §7's daily `rollup_coverage` **pg_cron**
job is not buildable — pg_cron cannot call the Python generator — and a third Railway schedule was
rejected for the reason §11 gives about the second one.

**Eight issues logged, not silently resolved** (I-074…I-081). Four matter before the next build:
the second land-masking criterion is **not computable** from stored data (I-074); an incomplete or
prospect-less snapshot pins its partition **forever**, fail-closed (I-075); a prospect present at
**zero** points gets **no row**, so downstream must read a missing row as zero coverage rather than
unknown (I-076); and `centroid_dist_at_loss` has **no formula in any spec** — one reading is
implemented and the other must be chosen deliberately before it reaches a prospect-facing claim
(I-080).

### 8.1 Unblocked, and the highest-regret thing to defer
1. ~~**Repoint the `outreach` Railway service at `main`.**~~ **DONE 2026-08-03.** It had been recorded as done on 2026-08-01 and was not: the service still tracked `claude/phase-1-outscraper-ingestion-llje34`, and a Deploy click faithfully built that branch's HEAD (`7f9430b`, 2026-08-01), failing with `invalid choice: 'verify-reviews'` — a commit old enough to predate both the build banner and the result marker, so it failed silently behind a green badge (I-065). *The lesson is not "repoint it" but "a config change recorded in a document is not a config change"*; verify with `get-service-config`.
2. ~~**The maps geogrid client + `tasks_ready` collector.**~~ **BUILT 2026-08-04 (#557)** — see §8.0a. Not run. The owner ruling stands: **first live run is ONE submarket × ONE keyword**, and `cmd_scan` refuses to do more.
2a. ~~**THE NEXT BUILD: the `prospect_coverage` rollup.**~~ **BUILT 2026-08-05** — see §8.0b. Applied live and verified in both directions; never run against real data, because there is none.
2b. ~~**THE NEXT BUILD: the placeholder score**~~ **BUILT 2026-08-05.** Was: (checklist §4 Phase 2, first item). "Raw geogrid coverage deficit, one SQL expression" — and it reads `prospect_coverage`, which now exists. It reads `prospect_coverage` through a LEFT JOIN gated on the `snapshot_rollup` marker, so a prospect present at zero grid points scores 100% deficit rather than vanishing (I-076), and an unrolled submarket produces no rows rather than reading as total invisibility. Both are asserted live.
2c. **THE NEXT THING IS NOT A BUILD — IT IS THE FIRST SCAN.** Recommended 2026-08-05, and the reasoning is about accumulated risk rather than about the queue.

**Five components are now built and have never been exercised**: the geogrid client, the collector, the rollup, the placeholder score and the I-004 probe. Every one is verified against fixtures and against Postgres; not one has met a live provider response. Each additional unrun layer raises the chance the first run surfaces several faults at once, interacting, in a batch that has been paid for — and the whole point of the one-submarket ruling is to meet them one at a time.

One submarket × one keyword exercises submission, collection, finalization, the rollup, land masking and the placeholder score in a single ~81-point pass. §11 has the three things it needs, none of which are code. **A sixth unrun layer is worth less than proving the five.**

*The checklist under-reports this state, and the discrepancy is not an error to correct blindly.* Four unticked Phase 2 boxes are code-complete but unrun — geometry parameters are persisted, partitioning and retention are in place, completeness marking exists. They stay unticked deliberately: "built" and "proven" are the two facts §11 exists to keep apart, and the `tasks_ready` box in particular cannot be ticked while the cron it names does not exist.

2d. **Then: organic SERP + AI Overview per submarket × keyword** (checklist §4 Phase 2) — the largest remaining Phase 2 build. `serp_result` already exists, partitioned. The AI half is blocked on `ai_region` names (§7.4, §8.2); the organic half is not. Free to build, paid to run, so it becomes the sixth unexercised component if it is built before the scan.

2e. **Cheap and useful either way: I-070**, enforcing `scan_snapshot` append-only. Listed as a Phase 2 requirement, nothing currently stops an `UPDATE`, and a silently mutated snapshot re-interprets every coverage figure computed against it rather than corrupting anything visibly. A trigger and a test. No closing window.

3. **Suite SPA pages.** Nothing in `frontend/` exists. The read surface they need is built and verified. Open question, see I-072 — decide rather than inherit. **NOT a prerequisite for the scan** — see §11a, which exists because that was asked directly and the file did not answer it.
4. ~~**The coverage rollup** (`ISSUES` I-042)~~ — **DONE.** The retention job now gets past the rollup guard and stops at the next one: `audit_asset` and `slot` do not exist, so a partition whose citations cannot be checked is still never dropped. Verified live (check 15 of `tests/coverage_rollup.sql`). Fail-closed remains the posture; what changed is which guard is doing the refusing.

### 8.2 Blocked on a human
- ~~**DataForSEO credentials on the `outreach` Railway service.**~~ **DONE 2026-08-01** — set as Railway reference variables (`OUTREACH_DATAFORSEO_LOGIN` = `${{PLATFORM.DATAFORSEO_LOGIN}}`, same for the password), so the secrets never left the platform and follow a rotation automatically. **Now wired and exercised for real:** `api/services/dataforseo_client.py` + `verify-reviews`, run live 2026-08-03 against `my_business_info/live` (I-066). The Phase 2 *scan* client is still not built.
- ~~**A public callback URL.**~~ **NO LONGER REQUIRED** — the postback MUST was over-specified and has been corrected to `tasks_ready` collection (PRD §B2, DECISIONS.md). The service stays a cron job: no domain, no receiver, no shape change. What it DOES need is a **second, frequent cron schedule** for the collector — see §7.6.
- **`ai_region` names for LA** (§7.4). A candidate list can be drafted from the 14 submarkets for a human to correct.
- **Two verification spikes.** `I-004` AI prompt granularity — **the instrument is built (#556); the RUN needs a Deploy plus `OUTREACH_CONFIRM_SPEND=probe-ai-granularity`.** `I-003` Outscraper pixel field (~1h) is still unbuilt and decides whether the site-fetch parse is optional or required, which changes the money-signal cost model.
- **Spend approval.** ~$3–6 per market-vertical per cycle, guarded at `max_market_run_cost_cents` 5000 — a gate that is only as honest as §7.1.

### 8.3 Do not
- Change grid radius, spacing or point count. §7.3 is settled by owner ruling and freezes at the first scan. Adding a submarket starts its own clean history; editing one orphans every snapshot it has.
- Derive `grid_result.scan_month` from `now()`. It must come from the snapshot being written, or one snapshot splits across two partitions and the retention job blames the rollup (`ISSUES` I-044).
- Add RLS policies to the CRM tables to silence the advisor's `rls_enabled_no_policy` INFO notices. That is the intended posture (§2).
- Point outreach code at AR-Internal-Tools, or file an outreach migration under `writer/supabase/migrations/`.
- Trigger a paid Outscraper or DataForSEO run without being asked. `OUTREACH_COMMAND` stays `filter` and `OUTREACH_CONFIRM_SPEND` stays empty between approved runs. The gate (§7.2) now refuses rather than trusting this instruction — but it bounds the damage, it does not grant permission.
- Set `review_count_inferred_zero` on further rows, or clear it, without an explicit decision. It is a human judgement about a vendor convention (§9) and the `prospect_preserve_decisions` trigger deliberately makes it non-re-derivable.
- "Fix" a `review_inferred_zero_audit` row by deleting it. That table is the falsification record for §9; a `contradicted` row is the system working.

---

## 8a. Also in §8.3 "do not", now that the collector exists

- **Do not gate `collect` behind `OUTREACH_CONFIRM_SPEND`.** `tasks_ready` and `task_get` are free; only `task_post` bills. Gating the collector would make every cron tick refuse and lose exactly the paid work it exists to save. There is a test asserting `collect` is not in `PAID_COMMANDS` — if it starts failing, read this line before "fixing" it.
- **Do not change the tag format** (`<snapshot_id>:<point_seq>`). It is part of the wire contract now: changing it orphans every task in flight for ~3 days after any submission.
- **Do not widen `cmd_scan` to a market sweep** before a real run has proven the envelope once. Its refusal to scan more than one submarket is the owner's ruling, not a placeholder.

---

## 9. The inferred-zero decision — read before touching review counts

**105 prospects carry `review_count_inferred_zero = true` with `review_count` still NULL.** Applied 2026-08-03 by owner decision (I-067). This is the single most easily misread piece of state in the database, so it gets its own section.

**What it means.** "This provider encodes *no reviews* as null." It is a claim about a **vendor convention**, not a measurement of any business. Nothing was written into `review_count` and nothing ever will be by this decision — a later real count comes only from a real measurement.

**Why it was safe to conclude.** Three independent lines, none of which is an opinion:

- **Mechanical.** A rating is an average of reviews, so zero reviews cannot produce one. All 105 have a null rating *and* a null count — the only internally coherent shape for a zero-review listing. The 7 rows with a rating but no count are NOT flagged: those two facts cannot both be true, so they are provider gaps.
- **Distributional.** `review_count = 0` appears **zero** times across all 1,388 prospects, while 1, 2, 3–5 and 6–9 appear 118 / 70 / 129 / 116 times. A provider that reports down to 1 and never emits 0 is encoding zero as null.
- **Corroborated.** An independent vendor was asked. DataForSEO returned no count for 20 of 20 sampled with no timeouts, and a control group proved the same call resolves down to a **single** review (Maximum Plumbing, `votes_count: 1`). Two vendors decline to report, and the instrument is known to work (I-061, I-066).

**Why it was decided rather than left open.** No source will ever affirmatively report zero — that *is* the convention under test — so waiting for an explicit `0` means waiting forever. An inference held open indefinitely is not caution; it is a decision never made.

**How it gets audited — this is the important part.** The geo-grid scan will eventually return `rating.votes_count` for these same listings. That is the first source that can *contradict* the flag, and the moment it does is the moment the contradiction is easiest to lose. So it is caught structurally, not by convention:

- `review_inferred_zero_audit` + the `prospect_audit_inferred_zero` BEFORE UPDATE trigger record any real count landing on a flagged row (`verdict: contradicted | confirmed`), `raise warning` to the server log, and clear the flag so the **measurement wins**.
- The `inferred_zero_requires_null_count` CHECK would otherwise have made that write ERROR — loud, but the wrong loud: it aborts the backfill instead of recording what was learned.
- Trigger ordering is load-bearing. `prospect_audit_inferred_zero` sorts before `prospect_preserve_decisions`, whose preservation branch is guarded on `new.review_count is null` and therefore correctly declines to re-set a flag cleared alongside a real count.

**What to do after the first scan:** `select verdict, count(*) from review_inferred_zero_audit group by 1;` A few `contradicted` rows means the inference was wrong for those listings and they have already self-corrected. A lot of them means the vendor-convention claim is wrong and the flag should be withdrawn wholesale — clear the boolean, never write 0.

**Migrations:** `20260803210000_inferred_zero_audit.sql` (mechanism), `20260803210100_set_inferred_zero_la.sql` (the write, guarded on `count = 105` so it refuses if the set has moved).

---

## 10. Layout

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
├── queries/                   phase1-dod.sql, first-scan-verify.sql (the post-run read, §11b)
├── tests/
│   ├── lead_crm_rls.sql       17-check CRM verification (run in the SQL editor)
│   ├── storage_partitioning.sql  14-check partitioning/retention verification
│   ├── coverage_rollup.sql    18-check rollup + placeholder-score verification
│   └── fixtures/              golden scorecard fixtures — Phase 4, hand-computed, never regenerate
├── Dockerfile · railway.toml  the Railway job image and its restart policy
└── api/
    ├── config.py              every tunable; nothing hardcoded
    ├── db.py                  Supabase client (service role)
    ├── services/              outscraper_client, parser, tiling, filters, suppression,
    │                          cost, paging, seeding, pipeline, geometry, dataforseo_client,
    │                          review_verify, maps_scan, scan_runner, ai_granularity
    ├── scripts/               run_market (the entrypoint), calibrate, calibrate_standalone
    └── tests/                 247 tests, no network or database
```

---

## 11. The scan layer has a producer and no data — the gap is not code

This section exists because the previous version of this file said "Phase 2 scanning has not started" and that sentence covered two very different situations. It now means only one thing, and conflating them would send the next session to write code that already exists.

**What is built:** the geogrid submission and collection path, end to end, with 42 tests (§8.0a). **What has happened:** nothing. Zero tasks posted, zero rows collected, zero snapshots.

Three things stand in between, and none of them are code:

1. **A Railway deploy with the scan variables set.** `OUTREACH_COMMAND=scan`, `OUTREACH_CONFIRM_SPEND=scan`, `OUTREACH_ARGS=--submarket '<name>'`. It must be a **fresh Deploy, not a redeploy** — a redeploy replays the previous deployment's config snapshot (§6.1, and the ~$0.11 it cost). Line one of the logs prints the resolved command and the confirm token, so what a run is about to do is visible before it does it.

2. **A SECOND, FREQUENT CRON SCHEDULE for `collect`.** This is the one most likely to be skipped and the most expensive to skip. The ready list holds a task about **three days**; the scan cadence is **fifteen**. A collector on the scan schedule lets every task age off the list between runs, silently converting the normal path into the fallback-by-id path — which still works, which is exactly why nobody would notice, until the day the fallback window (30 days) is also missed. `collect` is free and safe to run on any tick; run it hourly or daily. It is deliberately not spend-gated.

   **This schedule now carries the rollup too** (§8.0b), which raises the cost of skipping it a second time: no collection means no finalized snapshots, which means no completion markers, which means the retention job drops nothing — and the storage ceiling the whole partitioning policy exists to avoid arrives on schedule while every run reports clean. `rollup` standalone clears any backlog, so a missed tick is recoverable; a missing schedule is not noticed.

3. **The owner's go-ahead on spend.** One submarket × one keyword is 81 points, ~1 batch, so a wrong envelope costs one batch rather than a market. `cmd_scan` refuses to do more than that.

### 11a. What is NOT on this path — the UI

Asked directly on 2026-08-05: *"we need to create the UI so we can do the run, correct?"* **No.**
Recorded because §11 lists what is missing and never said what is not, which is what let the
question form.

The run is a **Railway job**. `scan` and `collect` are subcommands of `api.scripts.run_market`,
executed by the service's start command with `OUTREACH_COMMAND`. Posting 81 tasks, collecting
them, rolling them up and scoring them touches no frontend at any point, and the spend gate is
built around the deploy path specifically — `OUTREACH_CONFIRM_SPEND` must match the command name
before any credential is opened.

The UI is for LOOKING at results, and even that is not the only way: `routers/outreach.py` is 14
tested routes over this data, and SQL reaches the rest. Nothing in Phase 2 requires a page.

**A UI that TRIGGERS a scan is not a convenience — it is an architectural change**, and it needs
deciding rather than assuming. The gate that makes paid runs safe (§7.2) assumes a deploy carries
the confirmation; a button would have to either replicate that or bypass it, and "bypass" is how
the ~$0.11 incident happened with a gate that was merely procedural. If a trigger button is
wanted, it gets its own decision.

**What the UI IS blocked on is a choice, not a dependency** — ISSUES I-072. The operator/CRM board
is buildable today against an API that already exists and has never been consumed. The valuable
surfaces (coverage, heatmap, delta) need scan data and the Phase 3 renderer, so building the shell
now means building the interesting half twice. I-072 asks the next session to *choose* between
"operator board now" and "after Phase 3" and to write the answer down, because HANDOFF §1 has
listed Suite UI as "the next build" across several sessions that each built something else.

### 11b. The runbook for the first scan (prepared 2026-08-06)

Nothing here has been executed. This section exists so the three owner-side steps in §11 are a
sequence to follow rather than a thing to reconstruct, and so the run is readable afterwards.

**Live config, read 2026-08-06** — per CLAUDE.md, measured rather than inferred:

| | |
|---|---|
| `source.branch` | `main` ✅ (the 2026-08-03 repoint held — I-065 has not recurred) |
| `rootDirectory` / `railwayConfigFile` | `/outreach` · `outreach/railway.toml` ✅ |
| `startCommand` | carries `${OUTREACH_ARGS:-}` ✅ — flags will reach the command (I-064's fix is still in place) |
| `restartPolicyType` | `NEVER` ✅ |
| **`cronSchedule`** | **absent — there is no schedule of any kind**, confirming §11 item 2 |
| `builder` | reports `RAILPACK`; `railway.toml` says `DOCKERFILE` and is what actually builds. **Known-stale field — do not "fix" it** (§1) |

> **The variable VALUES could not be read from here, and that is a gap in the "read the live
> config" rule rather than an oversight.** `list-variables` returned `valuesRedacted: true` — an
> OAuth-app connection receives variable *names* only. All ten expected names are present
> (`OUTREACH_COMMAND`, `OUTREACH_CONFIRM_SPEND`, `OUTREACH_ARGS`, `OUTREACH_MARKET`, the two
> DataForSEO references, the Supabase pair, Outscraper, OpenAI), but **what `OUTREACH_COMMAND` and
> `OUTREACH_CONFIRM_SPEND` currently hold is unverified.** Check them in the dashboard before
> deploying. The spend gate makes a stale pair fail safe in both directions (§7.2), so this is a
> visibility limit, not an exposure.

**The target: `Van Nuys` × `plumber`.** Chosen for the densest possible read of the response
envelope — 152 prospects and 92 survivors, the most of any LA submarket, so grid results have the
best chance of joining to businesses we already know. That matters beyond sample size: a snapshot
whose grid contains **no** known prospect makes `finalize_snapshot_rollup()` raise, and the marker
can never be written (I-075). Van Nuys is inland San Fernando Valley, so nearly every point should
return a full pack — the happy path, which is what run one is for. `plumber` is the market's
`is_primary` keyword and is what `cmd_scan` defaults to; pass it explicitly anyway, because every
config incident in §6 has been a value someone assumed rather than set.

**Step 1 — set the variables** (owner; do not let a session set these):

```
OUTREACH_COMMAND       = scan
OUTREACH_CONFIRM_SPEND = scan                              ← must equal the command's own name
OUTREACH_ARGS          = --submarket 'Van Nuys' --keyword plumber
OUTREACH_MARKET        = markets/los-angeles-plumbing.json (unchanged)
```

**Step 2 — a fresh Deploy, NOT a redeploy.** A redeploy replays the previous deployment's config
snapshot and would run whatever was set last time (§6.1, and the ~$0.11 it cost). Line one of the
logs prints the resolved command, the confirm token and the commit SHA — read it before reading
anything else. Expect `command=scan PAID confirm=scan`.

Then **immediately set `OUTREACH_COMMAND` back to `filter` and blank `OUTREACH_CONFIRM_SPEND`.**
The gate refuses rather than trusting this, but a manual Deploy while `scan` is still set is the
likeliest remaining way to spend money by accident (§7.2).

~81 tasks in one batch. At config's placeholder rate (`dataforseo_cost_per_request_cents`, 1¢)
that is ~$0.81; **the real figure has to come from the DataForSEO dashboard, because the scan
writes no `cost_ledger` row at all — I-086.**

**Step 3 — the collector's schedule, before walking away.** `OUTREACH_COMMAND=collect` on a
frequent `cronSchedule` (hourly is fine; `0 * * * *`). Free, never spend-gated, safe on any tick,
and it carries the rollup. The ready list holds a task ~3 days against a 15-day scan cadence, so a
collector that runs per scan cycle silently converts the normal path into the fallback-by-id path
— which still works, which is exactly why nobody would notice (§11 item 2).

> A Railway cron service runs its start command **on every deploy as well as on schedule**. With
> `collect` set that is free and idempotent. It is also why the schedule must be set while the
> command is `collect` and not while it is `scan`.

**Step 4 — read the run.** `queries/first-scan-verify.sql`, 14 checks, read-only; every statement
has been executed against the live schema so it parses. Run it after `scan` (checks 1–3) and again
after the first `collect` tick (all of it). Checks 4, 6 and 8 are assertions — a non-empty result
is a defect. The rest print what you want to see beside what you got, because a first run's
expected values are not all knowable in advance.

**Capture the `collect` command's JSON output.** `recovered_by_tag` is a counter in that output
and nowhere else — not a column, not reconstructible afterwards (I-087).

**What run one does NOT prove**, so it is not later assumed to have:

- **The empty-pack path.** Van Nuys is inland; points returning zero businesses are what exercise
  `result_count = 0`, the land-mask counter and the "measured, not found" denominator rule. A
  coastal submarket (Santa Monica, Long Beach, Torrance) is the natural run two.
- **Land masking itself**, which needs 3 consecutive null scans and therefore 3 cycles minimum.
- **The fallback-by-id path**, which only runs when a task ages off `tasks_ready` after ~3 days.
- **Tag recovery**, unless it happens to fire.

---

**After the first real run, the thing to check is not "did it succeed"** — it is whether `scan_task` rows moved `pending → submitted → collected`, whether `actual_points` matches `expected_points`, and whether any row is sitting on `recovered_by_tag`. A run that posts nothing and collects nothing reports clean, because there is nothing to report.

> **Corrected 2026-08-06:** there is no row and no column named `recovered_by_tag` — it is a
> counter printed once in the `collect` command's output (I-087). The rest of this paragraph
> stands, and `queries/first-scan-verify.sql` is the durable form of it.
