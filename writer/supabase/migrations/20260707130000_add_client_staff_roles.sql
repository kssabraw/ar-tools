-- Migration: 20260707130000_add_client_staff_roles.sql
-- Purpose: Add two new user types to the suite role model — 'staff' and 'client'.
--
-- The suite previously had exactly two roles: 'admin' (full access, incl. user
-- management) and 'team_member' (VA — operational internal user). This widens
-- the profiles.role CHECK constraint to four tiers, ordered by privilege:
--
--   client      — external, READ-ONLY viewer (enforced in the API layer)
--   team_member — VA, internal operational user (unchanged)
--   staff       — senior internal operator = admin minus user/team management
--   admin       — full access (unchanged)
--
-- Backend enforcement lives in middleware/auth.py (require_admin / require_staff
-- + a read-only guard for 'client'). The RLS updates below keep the DB layer
-- consistent for the belt-and-suspenders case of direct (anon-key) access —
-- platform-api itself writes with the service role, which bypasses RLS.

-- 1) Widen the role allow-list. The inline column check is named
--    profiles_role_check by Postgres convention.
alter table public.profiles drop constraint if exists profiles_role_check;
alter table public.profiles
  add constraint profiles_role_check
  check (role in ('admin', 'staff', 'team_member', 'client'));

-- 2) A SECURITY DEFINER helper mirroring is_admin() (20260531181719) so RLS
--    policies can test "staff or admin" WITHOUT re-triggering the profiles
--    policies (which would raise 42P17 infinite recursion).
create or replace function public.is_staff_or_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and role in ('admin', 'staff')
  );
$$;

revoke execute on function public.is_staff_or_admin() from public;
grant execute on function public.is_staff_or_admin() to authenticated;

-- 3) clients: staff + admins manage (was admin-only). Mirrors the backend,
--    where client create/update/archive now require the 'staff' tier.
drop policy if exists "admins manage clients" on public.clients;
create policy "staff and admins manage clients"
  on public.clients for all
  using (public.is_staff_or_admin());

-- 4) runs: creators, staff, admins update (was creators + admin).
drop policy if exists "creators and admins update runs" on public.runs;
create policy "creators staff and admins update runs"
  on public.runs for update
  using (created_by = auth.uid() or public.is_staff_or_admin());

-- 5) local_seo_pages: creators, staff, admins update (was creators + admin).
drop policy if exists "creators and admins update local_seo_pages" on public.local_seo_pages;
create policy "creators staff and admins update local_seo_pages"
  on public.local_seo_pages for update
  using (created_by = auth.uid() or public.is_staff_or_admin());
