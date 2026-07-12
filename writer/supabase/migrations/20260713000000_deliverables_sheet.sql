-- Migration: 20260712220000_deliverables_sheet.sql
-- Purpose: Deliverables Sheet Sync (docs/modules/deliverables-sheet-sync-prd-v1_0.md).
--   Auto-maintain each client's Google "deliverables" sheet: append a row when
--   a task completes (type / keyword / link / date) and watch the client-facing
--   Notes column, alerting staff on new notes.
--
--   * clients.deliverables_sheet_id — the client's native Google Sheet id
--     (null = sync disabled for this client). Normally auto-provisioned by the
--     deliverables_sheet_provision job (Drive files.copy from the master
--     template); can also be set manually via the admin endpoint.
--   * deliverables_sync_log — one row per task ever considered for logging.
--     The UNIQUE task_id is the write-side idempotency guard: a task that is
--     completed, reopened, and completed again inserts once and is a no-op the
--     second time (PRD §8). Also the observability trail (status/error/row).
--   * deliverables_notes_state — one row per client: when the Notes column was
--     last scanned (the poller's interval gate) + the per-row snapshot the
--     diff runs against ({"<tab>!<row>": "<hash>"}).
--   * async_jobs job_type CHECK widened with the three new job types
--     (deliverables_sheet_provision / deliverables_log / deliverable_notes_scan),
--     preserving the full live set (which is wider than any single repo
--     migration file — keep every known type listed).

alter table clients add column if not exists deliverables_sheet_id text;

create table if not exists deliverables_sync_log (
  id           uuid primary key default gen_random_uuid(),
  task_id      uuid not null unique references tasks(id) on delete cascade,
  client_id    uuid not null references clients(id) on delete cascade,
  sheet_id     text,
  tab          text,                     -- 'content' | 'links' (logical tab)
  row_values   jsonb,                    -- the appended row (A..D), for audit
  link_url     text,                     -- resolved deliverable URL (null = missing link)
  status       text not null default 'pending',  -- pending | written | skipped | failed
  error        text,
  created_at   timestamptz not null default now(),
  written_at   timestamptz
);

create index if not exists idx_deliverables_sync_log_client
  on deliverables_sync_log (client_id, created_at desc);

alter table deliverables_sync_log enable row level security;

create table if not exists deliverables_notes_state (
  client_id    uuid primary key references clients(id) on delete cascade,
  sheet_id     text,
  snapshot     jsonb not null default '{}'::jsonb,  -- {"<tab>!<row>": "<note hash>"}
  scanned_at   timestamptz,
  updated_at   timestamptz not null default now()
);

alter table deliverables_notes_state enable row level security;

-- Widen the async_jobs job_type CHECK (full live set + the three new types).
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
  'leadoff_permits','leadoff_geocode','qa_review',
  'deliverables_sheet_provision','deliverables_log','deliverable_notes_scan'
));
