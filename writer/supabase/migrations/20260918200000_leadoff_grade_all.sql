-- LeadOff grade-all — the board/cache-aware bulk "rank every city for a service"
-- sweep. The cross-city sort the precomputed board can't do: it reaches the
-- sub-30k + off-catalog cities the board never scanned by grading the exact
-- city×service cells on demand.
--
-- Cheapest-path-first per city, exactly like the single-cell grader:
--   1. board-first (FREE)  — an exact city×category already on leadoff_board.
--   2. cache (FREE)        — a recent live grade for this city×service.
--   3. live (PAID, ~$0.06) — one Google Ads keyword task + one Maps SERP @ 13z.
-- Each live grade is persisted to leadoff_grades (the single-cell cache) so the
-- sweep is naturally idempotent/resumable on a reaper requeue and future
-- lookups of those cells are free.
--
-- Spend is bounded three ways: the caller's per-run max_spend ceiling (a hard
-- stop on live grading), a dedicated per-user daily grade_all budget (separate
-- from the tight $5 single-grade guard), and a candidate-city cap. Nothing
-- spends without staff auth + an explicit confirm + a max_spend ceiling.

create table if not exists public.leadoff_grade_all_runs (
    id             uuid primary key default gen_random_uuid(),
    requested_by   uuid,
    service_query  text not null,             -- the raw text the user typed
    category_name  text not null,             -- resolved catalog / cleaned typed service
    category_id    text,                      -- catalog id when the service is on-catalog
    on_catalog     boolean not null default false,
    state          text,                      -- optional 2-letter scope filter
    min_pop        integer not null default 10000,
    max_pop        integer,
    capture        numeric not null default 0.10,
    lead_tier      text    not null default 'mid',
    cpl            numeric,                    -- lead value used (catalog CPL or the flagged default)
    cpl_default    boolean not null default false,
    max_spend      double precision not null default 0,  -- caller ceiling on LIVE spend this run
    est_cost       double precision,          -- estimate recorded at enqueue
    status         text    not null default 'pending',   -- pending|running|complete|partial|failed
    results        jsonb,                     -- ranked normalized rows (exp_val desc)
    result_meta    jsonb,                     -- {cities,on_board,cached,needs_live,graded_live,budget_skipped,cost_spent,budget_reached}
    error          text,
    created_at     timestamptz not null default now(),
    completed_at   timestamptz
);

create index if not exists idx_leadoff_grade_all_recent
    on public.leadoff_grade_all_runs (created_at desc);

alter table public.leadoff_grade_all_runs enable row level security;
-- service-role only (the backend uses the service key); no anon/authenticated policy.

-- Record the grade_all sweep's spend on the per-user daily ledger (its own
-- action, so it's guarded against a dedicated daily cap — see config
-- leadoff_grade_all_daily_budget_usd — leaving the tight $5 single-grade
-- leadoff_daily_budget_usd guard intact). Rebuilt from the LIVE constraint set
-- (verified 2026-09-18) + 'grade_all'.
alter table public.leadoff_spend drop constraint if exists leadoff_spend_action_check;
alter table public.leadoff_spend add constraint leadoff_spend_action_check
    check (action = any (array[
        'tryout','scout','ai_probe','city_finder','map_refresh','grade','grade_all'
    ]));

-- Register the leadoff_grade_all async job type (rebuilt from the LIVE
-- constraint — verified 2026-09-18 — the repo migrations lag it, so this list
-- is the live set + leadoff_grade_all).
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
        'social_competitor_research','leadoff_grade','leadoff_grade_all'
    ]));
