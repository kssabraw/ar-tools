-- =============================================================================
-- keyword_demand + demand_fetch_request + submarket.location_code
--
-- Phase A of the missed-opportunity valuation (docs/missed-opportunity-valuation-
-- prd-v0_1.md): the dollar figure a prospect forgoes by not ranking in the Maps
-- pack. The FIRST link of that chain — local monthly search demand + CPC — is the
-- only one that needs a paid call; the rest are config + the rank_vector already
-- on disk (read at report-assembly time in platform-api).
--
-- Search volume + CPC are a property of the (keyword, location), NOT the business:
-- every prospect in a submarket scanning the same keyword shares one number. So we
-- fetch ONCE per (keyword, location_code) and cache it here, reused across all
-- prospects and across re-scans — the suite's keyword_market cache pattern, rebuilt
-- in the Outreacher DB (the two-database invariant: this NEVER goes in
-- writer/supabase/migrations).
--
-- The fetch is a signed order (`demand_fetch_request`), auto-enqueued when a scan
-- snapshot finalizes — the SAME model as organic_scan_request (20260810140000):
-- platform-api never spends, the outreach `tick` drains and runs the paid call, the
-- order row is the spend confirmation, and the STANDING confirmation for an auto
-- order is the `demand_auto_enabled` flag (a sentinel requested_by marks it
-- machine-originated). One cheap DataForSEO Google-Ads search_volume call per
-- (keyword, location); the cache makes a re-order a free no-op.
--
-- House posture (HANDOFF §2): RLS on, ZERO policies, service-role only. Supabase
-- grants ALL to anon/authenticated by default, so the revoke is the load-bearing
-- statement; do NOT add an RLS policy to silence the advisor.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- submarket.location_token — the DataForSEO google_ads location the demand fetch
-- pulls volume for, resolved from the submarket/market and cached here so the
-- resolution runs once per submarket, not once per fetch. ADDITIVE and NOT
-- geometry: it does not touch centre/radius/spacing, so it never invalidates a
-- snapshot (the grid-geometry-is-immutable invariant is about the lattice).
--
-- TEXT, not an int code, ON PURPOSE (spike-gated resolution — see the PRD §12
-- spike 1 / ISSUES). There is NO lat/lng → numeric location_code resolver in the
-- codebase; the google_ads search_volume endpoint also accepts a `location_name`
-- string ("City,Region,Country"), which the onboard path can build from data it
-- already has. Storing the RESOLVED TOKEN as text means the resolver can switch
-- from a location_name string to a stringified numeric code later WITHOUT a schema
-- change — the cheapest-to-reverse choice while the resolution mechanism is a spike.
-- ---------------------------------------------------------------------------
alter table submarket add column if not exists location_token text;

comment on column submarket.location_token is
  'DataForSEO google_ads location the keyword_demand fetch pulls volume for (a location_name string '
  'today, spike-gated; a stringified location_code if the resolver switches). Resolved from the '
  'submarket/market centre, cached here so the resolution runs once per submarket. Additive, not '
  'geometry.';

-- ---------------------------------------------------------------------------
-- keyword_demand — cached monthly search volume + CPC for one (keyword,
-- location_token). Keyed by the pair so it is shared by every submarket that
-- resolves to the same location and every scan of the same keyword there.
--
-- All three metrics are NULLABLE: the Google-Ads endpoint legitimately returns a
-- null search_volume / cpc for a thin local term (the same "measured but empty"
-- the coverage layer treats as a finding, never as an error). A null demand row is
-- a fact — "we asked and there wasn't measurable volume" — distinct from no row at
-- all ("we never fetched"), which is what the valuation reads as `not_fetched`
-- (unknown ≡ absent → the dollar line is simply omitted, never zeroed).
-- ---------------------------------------------------------------------------
create table if not exists keyword_demand (
  id uuid primary key default gen_random_uuid(),

  -- The scan keyword term, normalised (lower/trim) by the writer so the same term
  -- from two submarkets shares one row. Matches keyword.term after normalisation.
  keyword text not null,
  -- The resolved DataForSEO google_ads location token the volume was pulled for
  -- (text — see submarket.location_token). Two submarkets resolving to the same
  -- token share this row.
  location_token text not null,

  search_volume integer,   -- monthly searches; NULL = asked, no measurable volume
  cpc numeric,             -- USD; NULL = none returned
  competition numeric,     -- 0..1 or LOW/MED/HIGH-derived; NULL = none returned

  -- Which provider/endpoint produced the row (measure-don't-infer provenance).
  source text not null default 'dataforseo_google_ads',

  fetched_at timestamptz not null default now(),

  unique (keyword, location_token)
);

comment on table keyword_demand is
  'Cached monthly search volume + CPC per (keyword, location_token) for the missed-opportunity '
  'valuation (docs/missed-opportunity-valuation-prd-v0_1.md). Fetched once per (keyword, location) '
  'by a signed demand_fetch_request, reused by every prospect''s valuation. NULL metrics = asked, '
  'no measurable volume (a finding); no row = never fetched. Service-role only, RLS-on/zero-policy.';

alter table keyword_demand enable row level security;
revoke all on keyword_demand from anon, authenticated;

-- ---------------------------------------------------------------------------
-- demand_fetch_request — signed order authorising ONE Google-Ads search_volume
-- call for a snapshot's (keyword, resolved location). Mirrors organic_scan_request
-- exactly (same confirmation principle, same state machine, same one-active index).
-- Targets snapshot_id so the drain can resolve submarket → location_code; the
-- keyword_demand cache is the real idempotency layer (a second submarket in the
-- same city drains as a free no-op once the first has filled the (keyword,
-- location_code) row).
-- ---------------------------------------------------------------------------
create table if not exists demand_fetch_request (
  id uuid primary key default gen_random_uuid(),

  snapshot_id uuid not null references scan_snapshot(id) on delete cascade,
  keyword_id  uuid not null references keyword(id)       on delete cascade,

  -- AR Tools profile id of the requester, or the sentinel nil uuid for an auto
  -- order. NO cross-db FK (profiles live in AR-Internal-Tools), like every other
  -- order table. Not null — an unattributed order defeats the order being the
  -- confirmation.
  requested_by uuid not null,
  note text,

  -- pending → running → done | failed | cancelled. Same semantics as
  -- organic_scan_request: a failed order is terminal (re-placed by a human who read
  -- the error, never machine-retried); a claim is conditional (update .. where
  -- status='pending'); done includes the free cache-hit no-op.
  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),

  error text,

  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

-- One ACTIVE order per snapshot × keyword. Partial so history accumulates.
create unique index if not exists demand_fetch_request_one_active
  on demand_fetch_request (snapshot_id, keyword_id)
  where status in ('pending', 'running');

create index if not exists demand_fetch_request_pending_idx
  on demand_fetch_request (created_at)
  where status = 'pending';

alter table demand_fetch_request enable row level security;
revoke all on demand_fetch_request from anon, authenticated;

comment on table demand_fetch_request is
  'Signed order authorising ONE DataForSEO Google-Ads search_volume fetch for a snapshot''s '
  '(keyword, resolved location), cached into keyword_demand (missed-opportunity valuation, '
  'docs/missed-opportunity-valuation-prd-v0_1.md). platform-api writes admin-only / auto-enqueued '
  'on scan finalize; the outreach tick drains at most one per heartbeat. Service-role only, '
  'RLS-on/zero-policy per HANDOFF §2.';
