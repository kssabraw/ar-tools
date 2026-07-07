-- ============================================================
-- Internal-linking analyzer + injector — proposed-edit store
-- ============================================================
-- The internal-linking analyzer finds opportunities to link one of the client's
-- pages to another (topically relevant) and stores each as a proposed edit.
-- Because injecting a link MUTATES A LIVE SITE, each edit carries its own
-- approve/deny lifecycle (a human is notified, reviews, and approves) — only
-- then does the WordPress injector write it. Non-WordPress sites get
-- recommend-only edits (injectable=false): the team applies them by hand.
--
-- Client-scoped (no engagement coupling on this branch). Additive.
-- ============================================================

create table if not exists internal_link_edits (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients(id) on delete cascade,
  batch_id       uuid not null,                          -- groups one analysis run
  source_url     text not null,                          -- page the link is added TO
  source_post_id text,                                   -- WP post/page id (null for non-WP)
  source_type    text,                                   -- 'posts' | 'pages' (WP REST resource)
  target_url     text not null,                          -- page the link points to
  anchor_text    text not null,                          -- the phrase to wrap in the link
  context        text,                                   -- a snippet around the anchor (review aid)
  match_score    numeric,                                -- topical relevance (higher = better)
  injectable     boolean not null default false,         -- true only for WordPress sources
  status         text not null default 'proposed'
                   check (status in (
                     'proposed', 'approved', 'denied', 'applied', 'failed', 'superseded'
                   )),
  result         jsonb,                                  -- WP write result / failure detail
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists idx_internal_link_edits_client
  on internal_link_edits (client_id, created_at desc);
create index if not exists idx_internal_link_edits_batch
  on internal_link_edits (batch_id);

alter table internal_link_edits enable row level security;

-- ── async_jobs.job_type += internal-linking jobs ──────────────────────────────
-- Restates the FULL current deployed union (as read from the live DB) plus the
-- two internal-linking job types. NOTE: apply this against the live DB at the
-- moment this lands on `main` (re-check the live constraint first) so a job type
-- another PR added in the interim isn't dropped.
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
    'gbp_metrics_ingest', 'internal_link_analyze', 'internal_link_apply'
  ]));
