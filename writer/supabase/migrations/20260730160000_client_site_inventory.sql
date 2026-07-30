-- Client site inventory — the pages the client's LIVE site actually has.
--
-- SerMaStr could see everything about a campaign except the site it is being
-- run on: its `content` context module counts what THIS suite generated, which
-- is not the same question as "does a page for Pompano Beach exist". Answering
-- a ranking-strategy question needs the real inventory.
--
-- One row per client (the current snapshot, not a history) — "the site as it
-- stands" has no use for last month's version, and a single row keeps the
-- context read to one cheap primary-key lookup per chat turn. Refreshed weekly
-- by the site_inventory job; `discover_site_urls` itself is a live network call
-- and must never run inside a chat turn.
create table if not exists public.client_site_pages (
  client_id   uuid primary key references public.clients(id) on delete cascade,
  urls        jsonb       not null default '[]'::jsonb,
  page_count  integer     not null default 0,
  -- 'sitemap' (free) | 'google_index' (paid DataForSEO site: fallback) | 'none'
  source      text        not null default 'none',
  error       text,
  fetched_at  timestamptz not null default now()
);

comment on table public.client_site_pages is
  'Latest discovered URL inventory of each client''s live website (sitemap, or a paid site: query when no sitemap is readable). One row per client; refreshed by the site_inventory job.';

alter table public.client_site_pages enable row level security;

-- Service-role only, like the other agent-facing caches: every read goes
-- through platform-api, which uses the service key.
drop policy if exists "service manages client_site_pages" on public.client_site_pages;
create policy "service manages client_site_pages"
  on public.client_site_pages for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

-- Add the site_inventory job type. Recreated from the EXACT live definition
-- (which had drifted wider than any repo migration file — it carries
-- illustrate_run and the three gbp_post_* types) plus the new value.
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
    'rank_keyword_report', 'local_seo_action', 'backlink_snapshot',
    'content_batch_item', 'task_month_generate', 'task_due_sweep',
    'task_import_asana', 'leadoff_tryout', 'leadoff_scout', 'leadoff_ai_probe',
    'domain_overview', 'keyword_gap', 'link_gap', 'leadoff_permits',
    'leadoff_geocode', 'qa_review', 'leadoff_signal_refresh',
    'leadoff_city_finder', 'leadoff_income_backfill', 'leadoff_county_backfill',
    'keyword_research',
    'ecommerce_generate', 'ecommerce_reoptimize_url', 'ecommerce_action',
    'github_infer_patterns', 'illustrate_run', 'blog_github_publish',
    'gbp_post_publish', 'gbp_post_generate', 'gbp_posts_sync',
    'site_inventory'
  ]));
