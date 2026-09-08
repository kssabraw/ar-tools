-- Register the async_jobs job type for the Social Media Creator's Angle fan-out.
-- Drift-proof + idempotent (mirrors 20260905130000_social_publish_job): reads the
-- live CHECK definition and appends 'social_fanout' to its ARRAY, so it can't
-- clobber the (repo-wider-than-any-file) current set. The handler lives in
-- services/social/fanout.py; freeze is enforced INSIDE that handler (not the blanket
-- worker FREEZE_GATED_JOB_TYPES gate) so a client frozen mid-flight gets its
-- pre-created 'generating' drafts cleaned up rather than orphaned.
do $$
declare
  cur text;
  newdef text;
begin
  select pg_get_constraintdef(oid) into cur
  from pg_constraint
  where conrelid = 'async_jobs'::regclass and conname = 'async_jobs_job_type_check';

  if cur is null then
    raise exception 'async_jobs_job_type_check not found';
  end if;

  if position('''social_fanout''' in cur) > 0 then
    return;  -- already registered
  end if;

  newdef := regexp_replace(cur, '\]\)\)\)\s*$', ', ''social_fanout''::text])))');
  execute 'alter table async_jobs drop constraint async_jobs_job_type_check';
  execute 'alter table async_jobs add constraint async_jobs_job_type_check ' || newdef;
end $$;
