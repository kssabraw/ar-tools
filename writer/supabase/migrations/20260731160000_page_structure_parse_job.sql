-- Manual (pasted / uploaded) reference page structures.
--
-- A client with no website — a LeadOff market pick, a rebuild, or an onboarding
-- where all we have is a brand guide — has no live page for the page_structure
-- scraper to fetch, so every layout-mirroring path silently degraded to "no
-- reference". The new `page_structure_parse` job accepts the structure as TEXT
-- (pasted into the client form, or lifted from an uploaded document by the
-- existing file parser) and converts it into the same analysis shape a scrape
-- produces, stored on the same clients.page_structures JSONB.
--
-- No schema change is needed for the storage itself: page_structures is JSONB
-- and manual entries reuse the existing keys, adding `source` ('scrape' |
-- 'manual'), `guidelines_text`, and `original_filename`. Entries written before
-- this migration have no `source` and are read as scrapes (they always carry a
-- URL). Only the async_jobs job_type CHECK has to admit the new job type.
--
-- The array below preserves the FULL live constraint set (which is wider than
-- any single repo migration file) plus the new value.

alter table async_jobs drop constraint async_jobs_job_type_check;

alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'page_structure_parse', 'silo_dedup',
    'gsc_ingest', 'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank',
    'keyword_market', 'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan',
    'maps_report', 'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
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
    'leadoff_geocode', 'qa_review', 'leadoff_signal_refresh', 'leadoff_city_finder',
    'leadoff_income_backfill', 'leadoff_county_backfill', 'keyword_research',
    'ecommerce_generate', 'ecommerce_reoptimize_url', 'ecommerce_action',
    'github_infer_patterns', 'illustrate_run', 'blog_github_publish',
    'gbp_post_publish', 'gbp_post_generate', 'gbp_posts_sync', 'site_inventory'
  ]));
