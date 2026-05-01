-- ============================================================
-- briefs_cache — 7-day cache for Brief Generator v2.0 results
-- ============================================================
-- The brief generator is expensive (DataForSEO SERP + PAA + Reddit +
-- Autocomplete + Keyword Suggestions + 4× LLM Fan-Out + 3× LLM agent
-- calls + OpenAI embeddings). Per the v2.0 PRD the brief is
-- client-agnostic (PRD §2), so we cache by (keyword, location_code)
-- and serve cached output to all clients within the TTL unless
-- force_refresh=true on the request. Historical rows are preserved
-- (we never delete) so we can compare runs across threshold-tuning
-- iterations. The freshest matching row wins on lookup.
-- ============================================================

create table briefs_cache (
  id              uuid primary key default gen_random_uuid(),
  keyword         text not null,
  location_code   integer not null,
  output_payload  jsonb not null,
  schema_version  text not null,

  -- Audit trail: the client_id that triggered this generation. Useful for
  -- attributing cost and tracking which client first paid for which brief.
  -- The cache key intentionally does NOT include client_id — content is
  -- shared across clients per PRD §2.
  triggered_by_client_id uuid,

  -- Operational metrics for cost / performance tracking
  cost_usd        numeric(10, 4),
  duration_ms     integer,

  created_at      timestamptz not null default now()
);

-- Lookup the freshest row for (keyword, location_code) so the pipeline
-- can decide cache hit vs miss in one indexed query.
create index idx_briefs_cache_lookup
  on briefs_cache (keyword, location_code, created_at desc);

-- ============================================================
-- RLS: deny all by default; service role bypasses.
-- pipeline-api uses the service role key, so no policies needed.
-- ============================================================
alter table briefs_cache enable row level security;
