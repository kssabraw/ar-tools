-- LeadOff live-GBP competitor pins (owner request 2026-08-21).
--
-- Scout and Tryout already fire a live Google Maps SERP whose items carry each
-- competitor's real GBP coordinates / place_id / rating / review count — but the
-- parsers previously kept only name/domain/phone. This app-owned table persists
-- the live pins those actions capture, keyed by the scanner market (city_id,
-- category_id) so the LeadOff market map can plot the ACTUAL GBP locations and
-- derive a placement recommendation.
--
-- Deliberately SEPARATE from public.competitor_locations: that table's Census
-- street-centroid pins feed proximity_opportunity, which is a board grade input
-- (a winnability multiplier). Live-GBP pins are a display/advice layer only, so
-- scouting a market improves its MAP without silently shifting its GRADE.
--
-- Recapture is delete-then-insert per (city_id, category_id); there is no
-- uniqueness constraint (a market simply holds its latest captured field).

create table if not exists public.leadoff_gbp_pins (
  id            uuid primary key default gen_random_uuid(),
  source        text not null check (source in ('scout', 'tryout')),
  city_id       bigint not null,
  category_id   text not null,
  rank_position integer,
  place_id      text,
  business_name text,
  domain        text,
  rating        double precision,
  review_count  double precision,
  lat           double precision,
  lng           double precision,
  captured_at   timestamptz not null default now()
);

create index if not exists leadoff_gbp_pins_market_idx
  on public.leadoff_gbp_pins (city_id, category_id);

-- RLS on with no policy (service-role only) — mirrors every sibling app-owned
-- LeadOff table (competitor_locations, leadoff_market_signals, …). The backend
-- reads/writes with the service role (bypasses RLS); the anon/authenticated
-- PostgREST roles get no direct access.
alter table public.leadoff_gbp_pins enable row level security;
