-- Migration: 20260704170000_citations_page_backlinks.sql
-- Purpose: The offpage agent's two deferred checks, now built:
--
--   1. Citation liveness (Organic SOP §A.8 "citations still live";
--      _ORCHESTRATOR.md §Agents "citation status"): client_citations stores
--      the citation URLs the team orders (pasted in bulk); a weekly liveness
--      sweep fetches each and flags newly-dead listings via a citation_loss
--      offpage alert. Consistency (NAP matching) stays with the external
--      Citation Audit tool — this is liveness only.
--
--   2. Per-page RD imbalance (Link Building SOP §health checks: "no inner
--      page should carry far more RD than the home page"):
--      page_backlink_profiles stores monthly page-level DataForSEO Backlinks
--      summaries (homepage + money pages); an inner page materially
--      out-RD'ing the homepage opens an rd_imbalance offpage alert
--      (non-escalating hygiene — the SEO NEO assignee rebalances).
--
-- Also widens offpage_alerts.alert_type and async_jobs.job_type accordingly.
-- RLS on, service-role only (the backend uses the service role key).

create table if not exists client_citations (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients(id) on delete cascade,
  url           text not null,
  status        text not null default 'unknown'
                  check (status in ('live', 'dead', 'blocked', 'unknown')),
                  -- blocked = the directory bot-blocks us (403/429) — counts as
                  -- alive for alerting (fail-open; only hard 404/410/DNS = dead)
  consecutive_failures integer not null default 0,
  nap_found     boolean,                 -- business name seen in the HTML (best-effort)
  http_status   integer,
  last_checked_at timestamptz,
  last_ok_at    timestamptz,
  created_at    timestamptz not null default now(),
  unique (client_id, url)
);

create index if not exists idx_client_citations_client_status
  on client_citations (client_id, status);

create table if not exists page_backlink_profiles (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references clients(id) on delete cascade,
  url               text not null,
  is_homepage       boolean not null default false,
  url_rating        numeric,              -- DataForSEO rank (UR-equivalent)
  referring_domains integer,
  backlinks         integer,
  captured_at       timestamptz not null default now(),
  created_at        timestamptz not null default now()
);

create index if not exists idx_page_backlink_profiles_client_captured
  on page_backlink_profiles (client_id, captured_at desc);

alter table client_citations enable row level security;
alter table page_backlink_profiles enable row level security;

-- Widen offpage_alerts.alert_type for the two new checks.
alter table offpage_alerts drop constraint offpage_alerts_alert_type_check;
alter table offpage_alerts
  add constraint offpage_alerts_alert_type_check
  check (alert_type in ('rd_loss', 'rd_spike', 'citation_loss', 'rd_imbalance'));

-- Widen async_jobs.job_type (preserve the full set from 20260704130000_client_freezes).
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
    'freeze_check', 'citation_check', 'page_backlink_intel'
  ]));
