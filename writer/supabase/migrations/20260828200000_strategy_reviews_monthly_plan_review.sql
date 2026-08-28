-- SerMaStr monthly plan review → PACE assignment handoff.
-- Add a fourth strategist trigger, `monthly_plan_review`: a once-a-month run
-- fired a few days before task generation that proposes changes to next month's
-- Recipe-Engine task plan. Behaves like every other strategist run (advice +
-- proposals only); an approved proposal is auto-placed capacity-aware by PACE.
alter table public.strategy_reviews
  drop constraint if exists strategy_reviews_trigger_check;

alter table public.strategy_reviews
  add constraint strategy_reviews_trigger_check
  check (trigger = any (array[
    'scheduled'::text,
    'escalation'::text,
    'on_demand'::text,
    'monthly_plan_review'::text
  ]));
