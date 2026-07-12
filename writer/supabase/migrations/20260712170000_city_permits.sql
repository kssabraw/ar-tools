-- Migration: 20260712170000_city_permits.sql
-- Purpose: app-side Census building-permits "prospect pipeline" store
--          (docs/modules/leadoff-permits-plan-v1_0.md, app-side revision).
--          APP-OWNED on purpose: leadoff_board is drop/recreated by the
--          scanner loader, so permits columns written there would be wiped
--          on reload. city_permits lives in public, keyed by the scanner's
--          city_id, and is joined onto board/brief reads at request time.
--          Data source is the keyless BPS flat files (no API key, $0);
--          refreshed by the async leadoff_permits job.

create table if not exists city_permits (
  city_id          bigint primary key,   -- market_scanner.cities id
  city_name        text not null,
  state_code       text not null,
  vintage          integer not null,     -- latest full BPS year in the row
  permit_units_1yr integer,
  permits_pc       double precision,     -- units per 1k residents
  permit_sf_share  double precision,     -- 1-unit share of total units
  permit_trend     double precision,     -- latest year vs mean of prior 3
  permit_flag      text not null default '-'
                     check (permit_flag in ('HOT-pipeline','COLD-pipeline','-')),
  permit_source    text not null default 'place'
                     check (permit_source in ('place','county','none')),
  pulled_at        timestamptz not null default now()
);

alter table city_permits enable row level security;

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
  'leadoff_tryout','leadoff_scout','leadoff_ai_probe',
  'domain_overview','keyword_gap','link_gap',
  'leadoff_permits'
));
