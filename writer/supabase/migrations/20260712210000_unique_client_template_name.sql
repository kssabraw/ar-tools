-- Unique task names per client template (found in the 2026-07-12 ops audit).
--
-- asana_client_task_templates had only PK + FK: nothing prevented two rows
-- with the same name for one client (UI double-add, re-run bootstrap), and the
-- native monthly generator's idempotency key is per template ROW — a duplicate
-- "GBP Blast" row would generate the task TWICE every month. Case/whitespace-
-- insensitive to match how the generator matches names against the Task
-- Library. Live data verified duplicate-free before this was applied.
--
-- The template editor's replace-style PUT validates for duplicate names BEFORE
-- its delete+insert (routers/asana.py), so a dupe submission 400s cleanly
-- instead of tripping this index mid-replace.

create unique index if not exists uq_asana_client_template_name
  on asana_client_task_templates (client_id, lower(trim(name)));
