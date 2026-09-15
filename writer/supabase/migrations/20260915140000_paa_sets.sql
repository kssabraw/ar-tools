-- Migration: 20260915140000_paa_sets.sql
-- Purpose: PAA → SEO Neo v1 (the CONTENT HALF). The methodology's atomic unit is
--   the "PAA string as a universal join key": one exact-match People-Also-Ask
--   buyer question, filed identically as the blog title/H2, the GBP post, and the
--   syndication title, linking HIGH to the client's service page. v1 makes that a
--   first-class, persisted object plus three writing rules (one-question-one-post,
--   exact-match-everywhere, link-high-to-the-service-page) enforced as reused
--   writer constraints.
--
--   * paa_sets   — per (client, service keyword, geo): the service keyword
--                  ("metal roof repair", not "roofing"), the geo, a geo_mode flag
--                  (default 'geo' = geo-modified; 'naked' toggle), and the
--                  optional "link high" service_page_url.
--   * paa_items  — one row per PAA string in a set: the exact-match question, its
--                  reused DataForSEO volume/CPC enrichment, a chosen/candidate
--                  flag, a slug (the cannibalization-guard key), and a nullable
--                  run_id/post_url filled once a post is created.
--
--   NO new async_jobs job type: the "create PAA posts" action creates ordinary
--   blog `runs` (dispatched via BackgroundTasks like POST /runs) and best-effort
--   GBP-post drafts + a syndication scan — all already-modelled work.
--
--   Reuses `keyword_research_serp` for the PAA pull; there is no new data source.
--   Ships as a plain content-creation surface (no feature flag) — it is an
--   organizer over an existing paid SERP call that kicks off existing writers.
--
--   Design forks locked by the owner (2026-09-15, PRD §8): own tables (not a
--   research-run child), geo-modified default with a naked toggle, service-page
--   URL resolved explicit → site_page_index match → prompt.
--
--   Permanent guardrail (PRD §9): the suite NEVER executes the SEO Neo authority
--   layer (link blasts / RD 100 / PBNs) — v1 is Layer-1 content only. Nothing
--   here touches that layer.
--
-- Both tables RLS-on with no client-facing policies: access is service-role only,
-- authorization is API-layer client_id filtering (suite single-tenant model),
-- matching every other suite module table.

-- ---------------------------------------------------------------------------
-- PAA sets (one per service-in-geo)
-- ---------------------------------------------------------------------------
create table if not exists paa_sets (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references clients (id) on delete cascade,
  -- The unit of work is the SERVICE keyword ("metal roof repair"), not the head
  -- term ("roofing") — revenue + buyer intent + a clean entity (reference §4).
  service_keyword   text not null,
  -- The geo label (city) used to geo-modify the PAA query + for display, and the
  -- DataForSEO location code the SERP was actually scoped to (the client's
  -- rank_tracking_location_code by default).
  location          text,
  location_code     integer,
  -- Naked vs geo PAA is a contested point in the source (reference §9); the suite
  -- surfaces it rather than hardcoding it. Default 'geo' (geo-modified), with
  -- 'naked' as a per-set toggle (PRD §8.4).
  geo_mode          text not null default 'geo' check (geo_mode in ('geo', 'naked')),
  -- The "link high to the service page" target (the money page). Nullable; the
  -- API resolves it explicit → site_page_index auto-match → prompt (PRD §8.3),
  -- never a silent guess.
  service_page_url  text,
  status            text not null default 'draft' check (status in ('draft', 'active')),
  created_by        uuid,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists paa_sets_client_idx
  on paa_sets (client_id, created_at desc);

alter table paa_sets enable row level security;

-- ---------------------------------------------------------------------------
-- PAA items (one per PAA string in a set)
-- ---------------------------------------------------------------------------
create table if not exists paa_items (
  id            uuid primary key default gen_random_uuid(),
  set_id        uuid not null references paa_sets (id) on delete cascade,
  -- Denormalized so the cannibalization guard can find slug collisions across a
  -- client's OTHER sets/cities in one indexed query (reference §10: "never reuse
  -- an identical PAA slug across cities").
  client_id     uuid not null references clients (id) on delete cascade,
  -- The exact-match PAA string — the universal join key. Get it right once and it
  -- propagates to the blog title/H2, the GBP post, and the syndication title.
  question      text not null,
  -- Slugified question — the cannibalization-guard key (NOT unique: a collision is
  -- an acknowledgeable sign-off, mirroring local_seo_matrix scale gates, not a
  -- hard DB block).
  slug          text not null,
  -- Reused DataForSEO market enrichment (keyword_market.parse_market_items):
  -- competition is LOW/MEDIUM/HIGH text, not a number.
  volume        integer,
  cpc_usd       numeric,
  competition   text,
  -- candidate (pulled) vs chosen (the ~4 selected for posts).
  chosen        boolean not null default false,
  position      integer,
  -- Filled once a post is created from this PAA. run_id links the blog run;
  -- gbp_post_id is a soft reference (no FK — GBP Posts is a gated, optional module
  -- whose rows can be purged); post_url is the published URL once known.
  run_id        uuid references runs (id) on delete set null,
  gbp_post_id   uuid,
  post_url      text,
  -- Deterministic writer-constraint verification result once the run completes:
  -- {exact_match: {...}, service_link: {...}} — the enforcement made visible.
  checks        jsonb,
  created_at    timestamptz not null default now()
);

create index if not exists paa_items_set_idx
  on paa_items (set_id);

-- Cross-set cannibalization guard: all of a client's PAA slugs by slug.
create index if not exists paa_items_client_slug_idx
  on paa_items (client_id, slug);

alter table paa_items enable row level security;
