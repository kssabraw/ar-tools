-- Durable scheduler markers (ops fix 2026-07-12).
--
-- The in-process scheduler's "already ran today/this week" markers were
-- memory-only, so every deploy restarted the process and re-fired the daily
-- block: freeze_check ran up to 17x/client/day on heavy deploy days (170 jobs
-- for 10 clients on 2026-07-09), burning GSC URL-inspection quota and paid
-- DataForSEO site: probes. One row per marker key; loaded at loop start,
-- upserted after each block runs. A missing/unreadable table degrades to the
-- old in-memory behavior (best-effort on both read and write).

create table if not exists scheduler_state (
  key text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);

-- Service-role only (backend infra state; no user-facing reads).
alter table scheduler_state enable row level security;
