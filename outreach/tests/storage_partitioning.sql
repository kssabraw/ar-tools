-- Verification for the Phase 2 storage foundations (migration 20260801120000).
--
-- Run against the Outreacher project with the service role. The whole script executes inside a
-- DO block that ALWAYS raises at the end, so every insert, partition and dropped table is rolled
-- back. A passing run reports:
--
--     ERROR:  ROLLBACK — 14 checks passed
--
-- An ERROR that says anything else is a real failure. This is the same shape as
-- tests/lead_crm_rls.sql.
--
-- Why a live script rather than unit tests: partition routing, per-snapshot reconciliation and
-- the fail-closed guards are properties of Postgres and of this schema, and a Python mock of them
-- would only assert that the mock behaves as written.

do $$
declare
  checks      integer := 0;
  v_submarket uuid;
  v_keyword   uuid;
  v_prospect  uuid;
  v_snapshot  uuid;
  v_old_snap  uuid;
  v_part      text;
  v_count     bigint;
  v_dropped   integer;
  v_reason    text;
  v_month     date := date_trunc('month', current_date)::date;
  v_old_month date := (date_trunc('month', current_date) - interval '8 months')::date;
begin
  select id into v_submarket from submarket limit 1;
  select id into v_keyword   from keyword   limit 1;
  select id into v_prospect  from prospect  limit 1;
  if v_submarket is null or v_keyword is null then
    raise exception 'FAIL: no submarket/keyword seeded — run `run_market seed` first';
  end if;

  -- 1. Partitions exist for this month and the next two, on BOTH partitioned tables.
  select count(*) into v_count
  from pg_class c join pg_inherits i on i.inhrelid = c.oid join pg_class p on p.oid = i.inhparent
  where p.relname = any (partitioned_scan_tables());
  if v_count < 6 then
    raise exception 'FAIL 1: expected >= 6 partitions across grid_result/serp_result, found %', v_count;
  end if;
  checks := checks + 1;

  -- 2. No DEFAULT partition on either table.
  --    A default partition is the trap this schema deliberately avoids: rows for an uncreated
  --    month land in it silently, and then that month's partition can never be attached until
  --    every one of them is moved out — a failure that surfaces months later on a huge table.
  select count(*) into v_count
  from pg_class c join pg_inherits i on i.inhrelid = c.oid join pg_class p on p.oid = i.inhparent
  where p.relname = any (partitioned_scan_tables())
    and pg_get_expr(c.relpartbound, c.oid) = 'DEFAULT';
  if v_count <> 0 then
    raise exception 'FAIL 2: % default partition(s) exist — rows for missing months would be absorbed silently', v_count;
  end if;
  checks := checks + 1;

  -- 3. No lat/lng on grid_result. Coordinates regenerate from snapshot geometry + point_seq;
  --    storing them per row wastes ~240 MB/year at a quarter of the recorded portfolio.
  select count(*) into v_count from information_schema.columns
  where table_schema = 'public' and table_name = 'grid_result'
    and column_name in ('lat', 'lng', 'latitude', 'longitude');
  if v_count <> 0 then
    raise exception 'FAIL 3: grid_result carries % coordinate column(s) — the PRD copy of this table was implemented instead of the storage spec''s', v_count;
  end if;
  checks := checks + 1;

  -- 4. A row routes into the partition its scan_month names.
  insert into scan_snapshot (submarket_id, keyword_id, grid_radius_miles, grid_spacing_miles,
                             point_count, expected_points, actual_points, complete,
                             geometry_version, scanned_at)
  values (v_submarket, v_keyword, 5, 1, 81, 81, 81, true, 'test', now())
  returning id into v_snapshot;

  insert into grid_result (snapshot_id, scan_month, point_seq, place_id, rank)
  values (v_snapshot, v_month, 0, 'ChIJtest', 3);

  v_part := month_partition_name('grid_result', v_month);
  execute format('select count(*) from only %I where snapshot_id = %L', v_part, v_snapshot)
    into v_count;
  if v_count <> 1 then
    raise exception 'FAIL 4: row did not route into % (found %)', v_part, v_count;
  end if;
  checks := checks + 1;

  -- 5. A row for a month with no partition RAISES rather than being absorbed.
  begin
    insert into grid_result (snapshot_id, scan_month, point_seq, place_id, rank)
    values (v_snapshot, (current_date + interval '5 years')::date, 1, 'ChIJfuture', 1);
    raise exception 'FAIL 5: an insert for an uncovered month succeeded — a default partition must have been added';
  exception
    when check_violation then null;   -- "no partition of relation ... found for row"
  end;
  checks := checks + 1;

  -- 6. verify_grid_result_months catches a scan_month that disagrees with its snapshot.
  --    Nothing in the database forces the two to agree, and a writer that computes the month from
  --    now() instead of the snapshot splits one snapshot across two partitions — which would then
  --    make the retention job's per-snapshot reconciliation blame the ROLLUP for a partial count.
  select count(*) into v_count from verify_grid_result_months() where snapshot_id = v_snapshot;
  if v_count <> 0 then
    raise exception 'FAIL 6a: a correctly-monthed row was reported as mismatched';
  end if;

  update scan_snapshot set scanned_at = now() - interval '3 months' where id = v_snapshot;
  select count(*) into v_count from verify_grid_result_months() where snapshot_id = v_snapshot;
  if v_count <> 1 then
    raise exception 'FAIL 6b: a mismatched scan_month was NOT reported';
  end if;
  update scan_snapshot set scanned_at = now() where id = v_snapshot;
  checks := checks + 1;

  -- 7. create_month_partitions is idempotent — a second run creates nothing.
  if create_month_partitions(2) <> 0 then
    raise exception 'FAIL 7: create_month_partitions created partitions on a second run';
  end if;
  checks := checks + 1;

  -- 8. An EMPTY cold partition is dropped.
  execute format(
    'create table %I partition of grid_result for values from (%L) to (%L)',
    month_partition_name('grid_result', v_old_month), v_old_month,
    (v_old_month + interval '1 month')::date
  );
  v_dropped := drop_cold_partitions(90);
  if to_regclass('public.' || month_partition_name('grid_result', v_old_month)) is not null then
    raise exception 'FAIL 8: an empty cold partition was not dropped';
  end if;
  checks := checks + 1;

  -- 9. A cold partition WITH data is RETAINED, because the rollup does not exist.
  --    This is the whole fail-closed posture: prospect_coverage has no writer yet, so the guard
  --    can never be satisfied and nothing is ever dropped. Retaining a partition too long costs
  --    disk; dropping one whose evidence could not be verified costs a dispatched claim with
  --    nothing behind it.
  execute format(
    'create table %I partition of grid_result for values from (%L) to (%L)',
    month_partition_name('grid_result', v_old_month), v_old_month,
    (v_old_month + interval '1 month')::date
  );
  insert into scan_snapshot (submarket_id, keyword_id, grid_radius_miles, grid_spacing_miles,
                             point_count, expected_points, actual_points, complete,
                             geometry_version, scanned_at)
  values (v_submarket, v_keyword, 5, 1, 81, 81, 81, true, 'test', v_old_month)
  returning id into v_old_snap;
  insert into grid_result (snapshot_id, scan_month, point_seq, place_id, rank)
  values (v_old_snap, v_old_month, 0, 'ChIJcold', 5);

  v_dropped := drop_cold_partitions(90);
  if to_regclass('public.' || month_partition_name('grid_result', v_old_month)) is null then
    raise exception 'FAIL 9: a cold partition with unverifiable snapshots WAS DROPPED';
  end if;
  checks := checks + 1;

  -- 10. …and it said why, durably.
  --
  --     Ordered by `id`, NOT by `ran_at`. `now()` is TRANSACTION time in Postgres, so every log
  --     row written inside this script shares one timestamp and `order by ran_at desc limit 1`
  --     returns an arbitrary one — which made this check read a stale reason and blame the wrong
  --     guard. Same trap tests/lead_crm_rls.sql records for stage_changed_at; it is worth
  --     assuming any in-transaction ordering by now() is wrong.
  --
  --     A job that retains silently is indistinguishable from one that never ran (ISSUES I-034),
  --     so the reason must be durable and must name the guard that actually blocked.
  select reason into v_reason from storage_retention_log
  where partition_name = month_partition_name('grid_result', v_old_month)
    and outcome = 'retained'
  order by id desc limit 1;
  if v_reason is null then
    raise exception 'FAIL 10: the partition was retained with no logged reason';
  end if;
  if v_reason not like '%rollup%' then
    raise exception 'FAIL 10: retention reason does not name the missing rollup: %', v_reason;
  end if;
  checks := checks + 1;

  -- 11. With a rollup present, the NEXT guard stops it — audit_asset does not exist, so citation
  --     cannot be checked. Each guard must block independently; satisfying one must not let a
  --     partition through the others.
  if v_prospect is not null then
    insert into prospect_coverage (prospect_id, snapshot_id, coverage_pct, points_present,
                                   live_points, rank_vector)
    values (v_prospect, v_old_snap, 100.00, 1, 1, '\x01'::bytea);

    v_dropped := drop_cold_partitions(90);
    if to_regclass('public.' || month_partition_name('grid_result', v_old_month)) is null then
      raise exception 'FAIL 11: partition dropped with audit_asset absent — citation was never checked';
    end if;

    select reason into v_reason from storage_retention_log
    where partition_name = month_partition_name('grid_result', v_old_month)
      and outcome = 'retained'
    order by id desc limit 1;
    if v_reason not like '%audit_asset%' then
      raise exception 'FAIL 11: expected the audit_asset guard to be the blocker, got: %', v_reason;
    end if;
    checks := checks + 1;

    -- 12. A rollup claiming more coverage than the raw data supports blocks the drop.
    --     After the partition is gone this is unfalsifiable, so it must be caught before.
    update prospect_coverage set points_present = 99
    where snapshot_id = v_old_snap and prospect_id = v_prospect;
    v_dropped := drop_cold_partitions(90);
    select reason into v_reason from storage_retention_log
    where partition_name = month_partition_name('grid_result', v_old_month)
      and outcome = 'retained'
    order by id desc limit 1;
    if v_reason not like '%reconciliation%' then
      raise exception 'FAIL 12: an over-claiming rollup did not fail reconciliation, got: %', v_reason;
    end if;
    checks := checks + 1;
  end if;

  -- 13. grid_result_all spans both tables.
  insert into grid_result_retained (snapshot_id, scan_month, point_seq, place_id, rank)
  values (v_snapshot, v_month, 7, 'ChIJretained', 2);
  select count(*) into v_count from grid_result_all
  where snapshot_id = v_snapshot and place_id in ('ChIJtest', 'ChIJretained');
  if v_count <> 2 then
    raise exception 'FAIL 13: grid_result_all returned % of 2 rows across live + retained', v_count;
  end if;
  checks := checks + 1;

  -- 14. Service role only. Supabase grants ALL on new public objects to anon/authenticated by
  --     DEFAULT, so a missing revoke does not fail closed — it publishes the table.
  select count(*) into v_count
  from information_schema.role_table_grants
  where table_schema = 'public'
    and table_name in ('grid_result', 'grid_result_retained', 'serp_result', 'scan_snapshot',
                       'prospect_coverage', 'storage_retention_log', 'grid_result_all')
    and grantee in ('anon', 'authenticated');
  if v_count <> 0 then
    raise exception 'FAIL 14: % grant(s) to anon/authenticated remain on the storage tables', v_count;
  end if;
  checks := checks + 1;

  raise exception 'ROLLBACK — % checks passed', checks;
end $$;
