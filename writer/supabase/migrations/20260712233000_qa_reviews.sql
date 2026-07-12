-- Migration: 20260712233000_qa_reviews.sql
-- Purpose: QA Agent Phase 0 (docs/modules/qa-agent-plan-v1_0.md) — the
--          qa_reviews history table + the qa_review async job type.
--
-- NOTE (build deviation from the plan doc, recorded there too): the plan
-- proposed a new 'for_qa' status, but migration 20260712220000 had already
-- added 'in_qa' to the live workflow (Not Started → In Progress → In QA →
-- Sent to Client → …), and task_service's auto-advance Rule B already moves
-- tasks into it — so the QA agent triggers on the EXISTING in_qa status and
-- no status row is added here.
--
-- RLS on, NO client-facing policies (service-role only) — the suite convention.

create table if not exists qa_reviews (
  id           uuid primary key default gen_random_uuid(),
  task_id      uuid not null references tasks(id) on delete cascade,
  client_id    uuid references clients(id) on delete cascade,
  rubric       text not null,             -- qa_signals rubric key (gbp_posts, citations, …)
  verdict      text not null check (verdict in ('pass', 'fail', 'needs_human', 'skipped')),
  -- Composite only where a numeric score exists (website pages via the
  -- 8-engine scorer / structural fidelity); presence-check rubrics are
  -- pass/fail on their blocking set and carry null here.
  composite    numeric(5, 2),
  checks       jsonb not null default '[]'::jsonb,  -- [{key, label, ok, blocking, note}]
  issues       jsonb not null default '[]'::jsonb,  -- failed blocking labels (the rework list)
  urls         jsonb not null default '[]'::jsonb,  -- deliverable URLs examined
  narrative    text,                                 -- short assembled summary
  trigger      text not null default 'status',       -- 'status' | 'manual'
  created_at   timestamptz not null default now()
);

create index if not exists idx_qa_reviews_task
  on qa_reviews (task_id, created_at desc);
create index if not exists idx_qa_reviews_client
  on qa_reviews (client_id, created_at desc);

alter table qa_reviews enable row level security;

-- Widen the async_jobs job_type CHECK with 'qa_review', preserving the FULL
-- live set (the live constraint is wider than any single repo migration —
-- always rebuild from the live definition, per the task-manager precedent).
alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (job_type in (
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
  'rank_keyword_report', 'local_seo_action', 'backlink_snapshot',
  'content_batch_item', 'task_month_generate', 'task_due_sweep',
  'task_import_asana', 'leadoff_tryout', 'leadoff_scout', 'leadoff_ai_probe',
  'domain_overview', 'keyword_gap', 'link_gap', 'leadoff_permits',
  'leadoff_geocode',
  'qa_review'
));
