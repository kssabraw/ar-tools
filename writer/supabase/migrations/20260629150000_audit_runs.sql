-- ============================================================
-- audit_runs — engagement-scoped audit results (design §3.1, §6.2–6.4)
-- ============================================================
-- One row per audit kind per cycle. The Strategy Engine reads these to feed
-- richer actions. Phase 3 begins with site_technical; serp/maps/performance
-- kinds are reserved for the synthesis audits + baseline. Additive.
-- ============================================================

create table if not exists audit_runs (
  id            uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references engagements(id) on delete cascade,
  kind          text not null
                  check (kind in (
                    'site_technical', 'serp_competition',
                    'maps_competition', 'performance_baseline',
                    'backlink_gap', 'local_citation'
                  )),
  status        text not null default 'pending'
                  check (status in ('pending', 'running', 'complete', 'failed')),
  result        jsonb,
  score         numeric,
  error         text,
  created_at    timestamptz not null default now(),
  completed_at  timestamptz
);

create index if not exists idx_audit_runs_engagement
  on audit_runs (engagement_id, created_at desc);

alter table audit_runs enable row level security;

-- NOTE: the async_jobs.job_type allow-list is widened for the audit jobs in a
-- LATER migration (20260629220000_async_jobs_audit_jobtypes.sql) that sets the
-- UNION of main's list + the audit types. Doing it here would drop main's newer
-- job types (asana_monthly, *_intel, …) on a fresh/merged apply, since main's
-- own later migrations also redefine this constraint. Keep this migration to the
-- table only.
