-- LeadOff city-finder (assistant "which cities for category X"): the paid path
-- for a NEW category not in the scan. One category × a population-ranked city
-- shortlist → volume + Maps SERP + score. Results stored per run (like tryouts).
create table if not exists public.leadoff_city_finder_runs (
  id uuid primary key default gen_random_uuid(),
  requested_by uuid,
  category text not null,
  state text,
  region text,
  status text not null default 'pending',
  est_cost double precision,
  results jsonb,
  result_meta jsonb,
  error text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
alter table public.leadoff_city_finder_runs enable row level security;
-- (async_jobs job_type CHECK widened for 'leadoff_city_finder' — see the
-- applied migration; the full array is managed live.)
