-- Everhour time-tracking integration — Phase 1 (identity/mapping columns).
--
-- Adds the two join-key columns Phase 1's pickers write, per the plan doc
-- (docs/modules/everhour-time-tracking-integration-plan-v1_0.md §6, §9). Both
-- are nullable text and purely additive — nothing else changes, and the whole
-- integration stays gated on `everhour_enabled` (default False), so this is a
-- no-op for behavior until a real Everhour account is provisioned.
--
--   * asana_team_members.everhour_user_id — the Everhour user id (a number in
--     the API, stored as text like every other external-id column: gid,
--     slack_user_id, ...) this roster member logs time as. A PEER of profile_id
--     (the suite-login bridge), NOT of slack_user_id (which lives on profiles).
--     Set from the Team-page Everhour-user-link dropdown. Resolves member_id on
--     the Phase 3 time pull.
--
--   * clients.everhour_project_id — the single Everhour project this client's
--     time is logged against (opaque prefixed string like "ev:123"/"as:123",
--     NEVER numeric — so text, not integer). Mirrors clients.slack_channel_id's
--     single-external-id-column shape (a strict 1:1, so no separate mapping
--     table). Set from the client↔project mapping UI. The attribution anchor
--     (locked decision #4: Everhour project = suite client).
--
-- The tasks.everhour_task_id / _synced_at / actual_hours columns and the
-- time_entries table are Phase 2/3, deliberately NOT added here.
--
-- Both tables already have RLS on, service-role only (suite convention); the
-- new columns inherit it. Idempotent (add-if-not-exists).

alter table public.asana_team_members
  add column if not exists everhour_user_id text;

comment on column public.asana_team_members.everhour_user_id is
  'Everhour user id (stored as text) this roster member logs time as. Peer of profile_id; set from the Team-page Everhour link. Resolves member_id on the Phase 3 time pull.';

alter table public.clients
  add column if not exists everhour_project_id text;

comment on column public.clients.everhour_project_id is
  'The single Everhour project id (opaque string like "ev:123"/"as:123", not numeric) this client''s time is logged against. Null → not yet onboarded to Everhour. Locked decision #4: Everhour project = suite client.';
