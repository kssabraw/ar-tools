-- Migration: 20260627090000_brand_visibility_schema.sql
-- Purpose: AI Visibility module (Brand Strength) — Phase 0 data model.
--   Ports brand-strength-ai's core tables, re-anchored from its `business_profiles`
--   to the suite `clients` table. Follows the Local SEO port precedent: tables live
--   in the `public` schema with a `brand_` prefix (not a dedicated schema), so the
--   existing public-scoped service-role Supabase client works unchanged.
-- Scope: tracked keywords, tracked competitors, scan/mention history, scan schedules.
-- Deferred (not created here): notification_history / notification_preferences —
--   pending the suite notifications-service decision (plan §6 item 1; Phase 5).
-- Dropped from the source (internal-only suite): credits/billing, profiles/roles,
--   snippet encryption. See docs/modules/brand-strength-module-integration-plan-v1_0.md.

-- ============================================================
-- brand_tracked_keywords — keywords scanned for a client
-- ============================================================
create table brand_tracked_keywords (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid not null references clients(id) on delete cascade,
  keyword     text not null,
  category    text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (client_id, keyword)
);

create index brand_tracked_keywords_client_idx
  on brand_tracked_keywords (client_id, is_active);

-- ============================================================
-- brand_tracked_competitors — competitor brands tracked per client
-- ============================================================
create table brand_tracked_competitors (
  id                  uuid primary key default gen_random_uuid(),
  client_id           uuid not null references clients(id) on delete cascade,
  competitor_name     text not null,
  competitor_website  text,
  google_place_id     text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (client_id, competitor_name)
);

create index brand_tracked_competitors_client_idx
  on brand_tracked_competitors (client_id);

-- ============================================================
-- brand_mention_history — one row per keyword x engine per scan
-- ============================================================
create table brand_mention_history (
  id                    uuid primary key default gen_random_uuid(),
  client_id             uuid not null references clients(id) on delete cascade,
  keyword_id            uuid references brand_tracked_keywords(id) on delete cascade,
  -- Groups all rows produced by one scan trigger (one "Run scan now" / one
  -- scheduled fire), so the History UI can show a single scan as a unit.
  scan_batch_id         uuid,
  engine                text not null
                          check (engine in (
                            'chatgpt', 'claude', 'gemini', 'perplexity',
                            'google_ai_overview', 'google_ai_mode')),
  -- Brand actually scanned (the client's brand, or a competitor name when
  -- is_competitor_scan = true).
  scanned_brand_name    text,
  is_competitor_scan    boolean not null default false,
  status                text not null default 'queued'
                          check (status in ('queued', 'processing', 'completed', 'failed')),
  mention_found         boolean,
  mention_type          text check (mention_type in ('direct', 'implied', 'none')),
  sentiment             numeric(4, 3),          -- -1.000 .. 1.000
  confidence_score      numeric(4, 3),          --  0.000 .. 1.000
  citations             jsonb not null default '[]'::jsonb,
  competitor_results    jsonb,
  reasoning             text,
  snippet               text,                   -- plaintext (encryption dropped — internal-only)
  raw_response          text,
  invisibility_diagnosis text,
  failure_reason        text,
  retry_count           integer not null default 0,
  created_by            uuid references profiles(id),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index brand_mention_history_client_idx
  on brand_mention_history (client_id, created_at desc);
create index brand_mention_history_keyword_idx
  on brand_mention_history (keyword_id, created_at desc);
create index brand_mention_history_batch_idx
  on brand_mention_history (scan_batch_id);

-- ============================================================
-- brand_scan_schedules — one optional recurring scan per client
-- (driven by the shared asyncio scheduler; see plan Phase 3)
-- ============================================================
create table brand_scan_schedules (
  id                  uuid primary key default gen_random_uuid(),
  client_id           uuid not null references clients(id) on delete cascade,
  cadence             text not null default 'weekly'
                        check (cadence in ('weekly', 'monthly', 'disabled')),
  day_of_week         integer check (day_of_week between 0 and 6),
  day_of_month        integer check (day_of_month between 1 and 28),
  hour_utc            integer not null default 9 check (hour_utc between 0 and 23),
  selected_engines    text[] not null
                        default array['chatgpt', 'claude', 'gemini', 'perplexity',
                                      'google_ai_overview', 'google_ai_mode']::text[],
  include_competitors boolean not null default false,
  is_active           boolean not null default true,
  next_run_at         timestamptz,
  last_run_at         timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (client_id)
);

create index brand_scan_schedules_due_idx
  on brand_scan_schedules (is_active, next_run_at);

-- ============================================================
-- RLS — suite convention: the backend uses the service-role key and bypasses
-- these; policies gate anon/authenticated access. Mirrors local_seo_pages / runs.
-- ============================================================
alter table brand_tracked_keywords    enable row level security;
alter table brand_tracked_competitors enable row level security;
alter table brand_mention_history     enable row level security;
alter table brand_scan_schedules      enable row level security;

do $$
declare
  t text;
begin
  foreach t in array array[
    'brand_tracked_keywords', 'brand_tracked_competitors',
    'brand_mention_history', 'brand_scan_schedules'
  ]
  loop
    execute format(
      'create policy "authenticated read %1$s" on %1$s for select using (auth.role() = ''authenticated'')', t);
    execute format(
      'create policy "authenticated insert %1$s" on %1$s for insert with check (auth.role() = ''authenticated'')', t);
    execute format(
      'create policy "authenticated update %1$s" on %1$s for update using (auth.role() = ''authenticated'')', t);
    execute format(
      'create policy "authenticated delete %1$s" on %1$s for delete using (auth.role() = ''authenticated'')', t);
  end loop;
end $$;
