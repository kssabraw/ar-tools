-- Migration: 20260622232017_serp_snapshots.sql
-- Purpose: Organic Rank Tracker (Module #4) — Competitive SERP Snapshot.
--          Dated, stored SERP snapshots per tracked keyword, captured weekly
--          alongside the DataForSEO rank refresh. Diagnostic data store for
--          investigating ranking drops after the fact (no user-facing viewer;
--          retrieved on request via the API).
--
-- Each snapshot records, for a keyword at a point in time:
--   - the AI Overview (presence, text, cited sources),
--   - the SERP feature inventory (local pack/GBP, PAA, forums, featured
--     snippet, etc.),
--   - the query intent (informational/commercial/transactional/navigational),
--   - and the top organic results (url/domain/rendered title + description/
--     position), each enriched with referring domains + URL Rating
--     (DataForSEO Backlinks page rank, 0–1000) — including the client's own
--     ranking page.
--
-- Sources: DataForSEO SERP advanced (AIO + organic + features), DataForSEO Labs
-- search-intent, DataForSEO Backlinks summary (per target URL).
--
-- RLS on, NO client-facing policies (service-role only) — the async_jobs pattern.

-- ============================================================
-- serp_snapshots — one row per keyword per capture.
-- ============================================================
create table if not exists serp_snapshots (
  id                   uuid primary key default gen_random_uuid(),
  keyword_id           uuid not null references tracked_keywords(id) on delete cascade,
  client_id            uuid not null references clients(id) on delete cascade,
  keyword              text not null,                  -- denormalized for diagnosis convenience
  captured_at          timestamptz not null default now(),
  status               text not null default 'complete'
                         check (status in ('complete', 'partial', 'failed')),
  location_code        integer,                        -- DataForSEO location the SERP was pulled at
  language_code        text,
  -- Query intent (DataForSEO Labs search-intent).
  query_intent         text,                           -- informational/commercial/transactional/navigational
  intent_probabilities jsonb,                          -- {informational: 0.7, commercial: 0.2, ...}
  -- AI Overview.
  aio_present          boolean not null default false,
  aio_text             text,
  aio_sources          jsonb,                          -- [{url, domain, title}, ...] cited sources
  -- SERP feature inventory ("enhancements"): GBP/local pack, PAA, forums,
  -- featured snippet, etc. Shape:
  --   {feature_types: [...all item types present...],
  --    local_pack: [...], people_also_ask: [...questions...],
  --    discussions_and_forums: [...], featured_snippet: {...}}
  serp_features        jsonb,
  -- The client's own organic position + URL in this SERP (null = not in the
  -- fetched depth — a real, stored fact, not an error).
  client_rank          integer,
  client_url           text,
  error                text,
  created_at           timestamptz not null default now()
);

create index if not exists idx_serp_snapshots_keyword
  on serp_snapshots (keyword_id, captured_at desc);
create index if not exists idx_serp_snapshots_client
  on serp_snapshots (client_id, captured_at desc);

-- ============================================================
-- serp_snapshot_results — the ranking pages within a snapshot.
-- The top organic results plus, if it isn't already among them, the client's
-- own ranking/canonical page (is_client = true).
-- ============================================================
create table if not exists serp_snapshot_results (
  id                uuid primary key default gen_random_uuid(),
  snapshot_id       uuid not null references serp_snapshots(id) on delete cascade,
  position          integer,                           -- rank_absolute in the SERP
  url               text,
  domain            text,
  title             text,                              -- rendered title tag
  description       text,                              -- rendered snippet / meta description
  is_client         boolean not null default false,
  -- DataForSEO Backlinks summary enrichment (per target URL).
  referring_domains integer,
  url_rating        integer,                           -- DataForSEO page rank (0–1000), UR-equivalent
  backlinks         integer,
  backlinks_status  text not null default 'pending'
                      check (backlinks_status in ('ok', 'failed', 'skipped', 'pending')),
  created_at        timestamptz not null default now()
);

create index if not exists idx_serp_snapshot_results_snapshot
  on serp_snapshot_results (snapshot_id, position);

-- ============================================================
-- Widen async_jobs.job_type for the weekly serp_snapshot capture job.
-- (Same drop/re-add pattern as prior rank-tracker migrations.)
-- ============================================================
alter table async_jobs
  drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type in ('website_scrape', 'silo_dedup', 'gsc_ingest', 'gsc_materialize',
                      'dataforseo_rank', 'keyword_market', 'gsc_page_ingest', 'rank_report',
                      'serp_snapshot'));

-- ============================================================
-- RLS: enabled, no policies (service-role only).
-- ============================================================
alter table serp_snapshots        enable row level security;
alter table serp_snapshot_results enable row level security;
