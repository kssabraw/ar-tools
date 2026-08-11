-- GBP review-count + rating time-series (Client Reporting Phase 2 foundation).
-- One row per client per capture day; lets the client report show reviews and
-- rating "this period vs last period" exactly, once history accrues. New-review
-- COUNT per period is also derivable from dated reviews directly, but this series
-- gives the exact rating-over-time that individual reviews can't reconstruct.
create table if not exists public.gbp_review_snapshots (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete cascade,
  captured_at date not null default current_date,
  review_count integer,
  rating numeric,
  created_at timestamptz not null default now(),
  unique (client_id, captured_at)
);

create index if not exists gbp_review_snapshots_client_idx
  on public.gbp_review_snapshots (client_id, captured_at desc);

-- Internal table: backend uses the service role (bypasses RLS). Enable RLS with
-- no policies so anon/authenticated clients can't read it directly.
alter table public.gbp_review_snapshots enable row level security;
