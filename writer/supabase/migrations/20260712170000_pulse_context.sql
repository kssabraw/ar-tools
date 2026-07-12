-- Weekly Pulse context enrichment (owner decisions 2026-07-12):
--
-- 1. asana_task_library.client_blurb — a CLIENT-FACING one-liner per recurring
--    task type ("Citation cleanup → keeps your business info consistent
--    everywhere Google looks"), written once by the team, reused by every
--    pulse for every client. Edited on the Task Library page.
-- 2. tasks.client_note — an optional CLIENT-FACING note per task (one-off
--    explanations + completion outcomes), edited in the task drawer. Distinct
--    from tasks.description, which is INTERNAL (producer diagnoses, deep
--    links) and must never reach a client email.

alter table asana_task_library
  add column if not exists client_blurb text;

alter table tasks
  add column if not exists client_note text;
