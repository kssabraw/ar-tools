-- Add a distinct "For Revision" status to the native task board (owner choice).
-- The board already has "In Review"; this is a separate lane for a client-
-- requested revision (client rejected → back to the team for rework). Revision
-- tracking (tasks.revision_count) is repointed at this status via
-- config.revision_status_key = "for_revision".
--
-- Sits at the end with the other exception statuses (Blocked, In Review); a
-- non-initial, non-done active status in the in_progress category so downstream
-- category logic treats it as active (not-yet-done) work.

insert into public.task_statuses (key, label, color, category, is_initial, is_done, sort_order, active)
values ('for_revision', 'For Revision', '#d97706', 'in_progress', false, false, 8, true)
on conflict (key) do nothing;
