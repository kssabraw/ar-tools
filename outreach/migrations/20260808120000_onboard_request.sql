-- =============================================================================
-- onboard_request — the signed order for a WHOLE-PIPELINE run of a typed city
--
-- `scan_request` (2026-08-06) authorizes ONE thing: a geogrid scan of an
-- already-ingested submarket. But a city an operator TYPES has never been
-- ingested, and a scan of it rolls up zero prospects (ISSUES I-092:
-- prospect_coverage is grid_result joined to `prospect`, and `prospect` rows
-- come only from the paid Outscraper `ingest`). So the "City + Business type"
-- form needs an order that authorizes the whole chain — discover (ingest) →
-- filter → scan — where the business type IS the ingest category.
--
-- This is a SEPARATE table, not a flag on scan_request, on purpose: scan_request
-- carries a set of guarantees (one submarket x keyword, one scan's spend, a
-- drain built around exactly that) and this order spends differently (a variable
-- ingest pull PLUS a scan). Keeping them apart means neither table's invariants
-- bend to accommodate the other.
--
-- Same confirmation PRINCIPLE as scan_request (DECISIONS.md 2026-08-06): the row
-- is evidence of deliberate human intent the accidental path cannot manufacture,
-- written admin-only by platform-api, executed by the outreach service's `tick`.
-- platform-api creates the market/submarket/keyword rows (geo-derived, free) and
-- writes this order; the outreach service runs the paid pipeline, because that is
-- where the Outscraper + scan clients live.
-- =============================================================================

create table if not exists onboard_request (
  id uuid primary key default gen_random_uuid(),

  -- The rows platform-api created for the typed city + chosen sub-area + business
  -- type. The drain runs ingest for `submarket_id` and scans `submarket_id` x
  -- `keyword_id`; FKs cascade so a submarket teardown takes its orders with it.
  submarket_id uuid not null references submarket(id) on delete cascade,
  keyword_id   uuid not null references keyword(id)   on delete cascade,

  -- The Outscraper ingest CATEGORY (== the typed business type). Distinct from
  -- keyword.term even when the strings coincide: category drives the discovery
  -- pull, keyword drives the geogrid scan (the same separation the seeder keeps).
  category text not null,
  -- Tile-query disambiguation ("CA, USA"), from the city's geocoding. Without it
  -- "plumber, Highland Park" can resolve to the wrong state (the I-032 hazard).
  region text not null default '',

  -- AR Tools profile id of the admin who clicked. NO foreign key — profiles live
  -- in AR-Internal-Tools; Postgres cannot enforce across databases (HANDOFF §2,
  -- same as scan_request.requested_by / lead.owner_id). Not null: an unattributed
  -- order defeats the order being the confirmation.
  requested_by uuid not null,
  note text,

  -- pending   — signed, waiting for the next tick. The only state the UI creates.
  -- running   — a tick claimed it (conditional claim; two workers can't both take one).
  -- done      — discover+filter+scan all ran; snapshot_id points at the scan opened.
  -- failed    — refused (budget) or errored; `error` says why, `stage` says where.
  --             Terminal: re-placed by a human who read the error, never auto-retried
  --             (auto-retry is one click becoming N paid pulls).
  -- cancelled — withdrawn from the UI while still pending. Terminal.
  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),

  -- Where the run got to (ingest | filter | scan | done). Informational — the
  -- multi-stage run means "failed" alone can't say whether money moved, and this
  -- lets the status screen show progress across a multi-minute pull.
  stage text,
  prospects_ingested integer,
  prospects_survived integer,

  -- The scan the run opened, if it reached scanning. SET NULL on snapshot delete:
  -- the order is the spend-authorization record and must outlive the snapshot.
  snapshot_id uuid references scan_snapshot(id) on delete set null,
  error text,

  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

-- One ACTIVE onboard per submarket x keyword — mirrors scan_request's guard.
-- Partial so history accumulates; the constraint is "you cannot queue what is
-- already queued or running", not "each pair is onboarded once".
create unique index if not exists onboard_request_one_active
  on onboard_request (submarket_id, keyword_id)
  where status in ('pending', 'running');

create index if not exists onboard_request_status_created
  on onboard_request (status, created_at);

-- RLS on with ZERO policies — service-role only, the intended posture for every
-- outreach table (HANDOFF §2). platform-api holds the service role; nothing else
-- reads or writes this.
alter table onboard_request enable row level security;
