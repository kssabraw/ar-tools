-- Migration: 20260707040000_campaign_goals.sql
-- Purpose: Campaign goals — per-client success targets the strategist judges
--          progress against ("top 3 for these keywords by Q4", "800 organic
--          clicks/mo"). Without stored goals SerMaStr can describe movement
--          but can't say "on track / behind" — this is the foundation layer
--          for forecasting and goal-aware reviews.
-- Status (on_track/behind/achieved/…) is NEVER stored — it's computed
-- deterministically on read (services/campaign_goals.py) from the live
-- metric vs baseline vs target vs due date, per the suite's legibility rule
-- (the LLM never does trend arithmetic). achieved_at records only the first
-- time a goal was met.

create table if not exists campaign_goals (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  goal_type       text not null check (goal_type in (
                    'keyword_position',     -- one keyword to position <= target_value
                    'keywords_in_top',      -- target_value keywords at position <= target_position
                    'organic_clicks',       -- GSC clicks / 30 days >= target_value
                    'organic_impressions',  -- GSC impressions / 30 days >= target_value
                    'ai_visibility',        -- AI-answer visibility pct >= target_value
                    'maps_pack_presence',   -- geo-grid top-3 pin share pct >= target_value
                    'custom'                -- free-text goal, no auto-measurement
                  )),
  label           text not null,
  keyword         text,                     -- keyword_position goals only
  target_value    double precision,         -- null for custom
  target_position integer,                  -- keywords_in_top: the N in "top N"
  due_date        date,
  baseline_value  double precision,         -- measured at creation
  baseline_date   date,
  achieved_at     timestamptz,              -- first time the target was met
  active          boolean not null default true,
  notes           text,
  created_by      uuid references profiles(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists idx_campaign_goals_client
  on campaign_goals (client_id, active, created_at desc);

alter table campaign_goals enable row level security;
