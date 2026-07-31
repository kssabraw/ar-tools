# HANDOFF — Outreach Pipeline

**Read this first, then `CLAUDE.md` → `START-HERE.md` → `ISSUES.md` → `DECISIONS.md`.**

Status as of 2026-07-31: **Phase 1 (ingest + filter) is COMPLETE and verified against a real
market.** Nothing from Phase 2 has been started. Do not start it without being asked.

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

### 4.3 Grid geometry ambiguity — free now, frozen later
`ISSUES I-025`: the specs describe an "89-point geogrid" at 1-mile spacing over a 5-mile radius. A
1-mile lattice in a 5-mile radius holds **81** points (also exactly 9×9). 89 matches neither.
No Phase 1 impact, but **Phase 2 pins geometry and it becomes immutable**, so settle it before the
first scan.

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

## 7. If you are starting Phase 2

Read `START-HERE.md` §4 for the phase definition and `docs/storage-retention-spec.md` **before**
the second scan cycle writes data — `grid_result` partitioning is far cheaper to build than to
retrofit, and the spec is the owner of that table (the PRD's copy is context only).

Settle §4.3 (grid point count) first. Geometry becomes immutable the moment the first scan runs,
and the 14 LA submarket centroids are still freely editable **only until then**.
