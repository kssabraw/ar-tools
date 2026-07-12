-- Reposition Blocked + In Review as off-workflow EXCEPTION states (owner ruling
-- 2026-07-12). They aren't steps in the normal progression:
--   * Blocked   = a task someone can't start yet (external dependency)
--   * In Review = the client rejected it and it needs redoing (rework loop)
-- The linear workflow is:
--   Not Started → In Progress → In QA → Sent to Client → Client Approved → Completed
-- Both exception statuses stay valid + assignable, just parked at the end of
-- the board (highest sort_order) instead of sitting between the workflow steps.
-- Category/is_done/keys are unchanged, so all status logic + existing task rows
-- are untouched — this is a display-order change only.

update task_statuses set sort_order = 3, updated_at = now() where key = 'sent_to_client';
update task_statuses set sort_order = 4, updated_at = now() where key = 'client_approved';
update task_statuses set sort_order = 5, updated_at = now() where key = 'complete';
update task_statuses set sort_order = 6, updated_at = now() where key = 'blocked';
update task_statuses set sort_order = 7, updated_at = now() where key = 'in_review';
