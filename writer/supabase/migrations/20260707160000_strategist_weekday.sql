-- Migration: 20260707160000_strategist_weekday.sql
-- Purpose: Per-client staggering of the weekly SerMaStr strategist review.
--
--          Previously every client's scheduled strategist run fired on one
--          global weekday (config `strategist_weekly_weekday`), concentrating
--          the workload — and its token/API cost — on a single day. This adds
--          an optional per-client review day so managers can spread clients
--          across the week.
--
--          strategist_weekday: 0=Mon .. 6=Sun (matching Python's
--          datetime.weekday()). NULL → fall back to the global default. The
--          scheduler now runs the due-check daily and enqueues only the
--          clients whose assigned day is today; the durable "already ran this
--          week" guard keeps each client to at most one scheduled run per week.
--
-- RLS on, service-role only (the backend uses the service role key).

alter table clients add column if not exists strategist_weekday smallint
  check (strategist_weekday is null or strategist_weekday between 0 and 6);
