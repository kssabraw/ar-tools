-- Phase 2 storage foundations — partitioning and retention.
--
-- Owner: docs/storage-retention-spec.md. The PRD carries a copy of `grid_result` with an
-- unpartitioned shape and lat/lng columns; that copy is CONTEXT ONLY and implementing from it
-- would produce the wrong table (ISSUES R-001).
--
-- WHY THIS EXISTS BEFORE THERE IS ANY DATA. `grid_result` is ~99% of all rows the system will
-- ever write: ~58M rows/year at the recorded 50 market-vertical portfolio, ~7.0 GB, which
-- exhausts Supabase Pro's 8 GB allowance inside year one. (The spec said 64M / 7.7 GB on an
-- 89-point grid; the grid holds 81, so every figure is ~9% lower and the conclusion is identical
-- — see ISSUES I-025.) Retrofitting partitioning onto a
-- multi-gigabyte table is materially harder than building it first, and the window to build it
-- first closes the moment the first scan writes. Nothing has scanned yet. This is that window.
--
-- WHAT IS DELIBERATELY NOT HERE:
--
--   * The coverage rollup's IMPLEMENTATION. `prospect_coverage` is created (the storage spec owns
--     it), but `rollup_coverage()` is not written, because `rank_vector` — one byte per grid
--     point ordered by point_seq — cannot be produced correctly before the pinned geometry
--     generator and land masking exist, and a rank_vector with the wrong ordering silently
--     renders every historical heatmap against the wrong coordinates. That is a worse failure
--     than not having the rollup: the retention job below simply REFUSES to drop a partition
--     whose snapshots lack a rollup, so the absence fails closed and costs nothing until there is
--     something to drop. See DECISIONS.md.
--
--   * Any writer. Nothing in this migration ingests, scans or spends.

-- ---------------------------------------------------------------------------
-- scan_snapshot
--
-- Defined by docs/PRD-prospect-pipeline.md, reproduced verbatim because `grid_result` references
-- it and cannot be created without it. Immutable and append-only: deltas depend on history, and
-- a mutated snapshot silently rewrites the past that a delta claim was computed against.
--
-- `geometry_version` is the pin. Grid coordinates are NOT stored anywhere — they regenerate from
-- (centre, grid_radius_miles, grid_spacing_miles, point_seq) through a versioned generator, and
-- this column records which generator produced a given snapshot's point ordering. Changing the
-- ordering without bumping it re-maps every historical vector onto the wrong coordinates.
-- ---------------------------------------------------------------------------
create table if not exists scan_snapshot (
  id uuid primary key default gen_random_uuid(),
  submarket_id uuid not null references submarket(id) on delete cascade,
  keyword_id uuid not null references keyword(id) on delete cascade,
  grid_radius_miles numeric not null,
  grid_spacing_miles numeric not null,
  point_count integer not null,
  expected_points smallint not null,
  actual_points smallint not null,
  complete boolean not null default false,   -- actual/expected >= completeness_threshold (0.98)
  trigger_reason text,                       -- null = scheduled cadence; set for event-triggered
  geometry_version text not null,            -- pinned generator version (reporting spec §4.1)
  scanned_at timestamptz not null default now()
);

create index if not exists scan_snapshot_submarket_keyword_idx
  on scan_snapshot (submarket_id, keyword_id, scanned_at desc);

-- The retention job walks partitions by month and must find their snapshots cheaply.
create index if not exists scan_snapshot_scanned_at_idx on scan_snapshot (scanned_at);

alter table scan_snapshot enable row level security;

-- ---------------------------------------------------------------------------
-- grid_result — partitioned by month
--
-- NO lat/lng. Coordinates are derivable from the snapshot's geometry plus `point_seq`, and
-- storing them per row duplicates 16 bytes across ~20 results per point — ~240 MB/year wasted at
-- a QUARTER of the recorded portfolio size.
--
-- NO DEFAULT PARTITION, deliberately. A default partition never loses a row, which sounds like
-- the safe choice, but it has a trap with a long fuse: once a month's rows land in it,
-- `create table ... partition of ... for values from` for THAT month fails until every one of
-- those rows is moved out. The failure surfaces months later, during a routine partition
-- creation, on a table too large to reorganise casually.
--
-- Without one, an insert for a month with no partition raises immediately and loudly. That is the
-- better trade here for the reason the spec itself gives as its governing principle: grid_result
-- is the replaceable data — a lost scan is recoverable for cents, and an un-attachable partition
-- is not recoverable at all without a maintenance window. `create_month_partitions()` runs two
-- months ahead and is idempotent, so a writer can also call it defensively before a batch.
-- ---------------------------------------------------------------------------
create table if not exists grid_result (
  id           bigserial,
  snapshot_id  uuid not null references scan_snapshot(id) on delete cascade,
  scan_month   date not null,          -- partition key, denormalized from the snapshot
  point_seq    smallint not null,
  place_id     text not null,
  rank         smallint not null,
  primary key (id, scan_month)
) partition by range (scan_month);

create index if not exists grid_result_snapshot_place_idx on grid_result (snapshot_id, place_id);

alter table grid_result enable row level security;

-- ---------------------------------------------------------------------------
-- serp_result — partitioned identically
--
-- Shape from the PRD; `payload_path` / `payload_summary` from storage spec §6. Partitioned now
-- rather than later for exactly the reason grid_result is: it costs three lines while the table
-- is empty and a rebuild once it is not.
--
-- `payload_path IS NULL` means NOT YET MIGRATED, never "absent" — readers MUST fall back to the
-- in-Postgres `payload` column. Treating null as missing data is called out in CLAUDE.md as a
-- plausible-looking action that is wrong.
-- ---------------------------------------------------------------------------
create table if not exists serp_result (
  id              uuid not null default gen_random_uuid(),
  snapshot_id     uuid not null references scan_snapshot(id) on delete cascade,
  scan_month      date not null,
  engine          text not null,
  payload         jsonb,
  payload_path    text,       -- object key once migrated to R2; null = not yet migrated
  payload_summary jsonb,      -- the parsed fields the pipeline queries; stays in Postgres
  primary key (id, scan_month)
) partition by range (scan_month);

create index if not exists serp_result_snapshot_idx on serp_result (snapshot_id);

alter table serp_result enable row level security;

-- ---------------------------------------------------------------------------
-- grid_result_retained — where survivors go before a partition is dropped
--
-- Storage spec §11a chose relocation over a `(scan_month, retention_class)` composite partition
-- key. The composite key is cleaner at drop time but adds a column to every query touching
-- grid_result for the life of the system; relocation concentrates the complexity in one monthly
-- job instead of spreading it across every read path.
--
-- LIKE INCLUDING DEFAULTS keeps the bigserial default pointing at grid_result's own sequence, so
-- ids stay unique across both tables and a row does not change identity when it moves.
-- ---------------------------------------------------------------------------
create table if not exists grid_result_retained (
  like grid_result including defaults including indexes
);

alter table grid_result_retained enable row level security;

-- Reads span both transparently, so callers never need to know which table holds a snapshot.
create or replace view grid_result_all
with (security_invoker = true) as
  select id, snapshot_id, scan_month, point_seq, place_id, rank, false as retained
    from grid_result
  union all
  select id, snapshot_id, scan_month, point_seq, place_id, rank, true  as retained
    from grid_result_retained;

-- ---------------------------------------------------------------------------
-- prospect_coverage — the rollup target
--
-- One row per prospect per snapshot replaces ~1,780 raw rows: a ~46x reduction that preserves
-- everything trend charts, client reports and delta recomputation need.
--
-- `live_points` is STORED, never recomputed. Land masking changes the denominator over time, so
-- without the contemporaneous value every historical coverage figure becomes uninterpretable —
-- a coastal submarket's 60% in March would silently become a different number when read in June.
--
-- `rank_vector` is why the rollup keeps per-point detail at all: aggregate statistics cannot
-- reproduce a heatmap, and without it a dropped partition takes the picture with it while leaving
-- the numbers behind. One unsigned byte per grid point ordered by point_seq — 0 absent, 1-20
-- rank, 255 dead — aligned to the snapshot's PINNED geometry. Ordering that disagrees with
-- `scan_snapshot.geometry_version` renders history against the wrong coordinates.
-- ---------------------------------------------------------------------------
create table if not exists prospect_coverage (
  prospect_id     uuid not null references prospect(id) on delete cascade,
  snapshot_id     uuid not null references scan_snapshot(id) on delete cascade,
  coverage_pct    numeric(5,2) not null,   -- % of LIVE grid points where present
  points_present  smallint not null,
  live_points     smallint not null,       -- denominator after land masking, contemporaneous
  avg_rank        numeric(4,2),
  best_rank       smallint,
  worst_rank      smallint,
  centroid_dist_at_loss numeric(5,2),      -- miles from pin where they drop out
  rank_vector     bytea not null,          -- 1 byte per grid point, ordered by point_seq
  rolled_up_at    timestamptz not null default now(),
  primary key (prospect_id, snapshot_id)
);

create index if not exists prospect_coverage_snapshot_idx on prospect_coverage (snapshot_id);

alter table prospect_coverage enable row level security;

-- ---------------------------------------------------------------------------
-- storage_retention_log
--
-- Not in the spec's table list; added because §7 requires that a partition failing a check be
-- "retained and logged", and a `raise notice` inside a pg_cron job is written to a log nobody
-- reads. The whole point of the guards is that someone can later answer "why is this partition
-- still here" — which needs a durable answer, not a notice.
--
-- This is also the answer to ISSUES I-034 for the retention path specifically: an unattended job
-- that reports success by saying nothing is indistinguishable from one that never ran.
-- ---------------------------------------------------------------------------
create table if not exists storage_retention_log (
  id             bigserial primary key,
  ran_at         timestamptz not null default now(),
  job            text not null,          -- 'create_partitions' | 'drop_cold_partitions'
  partition_name text,
  outcome        text not null,          -- 'created' | 'dropped' | 'retained' | 'skipped' | 'error'
  reason         text,
  snapshots      integer,
  rows_relocated bigint
);

create index if not exists storage_retention_log_ran_at_idx on storage_retention_log (ran_at desc);

alter table storage_retention_log enable row level security;

-- ---------------------------------------------------------------------------
-- Partition management
-- ---------------------------------------------------------------------------

-- Tables partitioned by scan_month. One list, so a new one is added in exactly one place and
-- cannot be half-wired into the creation job.
-- `set search_path` on every function here, including the trivial ones. Supabase's advisor flags
-- a mutable search_path as a WARN, and the reason is real for the ones below that build DDL with
-- format(): a caller-controlled search_path is how an unqualified name gets resolved somewhere
-- unexpected.
create or replace function partitioned_scan_tables()
returns text[] language sql immutable set search_path = public as $$
  select array['grid_result', 'serp_result']::text[];
$$;

create or replace function month_partition_name(p_table text, p_month date)
returns text language sql immutable set search_path = public as $$
  select format('%s_%s', p_table, to_char(date_trunc('month', p_month), 'YYYY_MM'));
$$;

-- Create partitions for this month and the next `p_months_ahead`.
--
-- Idempotent by construction — `if not exists` on each — so it is safe to run from cron, by hand,
-- or defensively from a writer before a batch. Two months of lead time by default: enough that a
-- single missed monthly run is invisible, short enough that a persistently broken job surfaces
-- before it can silently accumulate.
create or replace function create_month_partitions(p_months_ahead integer default 2)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  tbl        text;
  i          integer;
  month_from date;
  month_to   date;
  part       text;
  made       integer := 0;
begin
  foreach tbl in array partitioned_scan_tables() loop
    for i in 0..p_months_ahead loop
      month_from := (date_trunc('month', current_date) + make_interval(months => i))::date;
      month_to   := (month_from + interval '1 month')::date;
      part       := month_partition_name(tbl, month_from);

      if to_regclass(format('public.%I', part)) is null then
        execute format(
          'create table %I partition of %I for values from (%L) to (%L)',
          part, tbl, month_from, month_to
        );
        execute format('alter table %I enable row level security', part);
        insert into storage_retention_log (job, partition_name, outcome)
        values ('create_partitions', part, 'created');
        made := made + 1;
      end if;
    end loop;
  end loop;

  return made;
end;
$$;

comment on function create_month_partitions(integer) is
  'Create this month plus N months of partitions for every table in partitioned_scan_tables(). '
  'Idempotent; safe to call from cron or defensively before a write batch.';

-- Does every snapshot''s rows sit in the partition its scan month says they should?
--
-- `grid_result.scan_month` is denormalized from the snapshot, so nothing in the database forces
-- the two to agree — a CHECK cannot reference another table, and a per-row trigger on a table
-- taking 64M rows a year is not worth its cost. A writer that computes the month from `now()`
-- instead of the snapshot will split one snapshot across two partitions, and the retention job''s
-- per-snapshot row reconciliation would then compare a partial count against a full one and
-- conclude the ROLLUP was wrong. Cheap to check once a month; confusing to debug later.
create or replace function verify_grid_result_months()
returns table (snapshot_id uuid, snapshot_month date, rows_in_wrong_month bigint)
language sql
stable
security definer
set search_path = public
as $$
  select g.snapshot_id,
         date_trunc('month', s.scanned_at)::date as snapshot_month,
         count(*)                                as rows_in_wrong_month
  from grid_result g
  join scan_snapshot s on s.id = g.snapshot_id
  where g.scan_month <> date_trunc('month', s.scanned_at)::date
  group by 1, 2;
$$;

-- ---------------------------------------------------------------------------
-- drop_cold_partitions
--
-- Storage spec §7. Three checks before anything is dropped, and a partition failing ANY of them
-- is retained whole and logged — never partially dropped.
--
--   1. Every snapshot in the partition has a reconciled rollup.
--   2. No snapshot is cited by a dispatched audit_asset (§3.3 — if a prospect disputes a claim,
--      the backing data must exist).
--   3. No snapshot belongs to a submarket holding a `filled` slot (§3.4 — a client's
--      pre-engagement ranking history is the product).
--
-- FAILS CLOSED ON EVERYTHING IT CANNOT VERIFY. `audit_asset`, `slot` and the rollup writer all
-- arrive in later phases, and until they do this function drops nothing at all. That is the
-- correct behaviour and not a placeholder: the cost of retaining a partition too long is disk;
-- the cost of dropping one whose citation table did not exist yet is a dispatched claim with no
-- evidence behind it. `to_regclass(...) is null` is checked explicitly rather than letting a
-- missing table raise, so the reason lands in the log as a sentence.
--
-- Idempotent and safely re-runnable after interruption: relocation is an insert of rows not
-- already in grid_result_retained, and the drop happens only after the copy is verified per
-- snapshot. An interrupted run leaves a partition that is copied but not dropped, which the next
-- run finishes.
create or replace function drop_cold_partitions(p_hot_window_days integer default 90)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  cutoff        date := (date_trunc('month', current_date - make_interval(days => p_hot_window_days)))::date;
  part          record;
  part_month    date;
  missing       bigint;
  cited         bigint;
  client_held   bigint;
  moved         bigint;
  snap_count    integer;
  unreconciled  bigint;
  dropped       integer := 0;
begin
  for part in
    select c.relname as name,
           -- Partition bounds are only available as text; the month is the reliable way back.
           to_date(right(c.relname, 7), 'YYYY_MM') as month_start
    from pg_class c
    join pg_inherits i on i.inhrelid = c.oid
    join pg_class p on p.oid = i.inhparent
    where p.relname = 'grid_result'
      and c.relnamespace = 'public'::regnamespace
    order by 2
  loop
    part_month := part.month_start;

    -- Inside the hot window: nothing to do, and not worth a log row every month.
    if part_month >= cutoff then
      continue;
    end if;

    execute format(
      'select count(distinct snapshot_id) from %I', part.name
    ) into snap_count;

    if snap_count = 0 then
      execute format('drop table %I', part.name);
      insert into storage_retention_log (job, partition_name, outcome, reason, snapshots)
      values ('drop_cold_partitions', part.name, 'dropped', 'empty partition', 0);
      dropped := dropped + 1;
      continue;
    end if;

    -- GUARD 1 — rollup exists and reconciles, per snapshot.
    --
    -- Per snapshot, not per partition: the spec is explicit that verification must compare row
    -- counts per snapshot, because a partial copy that happens to match on aggregate is exactly
    -- the failure being guarded against.
    if to_regclass('public.prospect_coverage') is null then
      insert into storage_retention_log (job, partition_name, outcome, reason, snapshots)
      values ('drop_cold_partitions', part.name, 'retained',
              'prospect_coverage does not exist — rollup cannot be verified', snap_count);
      continue;
    end if;

    execute format(
      'select count(*) from (select distinct snapshot_id from %I) s
         where not exists (select 1 from prospect_coverage pc where pc.snapshot_id = s.snapshot_id)',
      part.name
    ) into missing;

    if missing > 0 then
      insert into storage_retention_log (job, partition_name, outcome, reason, snapshots)
      values ('drop_cold_partitions', part.name, 'retained',
              format('%s snapshot(s) have no rollup', missing), snap_count);
      continue;
    end if;

    -- Points present in the rollup must not exceed the distinct points actually captured. A
    -- rollup claiming more coverage than the raw data supports is the one error that would make
    -- a pain claim overstate itself, and after the drop it is unfalsifiable.
    execute format(
      'select count(*) from (
         select g.snapshot_id, count(distinct g.point_seq) as raw_points
           from %I g group by 1
       ) r
       join (
         select snapshot_id, max(points_present) as rolled_points
           from prospect_coverage group by 1
       ) pc on pc.snapshot_id = r.snapshot_id
       where pc.rolled_points > r.raw_points',
      part.name
    ) into unreconciled;

    if unreconciled > 0 then
      insert into storage_retention_log (job, partition_name, outcome, reason, snapshots)
      values ('drop_cold_partitions', part.name, 'retained',
              format('%s snapshot(s) fail rollup reconciliation', unreconciled), snap_count);
      continue;
    end if;

    -- GUARD 2 — cited by a dispatched audit asset (§3.3).
    if to_regclass('public.audit_asset') is null then
      insert into storage_retention_log (job, partition_name, outcome, reason, snapshots)
      values ('drop_cold_partitions', part.name, 'retained',
              'audit_asset does not exist yet — citation cannot be checked, so nothing is dropped',
              snap_count);
      continue;
    end if;

    execute format(
      'select count(*) from (select distinct snapshot_id from %I) s
         where exists (select 1 from audit_asset a
                        where a.snapshot_id = s.snapshot_id and a.dispatched_at is not null)',
      part.name
    ) into cited;

    -- GUARD 3 — client submarket with a filled slot (§3.4).
    if to_regclass('public.slot') is null then
      insert into storage_retention_log (job, partition_name, outcome, reason, snapshots)
      values ('drop_cold_partitions', part.name, 'retained',
              'slot does not exist yet — client retention cannot be checked, so nothing is dropped',
              snap_count);
      continue;
    end if;

    execute format(
      'select count(*) from (select distinct snapshot_id from %I) s
         join scan_snapshot ss on ss.id = s.snapshot_id
        where exists (select 1 from slot sl
                       where sl.submarket_id = ss.submarket_id and sl.state = ''filled'')',
      part.name
    ) into client_held;

    -- Survivors are interleaved with cold rows inside the same monthly partition, so they are
    -- relocated rather than the partition being spared wholesale.
    if cited > 0 or client_held > 0 then
      execute format(
        'insert into grid_result_retained (id, snapshot_id, scan_month, point_seq, place_id, rank)
         select g.id, g.snapshot_id, g.scan_month, g.point_seq, g.place_id, g.rank
           from %I g
          where (
                exists (select 1 from audit_asset a
                         where a.snapshot_id = g.snapshot_id and a.dispatched_at is not null)
             or exists (select 1 from scan_snapshot ss join slot sl
                               on sl.submarket_id = ss.submarket_id and sl.state = ''filled''
                         where ss.id = g.snapshot_id)
                )
            and not exists (select 1 from grid_result_retained r
                             where r.id = g.id and r.scan_month = g.scan_month)',
        part.name
      );
      get diagnostics moved = row_count;

      -- Verify the copy per snapshot BEFORE dropping. Aggregate agreement is not enough.
      execute format(
        'select count(*) from (
           select g.snapshot_id, count(*) as src
             from %I g
            where exists (select 1 from audit_asset a
                           where a.snapshot_id = g.snapshot_id and a.dispatched_at is not null)
               or exists (select 1 from scan_snapshot ss join slot sl
                                 on sl.submarket_id = ss.submarket_id and sl.state = ''filled''
                           where ss.id = g.snapshot_id)
            group by 1
         ) s
         left join (
           select snapshot_id, count(*) as dst from grid_result_retained
            where scan_month = %L group by 1
         ) d on d.snapshot_id = s.snapshot_id
         where coalesce(d.dst, 0) < s.src',
        part.name, part_month
      ) into unreconciled;

      if unreconciled > 0 then
        insert into storage_retention_log
          (job, partition_name, outcome, reason, snapshots, rows_relocated)
        values ('drop_cold_partitions', part.name, 'retained',
                format('relocation incomplete for %s snapshot(s) — partition kept', unreconciled),
                snap_count, moved);
        continue;
      end if;
    else
      moved := 0;
    end if;

    execute format('drop table %I', part.name);
    insert into storage_retention_log
      (job, partition_name, outcome, reason, snapshots, rows_relocated)
    values ('drop_cold_partitions', part.name, 'dropped',
            format('cold partition older than %s days', p_hot_window_days), snap_count, moved);
    dropped := dropped + 1;
  end loop;

  return dropped;
end;
$$;

comment on function drop_cold_partitions(integer) is
  'Storage spec §7. Drops grid_result partitions past the hot window, after per-snapshot rollup '
  'reconciliation and relocation of cited (§3.3) and client (§3.4) survivors. Fails closed on '
  'anything it cannot verify — including tables that do not exist yet. Idempotent.';

-- ---------------------------------------------------------------------------
-- Access — service role only, matching every other object in this project.
-- Supabase grants ALL on new objects in `public` to anon/authenticated by default, so these
-- revokes are the only statements here that change anything.
-- ---------------------------------------------------------------------------
revoke all on grid_result, grid_result_retained, serp_result, scan_snapshot,
               prospect_coverage, storage_retention_log
  from anon, authenticated;
revoke all on grid_result_all from anon, authenticated;
revoke all on function create_month_partitions(integer)   from anon, authenticated, public;
revoke all on function drop_cold_partitions(integer)      from anon, authenticated, public;
revoke all on function verify_grid_result_months()        from anon, authenticated, public;
revoke all on function month_partition_name(text, date)   from anon, authenticated, public;
revoke all on function partitioned_scan_tables()          from anon, authenticated, public;

-- ---------------------------------------------------------------------------
-- Bootstrap + schedule
--
-- Partitions for the current month and the next two, so the table is writable the moment a
-- scanner exists rather than on the first of next month.
-- ---------------------------------------------------------------------------
select create_month_partitions(2);

create extension if not exists pg_cron;

-- Monthly, on the 1st: create ahead. Monthly, on the 2nd: drop behind — deliberately the day
-- after, so a failed creation run is visible before anything is dropped.
select cron.schedule('outreach_create_partitions',    '0 3 1 * *', 'select create_month_partitions(2)');
select cron.schedule('outreach_drop_cold_partitions', '0 4 2 * *', 'select drop_cold_partitions()');
