-- ============================================================
-- execution_events — the audit trail for plan approval + action execution
-- ============================================================
-- Design §3.1, §7–§8. Every approval / status change / (later) autonomous
-- execution writes an event here, powering the activity feed + the consolidated
-- report and making autonomy observable. Additive.
-- ============================================================

create table if not exists execution_events (
  id            uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references engagements(id) on delete cascade,
  action_id     uuid references strategy_actions(id) on delete cascade,
  type          text not null
                  check (type in (
                    'approved', 'status_change', 'assigned', 'skipped',
                    'started', 'completed', 'failed', 'paused',
                    'checkpoint', 'budget_halt', 'asana_status'
                  )),
  detail        jsonb,
  created_at    timestamptz not null default now()
);

create index if not exists idx_execution_events_engagement
  on execution_events (engagement_id, created_at desc);

create index if not exists idx_execution_events_action
  on execution_events (action_id, created_at desc);

alter table execution_events enable row level security;
