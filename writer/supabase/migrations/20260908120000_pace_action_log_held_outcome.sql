-- PACE action log: allow the "held" outcome.
--
-- The log now records PACE's AUTONOMOUS actions too (not just human-approved
-- ones) — see services/pace_audit.py AUTONOMOUS_ACTIONS. An auto-placement
-- (pm_assign.place_task) that can't be staffed because the eligible pool is at
-- capacity is recorded with outcome="held", which the original CHECK didn't
-- permit — so the row's insert would fail and (record() being best-effort) the
-- held placement would silently go unlogged. Widen the outcome CHECK to include
-- it. Additive; every existing value stays valid.

alter table public.pace_action_log
  drop constraint if exists pace_action_log_outcome_check;

alter table public.pace_action_log
  add constraint pace_action_log_outcome_check
  check (outcome = any (array[
    'executed', 'held', 'failed', 'skipped', 'denied', 'deferred', 'cancelled'
  ]));
