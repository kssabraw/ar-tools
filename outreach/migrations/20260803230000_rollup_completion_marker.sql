-- Make the rollup verification catch a PARTIAL write. ISSUES I-069.
--
-- `drop_cold_partitions` guards a partition on two things: that every snapshot in it has *some*
-- row in `prospect_coverage`, and that `max(points_present)` per snapshot does not exceed the
-- distinct `point_seq` count in the raw partition.
--
-- Neither catches a rollup that covered SOME prospects and not others. The first is
-- `not exists (... where pc.snapshot_id = s.snapshot_id)` — any row for the snapshot satisfies
-- it. The second compares point counts, so a prospect missing from the rollup entirely leaves
-- `max(points_present) <= raw_points` true. A rollup that died halfway therefore reads as
-- complete, and the raw partition it was being verified against gets dropped. The prospects that
-- were missed lose their `rank_vector` permanently, and nothing afterwards can tell.
--
-- That is precisely the failure the verification exists to prevent, so it gets two fixes: one
-- that stops the partial write being taken for a whole one, and one that detects a partial write
-- that happened some other way.
--
-- WHY A SEPARATE TABLE RATHER THAN A COLUMN ON scan_snapshot.
--
-- The obvious place for "this snapshot's rollup finished" is `scan_snapshot.rollup_completed_at`.
-- But `scan_snapshot` is specified as immutable and append-only (I-070), and adding a column that
-- must be UPDATEd after insert would build the exception into the table this project most wants
-- to be able to trust. An append-only marker table keeps both properties: the snapshot is still
-- written once and never altered, and the marker is still a single row that either exists or does
-- not.
--
-- It is also the honest shape. "The rollup completed" is a fact about a PROCESS, not an attribute
-- of the measurement — the same reason `review_count_inferred_zero` lives beside `review_count`
-- rather than inside it (I-051).

create table if not exists snapshot_rollup (
  snapshot_id     uuid primary key references scan_snapshot(id) on delete cascade,
  prospect_count  integer not null,
  point_count     integer not null,
  completed_at    timestamptz not null default now()
);

comment on table snapshot_rollup is
  'One row per snapshot whose prospect_coverage rollup ran to completion. Written ONLY by '
  'finalize_snapshot_rollup(), in the same transaction as the rollup rows, so its presence is '
  'proof the rollup did not die halfway (ISSUES I-069). drop_cold_partitions refuses to drop a '
  'partition holding a snapshot without one.';

-- The finalizer. Call this as the LAST statement of the rollup transaction, after every
-- prospect_coverage row for the snapshot has been inserted.
--
-- It re-derives both counts from the data rather than trusting what the caller believes it wrote,
-- and RAISES on a mismatch. Raising is the point: it aborts the transaction, so a rollup that
-- covered 380 of 400 prospects leaves no marker AND no partial rollup — the whole thing rolls
-- back and the partition stays. A caller cannot opt out of the check by forgetting to look at a
-- return value.
create or replace function finalize_snapshot_rollup(p_snapshot_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $function$
declare
  raw_prospects   integer;
  rolled_prospects integer;
  raw_points      integer;
begin
  -- Join through `prospect`: grid_result holds the top ~20 businesses at each of 81 points
  -- (~1,620 rows/snapshot, storage spec §1), and most of them are NOT prospects — they are
  -- whoever happened to rank. prospect_coverage is one row per PROSPECT. Comparing distinct
  -- place_id against coverage rows would compare hundreds of businesses to a few hundred
  -- prospects and raise forever, making every partition permanently undroppable.
  select count(distinct pr.id)
    into raw_prospects
    from grid_result g
    join prospect pr on pr.place_id = g.place_id
   where g.snapshot_id = p_snapshot_id;

  -- Points SCANNED, deliberately NOT joined through prospect. Counting only points where a
  -- prospect happened to appear would record a number that reads like grid coverage and is not:
  -- a snapshot with 81 points and prospects at 12 of them would record point_count 12.
  select count(distinct g.point_seq)
    into raw_points
    from grid_result g
   where g.snapshot_id = p_snapshot_id;

  select count(*) into rolled_prospects
    from prospect_coverage pc
   where pc.snapshot_id = p_snapshot_id;

  if raw_prospects = 0 then
    raise exception
      'snapshot % matched no known prospects in grid_result — nothing to roll up', p_snapshot_id;
  end if;

  -- The check the old guards could not make. Every prospect the raw data saw must appear in the
  -- rollup; a rollup covering fewer is partial, whatever its aggregate statistics look like.
  if rolled_prospects <> raw_prospects then
    raise exception
      'partial rollup for snapshot %: % prospects in grid_result, % in prospect_coverage',
      p_snapshot_id, raw_prospects, rolled_prospects;
  end if;

  insert into snapshot_rollup (snapshot_id, prospect_count, point_count)
  values (p_snapshot_id, rolled_prospects, raw_points)
  on conflict (snapshot_id) do update
    set prospect_count = excluded.prospect_count,
        point_count    = excluded.point_count,
        completed_at   = now();
end;
$function$;

revoke all on function finalize_snapshot_rollup(uuid) from anon, authenticated, public;

-- `rank_vector` is already `not null` on prospect_coverage, so a single row cannot be summary
-- statistics without its vector. That is the per-ROW half of "written in the same transaction".
-- The marker above is the per-SNAPSHOT half: it cannot exist unless every prospect's row,
-- vector included, was already committed alongside it.
--
-- Stated as a constraint comment rather than a check, because the property is transactional and
-- no column-level constraint can express it.
comment on column prospect_coverage.rank_vector is
  'One unsigned byte per grid point, ordered by point_seq (storage spec §4). NOT NULL is '
  'load-bearing: summary statistics without the vector would retain the numbers and lose the '
  'picture. Per-snapshot completeness is enforced separately by finalize_snapshot_rollup().';


-- ---------------------------------------------------------------------------------------------
-- GUARD 1, replaced. Everything else in drop_cold_partitions is BYTE-IDENTICAL to
-- `20260801120000_phase2_storage.sql` — the relocation of cited (§3.3) and client (§3.4)
-- survivors into grid_result_retained, both later reconciliation guards, and the logging are
-- unchanged. The whole function is restated because CREATE OR REPLACE takes a whole body, not
-- because any of the rest was reconsidered.
-- ---------------------------------------------------------------------------------------------

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

    -- GUARD 1 — the rollup was FINALIZED, per snapshot (ISSUES I-069).
    --
    -- This test was "the snapshot has some prospect_coverage rows". Presence of rows is not
    -- evidence the rollup finished: a run that covered some prospects and then died leaves rows
    -- behind that satisfy any existence test, so a partial rollup read as complete and the raw
    -- partition it was being verified against was dropped. The prospects that were missed lost
    -- their rank_vector permanently, and nothing afterwards could tell.
    --
    -- The marker is written by finalize_snapshot_rollup() inside the rollup's own transaction,
    -- after that function has verified every prospect in the raw data has a coverage row. So the
    -- marker existing is a FACT about completeness rather than an inference from row presence.
    if to_regclass('public.snapshot_rollup') is null then
      insert into storage_retention_log (job, partition_name, outcome, reason, snapshots)
      values ('drop_cold_partitions', part.name, 'retained',
              'snapshot_rollup does not exist — rollup completion cannot be verified', snap_count);
      continue;
    end if;

    execute format(
      'select count(*) from (select distinct snapshot_id from %I) s
         where not exists (select 1 from snapshot_rollup r where r.snapshot_id = s.snapshot_id)',
      part.name
    ) into missing;

    if missing > 0 then
      insert into storage_retention_log (job, partition_name, outcome, reason, snapshots)
      values ('drop_cold_partitions', part.name, 'retained',
              format('%s snapshot(s) have no finalized rollup', missing), snap_count);
      continue;
    end if;

    -- Re-check the prospect count against the raw data AT DROP TIME, not just at rollup time.
    -- finalize_snapshot_rollup() already proved this, but that was potentially months ago, and
    -- this is the last moment the raw data exists to be compared against.
    execute format(
      'select count(*) from (
         select g.snapshot_id, count(distinct pr.id) as raw_prospects
           from %I g join prospect pr on pr.place_id = g.place_id group by 1
       ) r
       join snapshot_rollup sr on sr.snapshot_id = r.snapshot_id
       where sr.prospect_count <> r.raw_prospects',
      part.name
    ) into unreconciled;

    if unreconciled > 0 then
      insert into storage_retention_log (job, partition_name, outcome, reason, snapshots)
      values ('drop_cold_partitions', part.name, 'retained',
              format('%s snapshot(s) fail prospect-count reconciliation', unreconciled), snap_count);
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

revoke all on function drop_cold_partitions(integer) from anon, authenticated, public;

comment on column snapshot_rollup.prospect_count is
  'Distinct PROSPECTS present in this snapshot''s grid_result at finalize time — the number the '
  'rollup had to match. Not the number of businesses in the grid, which is far larger.';
comment on column snapshot_rollup.point_count is
  'Distinct grid points captured in this snapshot, NOT joined through prospect. Points where a '
  'prospect appeared is a different measure and would misread as coverage.';
