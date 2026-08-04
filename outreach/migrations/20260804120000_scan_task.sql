-- The queued-lifecycle bookkeeping: one row per grid point, from before it is paid for until
-- after it is collected.
--
-- PRD §B1 and DECISIONS.md ("DataForSEO task collection: tasks_ready polling, not postback").
-- The provider's Maps geogrid is a QUEUED endpoint: `task_post` bills and returns an id, and the
-- result is fetched later. Between those two moments the only record that a paid task exists is
-- whatever we wrote down. The PRD states the consequence plainly: *"an un-persisted id is a paid
-- task that can never be collected."*
--
-- WHY ROWS EXIST BEFORE THE POST.
--
-- The naive order — post, then persist what came back — has a window in which we have spent money
-- and hold no record of it. A crash, a redeploy, or a 502 on the response of a request the
-- provider already accepted, and 81 paid tasks are unrecoverable. So rows are inserted `pending`
-- FIRST, the post fills in `provider_task_id`, and a row still `pending` afterwards simply means
-- "not yet posted" — the cheap, safe direction to be wrong in, because reposting an unposted
-- point costs one point and losing a posted one costs the batch.
--
-- WHY THE TAG IS LOAD-BEARING RATHER THAN DECORATIVE.
--
-- That still leaves a window: posted, response lost. `tag` closes it. We send
-- `<snapshot_id>:<point_seq>`, the provider echoes it on both `tasks_ready` and `task_get`, and
-- the collector can therefore reattach a result whose id we never managed to store. This is a
-- deliberate divergence from the suite's maps_dataforseo.py, where the tag is explicitly a debug
-- convenience and alignment is positional: that code polls ids it holds, so a lost id is a lost
-- pin and nothing more. Here the collector discovers work from a list rather than from our own
-- records, which is exactly what makes recovery-by-tag possible — and worth designing for.

create table if not exists scan_task (
  id uuid primary key default gen_random_uuid(),
  snapshot_id uuid not null references scan_snapshot(id) on delete cascade,
  point_seq smallint not null,

  -- Null until the post returns, or forever if the response was lost. Not unique-by-constraint
  -- alone: see the partial index below, which excludes the nulls.
  provider_task_id text,

  -- pending    — row exists, nothing has been paid for yet
  -- submitted  — the provider accepted it and billed for it
  -- collected  — the result is stored; terminal
  -- failed     — the provider returned a task-level error; terminal
  --
  -- There is deliberately no 'empty' status. A point that legitimately returns no businesses is
  -- COLLECTED, not missing, and conflating the two would make an ocean tile read as a scan
  -- failure and depress the completeness ratio that decides whether a snapshot is usable.
  status text not null default 'pending'
    check (status in ('pending', 'submitted', 'collected', 'failed')),

  result_count integer,          -- rows written for this point; 0 is a real, valid answer
  attempts integer not null default 0,
  last_error text,

  submitted_at timestamptz,
  collected_at timestamptz,
  created_at timestamptz not null default now(),

  unique (snapshot_id, point_seq)
);

comment on table scan_task is
  'One row per grid point per snapshot, created BEFORE the provider is paid. A row without a '
  'provider_task_id was never posted; a row with one is billed work that must be collected or '
  'explicitly written off. The tag we send (<snapshot_id>:<point_seq>) lets the collector '
  'reattach a result whose id we failed to store.';

-- Two ids must never map to the same point, and the same id must never be recorded twice. The
-- index is partial because un-posted rows share a null id and are not in conflict with anything.
create unique index if not exists scan_task_provider_id_idx
  on scan_task (provider_task_id) where provider_task_id is not null;

-- The collector's working set: what is outstanding, oldest first. Also the query behind the
-- fallback-by-id path (PRD §B1.3, ~3 days) and the alert (§B1.4, ~5 days).
create index if not exists scan_task_outstanding_idx
  on scan_task (status, submitted_at) where status in ('pending', 'submitted');

alter table scan_task enable row level security;


-- ---------------------------------------------------------------------------
-- The scan_month guard.
--
-- ISSUES I-044: `grid_result.scan_month` must come from the snapshot, never from now(). This is
-- listed as an invariant in CLAUDE.md, which is to say it was a convention that the next writer
-- had to know about — and a collector makes it materially easier to get wrong than it was when
-- the invariant was written, because collection happens HOURS OR DAYS after submission and can
-- therefore land in a different calendar month than the snapshot it belongs to. A writer using
-- now() would be correct in every test and wrong twice a year, splitting one snapshot across two
-- partitions and leaving the retention job to blame the rollup.
--
-- WHY A CHECK AT ROLLUP AND NOT A TRIGGER ON INSERT.
--
-- A BEFORE INSERT trigger could set scan_month from the snapshot and make the mistake impossible.
-- It would also run a lookup per row on the largest table in the system — ~58M rows/year, ~1,600
-- per snapshot — to re-derive a value the writer already has. That is a real cost paid forever to
-- guard a mistake made once. This check is per SNAPSHOT instead: one query, at the point where
-- the snapshot is declared finished, and it refuses rather than repairs.
-- ---------------------------------------------------------------------------
create or replace function public.assert_snapshot_month(p_snapshot_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $function$
declare
  expected date;
  strays   integer;
begin
  select date_trunc('month', scanned_at)::date into expected
    from scan_snapshot where id = p_snapshot_id;

  if expected is null then
    raise exception 'no such snapshot %', p_snapshot_id;
  end if;

  select count(*) into strays
    from grid_result
   where snapshot_id = p_snapshot_id
     and scan_month <> expected;

  if strays > 0 then
    raise exception
      'snapshot % has % grid_result rows outside its own month % — scan_month was derived from '
      'the clock rather than the snapshot (ISSUES I-044)',
      p_snapshot_id, strays, expected;
  end if;
end;
$function$;

revoke all on function public.assert_snapshot_month(uuid) from anon, authenticated, public;
