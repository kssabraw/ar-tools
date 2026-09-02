-- DORA guide sync (services/guide_sync.py): when a module change lands on main,
-- CI reports the user-facing diff to the platform and DORA reviews whether the
-- module's in-app guide (the `guides` row the Guides portal renders) still
-- describes the tool — rewriting it when it doesn't, with the prior version
-- kept here for a one-click revert.
--
-- One row per (commit, module) — the unique pair is the idempotency key for a
-- re-delivered CI webhook. Statuses:
--   queued / running  — the review job is pending / in flight
--   no_change         — DORA judged the change not user-visible (nothing written)
--   applied           — the guide was rewritten (prior_* holds the revert target)
--   proposed          — a rewrite is waiting for a human (auto-apply off)
--   rejected          — DORA's rewrite failed the size/shape sanity check
--   no_guide          — the module has no guide row to update
--   failed            — the review itself errored
--   reverted          — a human restored prior_* after an applied run
--   dismissed         — a human declined a proposed run
--
-- RLS on, service-role only (reads/writes go through the platform API).

create table if not exists guide_sync_runs (
  id               uuid primary key default gen_random_uuid(),
  module_key       text not null,
  module_label     text not null default '',
  guide_slug       text,
  guide_id         uuid references guides(id) on delete set null,
  commit_sha       text not null,
  commit_range     text,
  commits          jsonb not null default '[]'::jsonb,   -- [{sha, title, body}]
  files            jsonb not null default '[]'::jsonb,   -- the user-facing paths
  diff             text,                                 -- bounded unified diff
  status           text not null default 'queued'
                   check (status in ('queued','running','no_change','applied','proposed',
                                     'rejected','no_guide','failed','reverted','dismissed')),
  needs_update     boolean,
  reason           text,
  change_summary   text,
  prior_body       text,
  prior_summary    text,
  proposed_body    text,
  proposed_summary text,
  error            text,
  applied_at       timestamptz,
  reverted_at      timestamptz,
  decided_by       uuid,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (commit_sha, module_key)
);

create index if not exists idx_guide_sync_runs_guide
  on guide_sync_runs (guide_slug, created_at desc);
create index if not exists idx_guide_sync_runs_status
  on guide_sync_runs (status, created_at desc);

alter table guide_sync_runs enable row level security;

-- The `guide_sync` async_jobs type. The CHECK is rebuilt from the LIVE
-- constraint (wider than any single repo migration) + the new type, per the
-- suite's async_jobs convention.
ALTER TABLE async_jobs DROP CONSTRAINT IF EXISTS async_jobs_job_type_check;

ALTER TABLE async_jobs ADD CONSTRAINT async_jobs_job_type_check CHECK (
  job_type = ANY (ARRAY[
    'website_scrape','page_structure_scrape','page_structure_parse','silo_dedup',
    'gsc_ingest','gsc_page_ingest','gsc_materialize','dataforseo_rank','keyword_market',
    'gsc_research','rank_report','serp_snapshot','maps_scan','maps_report',
    'local_seo_silo','local_seo_generate','local_seo_reoptimize_url','local_seo_reoptimize_page',
    'service_page_plan','rank_location_derive','brand_scan','brand_report','notification_dispatch',
    'reopt_plan','client_report','maps_analyze','asana_monthly','competitor_gbp','review_intel',
    'backlink_intel','content_intel','local_relevance','syndication_scan','syndication_item',
    'freeze_check','citation_check','page_backlink_intel','strategy_review','maps_image_backfill',
    'brand_voice_scan','icp_scan','asana_push','competitor_intel','gbp_metrics_ingest',
    'internal_link_analyze','internal_link_apply','rank_keyword_report','local_seo_action',
    'backlink_snapshot','content_batch_item','task_month_generate','task_due_sweep','task_import_asana',
    'leadoff_tryout','leadoff_scout','leadoff_ai_probe','domain_overview','keyword_gap','link_gap',
    'leadoff_permits','leadoff_geocode','qa_review','leadoff_signal_refresh','leadoff_city_finder',
    'leadoff_income_backfill','leadoff_county_backfill','keyword_research','ecommerce_generate',
    'ecommerce_reoptimize_url','ecommerce_action','github_infer_patterns','illustrate_run',
    'blog_github_publish','gbp_post_publish','gbp_post_generate','gbp_posts_sync','site_inventory',
    'website_provision','website_theme_compile','website_core_pages','website_page_publish',
    'website_deploy_poll','website_page_generate','deliverables_sheet_provision','deliverables_log',
    'deliverable_notes_scan','service_page_score','service_page_reoptimize','keyword_topic_research',
    'keyword_research_report','backlink_lookup','fanout_report','blog_score','blog_reoptimize',
    'fanout_expand','gbp_onboard','gbp_search_keywords','fanout_plan','fanout_regate','fanout_fanout',
    'fanout_architecture','ga4_ingest','gbp_reviews','leadoff_map_refresh','leadoff_placement',
    'leadoff_zip_demand','voice_revalidate','autonomy_run','score_external','everhour_mirror',
    'everhour_sync','plan_handoff','local_seo_matrix_suggest','local_seo_matrix_publish',
    'guide_sync'
  ])
);
