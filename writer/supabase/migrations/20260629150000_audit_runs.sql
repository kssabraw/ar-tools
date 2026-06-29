-- ============================================================
-- audit_runs — engagement-scoped audit results (design §3.1, §6.2–6.4)
-- ============================================================
-- One row per audit kind per cycle. The Strategy Engine reads these to feed
-- richer actions. Phase 3 begins with site_technical; serp/maps/performance
-- kinds are reserved for the synthesis audits + baseline. Additive.
-- ============================================================

create table if not exists audit_runs (
  id            uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references engagements(id) on delete cascade,
  kind          text not null
                  check (kind in (
                    'site_technical', 'serp_competition',
                    'maps_competition', 'performance_baseline',
                    'backlink_gap', 'local_citation'
                  )),
  status        text not null default 'pending'
                  check (status in ('pending', 'running', 'complete', 'failed')),
  result        jsonb,
  score         numeric,
  error         text,
  created_at    timestamptz not null default now(),
  completed_at  timestamptz
);

create index if not exists idx_audit_runs_engagement
  on audit_runs (engagement_id, created_at desc);

alter table audit_runs enable row level security;

-- ── widen async_jobs.job_type for the audit jobs ─────────────────────────────
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
    'client_report',
    'site_audit', 'backlink_audit', 'citation_audit'
  ]));
