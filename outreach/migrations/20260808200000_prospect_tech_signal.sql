-- Site tech-signal capture — paid-placement Slice B1 (the money signal, PRD §B3).
--
-- The ad/marketing tech on a prospect's OWN site: Meta pixel, Google Ads (AW-) conversion tag, the
-- GTM container, and vendor tags (CallRail / Podium / Birdeye). These are the scoring-spec.md
-- §Buying-intent (Meta +10, AW +19, vendor +16) and §Decision-structure (`likely_represented` −21)
-- signals a SERP read cannot see — they live in the page, not the search results.
--
-- Keyed to the PROSPECT, not a snapshot: the site is the prospect's and does not change per scan, so
-- this does NOT ride serp_result (which is per snapshot x keyword). Append-per-fetch, read-latest —
-- the same shape the module uses everywhere it keeps history.
--
-- Service-role only (RLS on, zero policies — HANDOFF §2), like every other object here. Do NOT add
-- an RLS policy to silence the advisor.
--
-- THE MEASURED-VS-FOUND RULE IS STRUCTURAL. `fetch_status` carries it: 'ok' means the booleans are
-- real findings; anything else means the fetch failed and the booleans are NOT evidence of absence
-- (unknown ≡ absent for the scorer, but the report must be able to say "couldn't read the site"
-- rather than "no ad tech"). All signals are one-directional (PRD §B3): presence adds, absence never
-- subtracts, unknown behaves as absent. A failed fetch stores all-false booleans + a non-'ok' status.
create table if not exists prospect_tech_signal (
  id uuid primary key default gen_random_uuid(),
  prospect_id uuid not null references prospect(id) on delete cascade,
  fetched_at timestamptz not null default now(),
  fetch_status text not null check (fetch_status in ('ok', 'unreachable', 'timeout', 'blocked')),
  final_url text,
  -- Presence booleans + the captured ids/tags. Meaningful only when fetch_status = 'ok'.
  meta_pixel boolean not null default false,
  meta_pixel_ids text[] not null default '{}',
  google_ads_conversion boolean not null default false,
  aw_ids text[] not null default '{}',
  gtm_container_ids text[] not null default '{}',
  gtm_followed boolean not null default false,      -- did we fetch the container (I-003 / §16a.1)?
  vendor_tags text[] not null default '{}',         -- canonical vendor names: callrail/podium/birdeye
  google_guaranteed boolean not null default false, -- weak; the LSA signal (Slice A) is authoritative
  evidence jsonb not null default '{}'::jsonb        -- matched signatures, for replayability
);

-- Latest-per-prospect is the read; index the prospect + recency.
create index if not exists prospect_tech_signal_prospect_idx
  on prospect_tech_signal (prospect_id, fetched_at desc);

alter table prospect_tech_signal enable row level security;
