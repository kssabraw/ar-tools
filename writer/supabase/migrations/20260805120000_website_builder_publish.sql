-- Website Builder — the publish path: plan rows, generation inputs, deploy
-- resolution.
--
-- Slice 3 turned the site plan and the content→file conversion into pure,
-- tested functions. This migration adds the columns the impure half needs to
-- persist what those functions produce.

-- 1. A planned page carries WHY it was proposed (reference §2 rule 3: "the
--    matched trigger is recorded on the plan row"), its review tier, and the
--    inputs a generator needs. The generation inputs live in one jsonb rather
--    than four columns because they differ per page type — a local landing has
--    a service and a city, a top-level service page has neither.
alter table website_pages add column if not exists trigger text;
alter table website_pages add column if not exists tier integer not null default 1;
alter table website_pages add column if not exists plan jsonb not null default '{}'::jsonb;

-- 2. Body + frontmatter for pages with no upstream record. Service and location
--    pages resolve their body from `local_seo_pages` at publish time (so a
--    reoptimized page republishes without a second copy of the text drifting
--    from the first), but a composed core page or a static legal page has no
--    such record and has to live here.
alter table website_pages add column if not exists content jsonb;

-- 3. Publish idempotency, keyed on the RENDERED BYTES rather than on the page
--    id. "A retry never creates a second commit" cannot mean "a page is
--    committed at most once" — then a reoptimized page could never ship. What
--    it means is that committing unchanged content is a no-op.
alter table website_pages add column if not exists content_hash text;

-- 4. Two deploy outcomes the original CHECK could not express.
--
--    'unknown' — PRD §6.3 is explicit that a poll timeout is NOT a failure: the
--    site is very likely serving fine and we simply stopped being able to see
--    the run. Recording it as failed would train people to ignore red.
--
--    'superseded' — the template's deploy workflow sets
--    `concurrency: cancel-in-progress: true`, so publishing a 20-page batch
--    cancels 19 runs and only the last one deploys. Those runs conclude
--    'cancelled', which is not a failure of anything: the content they carried
--    shipped in the run that replaced them.
alter table website_deploys drop constraint if exists website_deploys_status_check;
alter table website_deploys
  add constraint website_deploys_status_check
  check (status in ('queued', 'building', 'success', 'failed', 'unknown', 'superseded'));

-- Which pages rode this commit, and any quality gate that was forced past on
-- the way (PRD §5.7 — an override invisible after the fact is indistinguishable
-- from a bug).
alter table website_deploys add column if not exists meta jsonb not null default '{}'::jsonb;
alter table website_deploys add column if not exists polled_at timestamptz;

-- Pending deploys are swept every scheduler tick, so they are queried by status.
create index if not exists website_deploys_pending_idx
  on website_deploys (website_id)
  where status in ('queued', 'building');

-- 5. The per-page generation job. The array preserves the FULL live constraint
--    set (verified against the deployed constraint, which is wider than any
--    single repo migration file) plus the new type.
alter table async_jobs drop constraint async_jobs_job_type_check;

alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'page_structure_parse', 'silo_dedup',
    'gsc_ingest', 'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank',
    'keyword_market', 'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan',
    'maps_report', 'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
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
    'leadoff_geocode', 'qa_review', 'leadoff_signal_refresh', 'leadoff_city_finder',
    'leadoff_income_backfill', 'leadoff_county_backfill', 'keyword_research',
    'ecommerce_generate', 'ecommerce_reoptimize_url', 'ecommerce_action',
    'github_infer_patterns', 'illustrate_run', 'blog_github_publish',
    'gbp_post_publish', 'gbp_post_generate', 'gbp_posts_sync', 'site_inventory',
    'website_provision', 'website_theme_compile', 'website_core_pages',
    'website_page_publish', 'website_deploy_poll', 'website_page_generate'
  ]));
