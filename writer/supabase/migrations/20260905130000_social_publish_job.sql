-- Register the async_jobs job type for the Social Media publish path.
-- Drift-proof + idempotent: reads the live CHECK definition and appends
-- 'social_publish' to its ARRAY, so it can't clobber the (repo-wider-than-any-file)
-- current set. The handler lives in services/social/publish.py; the type is
-- freeze-gated (services/freeze.py FREEZE_GATED_JOB_TYPES).
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

  if position('''social_publish''' in cur) > 0 then
    return;  -- already registered
  end if;

  newdef := regexp_replace(cur, '\]\)\)\)\s*$', ', ''social_publish''::text])))');
  execute 'alter table async_jobs drop constraint async_jobs_job_type_check';
  execute 'alter table async_jobs add constraint async_jobs_job_type_check ' || newdef;
end $$;
