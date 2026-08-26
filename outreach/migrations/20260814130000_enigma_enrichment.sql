-- =============================================================================
-- Enigma enrichment — OWNER identity + contact (name / phone / email) + firmographics.
--
-- The fallback layer for the contacts Outscraper's website scrape could NOT get.
-- Outscraper enrichment (prospect_enrichment / prospect_contact) reads a business's
-- own site; when that site is thin or absent it returns no owner and no contact.
-- Enigma resolves the business to its LEGAL ENTITY and the people on its government
-- registration (its genuine strength), plus whatever contact coordinates and card
-- revenue / growth / location-count it carries.
--
-- SAME spend + provenance discipline as Outscraper enrichment
-- (20260810120000_prospect_enrichment), and DELIBERATELY separate tables rather
-- than reusing prospect_contact: that table's store path does an UNSCOPED
-- delete-by-prospect_id (enrich_queue._store_prospect), so a later Outscraper
-- re-enrichment would clobber Enigma rows written there. The `prospect` table is
-- left untouched; Enigma state lives beside it.
--
-- NEW VENDOR — inert until provisioned. Nothing here runs until ENIGMA_API_KEY is
-- set on the outreach service; the tick drain is gated on the key, so applying this
-- migration on its own changes no behaviour and spends nothing (DECISIONS 2026-08-14).
--
-- Two invariants carried from the paid-signal work (I-099):
--   * FABRICATION GATE — an owner/contact is asserted ONLY when the entity match
--     clears `enigma_min_match_score`. Below it the row is `no_match` and NO owner
--     is written (raw kept for inspection). A wrong entity match must never
--     manufacture a false owner or phone.
--   * WHICH SOURCE FIRED — `owner_evidence` records whether the owner came from a
--     government registration, a contact dataset, or both, so a surface can say
--     only what that source actually measured.
--
-- House posture (HANDOFF §2 / §6.12): RLS on, zero policies, service-role only;
-- REVOKE is the part that restricts (default ALL grant to anon/authenticated).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- enigma_request — the signed order (the spend confirmation).
--
-- Mirrors enrichment_request exactly: a UI click writes one, the outreach `tick`
-- drains it, the row IS the authorization (single-use, attributed, carrying the
-- exact selection). Enigma is BATCHABLE per request, so one order carries the whole
-- selection and `est_cost_cents` doubles as the per-user daily budget ledger.
-- ---------------------------------------------------------------------------
create table if not exists enigma_request (
  id uuid primary key default gen_random_uuid(),

  -- The selection. prospect_ids (not place_ids): the drain resolves each prospect's
  -- identifying fields (name / address / website / phone) for the Enigma match, and
  -- the result attaches back to the prospect. An empty array is refused at placement.
  prospect_ids uuid[] not null,

  -- The AR Tools profile id of the admin who clicked. NO foreign key (profiles live
  -- in AR-Internal-Tools; cross-database FKs are impossible — same as
  -- enrichment_request.requested_by). Not null: an unattributed paid order defeats
  -- the point of the order being the confirmation.
  requested_by uuid not null,
  note text,

  -- The estimate recorded at placement — the per-user daily budget ledger
  -- (platform-api sums today's orders for a user before writing the next). Actual
  -- billed cost is reconciled to cost_ledger by the drain (ISSUES I-022).
  est_cost_cents integer not null default 0,

  -- pending → running → done | failed | cancelled. Same semantics + conditional
  -- claim as enrichment_request; a failed order is re-placed by a human, never
  -- auto-retried.
  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),

  -- Progress counters, all written by the drain. requested = len(prospect_ids);
  -- skipped = already-resolved prospects NOT re-billed (idempotency);
  -- resolved = prospects freshly matched to an Enigma entity this run;
  -- owners = prospects for which an owner cleared the match/confidence gate;
  -- contacts = owner phone/email coordinates written;
  -- failed = prospects whose Enigma call errored (retryable).
  requested_count integer not null default 0,
  skipped_count   integer not null default 0,
  resolved_count  integer not null default 0,
  owner_count     integer not null default 0,
  contact_count   integer not null default 0,
  failed_count    integer not null default 0,

  error text,
  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

create index if not exists enigma_request_pending_idx
  on enigma_request (created_at)
  where status = 'pending';

create index if not exists enigma_request_requester_idx
  on enigma_request (requested_by, created_at desc);

-- ---------------------------------------------------------------------------
-- prospect_enigma — one row per prospect: the resolved entity, the chosen owner,
-- the firmographics, and the idempotency marker the drain reads to avoid re-billing.
--
-- status:
--   resolved     — matched to an Enigma entity above the confidence gate. May or
--                  may not carry an owner/contact (owner columns null if none).
--   no_match     — no entity matched, OR the best match scored below
--                  enigma_min_match_score. NO owner is asserted. Terminal (a
--                  re-order does not re-bill it), so a genuine "Enigma has nothing"
--                  is recorded, not retried forever.
--   no_contacts  — entity + owner resolved but no phone/email coordinates found.
--   failed       — the call errored. RETRYABLE (a re-order re-bills only these).
-- ---------------------------------------------------------------------------
create table if not exists prospect_enigma (
  prospect_id uuid primary key references prospect(id) on delete cascade,

  -- Denormalized join key (self-describing without re-reading prospect).
  place_id text not null,

  status text not null
    check (status in ('resolved', 'no_match', 'no_contacts', 'failed')),

  -- The Enigma entity this prospect resolved to, and how confident the match was
  -- (0..1). match_score gates every assertion below it — see the fabrication gate.
  enigma_entity_id text,
  match_score numeric,
  legal_name text,

  -- The CHOSEN decision-maker (highest role score among the entity's people, per
  -- enigma_enrich.role_score). Null when no person cleared the gate.
  owner_name  text,
  owner_title text,
  owner_role_score integer,       -- the role-priority score of the chosen title (0..100)
  owner_email text,
  owner_phone text,
  -- WHICH SOURCE produced the owner, so a surface claims only what it measured:
  --   gov_registration — from a Secretary-of-State / registration record (strong)
  --   contact_data     — from a bundled contact dataset (identity weaker, but has
  --                      the phone/email)
  --   both             — the two agree (strongest)
  owner_evidence text
    check (owner_evidence in ('gov_registration', 'contact_data', 'both')),

  -- Firmographics captured from the same Brand response (economics is inert for
  -- SCORING under flat pricing — DECISIONS — so this is stored for qualification /
  -- segmentation / a future tool, never wired into the scorecard here).
  card_revenue_cents bigint,       -- estimated annual card revenue (cents)
  revenue_growth_pct numeric,      -- estimated YoY card-revenue growth (%)
  location_count integer,          -- operating-location count (1 = independent)

  -- Every candidate person the entity carried, with role scores, so the owner
  -- CHOICE is inspectable and an alternate decision-maker is not lost.
  officers jsonb not null default '[]'::jsonb,

  -- Which order produced this. SET NULL on order delete (the resolution is the
  -- durable fact; the order is the authorization record).
  enigma_request_id uuid references enigma_request(id) on delete set null,
  error text,                      -- populated only on status='failed'

  -- The untouched Enigma response fragment, for audit and for re-parsing against
  -- corrected field paths without a re-pull (the measure-don't-infer / raw-recovery
  -- discipline — ISSUES: the Enigma response shape is unconfirmed until a live run).
  raw jsonb,

  resolved_at timestamptz not null default now()
);

create index if not exists prospect_enigma_status_idx
  on prospect_enigma (status);
create index if not exists prospect_enigma_place_idx
  on prospect_enigma (place_id);
create index if not exists prospect_enigma_owner_email_idx
  on prospect_enigma (lower(owner_email)) where owner_email is not null;

-- ---------------------------------------------------------------------------
-- RLS + grants. REVOKE FIRST — the default ALL grant to anon/authenticated is what
-- actually needs removing (HANDOFF §6.12).
-- ---------------------------------------------------------------------------
alter table enigma_request  enable row level security;
alter table prospect_enigma enable row level security;

revoke all on enigma_request  from anon, authenticated;
revoke all on prospect_enigma from anon, authenticated;
