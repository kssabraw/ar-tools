# Supabase migrations — conventions & ledger

This folder (`writer/supabase/migrations/`) holds every schema migration for the
**AR Tools** suite's own tables. Read this before adding a migration.

## Golden rule: filename version **must equal** the recorded `schema_migrations.version`

The Supabase CLI reconciles by the 14-digit timestamp prefix of each filename
(`YYYYMMDDHHMMSS_name.sql`) against `supabase_migrations.schema_migrations.version`
in the database. If those don't match, the CLI thinks a file is an unapplied
migration and may try to re-run it.

**Therefore: author each migration filename with a real UTC timestamp** (the
moment you create it), not a placeholder like `...120000`. When a migration is
applied, that exact version is what lands in `schema_migrations`, so the two stay
in sync automatically.

> Historical note: early migrations in this repo used hand-authored `...120000`
> placeholder timestamps and were then applied via the Supabase MCP
> (`apply_migration`), which stamps each row with the *apply-time* UTC timestamp.
> That made filenames and recorded versions diverge. This was reconciled on
> 2026-05-31 (see "Reconciliation log" below) — filenames now match the recorded
> versions exactly.

## How migrations get applied

- **Web-only / no shell:** apply via the Supabase MCP `apply_migration` tool. It
  records a `schema_migrations` row stamped with the current UTC time — so name
  the file with that same timestamp (or rename it to match afterward).
- **Local dev:** `supabase db push` applies pending files and records each file's
  own version. Filenames are authoritative.
- All backend code reads/writes with the **service-role key** (RLS is bypassed),
  per `CLAUDE.md`.

## ⚠️ This Supabase project is shared with another tool

The live project (`AR-Internal-Tools`, ref `wvcthtmmcmhkybcesirb`) is **also used
by the Keyword Research / Fan-Out tool**, which has its own migration lineage
recorded in the same `schema_migrations` table but **not** stored in this repo.
Those rows live under their own `fanout` schema and `keywords`/`clusters`/
`sessions`/`topics`/`peer_entities`/`site_architecture`/`session_*`/`csv_exports`/
`keyword_metrics` tables.

**Do not copy those migrations into this folder.** They belong to that tool's
repo and will arrive when Keyword Research is formally migrated into the suite
(see `docs/suite-architecture-and-roadmap-v1_0.md`). Running `supabase migration
list` against this project will show those ~14 entries as "remote only" — that is
expected for a shared project, not a problem.

## AR Tools migration ledger

| Version (= filename prefix) | Migration |
|---|---|
| `20260430120000` | `schema` |
| `20260430120100` | `rls` |
| `20260430120200` | `indexes` |
| `20260501120000` | `sie_cache` |
| `20260501202328` | `silo_candidates` (recorded as `silo_candidates_v1_4`) |
| `20260501203231` | `brief_cache` (recorded as `briefs_cache_v2_0`) |
| `20260502120000` | `clients_google_drive_folder` |
| `20260502120100` | `snapshot_format_columns` |
| `20260503120000` | `runs_brief_force_refresh` |
| `20260529220918` | `clients_suite_fields` |
| `20260530003510` | `clients_gbp` |
| `20260531181719` | `fix_profiles_rls_recursion` *(lands via the logo/handoff branch)* |
| `20260531200317` | `client_logos_bucket` *(lands via the logo/handoff branch)* |
| `20260531210255` | `fanout_sourced_silo_auto_approve` |
| … | *(intervening Local SEO / brand-voice / ICP / keyword-analyses module migrations live in the folder with their own version prefixes)* |
| `20260622181919` | `gsc_properties` (Organic Rank Tracker #4 — M1) |
| `20260622181933` | `gsc_ingest_storage` (#4 — M2) |
| `20260622183357` | `rank_tracker_keywords` (#4 — M3; `rank_keyword_metrics`) |
| `20260622185307` | `keywords_client_anchor` (#4 — client-anchored keywords for the DataForSEO fallback) |
| `20260622185948` | `keyword_market` (#4 — CPC/volume/competition) |
| `20260622191240` | `gsc_query_page_daily` (#4 — canonical URL + Pages) |
| `20260622191831` | `keyword_index_status` (#4 — deindex URL-Inspection result) |
| `20260622203200` | `sie_cache_enable_rls` (drift fix — RLS on `sie_cache`) |
| `20260622232017` | `serp_snapshots` (Organic Rank Tracker #4 — Competitive SERP Snapshot store) |
| `20260623000343` | `rank_alerts` (Organic Rank Tracker #4 — in-app rank-drop alerting) |

> A few `schema_migrations.name` values carry version suffixes (`_v1_4`, `_v2_0`)
> from how they were originally applied. The CLI matches on the numeric version,
> not the name, so the repo keeps the cleaner descriptive filename. Both refer to
> the same migration.

## Reconciliation log

**2026-06-23** — Rank-drop alerting (#4): added `rank_alerts` (one-open-alert-per
-keyword-per-type via a partial unique index; in-app only) applied via the
Supabase MCP. Recorded version `20260623000343`; file renamed from its placeholder
`…235708` prefix and its `-- Migration:` header updated to match. RLS on, no
client-facing policies.

**2026-06-22** — Competitive SERP Snapshot (#4): added `serp_snapshots` +
`serp_snapshot_results` (+ `serp_snapshot` in the `async_jobs.job_type` check),
applied via the Supabase MCP. The MCP stamped version `20260622232017`, so the
file was renamed from its placeholder `…230758` prefix to that recorded version
and its `-- Migration:` header updated to match. RLS on, no client-facing
policies (service-role only).

**2026-06-22** — Organic Rank Tracker (#4) migrations + a security fix:

- Added 7 rank-tracker migrations (`gsc_properties` → `keyword_index_status`)
  applied via the Supabase MCP. The MCP stamps `schema_migrations` with the
  *apply-time* UTC version, so each file was **renamed from its placeholder
  `…HHMMSS` prefix to the recorded version** (e.g. `20260622160000` →
  `20260622181919`) and its `-- Migration:` header updated to match. Content is
  identical to what was applied.
- `sie_cache_enable_rls` (`20260622203200`): the Supabase advisor flagged
  `public.sie_cache` with **RLS disabled** on the live project, even though
  `20260501120000_sie_cache.sql` enabled it at creation (drift). The table is
  service-role-only (nothing reads it with the anon key — the frontend uses only
  the `sie_cache_hit` boolean on `runs`), so re-enabled RLS with no policies.

**2026-05-31** — aligned this repo's migration folder with the live
`schema_migrations`:

- Renamed 5 files whose placeholder timestamps didn't match their recorded
  versions: `brief_cache`, `silo_candidates`, `clients_suite_fields`,
  `clients_gbp`, `fanout_sourced_silo_auto_approve`. (Content was verified
  identical to the recorded statements before renaming.)
- `fanout_sourced_silo_auto_approve` had been committed but **never applied** to
  production — the unique index `uq_silo_client_keyword_active` and trigger
  `trg_silo_fanout_auto_approve` were missing. Applied it (0 pre-existing
  duplicate `(client_id, suggested_keyword)` rows, so the unique index built
  cleanly), then renamed the file to the recorded version `20260531210255`.
- `runs_brief_force_refresh` had been applied via raw SQL but was **untracked**.
  Inserted its `schema_migrations` row at the file's version `20260503120000`
  (a "migration repair").
- Documented the shared-project reality with the Keyword Research tool (above).
