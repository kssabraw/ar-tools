-- =============================================================================
-- scan_request — the signed order that lets a UI click spend money
--
-- Owner ruling 2026-08-06 (DECISIONS.md; resolves I-072, supersedes HANDOFF §11a's
-- default): the suite UI must START scans, not only read them. A button has no
-- honest way to reach the deploy path the spend gate (§7.2) was built around, so
-- the confirmation CHANGES CARRIER, NOT PRINCIPLE: money moves only on evidence
-- the accidental path cannot supply. For config-driven runs that evidence stays
-- the name-matched env token, untouched. For UI runs it is a row in this table —
-- single-use, named to one submarket x keyword, attributed to the AR Tools
-- profile that clicked, and consumed by execution. A replayed deploy, a leftover
-- variable, or an unrelated merge cannot manufacture one.
--
-- The drain lives in the outreach service's `tick` command (collect + at most
-- ONE order per tick), which the §11 collector cron runs. platform-api WRITES
-- orders and reads status; it never executes them — the scan client lives in
-- the outreach image, and splitting the spend path across two services is how
-- a gate stops being one.
-- =============================================================================

create table if not exists scan_request (
  id uuid primary key default gen_random_uuid(),

  submarket_id uuid not null references submarket(id) on delete cascade,
  keyword_id   uuid not null references keyword(id)   on delete cascade,

  -- The AR Tools profile id of the admin who clicked. NO foreign key, deliberately:
  -- profiles live in AR-Internal-Tools and Postgres cannot enforce a reference
  -- across databases (HANDOFF §2 — same reasoning as lead.owner_id). Not null,
  -- because an unattributed order defeats the point of the order being the
  -- confirmation.
  requested_by uuid not null,
  note text,

  -- pending    — signed, waiting for the next tick. The only state the UI creates.
  -- running    — a tick claimed it. Claims are conditional (update .. where
  --              status = 'pending'), so two workers cannot both take one.
  -- done       — submit_scan ran; snapshot_id points at what it opened. Terminal.
  -- failed     — refused (budget, unknown target) or errored; `error` says why.
  --              Terminal: a failed order is re-placed by a human reading the
  --              error, never silently retried — retrying is how one click
  --              becomes N paid scans.
  -- cancelled  — withdrawn from the UI while still pending. Terminal.
  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),

  -- Set when the order executes. SET NULL rather than CASCADE on snapshot delete:
  -- the order is the spend authorization record, and deleting a snapshot must not
  -- delete the evidence that somebody authorized paying for it.
  snapshot_id uuid references scan_snapshot(id) on delete set null,
  error text,

  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

-- One ACTIVE order per submarket x keyword. Partial so history accumulates: the
-- constraint is "you cannot queue what is already queued or running", not "each
-- pair is scanned once". This is also where the one-submarket ruling survives
-- structurally in the UI path — an order IS one submarket x one keyword, and the
-- drain takes at most one per tick, so a market sweep cannot be expressed.
create unique index if not exists scan_request_one_active
  on scan_request (submarket_id, keyword_id)
  where status in ('pending', 'running');

-- The drain's read: oldest pending first.
create index if not exists scan_request_pending_idx
  on scan_request (created_at)
  where status = 'pending';

-- House posture (HANDOFF §2): RLS on, zero policies, service-role only. And the
-- §6.12 lesson: Supabase grants ALL to anon/authenticated by default, so the
-- revoke is the part that does something.
alter table scan_request enable row level security;
revoke all on scan_request from anon, authenticated;
