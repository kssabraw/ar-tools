-- Migration: 20260710170000_backlinks_tool.sql
-- Purpose: Backlink explorer tool (Ahrefs Site Explorer analog) — an
--   any-domain backlink lookup on top of the DataForSEO Backlinks API family.
--   Until now only a summary count per client/competitor domain was stored
--   (backlink_profiles, page_backlink_profiles). This adds a target-keyed store
--   so ANY domain/subdomain/url can be looked up and its overview, referring
--   domains, anchor distribution, and history cached (24h TTL) + tracked over
--   time. The expensive per-link list is fetched on demand and NOT persisted.
--
--   * backlink_targets — one row per looked-up-or-saved target. client_id is
--     NULLABLE: null = an ad-hoc explorer lookup (any domain); set = a client's
--     own domain / a registered competitor surfaced in the workspace. `tracked`
--     marks targets that get scheduled re-snapshots + new/lost alerts (Phase 4).
--   * backlink_snapshots — a dated overview capture per target (RD, backlinks,
--     dofollow/nofollow, broken, referring IPs/subnets, DR=rank÷10). Also the
--     history points for the trend chart. The most-recent snapshot within the
--     TTL is served without a fresh paid pull.
--   * backlink_referring_domains — the per-snapshot referring-domains table
--     (one row per domain; is_new/is_lost carried from DataForSEO). Bounded set
--     — this is what new/lost domain diffing reads.
--   * backlink_anchors — the per-snapshot anchor-text distribution.

create table if not exists backlink_targets (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid references clients(id) on delete cascade,   -- null = ad-hoc any-domain lookup
  target        text not null,                                   -- normalized (no scheme; www stripped for domains)
  target_type   text not null default 'domain'                   -- domain | subdomain | url
                check (target_type in ('domain', 'subdomain', 'url')),
  label         text,
  tracked       boolean not null default false,                  -- scheduled re-snapshot + new/lost alerts (Phase 4)
  last_refreshed_at timestamptz,
  created_by    uuid references auth.users(id) on delete set null,
  created_at    timestamptz not null default now()
);

-- One canonical row per (target, type) — ad-hoc lookups upsert here (client_id
-- null); a client-scoped save is a distinct row so both can coexist.
create unique index if not exists uq_backlink_targets_global
  on backlink_targets (target, target_type) where client_id is null;
create unique index if not exists uq_backlink_targets_client
  on backlink_targets (client_id, target, target_type) where client_id is not null;
create index if not exists idx_backlink_targets_tracked
  on backlink_targets (tracked) where tracked = true;

alter table backlink_targets enable row level security;

create table if not exists backlink_snapshots (
  id                 uuid primary key default gen_random_uuid(),
  target_id          uuid not null references backlink_targets(id) on delete cascade,
  referring_domains  integer,
  backlinks          integer,
  dofollow           integer,
  nofollow           integer,
  broken_backlinks   integer,
  referring_ips      integer,
  referring_subnets  integer,
  domain_rating      numeric,          -- rank ÷ 10 (suite-wide DR proxy), 0–100
  raw                jsonb,            -- full parsed summary for forward-compat
  captured_at        timestamptz not null default now()
);

create index if not exists idx_backlink_snapshots_target
  on backlink_snapshots (target_id, captured_at desc);

alter table backlink_snapshots enable row level security;

create table if not exists backlink_referring_domains (
  id                uuid primary key default gen_random_uuid(),
  snapshot_id       uuid not null references backlink_snapshots(id) on delete cascade,
  domain            text not null,
  domain_rating     numeric,          -- referring domain's rank ÷ 10
  backlinks         integer,          -- links from this domain to the target
  dofollow          integer,
  first_seen        timestamptz,
  last_seen         timestamptz,
  is_new            boolean not null default false,
  is_lost           boolean not null default false
);

create index if not exists idx_backlink_rd_snapshot
  on backlink_referring_domains (snapshot_id);

alter table backlink_referring_domains enable row level security;

create table if not exists backlink_anchors (
  id                uuid primary key default gen_random_uuid(),
  snapshot_id       uuid not null references backlink_snapshots(id) on delete cascade,
  anchor            text,
  backlinks         integer,
  referring_domains integer,
  dofollow          integer,
  first_seen        timestamptz
);

create index if not exists idx_backlink_anchors_snapshot
  on backlink_anchors (snapshot_id);

alter table backlink_anchors enable row level security;
