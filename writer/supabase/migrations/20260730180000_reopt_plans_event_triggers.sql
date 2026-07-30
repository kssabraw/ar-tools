-- Allow the event-driven reopt_plans triggers the code already passes.
--
-- `reopt_plans.trigger` accepted only scheduled|drop|manual, but
-- `enqueue_reopt_plan` is called with `maps_drop` (maps_analyzer, on a local-pack
-- decline) and `offpage` (offpage_agent RD loss/spike, citation_check dead
-- citations, page_backlink_intel RD imbalance). Those rebuilds are dormant today
-- behind `reopt_plan_event_refresh_enabled` (default False), so the mismatch has
-- never fired — but enabling that flag would have made every event-driven
-- rebuild die at the INSERT, after doing all of the plan-building work.
--
-- Widening rather than collapsing the values to 'drop': the trigger records WHY
-- a plan was built, and "the local pack slipped" and "we lost referring domains"
-- are different stories from "an organic keyword dropped". Strictly additive —
-- the three existing values keep working.
alter table reopt_plans drop constraint reopt_plans_trigger_check;
alter table reopt_plans
  add constraint reopt_plans_trigger_check
  check (trigger = any (array[
    'scheduled',   -- weekly pass (gsc_scheduler)
    'manual',      -- a person hit refresh, or SerMaStr rebuilt on request
    'drop',        -- an organic rank-drop alert opened (rank_materialize)
    'maps_drop',   -- a local-pack alert opened (maps_analyzer)
    'offpage'      -- link loss / RD spike / dead citations / RD imbalance
  ]));
