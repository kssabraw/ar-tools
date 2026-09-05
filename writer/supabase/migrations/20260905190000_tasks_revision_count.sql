-- Revision tracking (owner request): how many times a task was marked "for
-- revision" (client rejected → rework, the In Review status), so a deliverable
-- that keeps getting bounced back flags work that misses client expectations.
--
-- tasks.revision_count is bumped by task_service.update_task on each transition
-- INTO the revision status going forward. This backfills it from the immutable
-- task_activity feed (status_changed rows whose detail.to is the revision
-- status), so any historical revisions are counted too.

alter table public.tasks
    add column if not exists revision_count integer not null default 0;

-- Backfill from history: count status_changed → in_review transitions per task.
update public.tasks t
set revision_count = c.n
from (
    select task_id, count(*) as n
    from public.task_activity
    where kind = 'status_changed'
      and detail->>'field' = 'status_key'
      and detail->>'to' = 'in_review'
    group by task_id
) c
where c.task_id = t.id
  and t.revision_count <> c.n;
