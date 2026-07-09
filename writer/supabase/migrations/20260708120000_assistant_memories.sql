-- Migration: 20260708120000_assistant_memories.sql
-- Purpose: SerMaStr durable memory — short notes the assistant saves from
--   conversations (decisions, commitments, client facts, team preferences) so
--   it remembers them across chats and surfaces. Written by the assistant's
--   `remember` tool (chat + Slack), folded back into every answer's context as
--   the `memories` module. Deliberately small: content + where it was said.
--   Not a conversation log — the thread itself stays browser/Slack-local.

create table if not exists assistant_memories (
  id         uuid primary key default gen_random_uuid(),
  client_id  uuid not null references clients(id) on delete cascade,
  content    text not null,             -- one short durable note
  source     text not null default 'chat',  -- 'chat' (dashboard) | 'slack'
  created_at timestamptz not null default now()
);

create index if not exists idx_assistant_memories_client
  on assistant_memories (client_id, created_at desc);

alter table assistant_memories enable row level security;
