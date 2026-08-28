-- =============================================================================
-- Site name-scrape — the FREE owner/manager fallback.
--
-- When Outscraper enrichment returns no NAME for a prospect (status
-- `no_contacts`, or contacts with an email/phone but nobody's name), the team
-- can scan the business's OWN site for the owner/manager. This is FREE — an own
-- HTTP GET, the exact posture as `prospect_tech_signal` / `scan-tech` (PRD §B3
-- "own request, not a paid service") — so unlike enrichment there is NO spend,
-- NO budget ledger and NO `cost_ledger` write.
--
-- The order row still exists (`name_scrape_request`), for the same reasons the
-- free tech backlog would if it were UI-triggered: it carries the selection, is
-- claimed conditionally so two ticks can't both take it, and gives the UI a row
-- to poll. It is NOT a spend confirmation (there is nothing to confirm) — the
-- `tick` command drains it with no env token, like the enrich drain.
--
-- Found names land in the EXISTING `prospect_contact` table with
-- `source = 'site_scrape'`, beside any Outscraper contacts (that column is
-- free-text and already defaults to 'outscraper'; no change needed there). The
-- two producers are independent: a name-scrape replaces only the site_scrape
-- contacts, never the Outscraper ones.
--
-- House posture (HANDOFF §6.12): RLS on, zero policies, service-role only; the
-- REVOKE is the part that actually restricts (Supabase grants ALL to
-- anon/authenticated by default).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- name_scrape_request — the free order the UI places; `tick` drains it.
-- ---------------------------------------------------------------------------
create table if not exists name_scrape_request (
  id uuid primary key default gen_random_uuid(),

  -- The selection. prospect_ids: the UI selects prospects, the drain resolves
  -- each to its website + place_id. An empty array is refused at placement.
  prospect_ids uuid[] not null,

  -- The AR Tools profile id of the staff member who placed it. NO foreign key
  -- (profiles live in AR-Internal-Tools — cross-database, same reasoning as
  -- enrichment_request.requested_by). Not null.
  requested_by uuid not null,
  note text,

  -- pending   — placed, waiting for a tick. The only state the UI creates.
  -- running   — a tick claimed it (conditional claim on status='pending').
  -- done       — the drain finished; counts below say what happened. Terminal.
  -- failed     — refused (over-cap / empty) or errored. Terminal.
  -- cancelled  — withdrawn from the UI while still pending. Terminal.
  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),

  -- Progress counters, all written by the drain. requested = len(prospect_ids);
  -- skipped = prospects with a durable marker (found|no_names) not re-scraped;
  -- scraped = prospects fetched this run; found = prospects with >=1 name;
  -- name_count = contact rows written; failed = prospects whose fetch errored.
  requested_count integer not null default 0,
  skipped_count   integer not null default 0,
  scraped_count   integer not null default 0,
  found_count     integer not null default 0,
  name_count      integer not null default 0,
  failed_count    integer not null default 0,

  error text,
  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

-- The drain's read: oldest pending first.
create index if not exists name_scrape_request_pending_idx
  on name_scrape_request (created_at)
  where status = 'pending';

-- ---------------------------------------------------------------------------
-- prospect_name_scrape — one row per prospect: the scrape STATUS + provenance,
-- and the idempotency marker the drain reads to avoid re-fetching.
--
-- Separate from the enrichment marker so the two producers are independent (an
-- enriched prospect can still be name-scraped, and vice versa). The
-- measured-vs-found distinction is the point: `unreachable` (the site was down /
-- blocked) is recorded distinctly from `no_names` (the site loaded and named
-- nobody), so the report can say "couldn't read the site" rather than "no owner
-- named". `found`/`no_names` are durable (never re-scraped); `unreachable` and
-- `failed` are retryable.
-- ---------------------------------------------------------------------------
create table if not exists prospect_name_scrape (
  prospect_id uuid primary key references prospect(id) on delete cascade,

  status text not null
    check (status in ('found', 'no_names', 'unreachable', 'failed')),

  -- The HOMEPAGE fetch outcome (ok|blocked|timeout|unreachable), so a reader can
  -- tell why an `unreachable` happened. Null on a `failed` (the fetch never
  -- returned a status).
  fetch_status text,

  name_count    integer not null default 0,
  pages_fetched integer not null default 0,
  source_urls   text[],                 -- the pages actually fetched

  -- Which order produced this. SET NULL on order delete (the scrape is the
  -- durable fact; the order is prunable). Null for a CLI/backfill scrape.
  name_scrape_request_id uuid references name_scrape_request(id) on delete set null,

  error text,                            -- populated only on status='failed'

  -- The extracted names + their evidence (source_kind / matched snippet), so a
  -- finding is replayable and a corrected extractor re-reads stored inputs.
  raw jsonb,

  scraped_at timestamptz not null default now()
);

create index if not exists prospect_name_scrape_status_idx
  on prospect_name_scrape (status);

-- ---------------------------------------------------------------------------
-- RLS + grants. House posture: RLS on, zero policies, service-role only. REVOKE
-- FIRST — the default ALL grant to anon/authenticated is what actually needs
-- removing (HANDOFF §6.12).
-- ---------------------------------------------------------------------------
alter table name_scrape_request  enable row level security;
alter table prospect_name_scrape enable row level security;

revoke all on name_scrape_request  from anon, authenticated;
revoke all on prospect_name_scrape from anon, authenticated;
