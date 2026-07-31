# HANDOFF — Outreach Pipeline

**Read this first, then `CLAUDE.md` → `START-HERE.md` → `ISSUES.md` → `DECISIONS.md`.**

Status as of 2026-08-01: **Phase 1 (ingest + filter) is merged. Phase 1b (lead CRM) is applied
live, PR #534 open. Phase 2's STORAGE FOUNDATIONS and the suite router are built** — see §8.

**Phase 2 SCANNING has not started and is still blocked on credentials.** Nothing built on
2026-08-01 scans, ingests or spends; `OUTREACH_COMMAND` stays `filter`.

---

## 1. What exists right now

| Thing | Where | State |
|---|---|---|
| Code | `outreach/` in `kssabraw/ar-tools` | branch `claude/phase-1-outscraper-ingestion-llje34` |
| PR | [#528](https://github.com/kssabraw/ar-tools/pull/528) | open, **draft**, CI green, not merged |
| Database | Supabase project **Outreacher**, ref `fkwhgvcggvsricuinuqy` | migration + RLS applied, LA market seeded and ingested |
| Job runner | Railway service **outreach**, id `928c84bc-d7ca-416a-bd61-39e91cc64872` in project `ar-tools` (`2c718e53-…`) | deploying from the feature branch, no cron schedule yet |

**This is a SEPARATE Supabase project from AR-Internal-Tools.** Do not point outreach code at
the suite's database, and do not put outreach migrations in `writer/supabase/migrations/`.

### Railway service configuration

```
source           kssabraw/ar-tools @ claude/phase-1-outscraper-ingestion-llje34
rootDirectory    /outreach
railwayConfigFile  outreach/railway.toml   ← repo-root-relative, NOT relative to rootDirectory
builder          DOCKERFILE (from railway.toml)
restartPolicy    NEVER                     ← this is a job; ALWAYS would re-run the paid ingest in a loop
cronSchedule     (none yet)
startCommand     sh -c "exec python -m api.scripts.run_market ${OUTREACH_COMMAND:-filter} ${OUTREACH_MARKET:-markets/los-angeles-plumbing.json}"
```

Variables set on the service: `OUTREACH_SUPABASE_URL`, `OUTREACH_SUPABASE_SERVICE_ROLE_KEY`,
`OUTREACH_OUTSCRAPER_API_KEY`, `OUTREACH_COMMAND` (currently `filter`), `OUTREACH_MARKET`.

> The Outscraper key and the Supabase service-role key were pasted into a chat transcript during
> this build. Rotating both is cheap and worth doing.

---

## 2. The Los Angeles result (real, verified)

Market `Los Angeles, CA — Plumbing`, 14 submarkets, category `plumber`.

| | |
|---|---|
| Listings returned (billed) | 2,807 across 15 tile-pulls |
| Prospects after `place_id` dedup | **1,388** |
| Tile overlap rate | 14.7% |
| Cost recorded | $5.68 — **at the placeholder rate, see §4.1** |
| Survived the filter | **925** |
| Excluded | 463 |
| Flagged as possible franchise | 22 (all still in play — flag never excludes) |

Failures per rule: `review_count_min` 433 · `has_phone` 46 · `not_franchise` 22 ·
`business_status_open` 14 · `not_suppressed` 0 · `review_recency` 1,388 `not_evaluated`.

Every acceptance criterion in `docs/PHASE-1-BRIEF.md` §5 is met. Verified independently: 30
prospects failed more than one rule with every rule logged (not first-match-only); all 1,388 are
in California (one distinct state); every prospect has a submarket; `prospect_score` was never
written.

**2,807 listings cost roughly double what one clean run costs** — two full ingests ran (see §5.4).
A single LA run is ~1,400 places.

---

## 3. Running it

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

Success is the log line `OUTREACH_RESULT status=ok command=<cmd> exit=0`. **The Railway
deployment status is NOT a success signal** — see §5.2.

Definition-of-done SQL: `queries/phase1-dod.sql`.

Adding a market: copy `markets/EXAMPLE-kansas-city-plumbing.json`, fill it in, `seed`. Idempotent.

---

## 4. What is NOT done

### 4.1 The Outscraper billing rate is still a placeholder — do this first
`outscraper_cost_per_1000_places_cents` is **200¢/1000, a guess**. Every cost figure above and the
`max_market_run_cost_cents` abort gate are only as honest as that number.

2,807 places have now been pulled on this account. Divide the Outscraper dashboard charge for
2026-07-31 by 2,807, multiply by 1000, set the variable. (ISSUES I-033.)

### 4.2 A paid run should need more than a variable
`OUTREACH_COMMAND=run` plus Railway's deploy-on-push means **any push to the branch fires a paid
ingest**. This actually happened (§5.4). Before the cron schedule is set, gate paid runs behind
something the deploy path cannot supply on its own — a required `--confirm` flag, a date-stamped
token, a check that the last ingest was ≥N days ago.

### 4.3 Grid geometry — RESOLVED at 81, still reversible until the first scan
`ISSUES I-025` is closed. `reporting-layer-spec.md` §4.1 defines the generator outright — square
lattice, row-major from NW, clipped to the radius — and that yields exactly **81** points. Nothing
produces 89: hexagonal gives 91, rings give 41, the unclipped box gives 121. Built as
`api/services/geometry.py` version `v1`; README, PRD and the storage spec's arithmetic corrected
with markers.

**Confirm this before the first scan.** It was decided from the specs, not by the owner, and every
`submarket.last_scanned_at` is still null — so it is free today and permanent afterwards.

### 4.4 Smaller open items
- **I-034** — nothing reads `OUTREACH_RESULT` yet. A log line nobody greps ≈ a green tick nobody
  questions. Belongs with the Phase 2 scheduler; cheap version is a `run_log` table.
- **I-020/I-026** — franchise pattern list is an unvalidated seed. 22 matched in LA. It can now be
  improved from data: a name appearing at ≥3 distinct `place_id`s in one market is almost
  certainly a chain.
- **I-019** — `suppression` is a Phase 1 placeholder owned by the CRM spec. `IF NOT EXISTS` is
  **not** a merge; whichever migration ran first wins. Reconcile explicitly with the Phase 1b work.
- **I-024** — the raw landing dir is on-disk and opt-in; it belongs in R2 in Phase 2.

---

## 5. Traps — every one of these cost real time or money here

### 5.1 Railway `redeploy` replays the OLD deployment's config
Changing `startCommand` and calling redeploy silently re-runs the *previous* command. Twice, and
it looked identical each time. Only a **fresh deployment** picks up config changes. This is why
run mode is driven by `OUTREACH_COMMAND` through one entrypoint instead of per-run start commands.

### 5.2 Railway reports a CRASHED job as deployment status SUCCESS
With `restartPolicy: NEVER`, a job that dies on an unhandled exception still shows SUCCESS and
posts a green commit status to the PR. Trust `OUTREACH_RESULT`, not the deployment badge.

### 5.3 The Railway log stream LAGS the container — do not diagnose from it
I concluded a run had died at 09:09:54 because logs stopped. It actually completed at 09:11:01.
The Railway agent agreed with my diagnosis **because it was reading the same lagging stream** —
that is not corroboration. **Check `cost_ledger` and `prospect` in the database**; those are
written synchronously and are the ground truth for what a run actually did.

### 5.4 …and that misdiagnosis caused a duplicate paid ingest
Pushing the "fix" auto-deployed while `OUTREACH_COMMAND=run` was still set, firing a second full
pull nobody asked for — about half the $5.68. **Set `OUTREACH_COMMAND` back to `filter`
immediately after any paid run**, not at the end of a working session. See §4.2.

### 5.5 PostgREST silently caps an unbounded `select()` at 1000 rows
No error, no header, nothing a caller notices. `run_filter` read 1,000 of 1,388 prospects and left
215 unfiltered; "how many survived" would have undercounted, confidently. **Every read that grows
with the portfolio must go through `services/paging.fetch_all`.** Note its argument is a
*callable* — supabase-py builders are stateful and reusing one compounds `.range()` instead of
replacing it, which pages wrongly in a way that also looks fine.

### 5.6 A directory named `supabase/` shadows the installed `supabase` package
Migrations live in `outreach/migrations/`, not `outreach/supabase/`, because once `/outreach` is
on `sys.path` Python resolves `from supabase import Client` to the directory. It fails as
`cannot import name 'Client' from 'supabase' (unknown location)`, which reads like a version
problem. Deliberate divergence from the `writer/supabase/migrations` convention.

### 5.7 Tile geography must be pinned TWICE
A pull for `plumber, Downtown Los Angeles` with no coordinates and no region returned businesses
in **Jersey City, New Jersey**. Outscraper resolves ambiguous place names against its own server
location, and Torrance/Whittier/Burbank/Hollywood/Pasadena all exist in several states. Both the
`coordinates` bias *and* the `region` qualifier in the query text are required. The failure mode
is the dangerous kind: a market full of the wrong state's businesses parses at 100%, passes every
filter, and is worthless.

### 5.8 The AR Tools repo is a source of verified provider behaviour
`writer/platform-api/services/gbp_service.py` has been calling Outscraper with this same API key
in production for months. It settled the endpoint (`GET /maps/search-v3` — the brief was right and
I had wrongly called it stale from the vendor's SDK) and the response field ordering. **Check the
repo before the vendor docs.**

### 5.9 Outscraper returns errors as HTTP 2xx
`{"error": true, "errorMessage": ...}` in the body with a 200 status. Status-code-only handling
swallows them.

### 5.10 Railway's `railwayConfigFile` resolves against the REPO ROOT
Not against `rootDirectory`. Setting it to `railway.toml` fails with `service config at
'railway.toml' not found`, the config is never read, and the builder silently falls back to
Railpack. It must be `outreach/railway.toml`.

---

## 6. Layout

```
outreach/
├── HANDOFF.md            this file
├── CLAUDE.md             session protocol + invariants
├── START-HERE.md         build phases, table ownership, config reference
├── DECISIONS.md          settled decisions WITH reasoning — read before proposing changes
├── ISSUES.md             open problems, corrections, unvalidated assumptions
├── docs/                 the six specs (PRD is Phase 2+; the Phase 1 brief is self-contained)
├── markets/              one JSON per market-vertical; EXAMPLE-* is the template
├── migrations/           SQL (applied out-of-band, never by the job)
├── queries/              phase1-dod.sql
├── Dockerfile            the Railway job image
├── railway.toml          builder + restart policy
└── api/
    ├── config.py         every tunable; nothing hardcoded
    ├── db.py             Supabase client (service role)
    ├── services/         outscraper_client, parser, tiling, filters, suppression,
    │                     cost, paging, seeding, pipeline
    ├── scripts/          run_market (the entrypoint), calibrate, calibrate_standalone
    └── tests/            85 tests, no network or database
```

---

## 7. If you are starting Phase 2 SCANNING

The storage foundations are already in place (§8) — do not rebuild them. What remains is the scan
layer itself: DataForSEO geogrid via the standard queue with postback, organic SERP + AI Overview
per submarket × keyword, AI checks per `ai_region`, land masking, and the coverage rollup.

Three things the foundations hand you, and one trap:

- **Use `api/services/geometry.generate_points()`** for scan points, and stamp
  `scan_snapshot.geometry_version` with the version you used. Never regenerate a historical
  snapshot with the default version — pass its stored one.
- **Derive `grid_result.scan_month` from the snapshot, never from `now()`** (ISSUES I-044). Getting
  this wrong splits a snapshot across two partitions and makes the retention job blame the rollup.
- **Write `rollup_coverage()`** (ISSUES I-042). Until it exists the retention job drops nothing but
  empty partitions — correct, but not finished.
- Partitions run two months ahead and there is **no default partition**, so an insert for an
  uncovered month raises. That is deliberate (DECISIONS.md); call `create_month_partitions()`
  defensively before a batch rather than adding one.

---

## 8. Built on 2026-08-01

### 8.1 The suite router — outreach is reachable from AR Tools
`platform-api`: `routers/outreach.py`, `services/outreach.py`, `services/outreach_db.py`, 24 unit
tests. Reads markets, the filter funnel, prospects and their per-rule verdicts; reads and writes
the lead CRM and suppression. **Nothing in it can spend money** — ingestion stays on the Railway
job, deliberately, because a route that fires a paid pull is one click from the duplicate ingest
that already happened once (§5.4).

`services/outreach_db.py` reaches a second **PROJECT**, not a second schema — the one real
divergence from the `leadoff_db.py` pattern. New on PLATFORM: `OUTREACH_SUPABASE_URL`,
`OUTREACH_SUPABASE_SERVICE_ROLE_KEY` (same names and values the outreach job already uses),
`OUTREACH_ENABLED`. Absent them every route answers `503 outreach_not_configured`.

Two objects were added to the Outreacher project to keep aggregation in Postgres (storage spec §9,
and I-036 — a Python-side funnel over 8,328 `filter_result` rows would have been silently truncated
at 1,000): `v_prospect_status` and `outreach_market_summary()`. Verified live against LA — 1,388
prospects, 925 survived, 463 excluded, 22 flagged, matching §2 exactly.

**Nothing in `frontend/` exists yet.** The suite pages are the next piece.

### 8.2 Phase 2 storage foundations — applied live
Migration `20260801120000`: `scan_snapshot`, `grid_result` (partitioned by month, no lat/lng),
`serp_result` (partitioned identically), `grid_result_retained`, `prospect_coverage`,
`grid_result_all` (the union view), `storage_retention_log`, `create_month_partitions()`,
`verify_grid_result_months()`, `drop_cold_partitions()`, and two `pg_cron` schedules (create on the
1st, drop on the 2nd — deliberately the day after, so a failed creation is visible before anything
is dropped).

Verified by `tests/storage_partitioning.sql` — **14 checks, run live, all passing**, including that
a cold partition with unverifiable snapshots is RETAINED and says why. Run it the same way as
`tests/lead_crm_rls.sql`; a pass reports `ERROR: ROLLBACK — 14 checks passed`.

The retention job **fails closed on everything it cannot verify**, including tables that do not
exist yet (`audit_asset`, `slot`) and the missing rollup. Today it drops nothing but empty
partitions. That is correct and is not the same as finished — see I-042.

### 8.3 A defect fixed along the way
`lead_log_changes` stamped `actor_id := auth.uid()`, which is NULL for the service role — so under
the module ruling every stage change would have been logged anonymously (ISSUES **I-040**).
Migration `20260801110000` adds `lead.updated_by` and the trigger prefers it. **Watch for the same
shape elsewhere in the port:** the Retool-era schema assumed an end-user JWT, and anything reading
`auth.uid()` is now reading a null.

### 8.4 The I-040 sweep — one instance, already fixed
Swept as two lists, because the failure modes differ: expressions that RUN under the service role
and receive null (defaults, generated columns, CHECK constraints, views, trigger bodies, functions
reading `auth.*` or `request.jwt`) versus RLS policies, which are bypassed silently and never
evaluated at all. Only the first produces an anonymous actor.

**List A: one row — `lead_log_changes`, already fixed.** Zero defaults, zero generated columns,
zero CHECKs, zero views, zero non-trigger functions, zero `request.jwt` readers.
**List B: zero policies exist**, which is the intended posture, not a gap.
Re-run after any migration that adds a trigger or a default; only List A can regress.

### 8.5 And one found, not fixed
`review_count_min` reports 842 passed / 433 failed / **113 not evaluated** — Outscraper returned no
review count for those 113, and they are counted among the 925 survivors. Correct filter behaviour,
invisible in §2's numbers, and ~12% of the shortlist pool would be contacted at Phase 5 on a
qualification never checked. ISSUES **I-041**, needs a decision before enrichment.
