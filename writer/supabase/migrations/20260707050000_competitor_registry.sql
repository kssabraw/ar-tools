-- Migration: 20260707050000_competitor_registry.sql
-- Purpose: Unified competitive intelligence (strategist roadmap phase 2).
--   * client_competitors — the per-client NAMED competitor registry. Until now
--     competitor identity lived scattered per-module (maps leaderboards by
--     place_id, backlink/serp rows by domain, AI-visibility competitors by
--     name); this table unifies them so one competitor can be profiled across
--     every module. Rows are auto-discovered (maps leaderboard, recurring
--     organic top-10 domains, AI-visibility list) and manually added; auto
--     rows are never auto-deactivated (human curation only).
--   * competitor_pages — the content-watch ledger: every URL seen on a
--     competitor's site (sitemap → DataForSEO site: fallback, reusing
--     site_page_index). The first index of a competitor is a BASELINE
--     (is_baseline=true) so it never reads as "300 new pages"; later syncs
--     insert only unseen URLs, which are the "competitor published new
--     content" signal.
--   * async_jobs.job_type gains 'competitor_intel' (weekly registry sync +
--     content watch per client, on the shared scheduler).

create table if not exists client_competitors (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  name            text not null,
  domain          text,                  -- normalized (no scheme/www); null for maps-only competitors without sites
  place_id        text,                  -- GBP identity when known (maps/GBP joins)
  sources         text[] not null default '{}',   -- maps | organic | ai_visibility | manual
  active          boolean not null default true,
  notes           text,
  last_synced_at  timestamptz,           -- content watch / profile sync clock
  first_seen      timestamptz not null default now(),
  last_seen       timestamptz not null default now(),
  created_at      timestamptz not null default now()
);

create index if not exists idx_client_competitors_client
  on client_competitors (client_id, active);
create unique index if not exists uq_client_competitors_domain
  on client_competitors (client_id, domain) where domain is not null;
create unique index if not exists uq_client_competitors_place
  on client_competitors (client_id, place_id) where place_id is not null;

alter table client_competitors enable row level security;

create table if not exists competitor_pages (
  id              uuid primary key default gen_random_uuid(),
  competitor_id   uuid not null references client_competitors(id) on delete cascade,
  client_id       uuid not null references clients(id) on delete cascade,
  url             text not null,
  is_baseline     boolean not null default false,  -- part of the first index, not "new content"
  first_seen      timestamptz not null default now()
);

create unique index if not exists uq_competitor_pages_url
  on competitor_pages (competitor_id, url);
create index if not exists idx_competitor_pages_client_seen
  on competitor_pages (client_id, first_seen desc);

alter table competitor_pages enable row level security;

alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'silo_dedup', 'gsc_ingest',
    'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank', 'keyword_market',
    'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan', 'maps_report',
    'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
    'local_seo_reoptimize_page', 'service_page_plan', 'rank_location_derive',
    'brand_scan', 'brand_report', 'notification_dispatch', 'reopt_plan',
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp', 'review_intel',
    'backlink_intel', 'content_intel', 'local_relevance',
    'syndication_scan', 'syndication_item',
    'freeze_check', 'citation_check', 'page_backlink_intel',
    'strategy_review',
    'brand_voice_scan', 'icp_scan',
    'asana_push',
    'competitor_intel'
  ]));
