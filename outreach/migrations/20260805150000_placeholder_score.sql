-- The placeholder score: raw geogrid coverage deficit. START-HERE §4 Phase 2, first item.
--
-- "Placeholder score = raw geogrid coverage deficit (one SQL expression). This belongs here, not
-- Phase 1 — it needs grid data to exist." It now can exist: the rollup writes `prospect_coverage`.
--
-- ---------------------------------------------------------------------------------------------
-- WHY THIS IS A VIEW AND NOT A ROW IN `prospect_score`
--
-- `prospect_score` is the Phase 4 MODEL's table, and its shape says so: `model in
-- ('reply','close','value')`, `pass in (1,2)`, a `channel`, a `predicted_prob`, a `decile`, and a
-- mandatory `score_run` carrying `model_version`, `lambda_shrink` and calibration constants.
--
-- A coverage deficit is none of those things. Writing it there would mean picking a `model` value
-- from an enum with no slot for "this is not a model", inventing a `lambda_shrink` for a run that
-- fits nothing, and satisfying a `score_factors` column whose stated invariant is that points plus
-- offset reproduce the score exactly (CLAUDE.md). Every one of those is a small lie, and they
-- compound in the one place the project cannot afford them: the reporting layer already reads
-- `prospect_score where pass = 2 and model = 'value'`, so a placeholder wearing a model's clothes
-- would be picked up as a fitted score by a query written months before it existed, and Phase 4's
-- refit would have no column to tell the two apart.
--
-- A view stores nothing, cannot pollute the modelling substrate, is literally the "one SQL
-- expression" the checklist asks for, and is deleted in one line when the real model arrives.
-- That is the cheapest thing to reverse, so it is what this is. Logged as I-082.
--
-- ---------------------------------------------------------------------------------------------
-- THE TWO WAYS THIS WOULD MANUFACTURE PAIN, AND WHAT STOPS EACH
--
-- 1. **An unmeasured submarket must not read as maximum deficit.** The gate is
--    `snapshot_rollup` — the completion marker — NOT `scan_snapshot.complete` and certainly not
--    "a snapshot exists". An incomplete snapshot has no coverage rows at all (the rollup refuses
--    it, PRD §9a.3), so gating on its existence would score every prospect in that submarket at
--    100% deficit — maximum pain — purely because the scan failed. The marker is the only proof
--    the coverage rows are there to be read.
--
-- 2. **A prospect with no coverage row IS the maximum deficit, and must not be dropped.**
--    ISSUES I-076: `finalize_snapshot_rollup()` reconciles with `<>`, so only prospects that
--    appeared somewhere get a row. The prospect invisible at every single grid point — the most
--    painful one in the market, and the best pitch in it — has no row at all. An inner join would
--    silently omit exactly the prospects this pipeline exists to find. Hence the LEFT JOIN and the
--    `coalesce(pc.coverage_pct, 0)`: within a submarket proven to have been measured, a missing
--    row means zero coverage, never unknown.
--
-- `excluded` is carried, not filtered on. Filtering here would make the view harsher than the
-- filter itself and hide the reason — the same shape as the franchise rule's original bug (R-003),
-- where a hard exclusion made a coefficient dead code and nothing in the output said so.

create or replace view v_prospect_placeholder_score
with (security_invoker = true) as
with measured as (
  -- The latest ROLLED-UP snapshot per submarket x keyword. `distinct on` rather than a window
  -- function because the tie-break is explicit in the ordering and reads as the rule it is.
  select distinct on (s.submarket_id, s.keyword_id)
         s.id as snapshot_id,
         s.submarket_id,
         s.keyword_id,
         s.scanned_at
    from scan_snapshot s
    join snapshot_rollup r on r.snapshot_id = s.id
   -- `s.id` breaks a tie on scanned_at. Two snapshots written in one transaction share a
   -- timestamp exactly (now() is TRANSACTION time — HANDOFF §6.14), and without a tie-break the
   -- view would silently pick a different one run to run.
   order by s.submarket_id, s.keyword_id, s.scanned_at desc, s.id desc
)
select
  p.id                as prospect_id,
  p.market_id,
  p.submarket_id,
  p.name,
  p.phone,
  st.excluded,
  count(*)::integer                                   as keywords_measured,
  count(pc.prospect_id)::integer                      as keywords_present,
  round(avg(coalesce(pc.coverage_pct, 0)), 2)         as coverage_pct,
  round(avg(100 - coalesce(pc.coverage_pct, 0)), 2)   as coverage_deficit,
  min(pc.best_rank)::smallint                         as best_rank,
  round(avg(pc.centroid_dist_at_loss), 2)             as centroid_dist_at_loss,
  max(m.scanned_at)                                   as measured_at
from prospect p
join measured m on m.submarket_id = p.submarket_id
left join prospect_coverage pc
       on pc.snapshot_id = m.snapshot_id and pc.prospect_id = p.id
left join v_prospect_status st on st.id = p.id
group by p.id, p.market_id, p.submarket_id, p.name, p.phone, st.excluded;

comment on view v_prospect_placeholder_score is
  'START-HERE §4 Phase 2 placeholder score: raw geogrid coverage deficit, averaged across the '
  'latest rolled-up snapshot per keyword. NOT a model and deliberately not a prospect_score row '
  '(ISSUES I-082) — Phase 4 replaces it by dropping this view. Rows exist only for submarkets '
  'with a completion marker; within one, a prospect with no coverage row scores 100 deficit '
  'rather than being omitted (ISSUES I-076).';

revoke all on v_prospect_placeholder_score from anon, authenticated;
