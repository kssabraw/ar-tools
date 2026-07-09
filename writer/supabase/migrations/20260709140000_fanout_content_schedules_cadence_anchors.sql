-- Persist the recurring-cadence anchors on fanout.content_schedules so the queue
-- can be re-flowed (compacted when an article is cancelled / re-expanded when one
-- is reinstated) without the caller re-supplying them. weekday/day_of_month/
-- week_of_month are single ints; weekdays is the multi-day set for the weekly
-- cadence. Applied live 2026-07-09.
alter table fanout.content_schedules
  add column if not exists weekday int,
  add column if not exists weekdays jsonb,
  add column if not exists day_of_month int,
  add column if not exists week_of_month int;
