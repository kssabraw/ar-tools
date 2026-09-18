-- LeadOff on-demand grader — the "type a city + a service → get a grade" cache.
--
-- The grader answers a single city × service on demand: board-first (free, from
-- the precomputed leadoff_board), else a cheap live single-cell grade (one
-- Google Ads keyword task + one Maps SERP @ 13z, ~a few cents) cached here so a
-- repeat lookup is free. This is the app-owned complement to the scanner's
-- precomputed board — it never touches market_scanner.
--
-- Unlike the board/tryout, the live path does NOT apply the vol>=20 demand gate:
-- the user asked for THIS cell, so it is graded regardless and the demand is
-- surfaced (grade.thin_demand when < 20). The gate only bounded PRECOMPUTE cost.

create table if not exists public.leadoff_grades (
    id            uuid primary key default gen_random_uuid(),
    requested_by  uuid,
    city_id       integer not null,
    city_name     text,
    state_code    text,
    -- category_id is the board/catalog id when the typed service resolves to a
    -- known GBP category; NULL for an off-catalog service (still gradeable live).
    category_id   text,
    category_name text not null,
    service_query text,            -- the raw text the user typed
    -- cache_key = f"{city_id}|{norm(category_name)}" — the freshness lookup key.
    cache_key     text not null,
    capture       numeric not null default 0.10,
    lead_tier     text    not null default 'mid',
    on_catalog    boolean not null default false,
    cpl_default   boolean not null default false,  -- true = default lead value used
    source        text    not null default 'live', -- 'live' (board/cache served inline)
    status        text    not null default 'running',
    grade         jsonb,           -- the full grade row (grade/exp_val/rankab/roi/beatability/competitors/…)
    error         text,
    pulled_at     timestamptz,
    created_at    timestamptz not null default now(),
    completed_at  timestamptz
);

-- freshness lookup: newest complete grade for a city×service
create index if not exists idx_leadoff_grades_cache
    on public.leadoff_grades (cache_key, pulled_at desc)
    where status = 'complete';

create index if not exists idx_leadoff_grades_recent
    on public.leadoff_grades (created_at desc);

alter table public.leadoff_grades enable row level security;
-- service-role only (the backend uses the service key); no anon/authenticated policy.

-- Record the grade action's spend on the per-user daily ledger.
alter table public.leadoff_spend drop constraint if exists leadoff_spend_action_check;
alter table public.leadoff_spend add constraint leadoff_spend_action_check
    check (action = any (array[
        'tryout','scout','ai_probe','city_finder','map_refresh','grade'
    ]));

-- Register the leadoff_grade async job type (rebuilt from the LIVE constraint —
-- the repo migrations lag it, so this list is the live set + leadoff_grade).
alter table public.async_jobs drop constraint if exists async_jobs_job_type_check;
alter table public.async_jobs add constraint async_jobs_job_type_check
    check (job_type = any (array[
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
        'everhour_sync','plan_handoff','local_seo_matrix_suggest','local_seo_matrix_publish','guide_sync',
        'gbp_profile_apply','gbp_profile_draft','gbp_profile_sync','gbp_profile_monitor','social_publish',
        'social_fanout','social_profile_provision','coverage_audit','google_trends_scan','paa_manifest_qa',
        'brand_guide_spike','brand_guide_generate','brand_guide_render','content_gap_scan',
        'social_competitor_research','leadoff_grade'
    ]));
