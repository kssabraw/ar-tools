-- =============================================================================
-- first-scan-verify.sql — read the first live geogrid scan
--
-- Paste into the Supabase SQL editor for the **Outreacher** project, or run
-- through the MCP `execute_sql` tool. Reads only; writes nothing.
--
-- HANDOFF §11 closing line: "the thing to check is not 'did it succeed'". A run
-- that posts nothing and collects nothing reports clean, because there is
-- nothing to report. Every check below is written to distinguish *nothing
-- happened* from *it worked*.
--
-- Run it TWICE:
--   • after `scan`    — checks 1–3 only. Everything after needs a collector tick.
--   • after `collect` — all of it.
--
-- Checks 4, 6 and 8 are assertions: a non-empty result is a defect. The rest are
-- observations, because a first run's expected values are not all knowable in
-- advance — each carries what you want to see.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. The snapshot. WANT: one row, expected_points = 81, center_lat/lng non-null.
--
-- `complete` is false and `actual_points` is 0 until the collector finalizes —
-- that is the insert-time state (scan_runner writes 0/false), not a failure.
-- A null centre means the writer did not populate it and I-078's tightening to
-- NOT NULL must wait; that is the fact this run exists to establish.
-- -----------------------------------------------------------------------------
select 'CHECK 1 — snapshot' as check,
       s.id as snapshot_id, sm.name as submarket, k.term as keyword,
       s.expected_points, s.actual_points, s.complete,
       s.geometry_version, s.grid_radius_miles, s.grid_spacing_miles,
       s.center_lat, s.center_lng,
       s.trigger_reason, s.scanned_at
  from scan_snapshot s
  join submarket sm on sm.id = s.submarket_id
  join keyword   k  on k.id  = s.keyword_id
 order by s.scanned_at desc;


-- -----------------------------------------------------------------------------
-- 2. Task lifecycle. WANT after `scan`: 81 submitted, 0 pending.
--                   WANT after `collect`: 81 collected, 0 pending, 0 submitted.
--
-- A `pending` row is a point whose post never returned — unpaid and safe to
-- repost. A `submitted` row that never reaches `collected` is the expensive
-- one: the provider billed for it. Past ~3 days it has aged off `tasks_ready`
-- and only the fallback-by-id path can reach it, for 30 days total (PRD §B2).
-- -----------------------------------------------------------------------------
select 'CHECK 2 — task lifecycle' as check,
       t.status, count(*) as tasks,
       min(t.submitted_at) as first_submitted,
       max(t.collected_at) as last_collected,
       sum(t.attempts)     as total_attempts,
       count(*) filter (where t.provider_task_id is null) as no_provider_id,
       count(*) filter (where t.last_error is not null)   as with_error
  from scan_task t
 group by t.status
 order by t.status;


-- -----------------------------------------------------------------------------
-- 3. Anything stuck, with its age. WANT: no rows.
--
-- Ordered by age because the deadlines are real: ~3 days off `tasks_ready`,
-- ~5 days is the alert threshold, 30 days and the paid result is gone.
-- -----------------------------------------------------------------------------
select 'CHECK 3 — stuck tasks' as check,
       t.point_seq, t.status, t.provider_task_id,
       t.attempts, t.last_error,
       round(extract(epoch from now() - t.submitted_at) / 86400.0, 2) as days_since_submit
  from scan_task t
 where t.status in ('pending', 'submitted')
 order by t.submitted_at nulls first;


-- -----------------------------------------------------------------------------
-- 4. ASSERTION — one snapshot must not straddle two partitions. WANT: no rows.
--
-- ISSUES I-044: `scan_month` derived from the clock instead of the snapshot
-- splits one snapshot across two monthly partitions, and the retention job
-- surfaces it months later blaming the rollup. `assert_snapshot_month()` guards
-- this at finalization; this is the independent read of the same fact.
-- -----------------------------------------------------------------------------
select 'CHECK 4 — month straddle (want no rows)' as check,
       g.snapshot_id, count(distinct g.scan_month) as distinct_months,
       array_agg(distinct g.scan_month) as months
  from grid_result g
 group by g.snapshot_id
having count(distinct g.scan_month) > 1;


-- -----------------------------------------------------------------------------
-- 5. Grid rows, and the empty-pack path. WANT: points_with_rows ≈ collected
--    tasks; result_count = 0 on some points is a FINDING, not a failure.
--
-- "Nobody ranks here" is data. `actual_points` counts points SCANNED, never
-- rows written (DECISIONS.md, corrected three times) — so an empty point still
-- counts toward completeness and still occupies the coverage denominator.
-- -----------------------------------------------------------------------------
select 'CHECK 5 — grid rows' as check,
       count(*)                                    as grid_rows,
       count(distinct g.point_seq)                 as points_with_rows,
       round(avg(per_point.n), 2)                  as avg_results_per_point,
       min(g.rank) as min_rank, max(g.rank) as max_rank,
       (select count(*) from scan_task t
         where t.status = 'collected' and t.result_count = 0) as points_returning_nothing
  from grid_result g
  join lateral (select count(*) as n from grid_result g2
                 where g2.snapshot_id = g.snapshot_id
                   and g2.point_seq  = g.point_seq) per_point on true;


-- -----------------------------------------------------------------------------
-- 6. ASSERTION — duplicate grid rows. WANT: no rows.
--
-- ISSUES I-077: `_collect_one` writes rows and THEN marks the task collected,
-- deliberately — a crash between them re-collects something free rather than
-- losing something paid. The cost is that the retry can double-write a point.
-- The rollup deduplicates with min(rank); nothing else that reads grid_result
-- knows to. If this returns rows, I-077 has fired for real and the
-- `on conflict do nothing` fix is no longer hypothetical.
-- -----------------------------------------------------------------------------
select 'CHECK 6 — duplicate grid rows (want no rows)' as check,
       g.snapshot_id, g.point_seq, g.place_id, count(*) as copies
  from grid_result g
 group by g.snapshot_id, g.point_seq, g.place_id
having count(*) > 1
 order by copies desc
 limit 50;


-- -----------------------------------------------------------------------------
-- 7. Completeness against the 0.98 threshold. WANT: ratio = 1.00, complete = t.
--
-- Below 0.98 the snapshot is excluded from scoring, delta and rollup — AND its
-- month partition can then never be dropped (ISSUES I-075, I-083). On a first
-- run that is one partition and bounded, but it is permanent, so read this row
-- deliberately rather than glancing at `complete`.
-- -----------------------------------------------------------------------------
select 'CHECK 7 — completeness' as check,
       s.id as snapshot_id, s.expected_points, s.actual_points,
       round(s.actual_points::numeric / nullif(s.expected_points, 0), 4) as ratio,
       s.complete,
       case when s.complete then 'rollup eligible'
            else 'EXCLUDED from scoring/delta/rollup — and pins its partition (I-075/I-083)'
       end as consequence
  from scan_snapshot s
 order by s.scanned_at desc;


-- -----------------------------------------------------------------------------
-- 8. ASSERTION — the rollup marker. WANT: exactly one row per complete
--    snapshot, once a collector tick has finalized it.
--
-- The marker is the completeness FACT the retention job reads (I-069). No
-- marker means `drop_cold_partitions` will never drop this month, and the
-- storage ceiling the whole partitioning policy exists to avoid arrives on
-- schedule while every run reports clean.
-- -----------------------------------------------------------------------------
select 'CHECK 8 — rollup marker' as check,
       s.id as snapshot_id, s.complete,
       r.snapshot_id is not null as has_marker,
       r.point_count, r.prospect_count, r.completed_at
  from scan_snapshot s
  left join snapshot_rollup r on r.snapshot_id = s.id
 order by s.scanned_at desc;


-- -----------------------------------------------------------------------------
-- 9. Land masking after one scan. WANT: rows exist with consecutive_null_scans
--    0 or 1, and NOTHING masked (land = true everywhere).
--
-- Masking needs `land_mask_null_scans` (3) consecutive nulls, so one scan
-- cannot mask anything. What this proves is that the counter is being written
-- at all. A masked point on run one would mean the threshold is not being read
-- from config.
-- -----------------------------------------------------------------------------
select 'CHECK 9 — land mask' as check,
       gps.land, count(*) as points,
       min(gps.consecutive_null_scans) as min_nulls,
       max(gps.consecutive_null_scans) as max_nulls,
       max(gps.last_evaluated_at)      as last_evaluated
  from grid_point_status gps
 group by gps.land;


-- -----------------------------------------------------------------------------
-- 10. Coverage rows. WANT: live_points equal across rows and = collected ∩ land;
--     coverage_pct = points_present / live_points.
--
-- `live_points` is stored contemporaneously and MUST NEVER be recomputed from
-- today's mask (storage spec §4) — this check reads it, it does not re-derive
-- it. The recompute-and-compare path is `rollup --verify`, which reads the
-- rank_vector rather than the mask.
-- -----------------------------------------------------------------------------
select 'CHECK 10 — coverage' as check,
       count(*)                          as prospects_with_rows,
       count(distinct pc.live_points)    as distinct_denominators,
       min(pc.live_points)               as live_points,
       round(avg(pc.coverage_pct), 2)    as avg_coverage_pct,
       max(pc.coverage_pct)              as best_coverage_pct,
       count(*) filter (where pc.centroid_dist_at_loss is null) as hold_every_live_point,
       round(avg(pc.centroid_dist_at_loss), 2) as avg_dist_at_loss,
       count(*) filter (where octet_length(pc.rank_vector) <> 81) as wrong_vector_length
  from prospect_coverage pc;


-- -----------------------------------------------------------------------------
-- 11. I-076 — the prospects with NO coverage row.
--
-- READ THIS ONE CAREFULLY. A prospect present at zero grid points gets no row,
-- so the worst-covered prospects are the ones missing here. Inside a submarket
-- carrying a rollup marker that is ZERO coverage, never "unknown". Outside one,
-- nothing was measured and there is no score to give.
--
-- The count below is the population the placeholder score must be scoring at
-- 100% deficit. If `v_prospect_placeholder_score` returns fewer rows than
-- `prospects_in_submarket`, the LEFT JOIN is not doing its job.
-- -----------------------------------------------------------------------------
select 'CHECK 11 — I-076 zero-coverage population' as check,
       sm.name as submarket,
       count(p.id)                        as prospects_in_submarket,
       count(pc.prospect_id)              as with_coverage_row,
       count(p.id) - count(pc.prospect_id) as zero_coverage_no_row
  from scan_snapshot s
  join submarket sm on sm.id = s.submarket_id
  join prospect  p  on p.submarket_id = sm.id
  left join prospect_coverage pc
         on pc.snapshot_id = s.id and pc.prospect_id = p.id
 group by sm.name;


-- -----------------------------------------------------------------------------
-- 12. The placeholder score, top of the list. WANT: one row per prospect in the
--     scanned submarket, deficit 100.00 for everyone absent everywhere.
-- -----------------------------------------------------------------------------
select 'CHECK 12 — placeholder score' as check, *
  from v_prospect_placeholder_score
 where excluded is not true
 order by coverage_deficit desc, best_rank nulls last
 limit 25;


-- -----------------------------------------------------------------------------
-- 13. HANDOFF §9 — the inferred-zero audit. This scan is the FIRST instrument
--     that can contradict the 105-prospect decision.
--
-- A few `contradicted` rows: the inference was wrong for those listings and
-- they have already self-corrected — the mechanism working. A LOT of them: the
-- vendor-convention claim is wrong and the flag should be withdrawn wholesale
-- (clear the boolean, never write 0). Never "fix" a row here by deleting it.
--
-- Expect zero rows if the geogrid response carries no review count — that is
-- itself the finding, and it means the audit still has no instrument.
-- -----------------------------------------------------------------------------
select 'CHECK 13 — inferred-zero audit' as check,
       a.verdict, count(*) as rows,
       min(a.observed_at) as first_seen, max(a.observed_at) as last_seen
  from review_inferred_zero_audit a
 group by a.verdict;

select 'CHECK 13b — flag still set' as check,
       count(*) filter (where p.review_count_inferred_zero) as still_flagged,
       count(*) filter (where p.review_count_inferred_zero
                          and p.review_count is not null)   as flagged_with_real_count
  from prospect p;


-- -----------------------------------------------------------------------------
-- 14. Cost. WANT — as of the first run — NO geogrid row, and that is a DEFECT,
--     not a pass. See ISSUES I-086.
--
-- `scan_runner` writes no `cost_ledger` row, so the geogrid is the one paid path
-- in the system that spends silently. Until I-086 is closed, reconcile this run
-- against the DataForSEO dashboard by hand and record the figure in HANDOFF.
-- -----------------------------------------------------------------------------
select 'CHECK 14 — cost ledger' as check,
       cl.stage, cl.provider, count(*) as rows,
       sum(cl.units) as units, sum(cl.cost_cents) as cost_cents,
       max(cl.recorded_at) as latest
  from cost_ledger cl
 group by cl.stage, cl.provider
 order by latest desc;
