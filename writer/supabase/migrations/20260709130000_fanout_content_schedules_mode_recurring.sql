-- Widen the fanout.content_schedules mode CHECK to cover the recurring cadences
-- (weekly / monthly-by-date / monthly-by-weekday). The scheduling code + planner
-- shipped these, but the DB constraint still only allowed all_at_once/drip/fixed,
-- so inserting a weekly/monthly schedule failed with a 23514 check violation that
-- surfaced in the UI as a bare internal_error. Applied live 2026-07-09.
alter table fanout.content_schedules
  drop constraint if exists content_schedules_mode_check;
alter table fanout.content_schedules
  add constraint content_schedules_mode_check
  check (mode in ('all_at_once', 'drip', 'fixed', 'weekly', 'monthly_date', 'monthly_weekday'));
