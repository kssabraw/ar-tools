-- GBP Profile Editor module (services/gbp_profile_service.py): edit a client's
-- Google Business Profile description / services / hours via the Business
-- Information API v1 locations.patch. Every edit is AI-drafted or manual, then
-- reviewed, then applied on an EXPLICIT click — nothing is auto-applied
-- (ADR 0004). One row per proposed/applied edit; the live field value is always
-- read on demand (locations.get), so there is no cached "current values" table —
-- current_value is the point-in-time snapshot for the diff + the re-read-and-diff
-- baseline at Apply.
--
-- Statuses:
--   draft         — proposed (manual / ai / strategist); awaiting a human Apply
--   applying      — the gbp_profile_apply job is in flight
--   applied       — the patch landed AND a re-read confirms the live value
--   pending_review — Google queued the edit; the gbp_profile_sync reconciler chases it
--   rejected      — Google rejected the edit (content policy / invalid)
--   live_changed  — the live value drifted out-of-band since the draft; re-review
--   failed        — the apply errored (network / auth / read-only listing)
--
-- RLS on, service-role only (reads/writes go through the platform API).

create table if not exists gbp_profile_edits (
  id               uuid primary key default gen_random_uuid(),
  client_id        uuid not null references clients(id) on delete cascade,
  location_row_id  uuid not null references gbp_locations(id) on delete cascade,
  field            text not null check (field in ('description','hours','services')),
  source           text not null default 'manual' check (source in ('manual','ai','strategist')),
  current_value    jsonb,                      -- snapshot at draft time (re-read-and-diff baseline)
  proposed_value   jsonb not null,             -- the edit to apply
  status           text not null default 'draft'
                   check (status in ('draft','applying','applied','pending_review',
                                     'rejected','live_changed','failed')),
  google_pending   boolean not null default false,  -- Google queued it for review
  sync_attempts    int not null default 0,     -- reconciler backoff progress
  next_sync_at     timestamptz,                -- reconciler self-continuation clock
  error            text,
  applied_at       timestamptz,
  created_by       uuid,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

-- Per-field history read (newest first).
create index if not exists idx_gbp_profile_edits_history
  on gbp_profile_edits (client_id, field, created_at desc);

-- The reconciler sweep: only pending_review rows with a due clock.
create index if not exists idx_gbp_profile_edits_sync
  on gbp_profile_edits (next_sync_at)
  where status = 'pending_review';

alter table gbp_profile_edits enable row level security;

-- The three new async_jobs types. The CHECK is rebuilt from the LIVE constraint
-- (wider than any single repo migration) + the new types, per the suite's
-- async_jobs convention (see 20260902180000_guide_sync.sql).
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
    'guide_sync','gbp_profile_apply','gbp_profile_draft','gbp_profile_sync'
  ])
);
