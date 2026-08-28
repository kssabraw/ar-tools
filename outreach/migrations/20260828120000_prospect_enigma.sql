-- =============================================================================
-- Enigma card-revenue rung — per-prospect card-transaction activity/health.
--
-- The PROVEN half of the Enigma integration (DECISIONS.md 2026-08-27 →
-- 2026-08-28). The Enigma GraphQL `search` query reliably returns each matched
-- business's `card_revenue_amount` over its native **1m / 3m / 12m** windows
-- (there is NO 6m period — DECISIONS.md); the owner/principal half of the same
-- call returned EMPTY for the home-service trades this pipeline targets and is a
-- SEPARATE, deferred rung (gated on a live console-batch yield test), so this
-- store is card-first.
--
-- Same signed-order model as `enrichment_request` / `name_search_request`: a
-- lookup BILLS one Enigma call per prospect, so the spend is authorized by a
-- single-use `enigma_request` row (the confirmation an accidental deploy cannot
-- manufacture), drained by the outreach `tick`. The per-prospect answer is
-- durable and idempotent — a re-order re-bills only the un-fetched prospects.
--
-- Value is PHASE-4-GATED (scoping doc `docs/enigma-integration-scoping-v0_1.md`):
-- the card windows are STORED now (they cannot be backfilled for a business we
-- never looked up) but only MOVE a prospect's score once Phase 4 Stage 2+ has
-- accumulated outcomes to fit against. Storing early is the whole point.
--
-- The `prospect` table is left pristine (owned verbatim by docs/PHASE-1-BRIEF.md
-- §1 — the same reason enrichment lives in its own tables), so the result lands
-- in `prospect_enigma`, keyed by prospect_id.
--
-- House posture (HANDOFF §2 / §6.12): RLS on, zero policies, service-role only;
-- the REVOKE is the part that actually restricts (Supabase grants ALL to
-- anon/authenticated by default).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- enigma_request — the signed order (the spend confirmation).
--
-- A placement writes one of these; the outreach `tick` drains it and bills
-- Enigma one lookup per prospect. The row IS the authorization: single-use,
-- attributed to the admin who placed it, carrying the exact selection and the
-- entity path that was authorized. Mirrors enrichment_request, minus the
-- enricher-set column (Enigma has no per-call enricher list) plus the entity
-- path (BRAND — where the probe found card data — vs OPERATING_LOCATION).
-- ---------------------------------------------------------------------------
create table if not exists enigma_request (
  id uuid primary key default gen_random_uuid(),

  -- The selection. prospect_ids (not place_ids): Enigma matches on name+address,
  -- and the card result attaches back to the prospect. An empty array is refused
  -- at placement.
  prospect_ids uuid[] not null,

  -- Which Enigma entity path to match. 'brand' returned the card windows in the
  -- probe (roles/owner were empty at BOTH entity levels for plumbers), so it is
  -- the default; 'operating_location' reads roles directly on the location and is
  -- kept for a future card/owner run against a vertical that carries principals.
  entity_type text not null default 'brand'
    check (entity_type in ('brand', 'operating_location')),

  -- The AR Tools profile id of the admin who placed it. NO foreign key,
  -- deliberately (profiles live in AR-Internal-Tools; Postgres cannot reference
  -- across databases — same reasoning as enrichment_request.requested_by). Not
  -- null: an unattributed order defeats the point of the order being the
  -- confirmation.
  requested_by uuid not null,
  note text,

  -- The estimate recorded at placement. This column doubles as the per-user daily
  -- budget ledger (a placement surface sums today's orders for a user before
  -- writing the next), mirroring enrichment_request. Actual billed cost is
  -- reconciled to `cost_ledger` by the drain (ISSUES I-022).
  est_cost_cents integer not null default 0,

  -- pending   — signed, waiting for a tick. The only state a placement creates.
  -- running   — a tick claimed it (conditional claim: update .. where
  --             status='pending', so two workers cannot both take one).
  -- done      — the drain finished; counts below say what happened. Terminal.
  -- failed    — refused (budget) or errored before/after any spend; `error` says
  --             why. Terminal: re-placed by a human reading it, never auto-retried.
  -- cancelled — withdrawn while still pending. Terminal.
  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),

  -- Progress counters, all written by the drain (CUMULATIVE across ticks — a
  -- large order resumes and still reports its whole self). requested = len(ids);
  -- skipped = already-fetched prospects the drain did NOT re-bill (idempotency);
  -- matched = prospects Enigma matched to an entity; card = of those, the ones
  -- carrying at least one 1m/3m/12m window; no_match = matched nothing (a real,
  -- billed answer); failed = the lookup call errored (retryable).
  requested_count integer not null default 0,
  skipped_count   integer not null default 0,
  matched_count   integer not null default 0,
  card_count      integer not null default 0,
  no_match_count  integer not null default 0,
  failed_count    integer not null default 0,

  error text,
  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

-- The drain's read: oldest pending first.
create index if not exists enigma_request_pending_idx
  on enigma_request (created_at)
  where status = 'pending';

-- The budget-guard read: a user's orders placed today.
create index if not exists enigma_request_requester_idx
  on enigma_request (requested_by, created_at desc);

-- ---------------------------------------------------------------------------
-- prospect_enigma — one row per prospect: the Enigma lookup result + the
-- idempotency marker the drain reads to avoid re-billing.
--
-- Card-first, but self-describing and extensible: the untouched matched entity
-- is kept in `raw`, so any owner/firmographic fields Enigma returns on the same
-- (already-billed) call are captured for a later re-parse WITHOUT a re-bill — the
-- prospect_enrichment.raw / FIELD_ALIASES discipline (measure-don't-infer, I-018).
--
-- status:
--   matched   — matched an entity AND got >=1 card window. Durable.
--   no_card   — matched an entity but no card window (billed answer). Durable.
--   no_match  — matched no entity at threshold (a real, billed answer: this
--               business is not in Enigma's index / didn't clear the floor).
--               Durable — never re-billed on a re-order.
--   failed    — the lookup call errored (transport/HTTP). RETRYABLE.
-- ---------------------------------------------------------------------------
create table if not exists prospect_enigma (
  prospect_id uuid primary key references prospect(id) on delete cascade,

  -- Denormalized join key, kept so an Enigma row is self-describing without
  -- re-reading prospect. NULLABLE: Enigma matches on name+address, not place_id,
  -- so a prospect with no place_id can still be looked up (unlike the contact
  -- rungs, whose contact rows need place_id as a NOT-NULL join key).
  place_id text,

  status text not null
    check (status in ('matched', 'no_card', 'no_match', 'failed')),

  -- Whether an Enigma entity matched at all (status matched OR no_card). Carried
  -- explicitly so a match-rate read never has to reason about the status set.
  matched boolean not null default false,
  -- The entity name Enigma matched, for QA of match quality (a wrong match is the
  -- silent failure — a plausible card number attached to the wrong business).
  matched_name text,

  -- The card_revenue_amount over Enigma's native windows (projected/panel-scaled
  -- $ figure, the console export's Card_revenue_amount_* value; null when Enigma's
  -- panel is too thin for that window — a compliance floor, not an error).
  card_revenue_1m  numeric,
  card_revenue_3m  numeric,
  card_revenue_12m numeric,
  -- The latest periodEndDate across the returned windows — the "revenue as of"
  -- recency the scoring model wants (the windows are a rolling series).
  card_as_of date,

  -- The entity path this result came from ('brand' | 'operating_location').
  entity_type text,

  -- Which order produced this. SET NULL on order delete: the result is the
  -- durable fact; the order is the authorization record and may be pruned.
  enigma_request_id uuid references enigma_request(id) on delete set null,
  error text,               -- populated only on status='failed'

  -- The untouched matched entity (card + any owner/firmographic fields), for
  -- audit and re-parse without a re-pull. Null on no_match.
  raw jsonb,

  fetched_at timestamptz not null default now()
);

create index if not exists prospect_enigma_status_idx
  on prospect_enigma (status);
-- Prospects with any card window (the scoring feature's read).
create index if not exists prospect_enigma_card_idx
  on prospect_enigma (prospect_id)
  where card_revenue_12m is not null;

-- ---------------------------------------------------------------------------
-- RLS + grants. House posture: RLS on, zero policies, service-role only. REVOKE
-- FIRST — the default ALL grant to anon/authenticated is what actually needs
-- removing (HANDOFF §6.12).
-- ---------------------------------------------------------------------------
alter table enigma_request  enable row level security;
alter table prospect_enigma enable row level security;

revoke all on enigma_request  from anon, authenticated;
revoke all on prospect_enigma from anon, authenticated;
