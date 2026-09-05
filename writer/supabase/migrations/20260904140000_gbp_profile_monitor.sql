-- GBP Profile Monitor — alert on a suspended listing or on out-of-band changes
-- (Google or an outside source editing the profile). A daily gbp_profile_monitor
-- job reads each registered 'ok' location, diffs the monitored fields against a
-- stored baseline, and alerts on a change or a suspension/access loss. The
-- baseline is the dedup: after alerting we advance it, so each distinct change
-- alerts exactly once. Our own applies update the baseline (note_own_edit) so the
-- monitor never flags the team's own edits.
--
-- One current-baseline row per location (upserted). `snapshot` is the monitored
-- fields (title/description/categories/phone/website/address/hours/services/
-- open-status/voice-of-merchant); `access_status` is the last observed access
-- state; `last_change` records the most recent detected out-of-band diff for the
-- UI. See services/gbp_monitor.py + docs/modules/gbp-profile-editor-prd-v1_0.md.

create table if not exists gbp_profile_snapshots (
  location_row_id  uuid primary key references gbp_locations(id) on delete cascade,
  client_id        uuid not null references clients(id) on delete cascade,
  snapshot         jsonb not null,
  access_status    text not null default 'ok'
                     check (access_status in ('ok', 'suspended', 'no_access')),
  checked_at       timestamptz not null default now(),
  last_change      jsonb,
  last_change_at   timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index if not exists idx_gbp_profile_snapshots_client
  on gbp_profile_snapshots (client_id);

-- Add the gbp_profile_monitor async job type (rebuilt from the live constraint).
alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
    'website_scrape','page_structure_scrape','page_structure_parse','silo_dedup',
    'gsc_ingest','gsc_page_ingest','gsc_materialize','dataforseo_rank','keyword_market',
    'gsc_research','rank_report','serp_snapshot','maps_scan','maps_report','local_seo_silo',
    'local_seo_generate','local_seo_reoptimize_url','local_seo_reoptimize_page',
    'service_page_plan','rank_location_derive','brand_scan','brand_report',
    'notification_dispatch','reopt_plan','client_report','maps_analyze','asana_monthly',
    'competitor_gbp','review_intel','backlink_intel','content_intel','local_relevance',
    'syndication_scan','syndication_item','freeze_check','citation_check',
    'page_backlink_intel','strategy_review','maps_image_backfill','brand_voice_scan',
    'icp_scan','asana_push','competitor_intel','gbp_metrics_ingest','internal_link_analyze',
    'internal_link_apply','rank_keyword_report','local_seo_action','backlink_snapshot',
    'content_batch_item','task_month_generate','task_due_sweep','task_import_asana',
    'leadoff_tryout','leadoff_scout','leadoff_ai_probe','domain_overview','keyword_gap',
    'link_gap','leadoff_permits','leadoff_geocode','qa_review','leadoff_signal_refresh',
    'leadoff_city_finder','leadoff_income_backfill','leadoff_county_backfill',
    'keyword_research','ecommerce_generate','ecommerce_reoptimize_url','ecommerce_action',
    'github_infer_patterns','illustrate_run','blog_github_publish','gbp_post_publish',
    'gbp_post_generate','gbp_posts_sync','site_inventory','website_provision',
    'website_theme_compile','website_core_pages','website_page_publish','website_deploy_poll',
    'website_page_generate','deliverables_sheet_provision','deliverables_log',
    'deliverable_notes_scan','service_page_score','service_page_reoptimize',
    'keyword_topic_research','keyword_research_report','backlink_lookup','fanout_report',
    'blog_score','blog_reoptimize','fanout_expand','gbp_onboard','gbp_search_keywords',
    'fanout_plan','fanout_regate','fanout_fanout','fanout_architecture','ga4_ingest',
    'gbp_reviews','leadoff_map_refresh','leadoff_placement','leadoff_zip_demand',
    'voice_revalidate','autonomy_run','score_external','everhour_mirror','everhour_sync',
    'plan_handoff','local_seo_matrix_suggest','local_seo_matrix_publish','guide_sync',
    'gbp_profile_apply','gbp_profile_draft','gbp_profile_sync','gbp_profile_monitor'
  ])
);
