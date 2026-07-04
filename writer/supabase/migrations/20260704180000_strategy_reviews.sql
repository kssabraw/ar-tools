-- Migration: 20260704180000_strategy_reviews.sql
-- Purpose: SerMaStr — the Search Marketing Strategist Agent (docs/modules/
--          seo-strategist-agent-plan-v1_0.md §2/§5). One strategy_reviews row
--          per strategist run: the strategic assessment, findings (signal
--          syntheses with SOP citations), proposals (advice objects staged for
--          human Approve/Dismiss — the strategist proposes, never executes),
--          and questions (halt-and-ask items no SOP owns). Proposals are JSONB
--          with per-proposal status patched in place on approve/dismiss.
--          Also widens async_jobs.job_type with 'strategy_review'.
--
-- RLS on, service-role only (the backend uses the service role key).

create table if not exists strategy_reviews (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients(id) on delete cascade,
  trigger       text not null default 'on_demand'
                  check (trigger in ('scheduled', 'escalation', 'on_demand')),
  status        text not null default 'running'
                  check (status in ('running', 'complete', 'failed')),
  model         text,
  assessment    text,                             -- the 1-paragraph strategic read
  findings      jsonb not null default '[]'::jsonb,   -- [{signal_refs[], synthesis, sop_citation}]
  proposals     jsonb not null default '[]'::jsonb,   -- [{title, action, rationale, sop_citation,
                                                      --   est_cost_usd?, effort?, assignee_hint?,
                                                      --   status: proposed|approved|dismissed|expired,
                                                      --   requires: none|approval|senior}]
  questions     jsonb not null default '[]'::jsonb,   -- [text] — halt-and-ask items
  input_digest  jsonb,                            -- the digest the run reasoned over
  token_usage   jsonb,                            -- {input_tokens, output_tokens, drilldowns[]}
  error         text,
  created_at    timestamptz not null default now(),
  completed_at  timestamptz
);

create index if not exists idx_strategy_reviews_client
  on strategy_reviews (client_id, created_at desc);

alter table strategy_reviews enable row level security;

-- Widen the async_jobs job_type CHECK (strictly additive).
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
    'strategy_review'
  ]));
