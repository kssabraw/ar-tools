-- Migration: 20260711130000_backlink_pages.sql
-- Purpose: Per-page authority breakdown for the Backlink Explorer (Ahrefs
--   "Best by links" analog). The default lookup becomes domain-wide AND
--   page-aware: summary + domain_pages + history (3 cheap calls), with the
--   referring-domains list + anchors moving to lazy on-demand tab loads.
--
--   * backlink_pages — one row per page of the target domain per snapshot:
--     UR (page rank ÷ 10), referring domains, backlinks, first seen.
--   * backlink_snapshots.pages_count — how many pages the capture returned
--     (shown on the tracked-domains strip).

create table if not exists backlink_pages (
  id                uuid primary key default gen_random_uuid(),
  snapshot_id       uuid not null references backlink_snapshots(id) on delete cascade,
  url               text not null,
  page_rating       numeric,          -- page rank ÷ 10 (UR proxy, 0–100)
  referring_domains integer,
  backlinks         integer,
  first_seen        timestamptz
);

create index if not exists idx_backlink_pages_snapshot
  on backlink_pages (snapshot_id);

alter table backlink_pages enable row level security;

alter table backlink_snapshots add column if not exists pages_count integer;
