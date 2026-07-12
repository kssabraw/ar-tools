-- Migration: 20260712130000_leadoff_ai_probe.sql
-- Purpose: the AI-lane pilot probe as an app-run job (validation, not a
--          feature build): widen leadoff_spend.action + async_jobs.job_type
--          for 'ai_probe' / 'leadoff_ai_probe'. The probe samples DataForSEO's
--          ai_optimization endpoints + AIO citations on known test markets
--          under a hard cap, so the go/no-go decision runs through the same
--          budget-guarded rails as tryout/scout instead of a desktop script.

alter table leadoff_spend drop constraint if exists leadoff_spend_action_check;
alter table leadoff_spend add constraint leadoff_spend_action_check
  check (action in ('tryout','scout','ai_probe'));

alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (job_type in (
  'website_scrape','page_structure_scrape','silo_dedup','gsc_ingest','gsc_page_ingest',
  'gsc_materialize','dataforseo_rank','keyword_market','gsc_research','rank_report',
  'serp_snapshot','maps_scan','maps_report','local_seo_silo','local_seo_generate',
  'local_seo_reoptimize_url','local_seo_reoptimize_page','service_page_plan',
  'rank_location_derive','brand_scan','brand_report','notification_dispatch',
  'reopt_plan','client_report','maps_analyze','asana_monthly','competitor_gbp',
  'review_intel','backlink_intel','content_intel','local_relevance',
  'syndication_scan','syndication_item','freeze_check','citation_check',
  'page_backlink_intel','strategy_review','maps_image_backfill','brand_voice_scan',
  'icp_scan','asana_push','competitor_intel','gbp_metrics_ingest',
  'internal_link_analyze','internal_link_apply','rank_keyword_report',
  'local_seo_action','backlink_snapshot','content_batch_item',
  'task_month_generate','task_due_sweep','task_import_asana',
  'leadoff_tryout','leadoff_scout','leadoff_ai_probe'
));
