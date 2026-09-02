-- Local SEO — service × location matrix (docs/modules/local-seo-matrix-plan-v1_0.md §2).
--
-- A durable per-client matrix: two axes (services, locations) and one cell per
-- combination, each cell carrying its coverage state and a link to the page it
-- produced. Layers on #953's cross-product parser (the cell source) and #951's
-- existing-page marking; adds persistence, gap-fill, sibling links, drip
-- release and bulk publish. `local_seo_pages` is untouched — a page learns about
-- its cell only through the cell's page_id.

create table if not exists local_seo_matrices (
  id                    uuid primary key default gen_random_uuid(),
  client_id             uuid not null references clients(id) on delete cascade,
  name                  text not null,
  -- The metro anchor: a DataForSEO-resolved area every cell generates against
  -- unless its location row carries its own code (plan §3.2).
  location              text not null,
  location_code         int,
  -- Axes as structured rows: [{label, slug}] and
  -- [{name, slug, location_code?, canonical?, source}].
  services              jsonb not null default '[]'::jsonb,
  locations             jsonb not null default '[]'::jsonb,
  -- How a cell's URL is derived (sibling links + the WordPress slug). Tokens
  -- {service} and {location}; presets in plan §3.3.
  url_pattern           text not null default '/{service}-{location}/',
  base_url              text,
  page_template_url     text,
  entity_provider       text,
  -- Publish defaults used by the drip's publish_after and by "Publish all".
  publish_destination   text not null default 'google_docs'
                          check (publish_destination in ('google_docs', 'wordpress', 'github')),
  publish_status        text not null default 'draft'
                          check (publish_status in ('draft', 'publish')),
  -- Drip release — one schedule per matrix; columns mirror website_releases.
  release_enabled       boolean not null default false,
  release_mode          text not null default 'daily'
                          check (release_mode in ('daily', 'weekly', 'monthly')),
  release_weekday       int check (release_weekday between 0 and 6),
  release_day_of_month  int check (release_day_of_month between 1 and 28),
  release_per_count     int not null default 1 check (release_per_count >= 1),
  release_status        text not null default 'active'
                          check (release_status in ('active', 'complete', 'paused')),
  release_next_run_at   timestamptz,
  release_last_run_at   timestamptz,
  created_by            uuid references profiles(id),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index if not exists local_seo_matrices_client_idx
  on local_seo_matrices (client_id, created_at desc);

create index if not exists local_seo_matrices_release_due_idx
  on local_seo_matrices (release_next_run_at)
  where release_enabled and release_status = 'active';

create table if not exists local_seo_matrix_cells (
  id               uuid primary key default gen_random_uuid(),
  matrix_id        uuid not null references local_seo_matrices(id) on delete cascade,
  client_id        uuid not null references clients(id) on delete cascade,
  service_label    text not null,
  service_slug     text not null,
  location_name    text not null,
  location_slug    text not null,
  -- Axis positions, so a release batch can walk the grid location-major.
  service_order    int not null default 0,
  location_order   int not null default 0,
  keyword          text not null,        -- "<service> <location>", deterministic
  path             text not null,        -- rendered from the matrix url_pattern
  -- Coverage state machine (plan §3.5 / §5). 'found' / 'on_site' are
  -- pre-existing coverage; 'skipped' is a cell dropped from the axes that kept
  -- its page.
  status           text not null default 'missing' check (status in (
                     'missing', 'found', 'on_site', 'queued', 'generating', 'done',
                     'failed', 'publishing', 'published', 'publish_failed',
                     'publish_blocked', 'skipped')),
  page_id          uuid references local_seo_pages(id) on delete set null,
  job_id           uuid,                 -- latest generate / publish job
  url              text,                 -- live / published URL when known
  released_at      timestamptz,          -- the drip's exactly-once claim
  link_coverage    jsonb,                -- {expected, present, missing:[...]}
  error            text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (matrix_id, service_slug, location_slug)
);

create index if not exists local_seo_matrix_cells_matrix_status_idx
  on local_seo_matrix_cells (matrix_id, status);
create index if not exists local_seo_matrix_cells_page_idx
  on local_seo_matrix_cells (page_id);

-- RLS — mirrors local_seo_pages: authenticated read; the backend writes with the
-- service-role key and bypasses these.
alter table local_seo_matrices enable row level security;
alter table local_seo_matrix_cells enable row level security;

create policy "authenticated users read local_seo_matrices"
  on local_seo_matrices for select
  using (auth.role() = 'authenticated');

create policy "authenticated users read local_seo_matrix_cells"
  on local_seo_matrix_cells for select
  using (auth.role() = 'authenticated');

-- Two new async_jobs types: `local_seo_matrix_suggest` (the Suggest services /
-- locations job) and `local_seo_matrix_publish` (one per cell for "Publish all
-- done cells"). The CHECK is rebuilt from the LIVE constraint (wider than any
-- single repo migration) + the new types, per the suite's async_jobs convention.
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
    'everhour_sync','plan_handoff',
    'local_seo_matrix_suggest','local_seo_matrix_publish'
  ])
);
