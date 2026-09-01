-- Migration: 20260901140000_pace_action_log_reverts.sql
-- Purpose: PACE Action Log v2 — revert detection. A daily read-only sweep marks
--          a logged, executed PACE action as reverted (its field was changed
--          back to the pre-PACE value) or overridden (changed to a third value)
--          — the strongest negative-training signal ("the work got undone").
--          See services/pace_audit.py::run_revert_sweep.
--
--          Retention stays "keep everything forever" (owner ruling) — no pruning.

alter table public.pace_action_log
  add column if not exists reverted_at    timestamptz,
  add column if not exists revert_detail  jsonb;

-- The sweep scans un-reverted executed rows; a partial index keeps it cheap as
-- the table grows unbounded.
create index if not exists idx_pace_action_log_unreverted
  on public.pace_action_log (created_at desc)
  where reverted_at is null and outcome = 'executed';

comment on column public.pace_action_log.reverted_at is
  'When a daily sweep detected this executed PACE change was undone/overridden; null = still standing.';
comment on column public.pace_action_log.revert_detail is
  '{field, from_pace, to_current, kind:reverted|overridden} — what changed since PACE set it.';
