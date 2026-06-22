-- Migration: 20260622160000_gsc_properties.sql
-- Purpose: Organic Rank Tracker (Module #4) — M1 "Connection (service account)".
--          Promote GSC property mapping from the single clients.gsc_property
--          column into its own table so a client can have BOTH a url-prefix and
--          a domain property, and so we can track per-property access state.
-- See: docs/modules/organic-rank-tracker-prd-v1_0.md §5, §11.
--
-- Access pattern (locked): RLS enabled, NO client-facing policies. Written by
-- the backend (service-role key) and read by the platform-api; authorization is
-- enforced in the API layer by client_id. This mirrors the async_jobs pattern
-- in 20260430120100_rls.sql.

-- ============================================================
-- gsc_properties — per-client Google Search Console property mapping
-- ============================================================
create table if not exists gsc_properties (
  id               uuid primary key default gen_random_uuid(),
  client_id        uuid not null references clients(id) on delete cascade,
  site_url         text not null,
                     -- url_prefix: "https://acmehvac.com/" (trailing slash)
                     -- domain:     "sc-domain:acmehvac.com"
  property_type    text not null
                     check (property_type in ('url_prefix', 'domain')),
  access_status    text not null default 'pending'
                     check (access_status in ('ok', 'no_access', 'pending')),
  last_verified_at timestamptz,
  created_by       uuid references profiles(id),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  -- One row per (client, site_url); a client may still have two DIFFERENT
  -- site_urls (a url-prefix and a domain property).
  constraint gsc_properties_client_site_unique unique (client_id, site_url)
);

create index if not exists idx_gsc_properties_client_id on gsc_properties (client_id);

-- ============================================================
-- Backfill from the existing clients.gsc_property column.
-- Infer property_type from the "sc-domain:" prefix. access_status stays
-- 'pending' until the verify-access button runs a test query (M1).
-- The clients.gsc_property column is intentionally LEFT IN PLACE (deprecated);
-- a follow-up migration drops it once nothing reads it.
-- ============================================================
insert into gsc_properties (client_id, site_url, property_type)
select
  c.id,
  c.gsc_property,
  case when c.gsc_property like 'sc-domain:%' then 'domain' else 'url_prefix' end
from clients c
where c.gsc_property is not null
  and length(trim(c.gsc_property)) > 0
on conflict (client_id, site_url) do nothing;

-- ============================================================
-- RLS: enabled, no policies (service-role only) — see header note.
-- ============================================================
alter table gsc_properties enable row level security;
