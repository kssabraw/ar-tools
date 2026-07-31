# outreach/api — Phase 1 (ingest and filter)

Pulls every business listing for one category in one city, drops the ones not worth pursuing, and
explains every exclusion. **No scoring** — `prospect_score` is not written in this phase, and
neither `scan_snapshot` nor `grid_result` exists yet.

Read `../docs/PHASE-1-BRIEF.md` for the phase, `../START-HERE.md` for the build order,
`../DECISIONS.md` before proposing a change, and `../ISSUES.md` for what is known-broken.

## Layout

```
config.py                     every tunable; nothing hardcoded
db.py                         Supabase client (SEPARATE project from AR Tools)
services/outscraper_client.py POST /google-maps-search, async submit + poll
services/parser.py            provider dict -> prospect columns, via an alias map
services/tiling.py            tile fan-out, place_id dedup, submarket assignment
services/filters.py           Stage A2 rule matrix (pure — no DB, no clock, no config)
services/suppression.py       suppression index, tolerant of a missing/empty table
services/cost.py              pre-flight estimate, abort gate, ledger rows
services/pipeline.py          Stage A1 then Stage A2
../queries/phase1-dod.sql     the four §6 definition-of-done questions
../supabase/migrations/       six tables + suppression
```

## Running the tests

```bash
cd outreach && python -m pytest api/tests -q
```

No network, no database. 42 tests covering the filter matrix, dedup across overlapping tiles, the
cost abort gate, and the parser aliases.

## Before a real market run

1. **Set `OUTREACH_OUTSCRAPER_COST_PER_1000_PLACES_CENTS` from the real plan.** The abort gate at
   `max_market_run_cost_cents` is exactly as honest as this number, and the default (200) is a
   placeholder.
2. **Define the submarkets first.** Grid geometry is immutable once scanning begins — changing a
   centroid later invalidates every prior snapshot and resets delta history. Without submarkets
   the tiler degrades to a single query per category, which Google caps at ~400 results and which
   will silently under-cover anything larger than a small town.
3. **Pin `parser.FIELD_ALIASES` against the first pull.** Response field names are unverified
   (ISSUES I-018); `parser.unmapped_fields()` logs what no alias claimed.
4. **Check the tile overlap rate.** Near-zero overlap between adjacent tiles means the tiling is
   too sparse to call the market covered (ISSUES I-017).

## What this deliberately does not do

No scoring, no scanning, no geogrid, no deltas, no enrichment, no audits, no outreach. The
Outscraper `enrichment` parameter is never populated — enrichments are billed separately and
belong to Phase 5.
