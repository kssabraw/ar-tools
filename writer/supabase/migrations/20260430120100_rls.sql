-- Migration: 20260430120100_rls.sql
-- Purpose: Row-level security policies for all tables
-- Note: Service role key bypasses RLS by default (used by platform-api)

-- Enable RLS on all tables
alter table profiles                  enable row level security;
alter table clients                   enable row level security;
alter table runs                      enable row level security;
alter table client_context_snapshots  enable row level security;
alter table module_outputs            enable row level security;
alter table async_jobs                enable row level security;


-- ============================================================
-- profiles: users read own; admins read/update all
-- ============================================================
create policy "users read own profile"
  on profiles for select
  using (auth.uid() = id);

create policy "admins read all profiles"
  on profiles for select
  using (exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  ));

create policy "admins update profiles"
  on profiles for update
  using (exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  ));


-- ============================================================
-- clients: all authenticated users read; only admins write
-- ============================================================
create policy "authenticated users read clients"
  on clients for select
  using (auth.role() = 'authenticated');

create policy "admins manage clients"
  on clients for all
  using (exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  ));


-- ============================================================
-- runs: all authenticated users read and create; creators/admins update
-- ============================================================
create policy "authenticated users read runs"
  on runs for select
  using (auth.role() = 'authenticated');

create policy "authenticated users create runs"
  on runs for insert
  with check (auth.role() = 'authenticated');

create policy "creators and admins update runs"
  on runs for update
  using (
    created_by = auth.uid()
    or exists (
      select 1 from profiles where id = auth.uid() and role = 'admin'
    )
  );


-- ============================================================
-- client_context_snapshots: all authenticated users read
-- (Service role writes via platform-api orchestrator)
-- ============================================================
create policy "authenticated users read snapshots"
  on client_context_snapshots for select
  using (auth.role() = 'authenticated');


-- ============================================================
-- module_outputs: all authenticated users read
-- (Service role writes via platform-api orchestrator)
-- ============================================================
create policy "authenticated users read module outputs"
  on module_outputs for select
  using (auth.role() = 'authenticated');


-- ============================================================
-- async_jobs: service role only (no policies — RLS denies all client access)
-- ============================================================
-- No policies defined intentionally. Service role (used by platform-api
-- orchestrator and job worker) bypasses RLS. Direct client access is denied.
