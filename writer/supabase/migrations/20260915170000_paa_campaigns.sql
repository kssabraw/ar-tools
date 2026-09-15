-- Migration: 20260915170000_paa_campaigns.sql
-- Purpose: PAA → SEO Neo PHASE 3 — the Service PAA Campaign object + the
--   automated single-variable gate. The v1 workflow
--   (single-variable-scan-verify-workflow.md) is a MANUAL loop: create posts →
--   settle ~1 wk → single-keyword Maps geo-grid scan → read the branch
--   (moved / drill / HALT) → rinse per service on cadence. Phase 3 makes that a
--   state machine with a clock and an AUTOMATED gate read.
--
--   Grain (owner-locked 2026-09-15, PRD §12.2 fork 2): ONE campaign per paa_set
--   (per service-in-geo), 1:1 via a UNIQUE set_id — mirrors paa_manifests. The
--   campaign wraps the EXISTING paa_set (its content) + the EXISTING per-set
--   manifest (its asset ledger); it does not duplicate either. Drilling adds
--   drill_level-tagged paa_items to the SAME set (the scan target — the service
--   keyword — is constant across drill levels; drilling adds supporting content),
--   so paa_items gains a drill_level column below.
--
--   Autonomy (owner-locked, PRD §12.2 fork 1): HYBRID propose-confirm. The
--   cheap/free steps advance automatically (settle timer, scan-complete
--   detection, the gate read, the drill/HALT decision, maintenance scheduling,
--   notifications); the two PAID/content steps (kick a paid geo-grid scan; create
--   a drill round of posts) advance to a *_ready state + notify, and a HUMAN
--   confirms. Nothing in this migration runs anything.
--
--   PERMANENT GUARDRAIL (PRD §9): the campaign ORCHESTRATES and TRACKS the
--   content→settle→scan→gate loop and hands off the (Phase-2) manifest — the
--   suite NEVER executes the SEO Neo authority layer (link blasts / RD 100 /
--   GMBB Blast / Omega / PBNs). The "moved" branch only builds/costs/QAs the
--   manifest; there is no execute affordance anywhere. HALT is a STOP condition
--   ("more PAAs won't fix it — re-check on-page/entity"), never "keep writing."
--
--   NO new async_jobs type: the campaign advance is an inline scheduler sweep
--   (run_paa_campaign_sync, like run_episode_sync); the expensive steps reuse the
--   existing maps_scan job + the v1 create-posts path.
--
--   RLS-on with no client-facing policies (service-role only, API-layer client_id
--   filtering — the suite single-tenant model), matching every other module table.

-- ---------------------------------------------------------------------------
-- paa_items: a drill level (0 = the root service set; 1..N = drill rounds of
-- sub-PAAs under the SAME service, reference §5.3, ≤ ~4 levels).
-- ---------------------------------------------------------------------------
alter table paa_items
  add column if not exists drill_level integer not null default 0;

-- ---------------------------------------------------------------------------
-- Campaigns (one per PAA set — the per-service-in-geo state machine)
-- ---------------------------------------------------------------------------
create table if not exists paa_campaigns (
  id             uuid primary key default gen_random_uuid(),
  -- One campaign per set (the per-service-in-geo grain). UNIQUE so create is an
  -- upsert, not a duplicate — mirrors paa_manifests.set_id.
  set_id         uuid not null unique references paa_sets (id) on delete cascade,
  client_id      uuid not null references clients (id) on delete cascade,
  -- Denormalized from the set for display + as the geo-grid scan target.
  service_keyword text not null,
  location        text,
  -- The state machine (PRD §12.3). draft → content → settling → scan_ready →
  -- scanning → evaluating → moved | drill_ready | halted; moved → maintenance.
  state          text not null default 'draft'
                   check (state in (
                     'draft', 'content', 'settling', 'scan_ready', 'scanning',
                     'evaluating', 'moved', 'drill_ready', 'halted', 'maintenance'
                   )),
  -- Drill round the campaign is on (0 = root). Bounded by paa_campaign_drill_cap
  -- (~4) in code; at the cap with no movement the gate branches to 'halted'.
  drill_level    integer not null default 0,
  -- The load-bearing settle wait (reference §5.2): scanning is not offered until
  -- now >= settle_until. Set when the content for a level finishes + verifies.
  settle_until   timestamptz,
  -- The rinse/maintenance clock: the next scheduled re-evaluation after 'moved'.
  next_action_at timestamptz,
  -- The single-variable gate's read: the campaign's baseline geo-grid average
  -- rank (lower = better, 1-based) at the level's scan baseline, and the latest.
  baseline_rank  numeric,
  current_rank   numeric,
  -- The specific scan the gate last read (a maps_scans row), and when the
  -- campaign requested a scan (to match the resulting manual scan on the sweep).
  last_scan_id     uuid references maps_scans (id) on delete set null,
  scan_requested_at timestamptz,
  -- Why a campaign halted (surfaced to the human — re-check on-page/entity).
  halted_reason  text,
  -- Append-only transition log: [{at, from, to, note}] — the campaign timeline.
  history        jsonb not null default '[]'::jsonb,
  created_by     uuid,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists paa_campaigns_client_idx
  on paa_campaigns (client_id, created_at desc);

-- The scheduler sweep claims campaigns whose clock is due (settle elapsed or a
-- maintenance re-scan due) — index the two due-driving timestamps.
create index if not exists paa_campaigns_due_idx
  on paa_campaigns (state, settle_until, next_action_at);

alter table paa_campaigns enable row level security;
