-- =============================================================================
-- Web-search owner/manager name — the PAID third-rung fallback.
--
-- When Outscraper enrichment returned no NAME and the free site-scrape found
-- none either ("not listed on the site"), the team can pay for a web search that
-- looks the owner/manager up (news, directories, licensing records, LinkedIn).
--
-- This BILLS (one OpenAI web-search call per prospect), so unlike the free
-- `name_scrape` it is a SIGNED, admin-gated, budget-guarded order — the exact
-- model as `enrichment_request` (the order row is the spend confirmation, its
-- `est_cost_cents` doubles as the per-user daily ledger). The `tick` command
-- drains it.
--
-- Anti-fabrication discipline (the module's deepest invariant): a web-searched
-- name is the LOWEST-trust source we have, so it is kept ONLY when the search
-- returns a real SOURCE URL that names the person for THIS business, the name
-- passes the same business-name/stopword plausibility guard as the site-scrape
-- (`name_extract.is_plausible_name`), and it is stored + surfaced as
-- "web-sourced, unverified" with its citation. An uncited name is dropped.
--
-- House posture (HANDOFF §6.12): RLS on, zero policies, service-role only; the
-- REVOKE is the part that actually restricts.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- name_search_request — the signed PAID order (the spend confirmation).
-- ---------------------------------------------------------------------------
create table if not exists name_search_request (
  id uuid primary key default gen_random_uuid(),

  -- The selection. One web search is run per prospect (like enrichment's per
  -- place_id), so an order carries the whole selection and the drain bills one
  -- search per un-searched prospect.
  prospect_ids uuid[] not null,

  -- The AR Tools profile id of the admin who placed it. NO foreign key
  -- (cross-database — same as enrichment_request.requested_by). Not null.
  requested_by uuid not null,
  note text,

  -- The estimate recorded at placement — this column is the per-user daily
  -- budget ledger (platform-api sums today's orders before writing the next).
  est_cost_cents integer not null default 0,

  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed', 'cancelled')),

  -- Progress counters, all written by the drain. requested = len(prospect_ids);
  -- skipped = already-searched prospects not re-billed; searched = prospects a
  -- search ran for this cycle; found = prospects a cited name was kept for;
  -- name_count = contact rows written; failed = prospects whose search errored.
  requested_count integer not null default 0,
  skipped_count   integer not null default 0,
  searched_count  integer not null default 0,
  found_count     integer not null default 0,
  name_count      integer not null default 0,
  failed_count    integer not null default 0,

  error text,
  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz
);

create index if not exists name_search_request_pending_idx
  on name_search_request (created_at)
  where status = 'pending';

create index if not exists name_search_request_requester_idx
  on name_search_request (requested_by, created_at desc);

-- ---------------------------------------------------------------------------
-- prospect_name_search — one row per prospect: the search STATUS + provenance,
-- and the idempotency marker the drain reads to avoid re-billing.
--
-- Separate from the enrichment + name-scrape markers so the three producers are
-- independent. `found`/`no_names` are durable (never re-billed); `failed` (the
-- call errored) is retryable.
-- ---------------------------------------------------------------------------
create table if not exists prospect_name_search (
  prospect_id uuid primary key references prospect(id) on delete cascade,

  status text not null
    check (status in ('found', 'no_names', 'failed')),
  name_count integer not null default 0,

  -- The source URLs the kept name(s) were cited from — the "web-sourced, verify"
  -- evidence a caller checks. A found name ALWAYS carries at least one (the
  -- require-citation guard); dropped uncited names never reach here.
  citations text[],
  model text,                -- the OpenAI model used, for provenance

  name_search_request_id uuid references name_search_request(id) on delete set null,
  error text,                -- populated only on status='failed'

  -- The extracted names + their citation/evidence, replayable from stored input.
  raw jsonb,

  searched_at timestamptz not null default now()
);

create index if not exists prospect_name_search_status_idx
  on prospect_name_search (status);

-- ---------------------------------------------------------------------------
-- RLS + grants. House posture: RLS on, zero policies, service-role only.
-- ---------------------------------------------------------------------------
alter table name_search_request  enable row level security;
alter table prospect_name_search enable row level security;

revoke all on name_search_request  from anon, authenticated;
revoke all on prospect_name_search from anon, authenticated;
