-- ============================================================
-- silo_candidates — cross-brief silo persistence + dedup (Platform PRD v1.4)
-- ============================================================
-- Implements PRD §7.7 + §8.5 + §14.1. Enables pgvector, creates the
-- silo_candidates table with HNSW index, and adds 'silo_dedup' to the
-- async_jobs.job_type allowlist.
--
-- Brief Generator v2.0 emits silo_candidates per brief; this table
-- accumulates them across briefs (client-scoped) so the team can
-- review, dedupe, and promote high-frequency candidates.
-- ============================================================

create extension if not exists vector;

-- ============================================================
-- async_jobs: extend job_type allowlist
-- ============================================================
-- The existing check constraint allows only 'website_scrape'. v1.4 adds
-- 'silo_dedup' so the same worker queue can handle both.
alter table async_jobs
  drop constraint async_jobs_job_type_check;

alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type in ('website_scrape', 'silo_dedup'));


-- ============================================================
-- silo_candidates
-- ============================================================
create table silo_candidates (
  id                              uuid primary key default gen_random_uuid(),

  -- Scope: silos are client-scoped; never cascade-deleted on client
  -- soft-delete so audit / promotion history survives.
  client_id                       uuid not null references clients(id),

  suggested_keyword               text not null,
  -- 1536 dimensions, unit-normalized. text-embedding-3-large supports
  -- a `dimensions` request parameter; we use 1536 because pgvector's
  -- HNSW index is capped at 2000 dimensions for vector_cosine_ops.
  -- 1536 is the same dimensionality as text-embedding-3-small and is
  -- plenty for keyword-level cosine similarity dedup.
  suggested_keyword_embedding     vector(1536) not null,

  status                          text not null default 'proposed'
                                    check (status in (
                                      'proposed',
                                      'approved',
                                      'rejected',
                                      'in_progress',
                                      'published',
                                      'superseded'
                                    )),
  occurrence_count                integer not null default 1,

  first_seen_run_id               uuid not null references runs(id),
  last_seen_run_id                uuid not null references runs(id),
  -- Append-on-dedup-hit; v1 has no built-in array dedup so the
  -- worker is responsible for not appending the same run_id twice.
  source_run_ids                  uuid[] not null default '{}',

  -- Brief output passthrough fields (PRD v1.4 §14.1).
  cluster_coherence_score         numeric(5,4),
  search_demand_score             numeric(5,4),
  viable_as_standalone_article    boolean not null default true,
  viability_reasoning             text,
  estimated_intent                text,
  routed_from                     text,
  discard_reason_breakdown        jsonb,
  -- Overwritten on dedup hit (latest-seen brief's headings win) to
  -- bound row size; historical headings stay in module_outputs.
  source_headings                 jsonb,

  -- Promotion lifecycle (PRD v1.4 §7.7.3).
  promoted_to_run_id              uuid references runs(id),
  last_promotion_failed_at        timestamptz,

  created_at                      timestamptz not null default now(),
  updated_at                      timestamptz not null default now()
);

-- ============================================================
-- Indexes (PRD v1.4 §14.1)
-- ============================================================
create index idx_silo_client_status
  on silo_candidates (client_id, status);

create index idx_silo_client_occurrence_desc
  on silo_candidates (client_id, occurrence_count desc);

create index idx_silo_client_demand_desc
  on silo_candidates (client_id, search_demand_score desc);

-- HNSW pgvector index for cosine-similarity dedup queries.
-- m=16, ef_construction=64 are pgvector's defaults — sufficient at
-- our scale (100s–1000s of rows per client; <10k total).
create index idx_silo_embedding_hnsw
  on silo_candidates
  using hnsw (suggested_keyword_embedding vector_cosine_ops);

-- ============================================================
-- updated_at maintenance
-- ============================================================
-- moddatetime isn't installed on the AR-Internal-Tools instance, so we
-- use a one-line plpgsql trigger to keep updated_at fresh.
create or replace function set_silo_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger trg_silo_candidates_updated_at
  before update on silo_candidates
  for each row execute function set_silo_updated_at();

-- ============================================================
-- Row-Level Security
-- ============================================================
-- Mirrors runs: admin sees all; team_member sees rows for clients they
-- have run access to (which in v1 is "all clients"). Service role
-- bypasses for the dedup worker + orchestrator.
alter table silo_candidates enable row level security;

-- Read policy: any authenticated profile can read all silos in v1.
create policy silo_candidates_read on silo_candidates
  for select
  to authenticated
  using (true);

-- Write policies (insert/update/delete): denied to authenticated users
-- through RLS — only service_role bypass writes (worker + promotion
-- endpoint write through the platform-api which uses the service key).
-- No write policies created → all writes from authenticated tokens fail
-- by default.
