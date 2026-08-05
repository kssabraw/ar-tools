-- Verification for the coverage rollup (migration 20260805120000).
--
-- Run against the Outreacher project with the service role. The whole script executes inside a DO
-- block that ALWAYS raises at the end, so every snapshot, task, grid row, coverage row and mask
-- change is rolled back. A passing run reports:
--
--     ERROR:  ROLLBACK — 18 checks passed
--
-- An ERROR that says anything else is a real failure. Same shape as tests/storage_partitioning.sql
-- and tests/lead_crm_rls.sql.
--
-- WHY A LIVE SCRIPT RATHER THAN UNIT TESTS. The rollup is one plpgsql function because
-- `rank_vector` must be written in the same transaction as the summary statistics, and PostgREST
-- gives one transaction per call. Transactionality, byte packing, mask transitions and the
-- interaction with `finalize_snapshot_rollup()` are properties of Postgres and of this schema; a
-- Python mock of them would only assert that the mock behaves as written. The pure half — geometry
-- payload, vector decoding, reconciliation — is unit-tested in api/tests/test_coverage_rollup.py.

do $$
declare
  checks      integer := 0;
  v_submarket uuid;
  v_submarket_b uuid;
  v_keyword   uuid;
  v_prospect_a uuid;  v_place_a text;
  v_prospect_b uuid;  v_place_b text;
  v_prospect_c uuid;
  v_deficit   numeric;
  v_snapshot  uuid;
  v_snap2     uuid;
  v_json      jsonb;
  v_count     bigint;
  v_vector    bytea;
  v_pct       numeric;
  v_live      smallint;
  v_land      boolean;
  v_nulls     smallint;
  v_reason    text;
  v_month     date := date_trunc('month', current_date)::date;
  v_old_month date := (date_trunc('month', current_date) - interval '8 months')::date;
  v_part      text;
  -- Four points, so the expectations can be written out by hand rather than computed. The real
  -- grid is 81; nothing here depends on the count, only on the payload matching the snapshot.
  v_points    jsonb := '[{"seq":0,"dist":0.0},{"seq":1,"dist":1.0},
                         {"seq":2,"dist":2.0},{"seq":3,"dist":3.0}]'::jsonb;
begin
  -- The submarket is chosen FROM the prospects rather than independently. The placeholder-score
  -- view joins prospects to snapshots through submarket_id, so a submarket picked at random would
  -- share no rows with the prospects and checks 15-16 would pass by returning nothing.
  select submarket_id into v_submarket
    from prospect where submarket_id is not null
   group by submarket_id having count(*) >= 3 limit 1;
  select id into v_submarket_b from submarket where id <> v_submarket limit 1;
  select id into v_keyword   from keyword   limit 1;
  select id, place_id into v_prospect_a, v_place_a
    from prospect where submarket_id = v_submarket order by id limit 1;
  select id, place_id into v_prospect_b, v_place_b
    from prospect where submarket_id = v_submarket order by id offset 1 limit 1;
  select id into v_prospect_c
    from prospect where submarket_id = v_submarket order by id offset 2 limit 1;
  if v_submarket is null or v_keyword is null or v_prospect_c is null then
    raise exception 'FAIL: need a submarket with >= 3 prospects — run `run_market seed` + ingest first';
  end if;

  -- 1. grid_point_status exists with the PRD's shape (PRD §10, START-HERE §3a names the PRD as
  --    its owner — this table is the one object here NOT owned by the storage spec).
  select count(*) into v_count from information_schema.columns
   where table_schema = 'public' and table_name = 'grid_point_status'
     and column_name in ('submarket_id','point_seq','land','consecutive_null_scans',
                         'last_evaluated_at');
  if v_count <> 5 then
    raise exception 'FAIL 1: grid_point_status has % of the 5 PRD columns', v_count;
  end if;
  checks := checks + 1;

  -- ------------------------------------------------------------------------------------------
  -- The fixture: four points, three of them measured.
  --
  --   point 0  collected, prospect A at rank 1
  --   point 1  collected, EMPTY pack — measured, found nothing
  --   point 2  collected, prospect B at rank 5
  --   point 3  NOT collected (task failed) — never measured
  -- ------------------------------------------------------------------------------------------
  insert into scan_snapshot (submarket_id, keyword_id, grid_radius_miles, grid_spacing_miles,
                             point_count, expected_points, actual_points, complete,
                             geometry_version, scanned_at)
  values (v_submarket, v_keyword, 5, 1, 4, 4, 3, true, 'test-v1', now() - interval '3 hours')
  returning id into v_snapshot;

  insert into scan_task (snapshot_id, point_seq, status, result_count) values
    (v_snapshot, 0, 'collected', 1),
    (v_snapshot, 1, 'collected', 0),
    (v_snapshot, 2, 'collected', 1),
    (v_snapshot, 3, 'failed',    null);

  insert into grid_result (snapshot_id, scan_month, point_seq, place_id, rank) values
    (v_snapshot, v_month, 0, v_place_a, 1),
    (v_snapshot, v_month, 2, v_place_b, 5);

  select rollup_snapshot_coverage(v_snapshot, 'test-v1', v_points, 3) into v_json;

  -- 2. One row per PROSPECT present in the snapshot — exactly the set finalize_snapshot_rollup()
  --    reconciles against with `<>`. Fewer is the partial rollup I-069 exists to catch; more
  --    (pre-seeding absent prospects at zero coverage) would raise just as hard.
  select count(*) into v_count from prospect_coverage where snapshot_id = v_snapshot;
  if v_count <> 2 then
    raise exception 'FAIL 2: expected 2 coverage rows, got % — payload %', v_count, v_json;
  end if;
  checks := checks + 1;

  -- 3. The completion marker exists and was written by the finalizer, in this same transaction.
  select count(*) into v_count from snapshot_rollup
   where snapshot_id = v_snapshot and prospect_count = 2 and point_count = 2;
  if v_count <> 1 then
    raise exception 'FAIL 3: no reconciled snapshot_rollup marker (prospect_count 2, point_count 2)';
  end if;
  checks := checks + 1;

  -- 4. THE VECTOR. One byte per grid point in point_seq order, and the encoding storage spec §4
  --    and reporting spec §4.2 both name: rank where present, 0 where measured and absent, 255
  --    where dead OR never scanned.
  --
  --    Prospect A: rank 1 at point 0, absent at 1 and 2, point 3 unmeasured -> \x010000ff.
  --    This is the check that catches a vector packed against the wrong geometry, which is the
  --    failure that renders every historical heatmap against coordinates never used to collect it.
  select rank_vector, coverage_pct, live_points into v_vector, v_pct, v_live
    from prospect_coverage where snapshot_id = v_snapshot and prospect_id = v_prospect_a;
  if v_vector <> '\x010000ff'::bytea then
    raise exception 'FAIL 4a: prospect A vector is %, expected \x010000ff', encode(v_vector, 'hex');
  end if;
  if length(v_vector) <> 4 then
    raise exception 'FAIL 4b: vector is % bytes, snapshot expects 4 points', length(v_vector);
  end if;
  checks := checks + 1;

  -- 5. The DENOMINATOR counts what was MEASURED, never what was FOUND.
  --
  --    Point 1 returned nothing and stays in: "nobody ranks here" is a finding, and the strongest
  --    one in a grid. Point 3 was never collected and leaves entirely: an uncollected task is not
  --    evidence of an absence anybody observed. So live_points = 3, not 4 and not 2, and A's
  --    coverage is 1/3 rather than 1/4 or 1/2.
  if v_live <> 3 then
    raise exception 'FAIL 5a: live_points is %, expected 3 (measured, minus nothing masked)', v_live;
  end if;
  if v_pct <> 33.33 then
    raise exception 'FAIL 5b: coverage_pct is %, expected 33.33', v_pct;
  end if;
  checks := checks + 1;

  -- 6. centroid_dist_at_loss — the nearest live point at which the prospect is absent, null when
  --    they hold every live point. A is absent at points 1 and 2, so 1.00.
  select centroid_dist_at_loss into v_pct
    from prospect_coverage where snapshot_id = v_snapshot and prospect_id = v_prospect_a;
  if v_pct <> 1.00 then
    raise exception 'FAIL 6: centroid_dist_at_loss is %, expected 1.00', v_pct;
  end if;
  checks := checks + 1;

  -- 7. Idempotent by REFUSAL. A second call finds the marker and does nothing — it does not
  --    rewrite rows, and it does not increment the mask a second time for the same evidence.
  select consecutive_null_scans into v_nulls
    from grid_point_status where submarket_id = v_submarket and point_seq = 1;
  select rollup_snapshot_coverage(v_snapshot, 'test-v1', v_points, 3) into v_json;
  if v_json->>'status' <> 'already_rolled_up' then
    raise exception 'FAIL 7a: a second rollup returned %', v_json;
  end if;
  select count(*) into v_count from prospect_coverage where snapshot_id = v_snapshot;
  if v_count <> 2 then
    raise exception 'FAIL 7b: a second rollup changed the row count to %', v_count;
  end if;
  select count(*) into v_count from grid_point_status
   where submarket_id = v_submarket and point_seq = 1 and consecutive_null_scans = v_nulls;
  if v_count <> 1 then
    raise exception 'FAIL 7c: a second rollup incremented the null counter again';
  end if;
  checks := checks + 1;

  -- 8. REFUSALS. Each one is a way to produce a vector that looks right and is not.
  -- These three statements sit OUTSIDE the sub-block on purpose. A `begin ... exception` block is
  -- a savepoint, so anything done inside it is undone when the expected error fires — the marker
  -- would come back and every refusal below would return `already_rolled_up` instead of raising.
  delete from snapshot_rollup   where snapshot_id = v_snapshot;
  delete from prospect_coverage where snapshot_id = v_snapshot;
  update scan_snapshot set complete = false where id = v_snapshot;

  begin
    perform rollup_snapshot_coverage(v_snapshot, 'test-v1', v_points, 3);
    raise exception 'FAIL 8a: an INCOMPLETE snapshot was rolled up — PRD §9a.3 excludes it';
  exception when others then
    if sqlerrm like 'FAIL 8a%' then raise; end if;
    if sqlerrm not like '%incomplete%' then
      raise exception 'FAIL 8a: wrong error for an incomplete snapshot: %', sqlerrm;
    end if;
  end;

  update scan_snapshot set complete = true where id = v_snapshot;

  begin
    perform rollup_snapshot_coverage(v_snapshot, 'v1', v_points, 3);
    raise exception 'FAIL 8b: a geometry-version MISMATCH was accepted — history would be re-mapped';
  exception when others then
    if sqlerrm like 'FAIL 8b%' then raise; end if;
    if sqlerrm not like '%version mismatch%' then
      raise exception 'FAIL 8b: wrong error for a version mismatch: %', sqlerrm;
    end if;
  end;

  begin
    perform rollup_snapshot_coverage(
      v_snapshot, 'test-v1', '[{"seq":0,"dist":0.0},{"seq":1,"dist":1.0}]'::jsonb, 3);
    raise exception 'FAIL 8c: a payload with the wrong POINT COUNT was accepted';
  exception when others then
    if sqlerrm like 'FAIL 8c%' then raise; end if;
    if sqlerrm not like '%points, snapshot%' then
      raise exception 'FAIL 8c: wrong error for a short payload: %', sqlerrm;
    end if;
  end;

  begin
    -- Right count, wrong membership: point 2 missing, point 9 invented. Every byte after the gap
    -- would land at the wrong offset, and the vector would still be exactly the right length.
    perform rollup_snapshot_coverage(
      v_snapshot, 'test-v1',
      '[{"seq":0,"dist":0.0},{"seq":1,"dist":1.0},{"seq":9,"dist":2.0},{"seq":3,"dist":3.0}]'::jsonb,
      3);
    raise exception 'FAIL 8d: a payload that does not cover 0..n-1 was accepted';
  exception when others then
    if sqlerrm like 'FAIL 8d%' then raise; end if;
    if sqlerrm not like '%does not cover point_seq%' then
      raise exception 'FAIL 8d: wrong error for a mis-membered payload: %', sqlerrm;
    end if;
  end;
  checks := checks + 1;

  -- Restore the fixture the refusals were run against.
  perform rollup_snapshot_coverage(v_snapshot, 'test-v1', v_points, 3);

  -- 9. ATOMICITY. A rollup that cannot finish writes NOTHING — no coverage rows, no marker, and
  --    no mask increment. This is the property the whole one-transaction design exists for: the
  --    alternative is summary numbers with no vectors behind them, which look healthy forever.
  insert into scan_snapshot (submarket_id, keyword_id, grid_radius_miles, grid_spacing_miles,
                             point_count, expected_points, actual_points, complete,
                             geometry_version, scanned_at)
  values (v_submarket, v_keyword, 5, 1, 4, 4, 4, true, 'test-v1', now() - interval '2 hours')
  returning id into v_snap2;
  insert into scan_task (snapshot_id, point_seq, status, result_count) values
    (v_snap2, 0, 'collected', 1), (v_snap2, 1, 'collected', 0),
    (v_snap2, 2, 'collected', 0), (v_snap2, 3, 'collected', 0);
  -- A business that is not one of our prospects — which is most of a grid.
  insert into grid_result (snapshot_id, scan_month, point_seq, place_id, rank)
  values (v_snap2, v_month, 0, 'ChIJ-not-a-prospect-fixture', 1);

  select consecutive_null_scans into v_nulls
    from grid_point_status where submarket_id = v_submarket and point_seq = 1;
  begin
    perform rollup_snapshot_coverage(v_snap2, 'test-v1', v_points, 3);
    raise exception 'FAIL 9a: a snapshot matching NO prospects was rolled up';
  exception when others then
    if sqlerrm like 'FAIL 9a%' then raise; end if;
    if sqlerrm not like '%no known prospects%' then
      raise exception 'FAIL 9a: wrong error for a prospect-less snapshot: %', sqlerrm;
    end if;
  end;

  select count(*) into v_count from prospect_coverage where snapshot_id = v_snap2;
  if v_count <> 0 then
    raise exception 'FAIL 9b: an aborted rollup left % coverage row(s) behind', v_count;
  end if;
  select count(*) into v_count from snapshot_rollup where snapshot_id = v_snap2;
  if v_count <> 0 then
    raise exception 'FAIL 9c: an aborted rollup left a completion marker';
  end if;
  select count(*) into v_count from grid_point_status
   where submarket_id = v_submarket and point_seq = 1 and consecutive_null_scans = v_nulls;
  if v_count <> 1 then
    raise exception 'FAIL 9d: an aborted rollup kept its mask increment — the denominator moved '
                    'for a claim that was never written';
  end if;
  checks := checks + 1;

  -- 10. Results at a point whose task never reached `collected`. The collector writes rows first
  --     and marks the task second, deliberately, so a crash in that window leaves exactly this
  --     shape. Rolling it up would pack the byte as 255 and lose the rank silently.
  update grid_result set place_id = v_place_a
   where snapshot_id = v_snap2 and point_seq = 0;
  update scan_task set status = 'failed' where snapshot_id = v_snap2 and point_seq = 0;
  begin
    perform rollup_snapshot_coverage(v_snap2, 'test-v1', v_points, 3);
    raise exception 'FAIL 10: results at an uncollected point were rolled up';
  exception when others then
    if sqlerrm like 'FAIL 10%' then raise; end if;
    if sqlerrm not like '%not live%' then
      raise exception 'FAIL 10: wrong error for results at an uncollected point: %', sqlerrm;
    end if;
  end;
  checks := checks + 1;

  -- 11. LAND MASKING. The counter is seeded to one short of the threshold — three consecutive
  --     null scans is three snapshots, and the transition is what is under test, not the counting.
  update scan_task set status = 'collected' where snapshot_id = v_snap2 and point_seq = 0;
  update grid_point_status set consecutive_null_scans = 2, land = true
   where submarket_id = v_submarket and point_seq = 1;

  select rollup_snapshot_coverage(v_snap2, 'test-v1', v_points, 3) into v_json;

  select land, consecutive_null_scans into v_land, v_nulls
    from grid_point_status where submarket_id = v_submarket and point_seq = 1;
  if v_land or v_nulls <> 3 then
    raise exception 'FAIL 11a: point 1 should be masked at 3 consecutive nulls, got land=% nulls=%',
      v_land, v_nulls;
  end if;

  -- …and it leaves the DENOMINATOR, not the geometry. All four points are collected on this
  -- snapshot, so measured = 4; point 1 is now masked, so live_points = 3. The point itself stays
  -- in the grid and in the vector — geometry is immutable.
  select live_points, coverage_pct into v_live, v_pct
    from prospect_coverage where snapshot_id = v_snap2 and prospect_id = v_prospect_a;
  if v_live <> 3 then
    raise exception 'FAIL 11b: live_points is % — a masked point did not leave the denominator', v_live;
  end if;
  -- The masked point renders as dead (255), NOT as "not found" (0). Conflating them overstates
  -- pain, and it is the kind of error a prospect can catch.
  select rank_vector into v_vector
    from prospect_coverage where snapshot_id = v_snap2 and prospect_id = v_prospect_a;
  if get_byte(v_vector, 1) <> 255 then
    raise exception 'FAIL 11c: masked point 1 packed as %, expected 255', get_byte(v_vector, 1);
  end if;
  checks := checks + 1;

  -- 12. REACTIVATION on any non-null result. Business density changes; coastlines do not.
  insert into scan_snapshot (submarket_id, keyword_id, grid_radius_miles, grid_spacing_miles,
                             point_count, expected_points, actual_points, complete,
                             geometry_version, scanned_at)
  values (v_submarket, v_keyword, 5, 1, 4, 4, 4, true, 'test-v1', now() - interval '1 hour')
  returning id into v_snap2;
  insert into scan_task (snapshot_id, point_seq, status, result_count) values
    (v_snap2, 0, 'collected', 1), (v_snap2, 1, 'collected', 1),
    (v_snap2, 2, 'collected', 0), (v_snap2, 3, 'collected', 0);
  insert into grid_result (snapshot_id, scan_month, point_seq, place_id, rank) values
    (v_snap2, v_month, 0, v_place_a, 2),
    (v_snap2, v_month, 1, v_place_a, 7);

  perform rollup_snapshot_coverage(v_snap2, 'test-v1', v_points, 3);

  select land, consecutive_null_scans into v_land, v_nulls
    from grid_point_status where submarket_id = v_submarket and point_seq = 1;
  if not v_land or v_nulls <> 0 then
    raise exception 'FAIL 12: a point that returned results was not reactivated (land=% nulls=%)',
      v_land, v_nulls;
  end if;
  checks := checks + 1;

  -- 13. DUPLICATE grid rows do not double-count. There is no unique constraint on
  --     (snapshot_id, point_seq, place_id), and the collector's write-then-mark ordering can
  --     legitimately produce duplicates after a crash — re-collecting is free, losing a paid task
  --     is not. Two rows for one prospect at one point is still ONE point of presence.
  select points_present into v_live
    from prospect_coverage where snapshot_id = v_snap2 and prospect_id = v_prospect_a;
  -- Deleting the marker to force a re-roll is deliberately doing what production cannot: the
  -- marker is what makes the rollup idempotent by refusal (check 7). Re-running this way also
  -- re-increments the null counters, which is why nothing below asserts on them.
  delete from snapshot_rollup where snapshot_id = v_snap2;
  delete from prospect_coverage where snapshot_id = v_snap2;
  insert into grid_result (snapshot_id, scan_month, point_seq, place_id, rank)
  values (v_snap2, v_month, 0, v_place_a, 2);
  perform rollup_snapshot_coverage(v_snap2, 'test-v1', v_points, 3);
  select points_present into v_nulls
    from prospect_coverage where snapshot_id = v_snap2 and prospect_id = v_prospect_a;
  if v_nulls <> v_live then
    raise exception 'FAIL 13: a duplicated grid row changed points_present from % to %',
      v_live, v_nulls;
  end if;
  checks := checks + 1;

  -- 14. Service role only. Supabase grants ALL on new public objects to anon/authenticated by
  --     DEFAULT, so a missing revoke does not fail closed — it publishes the table.
  select count(*) into v_count
    from information_schema.role_table_grants
   where table_schema = 'public' and table_name = 'grid_point_status'
     and grantee in ('anon', 'authenticated');
  if v_count <> 0 then
    raise exception 'FAIL 14a: % grant(s) to anon/authenticated remain on grid_point_status', v_count;
  end if;
  select count(*) into v_count
    from information_schema.role_routine_grants
   where routine_schema = 'public' and routine_name = 'rollup_snapshot_coverage'
     and grantee in ('anon', 'authenticated', 'PUBLIC');
  if v_count <> 0 then
    raise exception 'FAIL 14b: rollup_snapshot_coverage is executable by anon/authenticated/public';
  end if;
  checks := checks + 1;

  -- The placeholder-score checks run BEFORE the retention check, which backdates a snapshot and
  -- relocates its rows. Order matters here in a way it does not elsewhere in this script.
  --
  -- 15. THE PLACEHOLDER SCORE — a prospect with NO coverage row scores maximum deficit.
  --
  -- ISSUES I-076: the rollup writes a row only for prospects that appeared somewhere, so the
  -- prospect invisible at every single grid point has no row at all. That prospect is the most
  -- painful one in the market and the best pitch in it, and an inner join would silently omit
  -- exactly them. This is the check that fails if anyone "tidies" the LEFT JOIN away.
  select coverage_deficit, keywords_present into v_deficit, v_live
    from v_prospect_placeholder_score where prospect_id = v_prospect_c;
  if v_deficit is null then
    raise exception 'FAIL 15a: a prospect with no coverage row is MISSING from the placeholder '
                    'score — the most invisible prospect in the market has been dropped (I-076)';
  end if;
  if v_deficit <> 100.00 or v_live <> 0 then
    raise exception 'FAIL 15b: a prospect absent from every point scored deficit % (present %), '
                    'expected 100.00 (0)', v_deficit, v_live;
  end if;
  -- …and a prospect that DOES rank scores less than maximum, or the view is returning a constant.
  select coverage_deficit into v_deficit
    from v_prospect_placeholder_score where prospect_id = v_prospect_a;
  if v_deficit is null or v_deficit >= 100.00 then
    raise exception 'FAIL 15c: a ranking prospect scored deficit %, expected below 100', v_deficit;
  end if;
  checks := checks + 1;

  -- 16. An UNROLLED submarket produces no rows at all — it must not read as maximum deficit.
  --
  -- The gate is the completion marker, not `complete` and not "a snapshot exists". An incomplete
  -- snapshot has no coverage rows (the rollup refuses it), so gating on existence would score
  -- every prospect in that submarket at 100% deficit — maximum pain — purely because the scan
  -- failed. Manufacturing pain out of a provider failure is the exact error DECISIONS.md records
  -- three times over.
  insert into scan_snapshot (submarket_id, keyword_id, grid_radius_miles, grid_spacing_miles,
                             point_count, expected_points, actual_points, complete,
                             geometry_version, scanned_at)
  values (v_submarket_b, v_keyword, 5, 1, 4, 4, 1, false, 'test-v1', now());
  select count(*) into v_count
    from v_prospect_placeholder_score s
    join prospect p on p.id = s.prospect_id
   where p.submarket_id = v_submarket_b;
  if v_count <> 0 then
    raise exception 'FAIL 16: an unrolled submarket produced % placeholder rows — a failed scan '
                    'is being scored as total invisibility', v_count;
  end if;
  checks := checks + 1;

  -- 17. The snapshot carries the CENTRE it was generated from (ISSUES I-078).
  --
  -- Nullable on purpose — a stale writer must not fail a snapshot insert on a bookkeeping column
  -- — so this checks the columns exist and are writable, not that they are populated. The writer
  -- half is asserted in api/tests/test_scan_runner.py, where it can be tested without a scan.
  select count(*) into v_count from information_schema.columns
   where table_schema = 'public' and table_name = 'scan_snapshot'
     and column_name in ('center_lat', 'center_lng');
  if v_count <> 2 then
    raise exception 'FAIL 17: scan_snapshot has % of the 2 centre columns — Phase 3 would have to '
                    'read the mutable submarket instead (I-078)', v_count;
  end if;
  checks := checks + 1;

  -- 18. The retention job gets PAST the rollup guard now.
  --
  --     Before this migration, `drop_cold_partitions` retained every non-empty partition with
  --     "snapshot(s) have no finalized rollup" and dropped nothing but empties. With a finalized
  --     rollup it moves on to the next guard — which still refuses, because `audit_asset` and
  --     `slot` do not exist yet, and a partition whose citations cannot be checked must never be
  --     dropped. Progress here is the REASON changing, not a partition disappearing.
  v_part := month_partition_name('grid_result', v_old_month);
  if to_regclass('public.' || v_part) is null then
    execute format('create table %I partition of grid_result for values from (%L) to (%L)',
                   v_part, v_old_month, (v_old_month + interval '1 month')::date);
  end if;
  update scan_snapshot set scanned_at = v_old_month where id = v_snapshot;
  update grid_result set scan_month = v_old_month where snapshot_id = v_snapshot;

  perform drop_cold_partitions(90);
  select reason into v_reason from storage_retention_log
   where partition_name = v_part order by ran_at desc limit 1;
  if v_reason like '%no finalized rollup%' then
    raise exception 'FAIL 18: the partition is still blocked on the rollup guard: %', v_reason;
  end if;
  if v_reason is null then
    raise exception 'FAIL 18: drop_cold_partitions logged nothing for %', v_part;
  end if;
  checks := checks + 1;

  raise exception 'ROLLBACK — % checks passed', checks;
end $$;
