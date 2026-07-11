-- Migration: 20260711210000_profiles_slack_user_id.sql
-- Purpose: PACE Phase 1 identity bridge (docs/modules/project-manager-agent-plan
--          -v1_0.md §3.1) — the Slack→profile map. The merged
--          asana_team_members.profile_id bridge links a suite PROFILE to a
--          roster member; this links a SLACK USER to a profile, so PACE can
--          resolve "who is asking" in Slack (for the personal brief + the
--          actor/permission model). An admin sets it on the Team page.
--
--          Nullable + unique: most profiles have no Slack link (unique ignores
--          nulls); a given Slack user maps to at most one profile.

alter table profiles add column if not exists slack_user_id text;

create unique index if not exists uq_profiles_slack_user_id
  on profiles (slack_user_id) where slack_user_id is not null;
