-- Migration: 20260730120000_assistant_conversations.sql
-- Purpose: durable chat history for the two dashboard assistants — SerMaStr
--   (`/assistant`) and PACE (`/pace`). Until now a thread lived only in the
--   browser's sessionStorage and the last 12 turns were re-sent from the client
--   on every request, so closing the tab lost the conversation, another device
--   couldn't see it, and nothing survived for anyone to read afterwards (which
--   made diagnosing a bad answer log forensics).
--
--   Both surfaces share these tables, told apart by `surface`. Threads are
--   many-per-user and named (ChatGPT-style history list), owned by whoever
--   typed them. Visibility is author-private with admins able to read all —
--   enforced in the API (`assistant_store.can_read`), since the backend uses
--   the service role and RLS never sees the end user.
--
--   Distinct from `assistant_memories`, which stores the handful of durable
--   notes SerMaStr chooses to keep. This is the raw transcript.

create table if not exists assistant_conversations (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid not null references profiles(id) on delete cascade,
  surface     text not null check (surface in ('sermastr', 'pace')),
  -- The thread's sticky client (nullable: portfolio-mode chats name no client).
  -- Kept current as the conversation switches clients mid-thread.
  client_id   uuid references clients(id) on delete set null,
  title       text,                     -- derived from the first user message
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  archived_at timestamptz               -- soft delete; rows are never hard-deleted here
);

create table if not exists assistant_messages (
  conversation_id uuid not null references assistant_conversations(id) on delete cascade,
  id              uuid primary key default gen_random_uuid(),
  role            text not null check (role in ('user', 'assistant')),
  content         text not null,
  -- The client this particular turn resolved to (a thread can move between
  -- clients), and per-turn diagnostics: tools used, action staged, errors.
  client_id       uuid references clients(id) on delete set null,
  meta            jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);

-- The history list: a user's live threads on one surface, newest activity first.
create index if not exists idx_assistant_conversations_owner
  on assistant_conversations (owner_id, surface, updated_at desc)
  where archived_at is null;

-- Replaying a thread, and loading the last N turns as prompt history.
create index if not exists idx_assistant_messages_conversation
  on assistant_messages (conversation_id, created_at);

-- Service-role only, like the rest of the suite's backend-owned tables: RLS on
-- with no policies, so nothing reaches these rows except through the API (which
-- is where the owner/admin read check lives).
alter table assistant_conversations enable row level security;
alter table assistant_messages enable row level security;
