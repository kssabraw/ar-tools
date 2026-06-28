-- Migration: 20260628015542_serp_snapshot_domains.sql
-- Purpose: Organic Rank Tracker (Module #4) — Competitive SERP Snapshot,
--          per-domain Domain Rating (DR). Extends the existing serp_snapshots /
--          serp_snapshot_results store (migration 20260622232017) with the
--          whole-domain authority signal the PRD §14 calls for.
--
-- For each unique domain in a snapshot's SERP (every top-10 competitor domain
-- plus the client's own domain — always included, even if the client doesn't
-- rank in the fetched depth), we record the Domain Rating: DataForSEO's
-- Backlinks domain rank (0–1000), captured via backlinks/summary/live with the
-- bare domain as target + include_subdomains=true. Its `rank` is the
-- DR-equivalent (mirrors how the per-URL `rank` is the UR-equivalent).
--
-- RLS on, NO client-facing policies (service-role only) — the async_jobs pattern.

-- ============================================================
-- serp_snapshot_domains — the unique domains within a snapshot.
-- ============================================================
create table if not exists serp_snapshot_domains (
  id                uuid primary key default gen_random_uuid(),
  snapshot_id       uuid not null references serp_snapshots(id) on delete cascade,
  domain            text not null,
  is_client         boolean not null default false,
  -- DataForSEO Backlinks summary enrichment (per target domain).
  domain_rating     integer,                           -- DataForSEO domain rank (0–1000), DR-equivalent
  referring_domains integer,                           -- domain-level referring domains
  backlinks         integer,
  backlinks_status  text not null default 'pending'
                      check (backlinks_status in ('ok', 'failed', 'skipped', 'pending')),
  created_at        timestamptz not null default now()
);

create index if not exists idx_serp_snapshot_domains_snapshot
  on serp_snapshot_domains (snapshot_id);

-- ============================================================
-- RLS: enabled, no policies (service-role only).
-- ============================================================
alter table serp_snapshot_domains enable row level security;
