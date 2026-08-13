-- WheelHouse IT — location/service landing-page poster (Wheelhouse-only module).
--
-- Publishes a 3-level hierarchy of standard WordPress *Pages* (NOT a custom post
-- type): State → City → Service, linked by the page `parent` field, giving
-- prefix-free nested URLs (/florida/miami/managed-it/). Only the leaf (Service)
-- page carries on-page copy — 33 ACF fields written under the WP REST `acf`
-- object; State/City are lightweight title+slug hub pages. Elementor renders the
-- layout from the ACF fields, so the app only sends title/slug/parent/status/acf.
--
-- Reuses the existing per-client WordPress credentials on `clients`
-- (wordpress_site_url / wordpress_username / wordpress_app_password) — no new
-- credential storage. This migration adds only the per-client gate + the in-tool
-- draft/upsert store.

-- Per-client feature gate. The whole module (workspace card, routes, generation,
-- publishing) is invisible/inert unless this is true for the client. Default
-- false so every other client is unaffected.
alter table clients
  add column if not exists wheelhouse_cpt_enabled boolean not null default false;

-- In-tool store for generated/drafted leaf pages: the 33-field ACF object, the
-- resolved WordPress page ids for the parent chain + leaf, the per-field
-- supplied-vs-generated map (for reporting), and the draft→publish lifecycle.
-- Soft-delete (`deleted_at`) drives a Drafts tab like local_seo_pages.
create table if not exists wheelhouse_pages (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients(id) on delete cascade,

  -- The generation inputs that identify a leaf page.
  state text not null,
  city text not null,
  service text not null,

  -- Slugs used for the WP slug+parent lookup (unique per parent).
  state_slug text not null,
  city_slug text not null,
  service_slug text not null,
  -- Full nested path for reporting/links, e.g. "/florida/miami/managed-it/".
  slug_path text,

  -- The 33 ACF fields sent under the WP REST `acf` object.
  acf jsonb not null default '{}'::jsonb,
  -- Per-field origin: { "hero_headline": "generated" | "supplied", ... } — powers
  -- the "which fields were generated vs supplied" report line.
  field_sources jsonb not null default '{}'::jsonb,
  -- Non-fatal per-field length/focus validation warnings from the last assemble.
  validation_warnings jsonb not null default '[]'::jsonb,

  -- Resolved WordPress page ids (null until first published/upserted).
  wp_state_id integer,
  wp_city_id integer,
  wp_page_id integer,        -- the leaf (service) page id
  wp_status text,            -- WP page status the leaf was last written with (draft|publish)
  published_url text,        -- the live leaf URL (WP `link`)
  edit_link text,            -- wp-admin edit URL for the leaf

  -- In-tool lifecycle: draft (generated, not yet posted) → published (posted to WP).
  status text not null default 'draft'
    check (status in ('draft', 'published')),

  title text,                -- the leaf WP post title (e.g. "Managed IT in Miami, FL")
  deleted_at timestamptz,    -- soft-delete → Drafts tab
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- One live in-tool row per client+state+city+service (upsert idempotency mirrors
-- the WP-side "resolve by slug+parent, update in place" behaviour). Soft-deleted
-- rows are excluded so a purge/restore can't collide.
create unique index if not exists wheelhouse_pages_client_combo_uniq
  on wheelhouse_pages (client_id, state_slug, city_slug, service_slug)
  where deleted_at is null;

create index if not exists wheelhouse_pages_client_idx
  on wheelhouse_pages (client_id)
  where deleted_at is null;

-- Background generation job type (mass city×service runs generate one job per
-- leaf, mirroring local_seo_generate). Widen the CHECK preserving the FULL LIVE
-- set (read from the live constraint, which had drifted wider than repo files:
-- blog_score/blog_reoptimize were live-only).
alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type in (
    'website_scrape', 'page_structure_scrape', 'page_structure_parse',
    'silo_dedup', 'gsc_ingest', 'gsc_page_ingest', 'gsc_materialize',
    'dataforseo_rank', 'keyword_market', 'gsc_research', 'rank_report',
    'serp_snapshot', 'maps_scan', 'maps_report', 'local_seo_silo',
    'local_seo_generate', 'local_seo_reoptimize_url', 'local_seo_reoptimize_page',
    'service_page_plan', 'rank_location_derive', 'brand_scan', 'brand_report',
    'notification_dispatch', 'reopt_plan', 'client_report', 'maps_analyze',
    'asana_monthly', 'competitor_gbp', 'review_intel', 'backlink_intel',
    'content_intel', 'local_relevance', 'syndication_scan', 'syndication_item',
    'freeze_check', 'citation_check', 'page_backlink_intel', 'strategy_review',
    'maps_image_backfill', 'brand_voice_scan', 'icp_scan', 'asana_push',
    'competitor_intel', 'gbp_metrics_ingest', 'internal_link_analyze',
    'internal_link_apply', 'rank_keyword_report', 'local_seo_action',
    'backlink_snapshot', 'content_batch_item', 'task_month_generate',
    'task_due_sweep', 'task_import_asana', 'leadoff_tryout', 'leadoff_scout',
    'leadoff_ai_probe', 'domain_overview', 'keyword_gap', 'link_gap',
    'leadoff_permits', 'leadoff_geocode', 'qa_review', 'leadoff_signal_refresh',
    'leadoff_city_finder', 'leadoff_income_backfill', 'leadoff_county_backfill',
    'keyword_research', 'ecommerce_generate', 'ecommerce_reoptimize_url',
    'ecommerce_action', 'github_infer_patterns', 'illustrate_run',
    'blog_github_publish', 'gbp_post_publish', 'gbp_post_generate',
    'gbp_posts_sync', 'site_inventory', 'website_provision',
    'website_theme_compile', 'website_core_pages', 'website_page_publish',
    'website_deploy_poll', 'website_page_generate',
    'deliverables_sheet_provision', 'deliverables_log', 'deliverable_notes_scan',
    'service_page_score', 'service_page_reoptimize',
    'keyword_topic_research', 'keyword_research_report',
    'backlink_lookup', 'fanout_report', 'blog_score', 'blog_reoptimize',
    -- New in this migration.
    'wheelhouse_generate'
  )
);
