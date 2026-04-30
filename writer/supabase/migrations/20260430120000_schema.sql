-- Migration: 20260430120000_schema.sql
-- Purpose: Initial schema for Content Generation Platform
-- Tables: profiles, clients, runs, client_context_snapshots, module_outputs, async_jobs

-- ============================================================
-- profiles (extends Supabase Auth users)
-- ============================================================
create table profiles (
  id           uuid primary key references auth.users(id) on delete cascade,
  role         text not null default 'team_member'
                 check (role in ('admin', 'team_member')),
  full_name    text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- Auto-create profile when a new auth user signs up
create or replace function handle_new_user()
returns trigger as $$
begin
  insert into profiles (id, full_name)
  values (new.id, new.raw_user_meta_data->>'full_name');
  return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();


-- ============================================================
-- clients
-- ============================================================
create table clients (
  id                              uuid primary key default gen_random_uuid(),
  name                            text not null,
  website_url                     text not null,
  website_analysis                jsonb,
  website_analysis_status         text not null default 'pending'
                                    check (website_analysis_status in ('pending', 'complete', 'failed')),
  website_analysis_error          text,
  brand_guide_source_type         text not null
                                    check (brand_guide_source_type in ('text', 'file')),
  brand_guide_text                text not null default '',
  brand_guide_file_path           text,
  brand_guide_original_filename   text,
  icp_source_type                 text not null
                                    check (icp_source_type in ('text', 'file')),
  icp_text                        text not null default '',
  icp_file_path                   text,
  icp_original_filename           text,
  archived                        boolean not null default false,
  created_by                      uuid references profiles(id),
  created_at                      timestamptz not null default now(),
  updated_at                      timestamptz not null default now(),
  constraint clients_name_unique unique (name)
);


-- ============================================================
-- runs
-- ============================================================
create table runs (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references clients(id),
  keyword           text not null,
  intent_override   text,
  sie_outlier_mode  text not null default 'safe'
                      check (sie_outlier_mode in ('safe', 'aggressive')),
  sie_force_refresh boolean not null default false,
  status            text not null default 'queued'
                      check (status in (
                        'queued', 'brief_running', 'sie_running',
                        'research_running', 'writer_running',
                        'sources_cited_running', 'complete', 'failed', 'cancelled'
                      )),
  error_stage       text,
  error_message     text,
  sie_cache_hit     boolean,
  total_cost_usd    numeric(10, 4),
  started_at        timestamptz,
  completed_at      timestamptz,
  created_by        uuid references profiles(id),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);


-- ============================================================
-- client_context_snapshots — frozen client context per run
-- ============================================================
create table client_context_snapshots (
  id                            uuid primary key default gen_random_uuid(),
  run_id                        uuid not null unique references runs(id) on delete cascade,
  client_id                     uuid not null references clients(id),
  brand_guide_text              text,
  icp_text                      text,
  website_analysis              jsonb,
  website_analysis_unavailable  boolean not null default false,
  created_at                    timestamptz not null default now()
);


-- ============================================================
-- module_outputs — per-module output storage
-- ============================================================
create table module_outputs (
  id              uuid primary key default gen_random_uuid(),
  run_id          uuid not null references runs(id) on delete cascade,
  module          text not null
                    check (module in ('brief', 'sie', 'research', 'writer', 'sources_cited')),
  status          text not null
                    check (status in ('running', 'complete', 'failed')),
  input_payload   jsonb,
  output_payload  jsonb,
  cost_usd        numeric(10, 4),
  duration_ms     integer,
  module_version  text,
  attempt_number  integer not null default 1,
  created_at      timestamptz not null default now(),
  completed_at    timestamptz,
  unique (run_id, module, attempt_number)
);


-- ============================================================
-- async_jobs — background job queue (website scraping, etc.)
-- ============================================================
create table async_jobs (
  id            uuid primary key default gen_random_uuid(),
  job_type      text not null check (job_type in ('website_scrape')),
  entity_id     uuid not null,
  status        text not null default 'pending'
                  check (status in ('pending', 'running', 'complete', 'failed')),
  attempts      integer not null default 0,
  max_attempts  integer not null default 2,
  payload       jsonb,
  result        jsonb,
  error         text,
  scheduled_at  timestamptz not null default now(),
  started_at    timestamptz,
  completed_at  timestamptz,
  created_at    timestamptz not null default now()
);
