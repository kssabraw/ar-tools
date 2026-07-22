-- Migration: 20260722000000_maps_dataforseo.sql
-- Purpose: Switch the Maps / local-pack geo-grid ranker (Module #5) from the
--          Local Dominator API to DataForSEO's Google Maps SERP API. This is
--          the schema half of that switchover (additive + dormant): existing
--          Local Dominator scans keep working, and DataForSEO scans are enabled
--          later by flipping MAPS_SCAN_PROVIDER=dataforseo.
--
-- Reverses the locked suite-roadmap decision of 2026-06-23 ("Local Dominator
-- supersedes DataForSEO geo-grid"); owner-approved 2026-07-20.
--
-- DataForSEO has no native geo-grid endpoint, so we build the grid ourselves:
-- one /v3/serp/google/maps/task_post per in-circle pin (location_coordinate =
-- "lat,lng,zoom"), collected incrementally via task_get. maps_scan_pins is the
-- per-pin bookkeeping that makes that collection idempotent + restart-safe.
--
-- Additive only: no changes to maps_scan_results shape/semantics, so every
-- downstream consumer (heatmap, analytics, reports, alerts, Action Plan) is
-- unaffected. RLS on, service-role only (the async_jobs pattern).

-- Provider per scan. Existing rows predate DataForSEO, so they default to
-- Local Dominator; the poller routes each in-flight scan by THIS column (not
-- the global config flag) so both providers coexist across the cutover.
alter table maps_scans add column if not exists provider text not null default 'local_dominator';

-- Per-pin task bookkeeping for DataForSEO scans: incremental, idempotent,
-- restart-safe collection. One row per (keyword, in-circle pin).
create table if not exists maps_scan_pins (
  id uuid primary key default gen_random_uuid(),
  scan_id uuid not null references maps_scans(id) on delete cascade,
  keyword text not null,
  row_idx int not null,
  col_idx int not null,
  lat double precision not null,
  lng double precision not null,
  task_id text,                      -- DataForSEO task id (null until posted)
  status text not null default 'pending',  -- pending | posted | done | failed
  attempts int not null default 0,
  client_rank int,                   -- 1-based, null = not in top 20
  pin_data jsonb,                    -- compact ordered business list for rollups
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (scan_id, keyword, row_idx, col_idx)
);
create index if not exists maps_scan_pins_scan_status on maps_scan_pins (scan_id, status);

alter table maps_scan_pins enable row level security;

-- Parallel-run trigger (§7): before cutover, the operator runs DataForSEO test
-- scans tagged trigger='parallel_test' whose completion path skips the report +
-- analyzer hooks (no LLM spend / no alerts from test data) and whose rows are
-- deleted after comparison. Widen the CHECK so those scans can be inserted. The
-- quarantine skip itself lives in maps_dataforseo.poll_scan_dfs.
alter table maps_scans drop constraint if exists maps_scans_trigger_check;
alter table maps_scans
  add constraint maps_scans_trigger_check
  check (trigger in ('scheduled', 'manual', 'parallel_test'));
