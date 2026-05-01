-- ============================================================
-- sie_cache — 7-day cache for SIE module results
-- ============================================================
-- The SIE module is expensive (DataForSEO + ScrapeOwl + Google NLP +
-- OpenAI). Per the SIE PRD we cache by (keyword, location_code) for 7 days
-- and serve cached output unless force_refresh=true. Historical rows are
-- preserved (we never delete) so we can compare runs over time.
-- ============================================================

create table sie_cache (
  id              uuid primary key default gen_random_uuid(),
  keyword         text not null,
  location_code   integer not null,
  outlier_mode    text not null default 'safe'
                    check (outlier_mode in ('safe', 'aggressive')),
  output_payload  jsonb not null,
  schema_version  text not null,
  cost_usd        numeric(10, 4),
  duration_ms     integer,
  created_at      timestamptz not null default now()
);

-- Lookup the freshest row for a given (keyword, location_code, outlier_mode)
-- so the pipeline can decide cache hit vs miss in one query.
create index idx_sie_cache_lookup
  on sie_cache (keyword, location_code, outlier_mode, created_at desc);

-- ============================================================
-- RLS: deny all by default; service role bypasses.
-- pipeline-api uses the service role key, so no policies needed.
-- ============================================================
alter table sie_cache enable row level security;
