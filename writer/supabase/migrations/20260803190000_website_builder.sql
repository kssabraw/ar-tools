-- Website Builder — the module's data model (plan §5).
--
-- A "website" is one GitHub repo + one Cloudflare Workers project. The repo IS
-- the site: it builds and deploys itself from its own Actions workflow, so a
-- generated site has no runtime dependency on this suite. These tables are the
-- suite's *index* of those sites, not their source of truth.
--
-- Every site belongs to a client (owner ruling 2026-07-17) — standalone
-- informational sites get a lightweight client row — so the freeze, notification,
-- rank-tracking and GSC rails all work unmodified.

create table if not exists website_themes (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  -- Where the design came from. 'default' is the house theme that ships in the
  -- template repo and needs no compile step.
  source_kind text not null default 'default'
    check (source_kind in ('default', 'upload', 'url')),
  source_ref text,
  version integer not null default 1,
  -- Extracted design tokens (colors/type/spacing/radii) — the compiler's output.
  tokens jsonb not null default '{}'::jsonb,
  -- Storage path of the compiled theme files, and of the approval preview.
  storage_path text,
  preview_path text,
  status text not null default 'ready'
    check (status in ('compiling', 'ready', 'failed')),
  approved_at timestamptz,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists websites (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients(id) on delete cascade,
  name text not null,
  slug text not null,
  site_type text not null check (site_type in ('local_business', 'informational')),
  theme_id uuid references website_themes(id) on delete set null,
  -- owner/repo of the generated site repo, and the Cloudflare Workers project.
  github_repo text,
  cf_project text,
  -- The *.workers.dev URL, live from the first deploy — every site is viewable
  -- before its real domain exists.
  staging_url text,
  custom_domain text,
  domain_status text not null default 'none'
    check (domain_status in ('none', 'pending_ns', 'active')),
  status text not null default 'draft'
    check (status in ('draft', 'provisioning', 'live', 'error')),
  -- site.config.json as the suite knows it (business facts + provenance, nav,
  -- forms/analytics keys). Committed into the repo on provision and on change.
  config jsonb not null default '{}'::jsonb,
  -- Per-step provisioning state, so a partial failure is resumable rather than
  -- leaving a half-built site the module can't reason about.
  provision_state jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, slug)
);

create index if not exists websites_client_idx on websites(client_id);

create table if not exists website_pages (
  id uuid primary key default gen_random_uuid(),
  website_id uuid not null references websites(id) on delete cascade,
  route text not null,
  title text not null default '',
  -- Where the content came from, so a reoptimized page can be re-published
  -- from its source record rather than regenerated.
  content_source text not null default 'composed'
    check (content_source in ('local_seo_page', 'run', 'composed', 'static')),
  source_id text,
  repo_path text,
  commit_sha text,
  status text not null default 'draft'
    check (status in ('draft', 'queued', 'published', 'failed')),
  error text,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (website_id, route)
);

create index if not exists website_pages_site_idx on website_pages(website_id);

create table if not exists website_deploys (
  id uuid primary key default gen_random_uuid(),
  website_id uuid not null references websites(id) on delete cascade,
  commit_sha text,
  trigger text not null default 'manual'
    check (trigger in ('provision', 'publish', 'theme', 'config', 'manual')),
  status text not null default 'queued'
    check (status in ('queued', 'building', 'success', 'failed')),
  -- The GitHub Actions run that is doing the build, so status is read from the
  -- site's own deploy log rather than inferred.
  actions_run_id text,
  url text,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists website_deploys_site_idx
  on website_deploys(website_id, created_at desc);

-- These tables are written only by the service-role backend; RLS on with no
-- policies matches how the suite's other backend-owned tables are locked.
alter table website_themes enable row level security;
alter table websites enable row level security;
alter table website_pages enable row level security;
alter table website_deploys enable row level security;

-- The array preserves the FULL live constraint set (wider than any single repo
-- migration file) plus the new website_* job types.
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
    'website_page_publish', 'website_deploy_poll'
  ]));
