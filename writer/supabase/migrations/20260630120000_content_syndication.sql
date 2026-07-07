-- Migration: 20260630120000_content_syndication.sql
-- Purpose: Content Syndication module. Continuously watches a client's website
--          for new content (blog posts, pages, products), rewrites each new
--          piece into a unique version, and publishes it as a public,
--          search-discoverable Google Doc AND a public Google Sheet — each
--          carrying a backlink to the original page on the site. The originals
--          stay untouched on the site; the rewritten copies become additional
--          indexable Google properties that link back.
--
--          Two tables:
--            * syndication_config — one row per client (enable + cadence + which
--              content types to syndicate + sharing mode).
--            * syndication_items  — one row per discovered source URL (the
--              dedup key that detects "new" content), carrying the rewrite +
--              publish lifecycle and the resulting Doc/Sheet links.
--
-- RLS on, service-role only (the backend uses the service role key).

create table if not exists syndication_config (
  client_id        uuid primary key references clients(id) on delete cascade,
  enabled          boolean not null default false,
  interval_days    integer not null default 1,          -- daily scan by default
  include_blog     boolean not null default true,
  include_pages    boolean not null default true,
  include_products boolean not null default true,
  share_mode       text not null default 'public'       -- 'public' (findable) | 'link'
                     check (share_mode in ('public', 'link')),
  last_scan_date   date,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create table if not exists syndication_items (
  id                 uuid primary key default gen_random_uuid(),
  client_id          uuid not null references clients(id) on delete cascade,
  source_url         text not null,
  content_type       text not null default 'page'       -- 'blog_post' | 'page' | 'product'
                       check (content_type in ('blog_post', 'page', 'product')),
  title              text,
  status             text not null default 'discovered'  -- discovered|rewriting|published|failed|skipped
                       check (status in ('discovered', 'rewriting', 'published', 'failed', 'skipped')),
  rewritten_title    text,
  rewritten_markdown text,
  doc_id             text,
  doc_url            text,
  sheet_id           text,
  sheet_url          text,
  error              text,
  first_seen_at      timestamptz not null default now(),
  published_at       timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  -- A known URL is never re-discovered → this is the "new content" detector.
  unique (client_id, source_url)
);

create index if not exists idx_syndication_items_client_status
  on syndication_items (client_id, status, first_seen_at desc);
create index if not exists idx_syndication_items_client_created
  on syndication_items (client_id, created_at desc);

alter table syndication_config enable row level security;
alter table syndication_items enable row level security;

-- Widen async_jobs.job_type for the syndication jobs (preserve the full set from
-- 20260629210000_local_relevance_scores).
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
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp', 'review_intel',
    'backlink_intel', 'content_intel', 'local_relevance',
    'syndication_scan', 'syndication_item'
  ]));
