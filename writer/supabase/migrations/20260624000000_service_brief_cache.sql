-- ============================================================
-- service_brief_cache — research-bundle cache for the Service Page
-- Brief Generator (PRD §7)
-- ============================================================
-- The Service Page Brief Generator runs its own research pipeline
-- (DataForSEO SERP + competitor scrape/teardown + entity extraction +
-- question mining + AIO). That research is client-agnostic — the
-- competitor SERP for a service doesn't move much week-to-week — so we
-- cache the RESEARCH BUNDLE by (keyword, location_code) and reuse it
-- across clients within the TTL unless force_refresh=true. Synthesis
-- still runs per-client, so two clients targeting the same query share
-- the cached research but get differentiated briefs. A repeat run within
-- the TTL does not re-fetch the SERP (PRD §8.6).
--
-- Mirrors briefs_cache: append-only, freshest-row-wins, schema_version
-- also embedded inside output_payload for deploy robustness.
-- ============================================================

create table service_brief_cache (
  id              uuid primary key default gen_random_uuid(),
  keyword         text not null,          -- normalized primary_query
  location_code   integer not null,
  output_payload  jsonb not null,         -- the ResearchBundle dict
  schema_version  text not null,

  -- Operational metrics for cost / performance tracking
  cost_usd        numeric(10, 4),
  duration_ms     integer,

  created_at      timestamptz not null default now()
);

-- Lookup the freshest row for (keyword, location_code) in one indexed query.
create index idx_service_brief_cache_lookup
  on service_brief_cache (keyword, location_code, created_at desc);

-- ============================================================
-- RLS: deny all by default; service role bypasses.
-- pipeline-api uses the service role key, so no policies needed.
-- ============================================================
alter table service_brief_cache enable row level security;
