-- Per-client Slack channel for PACE.
--
-- When set, PACE delivers this client's client-scoped PM notifications
-- (task_assigned / task_mention / task_comment / task_month_generated /
-- task_nudge) to this channel instead of the single master PACE channel.
-- Portfolio rollups (the daily digest, Chase Plan, workload report, escalations)
-- and every non-PACE notification are unaffected. Null → the master PACE
-- channel (settings.pace_slack_channel), exactly as before.
--
-- Accepts a Slack channel id (e.g. C0ABC123) or a #name; the PACE bot must be a
-- member of the channel to post there.
alter table public.clients
  add column if not exists slack_channel_id text;

comment on column public.clients.slack_channel_id is
  'Slack channel PACE posts this client''s PM notifications to (channel id like C0... or #name). Null → the master PACE channel.';
