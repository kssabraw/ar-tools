-- =============================================================================
-- Lead enrichment — contact NAMES, PHONES and EMAILS per prospect.
--
-- On-demand, per-prospect (and per-selection) enrichment via Outscraper's
-- "Emails & Contacts"-style enrichers. This is DELIBERATELY separate from the
-- mass ingest: `outscraper_client.submit_maps_search` hardcodes `enrichment=""`
-- with a hard invariant, so the base pull (thousands of places/market) can never
-- silently bill per-place enrichment. Enrichment here is a distinct, explicitly
-- spend-gated action, executed by the outreach job's `tick` from a SIGNED ORDER
-- ROW (`enrichment_request`) — the same order-is-its-own-confirmation model as
-- `scan_request` / `onboard_request` (DECISIONS.md 2026-08-06 / 2026-08-08).
--
-- Contact-aware by construction: an enriched business returns MULTIPLE contacts
-- (up to ~3), so ONE business (one place_id / one prospect) maps to N
-- `prospect_contact` rows. It is NEVER flattened into duplicate `prospect` rows —
-- that would double-count coverage and every score built on it. The `prospect`
-- table is left untouched (it is owned verbatim by docs/PHASE-1-BRIEF.md §1);
-- enrichment state lives in these three new tables beside it.
--
-- House posture (HANDOFF §2): RLS on, zero policies, service-role only; and the
-- §6.12 lesson — Supabase grants ALL to anon/authenticated by default, so the
-- REVOKE is the part that actually restricts.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- enrichment_request — the signed order (the spend confirmation).
--
-- A UI click writes one of these; the outreach `tick` command drains it and
-- bills Outscraper. The row IS the authorization: single-use, attributed to the
-- admin who clicked, carrying the exact selection and the enricher set that was
-- authorized. A replayed deploy or an unrelated merge cannot manufacture one.
--
-- Unlike a geogrid scan, enrichment is LIGHTWEIGHT and BATCHABLE (one Outscraper
-- request covers many place_ids), so an order carries the WHOLE selection as a
-- place-id/prospect-id list and the drain processes it in one pass — there is no
-- ≤1-per-tick cadence here. `est_cost_cents` doubles as the per-user daily spend
-- LEDGER: platform-api sums a user's orders placed today to enforce the budget
-- guard, so no separate spend table is needed (mirrors LeadOff's leadoff_spend).
-- ---------------------------------------------------------------------------
create table if not exists enrichment_request (
  id uuid primary key default gen_random_uuid(),

  -- The selection. prospect_ids (not place_ids): the UI selects prospects, the
  -- drain resolves each to its place_id for the by-place-id enrichment call, and
  -- contacts attach back to the prospect. An empty array is refused at placement.
  prospect_ids uuid[] not null,

  -- The enricher set FROZEN at authorization time (e.g.
  -- {emails_validator_service, phones_enricher_service}). Recorded so the order
  -- says exactly what was billed, and so a later config change to the default set
  -- does not rewrite what a historical order authorized.
  enrichments text[] not null,

  -- The AR Tools profile id of the admin who clicked. NO foreign key, deliberately
  -- (profiles live in AR-Internal-Tools; Postgres cannot reference across
  -- databases — same reasoning as scan_request.requested_by / lead.owner_id). Not
  -- null: an unattributed order defeats the point of the order being the
  -- confirmation.
  requested_by uuid not null,
  note text,

  -- The estimate recorded at placement. This column is the per-user daily budget
  -- ledger (platform-api sums today's orders for a user before writing the next).
  -- Actual billed cost is reconciled to `cost_ledger` by the drain, like every
  -- other rate in this pipeline (ISSUES I-022).
  est_cost_cents integer not null default 0,

  -- pending   — signed, waiting for a tick. The only state the UI creates.
  -- running   — a tick claimed it (conditional claim: update .. where
  --             status='pending', so two workers cannot both take one).
  -- done       — the drain finished; counts below say what happened. Terminal.
  -- failed     — refused (budget) or errored before/after any spend; `error` says
  --             why. Terminal: re-placed by a human reading it, never auto-retried.
  -- cancelled  — withdrawn from the UI while still pending. Terminal.
  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),

  -- Progress counters, all written by the drain. requested = len(prospect_ids);
  -- skipped = already-enriched prospects the drain did NOT re-bill (idempotency);
  -- enriched = prospects freshly enriched this run; contacts = rows written;
  -- failed = prospects whose enrichment call errored.
  requested_count integer not null default 0,
  skipped_count   integer not null default 0,
  enriched_count  integer not null default 0,
  contact_count   integer not null default 0,
  failed_count    integer not null default 0,

  error text,
  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

-- The drain's read: oldest pending first.
create index if not exists enrichment_request_pending_idx
  on enrichment_request (created_at)
  where status = 'pending';

-- The budget-guard read: a user's orders placed today (platform-api sums
-- est_cost_cents over these).
create index if not exists enrichment_request_requester_idx
  on enrichment_request (requested_by, created_at desc);

-- ---------------------------------------------------------------------------
-- prospect_enrichment — one row per prospect: the enrichment STATUS + provenance,
-- and the idempotency marker the drain reads to avoid re-billing.
--
-- Separate from `prospect_contact` because a prospect can be enriched and yield
-- ZERO contacts (a real, billed outcome — Outscraper found nobody), which must be
-- recorded so the drain never re-bills it. `status='failed'` (the call errored)
-- IS retryable; 'enriched' and 'no_contacts' are not.
-- ---------------------------------------------------------------------------
create table if not exists prospect_enrichment (
  prospect_id uuid primary key references prospect(id) on delete cascade,

  -- Denormalized join key (grid_result joins on place_id; kept here so an
  -- enrichment row is self-describing without re-reading prospect).
  place_id text not null,

  status text not null
    check (status in ('enriched', 'no_contacts', 'failed')),
  contact_count integer not null default 0,

  -- Which order produced this. SET NULL on order delete: the enrichment is the
  -- durable fact; the order is the authorization record and may be pruned.
  enrichment_request_id uuid references enrichment_request(id) on delete set null,
  enrichments text[],       -- the enricher set actually requested for this prospect
  error text,               -- populated only on status='failed'

  -- The untouched business-level enriched record, for audit and for re-parsing
  -- against corrected field aliases without a re-pull (the parser.FIELD_ALIASES
  -- discipline, I-018 — measure-don't-infer).
  raw jsonb,

  enriched_at timestamptz not null default now()
);

create index if not exists prospect_enrichment_status_idx
  on prospect_enrichment (status);

-- ---------------------------------------------------------------------------
-- prospect_contact — the N contacts an enriched business returns.
--
-- One business (place_id / prospect) → many contacts. Store WHAT COMES BACK and
-- mark validation status; never block a contact because a field is missing
-- (a real enriched export is partial + mixed quality: email ~83% filled,
-- full_name ~51%, contact_phone ~13%, some full_name = "Unknown Unknown",
-- generic info@ addresses). Field names follow the documented Outscraper
-- "Emails & Contacts" column prefixes; the parser reads them defensively and the
-- untouched fragment is kept in `raw` so a corrected alias needs no re-pull.
--
-- Replace-on-place at store time (delete this prospect's contacts, insert fresh),
-- so a re-enrichment is idempotent and never duplicates contacts.
-- ---------------------------------------------------------------------------
create table if not exists prospect_contact (
  id uuid primary key default gen_random_uuid(),
  prospect_id uuid not null references prospect(id) on delete cascade,
  place_id text not null,               -- denormalized join key

  contact_index integer not null default 0,  -- position in the returned set

  full_name       text,
  first_name      text,
  last_name       text,
  title           text,
  name_for_emails text,                 -- Outscraper's name_for_emails column

  email        text,
  email_status text,                    -- email.emails_validator.status (valid/invalid/unknown/…)
  email_is_generic boolean not null default false,  -- info@/contact@/office@ etc.

  phone         text,
  phone_type    text,                   -- phone.phones_enricher.* (mobile/landline/voip/…)
  phone_carrier text,                   -- phone.phones_enricher / whitepages_phones carrier

  source text not null default 'outscraper',
  raw jsonb,                            -- the untouched per-contact fragment
  enriched_at timestamptz not null default now()
);

create index if not exists prospect_contact_prospect_idx
  on prospect_contact (prospect_id);
create index if not exists prospect_contact_place_idx
  on prospect_contact (place_id);
-- Email lookups (dedup across the CRM, suppression cross-checks later).
create index if not exists prospect_contact_email_idx
  on prospect_contact (lower(email)) where email is not null;

-- ---------------------------------------------------------------------------
-- RLS + grants. House posture: RLS on, zero policies, service-role only. REVOKE
-- FIRST — the default ALL grant to anon/authenticated is what actually needs
-- removing (HANDOFF §6.12).
-- ---------------------------------------------------------------------------
alter table enrichment_request  enable row level security;
alter table prospect_enrichment enable row level security;
alter table prospect_contact    enable row level security;

revoke all on enrichment_request  from anon, authenticated;
revoke all on prospect_enrichment from anon, authenticated;
revoke all on prospect_contact    from anon, authenticated;
