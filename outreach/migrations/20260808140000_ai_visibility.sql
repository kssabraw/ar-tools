-- AI-visibility scan — the report's LLM signal (report increment 3, outreach ISSUES I-095).
--
-- "Whether an AI assistant names this business when a customer asks about its keyword in its
-- region." Two engines (owner ruling 2026-08-08): ChatGPT (OpenAI) and Google AI Overview (AIO,
-- via DataForSEO). Distinct from the maps geogrid and the organic SERP — it measures recognition,
-- not ranking.
--
-- TWO NEW TABLES, both service-role only (RLS on, zero policies — HANDOFF §2), matching every
-- other object in this project. Do NOT add an RLS policy to silence the advisor.
--
-- ---------------------------------------------------------------------------------------------
-- ai_region — the COARSE geography AI checks run at (PRD §8b, §7.4; ISSUES I-073).
--
-- Deliberately NOT the submarket. The grid and the AI layer measure different things at different
-- resolutions and were never meant to align: a submarket is a 5-mile grid (~10 per market); an
-- ai_region is a recognised PLACE NAME (~5 per market), because the AI question is "does the model
-- name you at all in <place>", which only makes sense at a granularity the model recognises. Its
-- geography is a name, not a lattice, so it carries no centre/radius and no FK to submarket — a
-- prospect maps to a region by NAME (its submarket's name matching a region), the honest join for
-- "several submarkets share one region".
--
-- `name_level` records the recognition risk (I-004): a 'neighbourhood' is where the model may
-- silently fall back to the metro, so a report built on one must carry that caveat. It is a human
-- judgement (I-073), never derived.
-- ---------------------------------------------------------------------------------------------
create table if not exists ai_region (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  name text not null,
  name_level text not null check (name_level in ('metro', 'city', 'suburb', 'neighbourhood')),
  created_at timestamptz not null default now(),
  unique (market_id, name)
);

create index if not exists ai_region_market_idx on ai_region (market_id);

alter table ai_region enable row level security;

-- ---------------------------------------------------------------------------------------------
-- ai_scan_result — one engine's answer for one region x keyword, at one time.
--
-- The scan is per (region, keyword) — the answer is the same for every prospect in the region, so
-- the prospect-level detection ("is THIS business named") happens at report-read time against the
-- stored answer, not per-prospect at scan time. That is what keeps the scan cheap: a handful of
-- regions x keywords x 2 engines, not one call per prospect.
--
-- `present` = the engine returned a usable answer (distinct from "named nobody" and from "the call
-- failed" — the same three-way distinction ai_granularity.py keeps, because collapsing them lets an
-- outage read as "the AI doesn't know you"). `named_businesses` is what the engine named;
-- `reference_domains` is the AIO's cited domains (empty for ChatGPT); `raw_excerpt` is a snippet
-- kept for audit. A prospect is "visible" if their name or domain matches any of these.
-- ---------------------------------------------------------------------------------------------
create table if not exists ai_scan_result (
  id uuid primary key default gen_random_uuid(),
  ai_region_id uuid not null references ai_region(id) on delete cascade,
  keyword_id uuid not null references keyword(id) on delete cascade,
  engine text not null check (engine in ('chatgpt', 'google_aio')),
  present boolean not null default false,
  named_businesses jsonb not null default '[]'::jsonb,
  reference_domains jsonb not null default '[]'::jsonb,
  raw_excerpt text,
  scanned_at timestamptz not null default now()
);

create index if not exists ai_scan_result_region_keyword_idx
  on ai_scan_result (ai_region_id, keyword_id, engine, scanned_at desc);

alter table ai_scan_result enable row level security;

-- ---------------------------------------------------------------------------------------------
-- Seed the LA regions from the I-073 free-evidence run (owner: yes, seed the region names).
--
-- The TEN unambiguous names only (a real `city` value on 34-90 prospects each) as their level,
-- plus Hollywood as a 'neighbourhood' (real place, addressed "Los Angeles" — the I-004 case, so
-- its report carries the recognition caveat). The three WEAK names (Downtown LA, West LA, East LA)
-- are deliberately NOT seeded — I-073 found zero-to-near-zero prospects treat them as a locality,
-- so asking an engine about them is the "reads specific, returns metro" trap. Add them only after
-- a recognition test says they work.
--
-- Guarded on the LA market existing and on its name, and idempotent (on conflict do nothing), so
-- this is a no-op on any project where that market has not been ingested.
-- ---------------------------------------------------------------------------------------------
do $$
declare
  la_market uuid;
begin
  select id into la_market from market where name = 'Los Angeles, CA — Plumbing' limit 1;
  if la_market is null then
    raise notice 'LA market not found — ai_region seed skipped (safe: apply later or seed by hand)';
    return;
  end if;

  insert into ai_region (market_id, name, name_level) values
    (la_market, 'Long Beach', 'city'),
    (la_market, 'Burbank', 'city'),
    (la_market, 'Pasadena', 'city'),
    (la_market, 'Santa Monica', 'city'),
    (la_market, 'Torrance', 'city'),
    (la_market, 'Inglewood', 'city'),
    (la_market, 'Whittier', 'city'),
    (la_market, 'Van Nuys', 'suburb'),
    (la_market, 'Woodland Hills', 'suburb'),
    (la_market, 'Northridge', 'suburb'),
    (la_market, 'Hollywood', 'neighbourhood')
  on conflict (market_id, name) do nothing;
end $$;

-- Access: service role only. Supabase grants ALL to anon/authenticated by default, so the revoke
-- is the only statement here that changes anything.
revoke all on ai_region, ai_scan_result from anon, authenticated;

comment on table ai_region is
  'The coarse place-name geography AI-visibility checks run at (PRD §8b, ISSUES I-073). A prospect '
  'maps to a region by its submarket name; name_level records the I-004 recognition risk. '
  'Service-role only, RLS-on/zero-policy per HANDOFF §2.';
comment on table ai_scan_result is
  'One engine (chatgpt | google_aio) answer for one region x keyword. Prospect-level "is this '
  'business named" is detected at report-read time against named_businesses / reference_domains.';
