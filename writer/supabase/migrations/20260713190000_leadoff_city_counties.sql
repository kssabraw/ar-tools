-- LeadOff — per-city county map (app-owned; the scanner's cities table has no
-- county, and its loader drop/recreates that table so we can't add a column to
-- it). Populated by the leadoff_county_backfill job, which reverse-geocodes each
-- city's stored lat/lng to a county via the free US Census geographies endpoint.
-- Powers a county filter on the board ("show me every scanned market in Hudson
-- County, NJ").

create table if not exists public.city_counties (
  city_id     bigint primary key,
  city_name   text,
  state_code  text,
  county_name text,               -- full Census name, e.g. "Hudson County", "Orleans Parish"
  county_fips text,               -- 5-digit state+county GEOID
  source      text not null default 'census',
  updated_at  timestamptz not null default now()
);

create index if not exists city_counties_state_county_idx
  on public.city_counties (state_code, lower(county_name));
create index if not exists city_counties_fips_idx
  on public.city_counties (county_fips);

-- Register the new async job type (full array reproduced from the live
-- constraint, which has drifted wider than any single repo migration).
alter table public.async_jobs drop constraint if exists async_jobs_job_type_check;
alter table public.async_jobs add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape','page_structure_scrape','silo_dedup','gsc_ingest',
    'gsc_page_ingest','gsc_materialize','dataforseo_rank','keyword_market',
    'gsc_research','rank_report','serp_snapshot','maps_scan','maps_report',
    'local_seo_silo','local_seo_generate','local_seo_reoptimize_url',
    'local_seo_reoptimize_page','service_page_plan','rank_location_derive',
    'brand_scan','brand_report','notification_dispatch','reopt_plan',
    'client_report','maps_analyze','asana_monthly','competitor_gbp',
    'review_intel','backlink_intel','content_intel','local_relevance',
    'syndication_scan','syndication_item','freeze_check','citation_check',
    'page_backlink_intel','strategy_review','maps_image_backfill',
    'brand_voice_scan','icp_scan','asana_push','competitor_intel',
    'gbp_metrics_ingest','internal_link_analyze','internal_link_apply',
    'rank_keyword_report','local_seo_action','backlink_snapshot',
    'content_batch_item','task_month_generate','task_due_sweep',
    'task_import_asana','leadoff_tryout','leadoff_scout','leadoff_ai_probe',
    'domain_overview','keyword_gap','link_gap','leadoff_permits',
    'leadoff_geocode','qa_review','leadoff_signal_refresh','leadoff_city_finder',
    'leadoff_income_backfill','leadoff_county_backfill','keyword_research'
  ]));
