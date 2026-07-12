-- Migration: 20260712180000_competitor_locations.sql
-- Purpose: app-owned home for the LeadOff proximity signal's competitor
--          coordinates (docs/modules/leadoff-proximity-plan-v1_0.md §5c).
--          The scanner's serp_results.csv kept a text `address` per
--          competitor but the loaded market_scanner.serp_top5 dropped it and
--          coordinates were never saved. A one-time desktop uploader pushes
--          the (city_id, category_id, rank_position, business_name, domain,
--          review_count, address) rows here; the deployed worker then
--          geocodes them (free US Census Geocoder for addressed rows;
--          optional paid Outscraper fill for service-area businesses whose
--          address is blank) — all app-side, no re-pull.
--
-- APP-OWNED (public schema) on purpose: market_scanner.* is drop/recreated
-- by the scanner loader (would wipe this + strip grants). Keyed by the
-- scanner's city_id/category_id so it joins back to the board.

create table if not exists competitor_locations (
  id            uuid primary key default gen_random_uuid(),
  city_id       bigint not null,
  category_id   text not null,
  rank_position integer not null,
  business_name text not null,
  domain        text,
  review_count  double precision,
  address       text,                 -- raw street address; null for SABs
  lat           double precision,
  lng           double precision,
  geo_source    text check (geo_source in ('census','outscraper','none') or geo_source is null),
  geocoded_at   timestamptz,
  imported_at   timestamptz not null default now()
);

-- one row per competitor slot (matches the serp_top5 grain); re-imports upsert
create unique index if not exists uq_competitor_locations_slot
  on competitor_locations (city_id, category_id, rank_position);
create index if not exists idx_competitor_locations_market
  on competitor_locations (city_id, category_id);
-- the geocode job's work queue: addressed rows not yet geocoded
create index if not exists idx_competitor_locations_ungeocoded
  on competitor_locations (city_id) where lat is null and address is not null;

alter table competitor_locations enable row level security;

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
  'leadoff_permits','leadoff_geocode'
));
