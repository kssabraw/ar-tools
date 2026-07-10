-- Migration: 20260710120000_content_batches.sql
-- Purpose: Suite-wide bulk page creation + scheduling (the "Content Scheduler").
--          A per-client, content-type-scoped batch: paste/upload a keyword list,
--          choose a page type (blog_post | service_page | location_page |
--          local_seo_page), then either create every page now or drip/weekly/
--          monthly-schedule them. This is the suite-native analogue of the
--          Fanout content scheduler; it reuses the shared scheduler
--          (services/gsc_scheduler.py) + async_jobs + job_worker instead of
--          Fanout's session/cluster-bound `scheduled_article_runs` table, so it
--          works from any content card without a keyword-research session.
--
--          content_batches  = the parent (cadence config + batch-level publish
--                             opts + status).
--          content_batch_items = one row per keyword, carrying its OWN per-row
--                             params (location / location_code / services /
--                             page_template_url) so a single upload can mix
--                             locations and per-page service sets (location
--                             pages, Option B), plus its release time + lifecycle
--                             (scheduled -> queued -> running -> complete/failed,
--                             or cancelled) and the produced artifact reference.
--
--          Scheduling model: a scheduled item sits with status='scheduled' and a
--          future scheduled_at; the shared scheduler's per-tick due-check
--          enqueues a `content_batch_item` async job only once it is due (the
--          job_worker has no <=now gate, so future work can't live directly in
--          async_jobs). "Create now" enqueues immediately at request time.
--          Also widens async_jobs.job_type with 'content_batch_item'.
--
-- RLS on, service-role only (the backend uses the service role key; the frontend
-- reaches these tables only through the platform-api).

create table if not exists content_batches (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients(id) on delete cascade,
  created_by    uuid,
  content_type  text not null
                  check (content_type in ('blog_post', 'service_page',
                                          'location_page', 'local_seo_page')),
  -- 'now' = enqueue every item immediately (create-now). The rest are the
  -- Fanout cadence vocabulary, planned by the reused fanout schedule_planner.
  mode          text not null default 'now'
                  check (mode in ('now', 'all_at_once', 'drip', 'weekly',
                                  'monthly_date', 'monthly_weekday', 'fixed')),
  -- Cadence anchors (mirror fanout.content_schedules): count-per-period, the
  -- weekly weekday(s), the monthly day-of-month / nth-weekday, the periodic
  -- start day, and the local time-of-day + timezone the slots resolve against.
  per_day       integer,
  weekday       integer check (weekday is null or (weekday between 0 and 6)),
  weekdays      jsonb,                                  -- [int] weekly multi-day
  day_of_month  integer check (day_of_month is null or (day_of_month between 1 and 31)),
  week_of_month integer check (week_of_month is null or (week_of_month between -1 and 4)),
  start_date    date,
  time_of_day   time not null default '09:00',
  timezone      text not null default 'UTC',
  -- Batch-level publish opts (per-item generation honours these on success).
  auto_publish  boolean not null default false,        -- -> client's Drive folder
  wp_publish    boolean not null default false,        -- -> client's WordPress site
  wp_status     text not null default 'draft' check (wp_status in ('draft', 'publish')),
  status        text not null default 'active'
                  check (status in ('active', 'paused', 'complete', 'cancelled')),
  total_count   integer not null default 0,
  created_at    timestamptz not null default now()
);

create index if not exists idx_content_batches_client
  on content_batches (client_id, created_at desc);

create table if not exists content_batch_items (
  id            uuid primary key default gen_random_uuid(),
  batch_id      uuid not null references content_batches(id) on delete cascade,
  client_id     uuid not null references clients(id) on delete cascade,
  keyword       text not null,
  -- Per-row params (Option B). location/location_code target a place
  -- (local_seo_page + optionally location_page); services is the per-page set of
  -- offerings a location_page must cover (one section each); page_template_url is
  -- an optional "structure to mirror" for local_seo_page.
  location          text,
  location_code     integer,
  services          jsonb not null default '[]'::jsonb,
  page_template_url text,
  scheduled_at  timestamptz not null default now(),
  status        text not null default 'scheduled'
                  check (status in ('scheduled', 'queued', 'running',
                                    'complete', 'failed', 'cancelled')),
  job_id        uuid,                                   -- the async_jobs row once released
  result_ref    uuid,                                   -- runs.id | local_seo_pages.id
  result_kind   text check (result_kind in ('run', 'local_seo_page')),
  error         text,
  created_at    timestamptz not null default now(),
  started_at    timestamptz,
  completed_at  timestamptz
);

-- The scheduler's due-check scans for scheduled rows past their release time.
create index if not exists idx_content_batch_items_due
  on content_batch_items (status, scheduled_at);
create index if not exists idx_content_batch_items_batch
  on content_batch_items (batch_id, scheduled_at);

alter table content_batches enable row level security;
alter table content_batch_items enable row level security;

-- Widen the async_jobs job_type CHECK (strictly additive).
alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'silo_dedup', 'gsc_ingest',
    'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank', 'keyword_market',
    'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan', 'maps_report',
    'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
    'local_seo_reoptimize_page', 'service_page_plan', 'rank_location_derive',
    'brand_scan', 'brand_report', 'notification_dispatch', 'reopt_plan',
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp',
    'review_intel', 'backlink_intel', 'content_intel', 'local_relevance',
    'syndication_scan', 'syndication_item', 'freeze_check', 'citation_check',
    'page_backlink_intel', 'strategy_review', 'maps_image_backfill',
    'brand_voice_scan', 'icp_scan', 'asana_push', 'competitor_intel',
    'gbp_metrics_ingest', 'internal_link_analyze', 'internal_link_apply',
    'rank_keyword_report', 'local_seo_action', 'content_batch_item'
  ]));
