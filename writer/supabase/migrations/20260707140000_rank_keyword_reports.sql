-- Migration: 20260707140000_rank_keyword_reports.sql
-- Purpose: Organic Rank Analysis report — the per-keyword deep-dive (the organic
--   analogue of the Maps Local Rank Analysis report).
--   * rank_keyword_reports — one dated row per generated per-keyword report,
--     carrying the deterministic analysis blob (report_analytics: trajectory +
--     competitive landscape + authority gap + winnability + forecast + what
--     changed), the ranked gap-to-close work order (report_work_order), the
--     headline priority, the Sonnet narrative (report_md), and the published
--     Google-Doc link. Kept as a table (not columns on a scan result, as maps
--     does) because organic reports are per-keyword and reuse the latest stored
--     SERP snapshot rather than riding a fresh capture. Dated history like the
--     maps report — the newest row per keyword is "current".
--   * async_jobs.job_type gains 'rank_keyword_report' (on-demand per keyword,
--     auto on a rank-drop alert, and weekly per keyword on the shared scheduler).

create table if not exists rank_keyword_reports (
  id                 uuid primary key default gen_random_uuid(),
  client_id          uuid not null references clients(id) on delete cascade,
  keyword_id         uuid not null references tracked_keywords(id) on delete cascade,
  keyword            text not null,
  snapshot_id        uuid references serp_snapshots(id) on delete set null,  -- the landscape analyzed
  trigger            text not null default 'on_demand',   -- on_demand | drop | weekly
  status             text not null default 'pending',     -- pending | complete | failed
  error              text,
  report_md          text,                 -- the Sonnet narrative (client-facing Markdown)
  report_headline    text,                 -- the one-line executive headline
  report_analytics   jsonb,                -- the full deterministic analysis blob
  report_work_order  jsonb,                -- the ranked gap-to-close action list
  priority           numeric,             -- winnability × value × urgency (headline number)
  doc_url            text,                 -- published Google Doc (best-effort)
  generated_at       timestamptz,
  created_at         timestamptz not null default now()
);

create index if not exists idx_rank_keyword_reports_keyword
  on rank_keyword_reports (keyword_id, generated_at desc nulls last);
create index if not exists idx_rank_keyword_reports_client
  on rank_keyword_reports (client_id, generated_at desc nulls last);
-- One in-flight (pending) report per keyword — the enqueue path dedups on this.
create unique index if not exists uq_rank_keyword_reports_pending
  on rank_keyword_reports (keyword_id) where status = 'pending';

alter table rank_keyword_reports enable row level security;

-- Re-check the live constraint before applying (another PR may have added a job
-- type since this list was copied) so nothing is silently dropped.
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
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp',
    'review_intel', 'backlink_intel', 'content_intel', 'local_relevance',
    'syndication_scan', 'syndication_item', 'freeze_check', 'citation_check',
    'page_backlink_intel', 'strategy_review', 'maps_image_backfill',
    'brand_voice_scan', 'icp_scan', 'asana_push', 'competitor_intel',
    'gbp_metrics_ingest', 'internal_link_analyze', 'internal_link_apply',
    'rank_keyword_report'
  ]));
