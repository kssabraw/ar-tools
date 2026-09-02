-- SerMaStr autonomous recovery plans (PRD PR 2 —
-- docs/modules/sermastr-autonomous-recovery-plans-prd-v1_0.md §5).
--
-- 1) A fifth strategist trigger, `goal_recovery`: the run the chronic-goal
--    escalation sweep fires so a goal that stays critically behind gets a
--    costed, tiered, approvable recovery plan (not just the alarm).
-- 2) `strategy_reviews.budget` — the budget snapshot the plan was costed
--    against (envelope + tier ceilings + per-tier counts + root cause + the
--    chronic goals), so an edited retainer never silently re-tiers an old plan.
--    The client card stays the only place budget is SET.
-- 3) `sermastr_action_log.decision` gains 'superseded': the prior recovery
--    plan's still-open proposals are superseded when a fresh plan lands — its
--    own value so it can never read as a human dismissal in the learning rates.

alter table public.strategy_reviews
  drop constraint if exists strategy_reviews_trigger_check;

alter table public.strategy_reviews
  add constraint strategy_reviews_trigger_check
  check (trigger = any (array[
    'scheduled'::text,
    'escalation'::text,
    'on_demand'::text,
    'monthly_plan_review'::text,
    'goal_recovery'::text
  ]));

alter table public.strategy_reviews
  add column if not exists budget jsonb;

comment on column public.strategy_reviews.budget is
  'goal_recovery runs only: the budget snapshot the plan was costed against — {envelope, tiers (cumulative ceilings over deployable), tier_steps, fundable_count, total_cost_usd, by_tier, root_cause, goals}. Computed by services/goal_recovery.py; the client card is the input, this is the record.';

alter table public.sermastr_action_log
  drop constraint if exists sermastr_action_log_decision_check;

alter table public.sermastr_action_log
  add constraint sermastr_action_log_decision_check
  check (decision in ('approved', 'dismissed', 'superseded'));

comment on column public.sermastr_action_log.decision is
  'The human decision on the proposal; null = still pending (itself a training signal). ''superseded'' = replaced by a newer recovery plan (system, not a human verdict — excluded from approve/dismiss rates).';
