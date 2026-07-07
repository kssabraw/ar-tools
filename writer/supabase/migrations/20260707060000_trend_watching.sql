-- Migration: 20260707060000_trend_watching.sql
-- Purpose: Trend watching (strategist roadmap phase 4, final phase).
--   * keyword_market.monthly_searches — the 12-month volume history DataForSEO
--     already returns on every search-volume call (we were discarding it).
--     Stored on the existing cache row, it makes SEASONALITY free: the cache
--     fills/refreshes on the same monthly market job, no new paid calls.
--   * algo_events — cross-client algorithm-update detection. When several
--     clients open rank-drop alerts inside the same short window, that's a
--     Google update, not N separate client problems — which changes the drop
--     playbook (verify against industry trackers; don't reoptimize into a
--     rolling update). Events are immutable detections (deduped by window
--     overlap), found by a daily DB-reads-only sweep on the shared scheduler
--     (inline like the offpage sweep — no new job type).

alter table keyword_market add column if not exists monthly_searches jsonb;

create table if not exists algo_events (
  id                uuid primary key default gen_random_uuid(),
  window_start      date not null,
  window_end        date not null,
  clients_affected  integer not null,
  clients_total     integer not null,          -- clients with tracked keywords at detection time
  drop_count        integer not null,
  affected_clients  jsonb,                     -- [{client_id, name, drops}] sample
  detected_at       timestamptz not null default now()
);

create index if not exists idx_algo_events_window on algo_events (window_end desc);

alter table algo_events enable row level security;
