-- Migration: 20260916170000_brand_guides.sql
-- Purpose: Brand Guide Generator — Phase 1 (capture, no browser).
--   docs/modules/brand-guide-generator-prd-v1_0.md §6 (data model) / §10 (phasing).
--
--   Phase 0 (merged #1138) shipped the pure extraction core + the D4 palette
--   spike (GATE PASSED live: css_recovered_any=true, 4/4 sites captured). Phase 1
--   is the real capture pipeline: homepage (the visual authority) + up to 2
--   auto-discovered pages, ScrapeOwl rendered HTML + DataForSEO screenshot →
--   store the deterministic `visual_census`. NO synthesis, NO vibe read, NO
--   render yet (those are Phases 1.5 / 2 / 3).
--
--   * brand_guides — one versioned row per generation (§6). Phase 1 populates
--     `captured` (per-page dom digest / screenshot paths / notes) + `visual_census`
--     (the deterministic extract) and finalizes `done`. `vibe_read` / `synthesized`
--     / render fields land in later phases; `edited` / `awaiting_signoff` are wired
--     when the editor + regulated sign-off gate land (Phase 4).
--
--   NO new regulated flag: the guardrail + the future `awaiting_signoff` gate read
--   the existing `clients.content_compliance_mode` (`!= 'off'`, migration
--   20260828230000) — the suite's live regulated-vertical switch (PRD §5.3 / §6).
--   Nothing in Phase 1 touches it (no synthesis to gate yet).
--
--   Two async_jobs job types are added now so later phases need no further CHECK
--   migration: `brand_guide_generate` (capture → extract → store census; Phase 1)
--   and `brand_guide_render` (enqueued on a human sign-off in Phase 3/4 — the
--   GBP-Profile-Editor "status + a 2nd job" pattern, since in-process jobs can't
--   pause mid-run). Only `brand_guide_generate` is wired in the worker in Phase 1.
--   Both are NOT freeze-gated (generation is observation/deliverable — PRD §5.5).
--
-- RLS on, no client-facing policies (service-role only; API-layer client_id
-- filtering) — matching every other suite module table.

-- ---------------------------------------------------------------------------
-- The versioned guide record
-- ---------------------------------------------------------------------------
create table if not exists brand_guides (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients (id) on delete cascade,
  -- Monotonic per client. Regenerating creates a NEW version; an operator-edited
  -- guide is never silently overwritten (the page-spec / voice-card "edited stays"
  -- pattern — enforced in the API, Phase 4).
  version        integer not null default 1,
  -- queued → capturing → (synthesizing → rendering | awaiting_signoff) → done|error.
  -- Phase 1 uses queued → capturing → done|error; the middle states arrive with
  -- synthesis (Phase 2) + the regulated sign-off gate (Phase 4).
  status         text not null default 'queued'
                   check (status in (
                     'queued', 'capturing', 'synthesizing', 'rendering',
                     'awaiting_signoff', 'done', 'error'
                   )),
  source_url     text,                 -- the URL captured (defaults to clients.website_url)
  captured       jsonb,                -- per-page: dom digest, screenshot paths, capture notes
  visual_census  jsonb,                -- deterministic extract (colors/fonts/scale/logos/…)
  vibe_read      jsonb,                -- aesthetic/vibe read (Phase 1.5)
  synthesized    jsonb,                -- proposed layer (Phase 2)
  edited         boolean not null default false,  -- operator edited → never auto-overwrite (Phase 4)
  storage_path   text,                 -- pdf in the reports bucket (Phase 3)
  pdf_url        text,                 -- signed (Phase 3)
  error          text,
  generated_at   timestamptz,
  created_at     timestamptz not null default now()
);

-- One row per (client, version); also the fast "latest version" lookup.
create unique index if not exists idx_brand_guides_client_version
  on brand_guides (client_id, version desc);

alter table brand_guides enable row level security;

-- ---------------------------------------------------------------------------
-- Private storage bucket for captured page screenshots (service-role + signed
-- URLs). Screenshots are intermediate capture artifacts the Phase-1.5 vibe read
-- reuses (so it doesn't re-pay DataForSEO); kept out of the `reports` bucket,
-- which holds the client-facing PDF deliverable (Phase 3).
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('brand-guides', 'brand-guides', false)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- Widen async_jobs.job_type for brand_guide_generate + brand_guide_render.
-- REBUILT FROM THE LIVE CONSTRAINT (verified 2026-09-15) verbatim + the two new
-- values — the repo migration history has drifted from the live set, so this
-- reproduces the live list and only adds the new values (per CLAUDE.md).
-- ---------------------------------------------------------------------------
alter table public.async_jobs drop constraint if exists async_jobs_job_type_check;

alter table public.async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
    'website_scrape'::text, 'page_structure_scrape'::text, 'page_structure_parse'::text,
    'silo_dedup'::text, 'gsc_ingest'::text, 'gsc_page_ingest'::text, 'gsc_materialize'::text,
    'dataforseo_rank'::text, 'keyword_market'::text, 'gsc_research'::text, 'rank_report'::text,
    'serp_snapshot'::text, 'maps_scan'::text, 'maps_report'::text, 'local_seo_silo'::text,
    'local_seo_generate'::text, 'local_seo_reoptimize_url'::text, 'local_seo_reoptimize_page'::text,
    'service_page_plan'::text, 'rank_location_derive'::text, 'brand_scan'::text, 'brand_report'::text,
    'notification_dispatch'::text, 'reopt_plan'::text, 'client_report'::text, 'maps_analyze'::text,
    'asana_monthly'::text, 'competitor_gbp'::text, 'review_intel'::text, 'backlink_intel'::text,
    'content_intel'::text, 'local_relevance'::text, 'syndication_scan'::text, 'syndication_item'::text,
    'freeze_check'::text, 'citation_check'::text, 'page_backlink_intel'::text, 'strategy_review'::text,
    'maps_image_backfill'::text, 'brand_voice_scan'::text, 'icp_scan'::text, 'asana_push'::text,
    'competitor_intel'::text, 'gbp_metrics_ingest'::text, 'internal_link_analyze'::text,
    'internal_link_apply'::text, 'rank_keyword_report'::text, 'local_seo_action'::text,
    'backlink_snapshot'::text, 'content_batch_item'::text, 'task_month_generate'::text,
    'task_due_sweep'::text, 'task_import_asana'::text, 'leadoff_tryout'::text, 'leadoff_scout'::text,
    'leadoff_ai_probe'::text, 'domain_overview'::text, 'keyword_gap'::text, 'link_gap'::text,
    'leadoff_permits'::text, 'leadoff_geocode'::text, 'qa_review'::text, 'leadoff_signal_refresh'::text,
    'leadoff_city_finder'::text, 'leadoff_income_backfill'::text, 'leadoff_county_backfill'::text,
    'keyword_research'::text, 'ecommerce_generate'::text, 'ecommerce_reoptimize_url'::text,
    'ecommerce_action'::text, 'github_infer_patterns'::text, 'illustrate_run'::text,
    'blog_github_publish'::text, 'gbp_post_publish'::text, 'gbp_post_generate'::text,
    'gbp_posts_sync'::text, 'site_inventory'::text, 'website_provision'::text,
    'website_theme_compile'::text, 'website_core_pages'::text, 'website_page_publish'::text,
    'website_deploy_poll'::text, 'website_page_generate'::text, 'deliverables_sheet_provision'::text,
    'deliverables_log'::text, 'deliverable_notes_scan'::text, 'service_page_score'::text,
    'service_page_reoptimize'::text, 'keyword_topic_research'::text, 'keyword_research_report'::text,
    'backlink_lookup'::text, 'fanout_report'::text, 'blog_score'::text, 'blog_reoptimize'::text,
    'fanout_expand'::text, 'gbp_onboard'::text, 'gbp_search_keywords'::text, 'fanout_plan'::text,
    'fanout_regate'::text, 'fanout_fanout'::text, 'fanout_architecture'::text, 'ga4_ingest'::text,
    'gbp_reviews'::text, 'leadoff_map_refresh'::text, 'leadoff_placement'::text,
    'leadoff_zip_demand'::text, 'voice_revalidate'::text, 'autonomy_run'::text, 'score_external'::text,
    'everhour_mirror'::text, 'everhour_sync'::text, 'plan_handoff'::text,
    'local_seo_matrix_suggest'::text, 'local_seo_matrix_publish'::text, 'guide_sync'::text,
    'gbp_profile_apply'::text, 'gbp_profile_draft'::text, 'gbp_profile_sync'::text,
    'gbp_profile_monitor'::text, 'social_publish'::text, 'social_fanout'::text, 'coverage_audit'::text,
    'google_trends_scan'::text, 'paa_manifest_qa'::text, 'brand_guide_spike'::text,
    'brand_guide_generate'::text, 'brand_guide_render'::text
  ])
);
