-- Add an "In QA" workflow status and relabel the terminal status "Completed"
-- (owner request 2026-07-12). Statuses are global v1 (one set for all boards),
-- read dynamically by the board + config API, so this shows up everywhere.
--
-- New pipeline order:
--   Not Started → In Progress → In QA → Blocked → In Review
--   → Sent to Client → Client Approved → Completed
--
-- Idempotent: safe to re-run and applied identically to the live DB. The
-- 20260711130000 seed used ON CONFLICT DO NOTHING, so these adjustments to
-- already-seeded rows live here rather than in that file.

-- In QA: an in-progress-category check between In Progress and In Review.
insert into task_statuses (key, label, color, category, is_initial, is_done, sort_order, active)
values ('in_qa', 'In QA', '#ec4899', 'in_progress', false, false, 2, true)
on conflict (key) do update
  set label = excluded.label,
      color = excluded.color,
      category = excluded.category,
      sort_order = excluded.sort_order,
      active = true,
      updated_at = now();

-- Reflow sort_order so In QA sits right after In Progress.
update task_statuses set sort_order = 3, updated_at = now() where key = 'blocked';
update task_statuses set sort_order = 4, updated_at = now() where key = 'in_review';
update task_statuses set sort_order = 5, updated_at = now() where key = 'sent_to_client';
update task_statuses set sort_order = 6, updated_at = now() where key = 'client_approved';

-- Relabel the terminal done status "Complete" → "Completed" (key/category
-- unchanged, so all is_done/category logic and existing task rows are intact).
update task_statuses set label = 'Completed', sort_order = 7, updated_at = now()
  where key = 'complete';
