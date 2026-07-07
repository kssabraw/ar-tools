-- Allow the one-off 'maps_image_backfill' job type on async_jobs.
--
-- Renders + stores the saved geo-grid map PNG for existing maps_scan_results
-- rows that predate the image feature (services/maps_report.run_maps_image_backfill_job).
-- Strictly additive — no previously-allowed value is removed.
--
-- The array below is the UNION of the worker-dispatched job types and the legacy
-- values still present in live async_jobs rows (brand_voice_scan, icp_scan,
-- asana_push, competitor_intel) — retired job types whose history rows remain, so
-- the CHECK must keep permitting them or the constraint can't be re-validated.
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
    'syndication_scan', 'syndication_item',
    'freeze_check', 'citation_check', 'page_backlink_intel',
    'strategy_review', 'maps_image_backfill',
    -- legacy (retired job types with rows still in the table):
    'brand_voice_scan', 'icp_scan', 'asana_push', 'competitor_intel'
  ]));
