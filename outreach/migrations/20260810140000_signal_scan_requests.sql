-- =============================================================================
-- organic_scan_request / ai_scan_request — signed orders that let a UI click
-- run the report's ORGANIC and AI-VISIBILITY paid scans, per prospect.
--
-- The per-prospect report (writer/platform-api ProspectReport) already renders
-- four signals — maps, organic, AI, paid — but only the maps geogrid has ever
-- had an in-app trigger. Organic (`scan-organic`) and AI (`scan-ai`) could only
-- be run from the CLI, so their report sections read `not_scanned` for every
-- prospect nobody hand-ran. The owner asked for those two to be runnable from
-- the report (this session). These are the two order tables that carry it.
--
-- SAME confirmation PRINCIPLE as scan_request (DECISIONS.md 2026-08-06): the row
-- is evidence of deliberate human intent the accidental deploy path cannot
-- manufacture. platform-api WRITES the order (admin-gated) and reads status; it
-- never executes — the scan clients live in the outreach image, and the outreach
-- service's `tick` command drains and runs at most one order per queue per tick
-- (the §11 collector cron). Splitting the spend path across two services is how
-- a gate stays one.
--
-- TWO tables, not one polymorphic order: organic attaches to an existing
-- rolled-up `scan_snapshot` (submarket × keyword × time), AI runs against an
-- `ai_region` (a coarse human-seeded place name, NOT a submarket — see
-- 20260808140000). Different targets carry different invariants, and keeping
-- them apart means neither bends to fit the other (the same reasoning that made
-- onboard_request separate from scan_request).
--
-- House posture (HANDOFF §2): RLS on, ZERO policies, service-role only. Supabase
-- grants ALL to anon/authenticated by default, so the revoke is the statement
-- that does something. Do NOT add an RLS policy to silence the advisor.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- organic_scan_request — one organic SERP capture for the snapshot the report
-- reads. Targets snapshot_id directly (resolved by platform-api from the
-- prospect's report provenance) so the capture lands on the EXACT snapshot the
-- organic section reads, never a drifted "latest".
-- ---------------------------------------------------------------------------
create table if not exists organic_scan_request (
  id uuid primary key default gen_random_uuid(),

  -- The rolled-up snapshot the report reads. capture_organic attaches the
  -- serp_result to this snapshot; ON DELETE CASCADE because an order for a
  -- deleted snapshot can never execute.
  snapshot_id uuid not null references scan_snapshot(id) on delete cascade,
  keyword_id  uuid not null references keyword(id)       on delete cascade,

  -- AR Tools profile id of the admin who clicked. NO foreign key: profiles live
  -- in AR-Internal-Tools and Postgres cannot enforce across databases (HANDOFF
  -- §2, same as scan_request.requested_by / lead.owner_id). Not null — an
  -- unattributed order defeats the order being the confirmation.
  requested_by uuid not null,
  note text,

  -- pending   — signed, waiting for the next tick. The only state the UI creates.
  -- running   — a tick claimed it (conditional update where status='pending', so
  --             two workers cannot both take one).
  -- done      — capture ran (a snapshot already captured drains as a free no-op,
  --             capture_organic is idempotent). Terminal.
  -- failed    — refused (budget, vanished target) or errored; `error` says why.
  --             Terminal: re-placed by a human who read the error, never retried.
  -- cancelled — withdrawn from the UI while still pending. Terminal.
  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),

  error text,

  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

-- One ACTIVE order per snapshot × keyword. Partial so history accumulates: "you
-- cannot queue what is already queued or running". Many prospects share one
-- submarket snapshot, so clicking organic for a dozen of them collapses to ONE
-- order here (the rest read back `already_active`) — one billed capture fills
-- the section for all of them.
create unique index if not exists organic_scan_request_one_active
  on organic_scan_request (snapshot_id, keyword_id)
  where status in ('pending', 'running');

create index if not exists organic_scan_request_pending_idx
  on organic_scan_request (created_at)
  where status = 'pending';

alter table organic_scan_request enable row level security;
revoke all on organic_scan_request from anon, authenticated;

comment on table organic_scan_request is
  'Signed order authorizing ONE organic-SERP capture for the snapshot the report reads '
  '(report metrics UI trigger, 2026-08-10). platform-api writes admin-only; the outreach tick '
  'drains at most one per heartbeat. Service-role only, RLS-on/zero-policy per HANDOFF §2.';

-- ---------------------------------------------------------------------------
-- ai_scan_request — one AI-visibility capture (ChatGPT + Google AI Overview)
-- for an ai_region × keyword. The answer is shared by every prospect in the
-- region, so the order targets the region, not the prospect (the report does
-- the per-prospect "is this business named" read at read time).
-- ---------------------------------------------------------------------------
create table if not exists ai_scan_request (
  id uuid primary key default gen_random_uuid(),

  ai_region_id uuid not null references ai_region(id) on delete cascade,
  keyword_id   uuid not null references keyword(id)   on delete cascade,

  requested_by uuid not null,          -- AR Tools profile id; no cross-db FK (HANDOFF §2)
  note text,

  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),

  error text,

  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

-- One active order per region × keyword. run_ai_scan is re-runnable (latest wins
-- at read time), so this only prevents a DUPLICATE in-flight order, not a re-scan.
create unique index if not exists ai_scan_request_one_active
  on ai_scan_request (ai_region_id, keyword_id)
  where status in ('pending', 'running');

create index if not exists ai_scan_request_pending_idx
  on ai_scan_request (created_at)
  where status = 'pending';

alter table ai_scan_request enable row level security;
revoke all on ai_scan_request from anon, authenticated;

comment on table ai_scan_request is
  'Signed order authorizing ONE AI-visibility capture (ChatGPT + AIO) for an ai_region × keyword '
  '(report metrics UI trigger, 2026-08-10). platform-api writes admin-only; the outreach tick '
  'drains at most one per heartbeat. Service-role only, RLS-on/zero-policy per HANDOFF §2.';
