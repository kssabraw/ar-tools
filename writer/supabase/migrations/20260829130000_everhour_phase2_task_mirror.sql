-- Everhour time-tracking integration — Phase 2 (task mirror join keys + job type).
--
-- Adds the columns the metadata-only task mirror writes, per the plan doc
-- (docs/modules/everhour-time-tracking-integration-plan-v1_0.md §3, §6), and
-- registers the `everhour_mirror` async job type that performs the outbound
-- create. Purely additive; the whole integration stays gated on
-- `everhour_enabled` (default False) AND its `everhour_mirror_enabled` sub-gate,
-- so this is a behavioral no-op until a real Everhour account is provisioned.
--
--   * tasks.everhour_task_id — the Everhour task id (opaque prefixed string
--     like "ev:9876543210", never numeric — so text) this native task was
--     mirrored to. Null → not yet mirrored (or the client isn't Everhour-mapped).
--     Set once by the mirror; the Phase 3 time pull joins on it.
--
--   * tasks.everhour_synced_at — the last SUCCESSFUL mirror attempt's timestamp.
--
--   NOTE: tasks.actual_hours + the time_entries table are Phase 3, deliberately
--   NOT added here — Phase 2 is the write side (the join key) only.
--
-- The async_jobs job_type CHECK is widened to accept `everhour_mirror`. Rebuilt
-- from the live constraint (the live job_type set is wider than any single repo
-- migration file — see CLAUDE.md; this list is the score_external widen
-- (20260828170000) verbatim + the new value), preserving every existing type.
--
-- Backfill scan support: a partial index over the exact predicate the one-time
-- mirror backfill walks (open, top-level, unmirrored tasks) so the cutover sweep
-- doesn't seq-scan the whole board.
--
-- tasks already has RLS on, service-role only (suite convention); the new
-- columns inherit it. Idempotent (add-if-not-exists / drop-then-add CHECK).

alter table public.tasks
  add column if not exists everhour_task_id text;

comment on column public.tasks.everhour_task_id is
  'Everhour task id (opaque string like "ev:123", not numeric) this native task was mirrored to. Null → not yet mirrored. Set once by the everhour_mirror job; the Phase 3 time pull joins on it.';

alter table public.tasks
  add column if not exists everhour_synced_at timestamptz;

comment on column public.tasks.everhour_synced_at is
  'Timestamp of the last successful Everhour task-mirror for this task.';

-- Backfill / re-mirror scan predicate (mirror_backfill in services/everhour_sync.py).
create index if not exists idx_tasks_everhour_unmirrored
  on public.tasks (client_id)
  where everhour_task_id is null
    and parent_task_id is null
    and deleted_at is null
    and completed = false;

alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
    'website_scrape','page_structure_scrape','page_structure_parse','silo_dedup','gsc_ingest',
    'gsc_page_ingest','gsc_materialize','dataforseo_rank','keyword_market','gsc_research','rank_report',
    'serp_snapshot','maps_scan','maps_report','local_seo_silo','local_seo_generate','local_seo_reoptimize_url',
    'local_seo_reoptimize_page','service_page_plan','rank_location_derive','brand_scan','brand_report',
    'notification_dispatch','reopt_plan','client_report','maps_analyze','asana_monthly','competitor_gbp',
    'review_intel','backlink_intel','content_intel','local_relevance','syndication_scan','syndication_item',
    'freeze_check','citation_check','page_backlink_intel','strategy_review','maps_image_backfill',
    'brand_voice_scan','icp_scan','asana_push','competitor_intel','gbp_metrics_ingest','internal_link_analyze',
    'internal_link_apply','rank_keyword_report','local_seo_action','backlink_snapshot','content_batch_item',
    'task_month_generate','task_due_sweep','task_import_asana','leadoff_tryout','leadoff_scout','leadoff_ai_probe',
    'domain_overview','keyword_gap','link_gap','leadoff_permits','leadoff_geocode','qa_review',
    'leadoff_signal_refresh','leadoff_city_finder','leadoff_income_backfill','leadoff_county_backfill',
    'keyword_research','ecommerce_generate','ecommerce_reoptimize_url','ecommerce_action','github_infer_patterns',
    'illustrate_run','blog_github_publish','gbp_post_publish','gbp_post_generate','gbp_posts_sync','site_inventory',
    'website_provision','website_theme_compile','website_core_pages','website_page_publish','website_deploy_poll',
    'website_page_generate','deliverables_sheet_provision','deliverables_log','deliverable_notes_scan',
    'service_page_score','service_page_reoptimize','keyword_topic_research','keyword_research_report',
    'backlink_lookup','fanout_report','blog_score','blog_reoptimize','fanout_expand','gbp_onboard',
    'gbp_search_keywords','fanout_plan','fanout_regate','fanout_fanout','fanout_architecture','ga4_ingest',
    'gbp_reviews','leadoff_map_refresh','leadoff_placement','leadoff_zip_demand','voice_revalidate',
    'autonomy_run','score_external','everhour_mirror'
  ])
);
