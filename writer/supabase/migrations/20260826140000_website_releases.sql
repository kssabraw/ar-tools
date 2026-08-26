-- Website Builder — the release (drip-publish) schedule.
--
-- The other content-creator modules (the Topic Fanout scheduler) publish content
-- on a cadence: some now, the rest dripped out over time. This gives a website
-- the same option — publish an immediate batch, then release N more per day /
-- week / month — instead of committing every page at once.
--
-- Owner ruling: each release GENERATES then PUBLISHES the next planned posts
-- just-in-time (Fanout-style), so a schedule needs no pages generated up front.
-- It reuses the existing `website_page_generate` job with a `publish_after`
-- flag, so NO new async_jobs job type is added.

create table if not exists website_releases (
  id uuid primary key default gen_random_uuid(),
  -- One schedule per site: the drip is a property of the whole site's content
  -- plan, not of an individual page.
  website_id uuid not null references websites(id) on delete cascade,
  enabled boolean not null default true,
  -- Cadence. The shared scheduler ticks daily, so daily is the finest grain;
  -- weekly pins a weekday, monthly pins a day-of-month.
  mode text not null default 'daily'
    check (mode in ('daily', 'weekly', 'monthly')),
  weekday int check (weekday between 0 and 6),          -- weekly: 0=Mon .. 6=Sun
  day_of_month int check (day_of_month between 1 and 28), -- monthly: 1..28 (every month has these)
  -- How many pages go out the moment the schedule is set, and how many each tick.
  immediate_count int not null default 0 check (immediate_count >= 0),
  per_release_count int not null default 1 check (per_release_count >= 1),
  -- 'active' while pages remain; 'complete' once the plan is fully released;
  -- 'paused' by a human. Only 'active' schedules are picked up by the tick.
  status text not null default 'active'
    check (status in ('active', 'complete', 'paused')),
  -- Self-clocked, like the report/rank schedules: the tick reads next_run_at and
  -- advances it by the cadence after each release.
  next_run_at timestamptz,
  last_run_at timestamptz,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (website_id)
);

create index if not exists website_releases_due_idx
  on website_releases (next_run_at)
  where enabled and status = 'active';

alter table website_releases enable row level security;

-- Which pages a release has already claimed, so a page is enqueued exactly once
-- even though generation is slow and a manual + scheduled release could overlap
-- the window between "enqueued its generate job" and "that job finished". The
-- status column can't carry this: a page stays 'draft' after generation and only
-- flips to 'published' at commit, so "released but not yet published" needs its
-- own mark. Cleared to re-release a page (e.g. after a plan rebuild).
alter table website_pages add column if not exists released_at timestamptz;
