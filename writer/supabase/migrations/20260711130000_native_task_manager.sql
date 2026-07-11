-- Migration: 20260711130000_native_task_manager.sql
-- Purpose: Native In-App Task Manager — Phase 0 foundations
--          (docs/modules/in-app-task-manager-prd-v1_0.md §7).
--          The suite replaces Asana with a native task system. This migration
--          creates the full §7 data model (tasks + subtasks-as-tasks, sections,
--          configurable statuses/categories, comments, attachments, activity,
--          watchers, saved views, notification prefs, and the Task Library's
--          default subtask checklists) and seeds the team's real statuses +
--          Service Type categories (§19.2/§19.3).
--
-- Decisions carried from planning (2026-07-11):
--   * Assignees stay Asana member GIDs for v1 (`assignee_gid` text +
--     cached `assignee_name`), matching asana_client_task_templates /
--     asana_team_members — the capacity + auto-distribution source of truth.
--     Unification onto profiles.id is a later, explicit migration (PRD §17 Q8).
--   * task_library_subtasks keys by library NAME (case-insensitive), NOT an FK
--     to asana_task_library(id): the library's replace-style PUT deletes +
--     reinserts rows (new ids every save), so an id FK would cascade-wipe every
--     checklist on save. Name is already the library's inheritance key.
--   * source + source_ref are the suite auto-integration backbone (PRD §11):
--     unique per open/completed task so a producer signal never duplicates its
--     task and can auto-close it later.
--
-- RLS on, NO client-facing policies (service-role only) — the suite convention.

-- ---------------------------------------------------------------------------
-- Configurable workflow statuses (global v1). Seeded below; edited via the
-- admin config endpoint (upsert + deactivate, never delete — tasks FK this).
-- ---------------------------------------------------------------------------
create table if not exists task_statuses (
  key         text primary key,
  label       text not null,
  color       text,
  category    text not null default 'in_progress'
                check (category in ('not_started', 'in_progress', 'blocked', 'done')),
  is_initial  boolean not null default false,   -- the status new tasks get
  is_done     boolean not null default false,   -- counts as complete
  sort_order  integer not null default 0,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table task_statuses enable row level security;

insert into task_statuses (key, label, color, category, is_initial, is_done, sort_order) values
  ('not_started',     'Not Started',     '#9ca3af', 'not_started', true,  false, 0),
  ('in_progress',     'In Progress',     '#3b82f6', 'in_progress', false, false, 1),
  ('blocked',         'Blocked',         '#ef4444', 'blocked',     false, false, 2),
  ('in_review',       'In Review',       '#a855f7', 'in_progress', false, false, 3),
  ('sent_to_client',  'Sent to Client',  '#f59e0b', 'in_progress', false, false, 4),
  ('client_approved', 'Client Approved', '#14b8a6', 'in_progress', false, false, 5),
  ('complete',        'Complete',        '#22c55e', 'done',        false, true,  6)
on conflict (key) do nothing;

-- ---------------------------------------------------------------------------
-- Category / "Service Type" options (global v1; generalizes to custom fields
-- in v2 — PRD §6.4).
-- ---------------------------------------------------------------------------
create table if not exists task_categories (
  key         text primary key,
  label       text not null,
  color       text,
  sort_order  integer not null default 0,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table task_categories enable row level security;

insert into task_categories (key, label, color, sort_order) values
  ('content',       'Content',       '#3b82f6', 0),
  ('link_building', 'Link Building', '#a855f7', 1),
  ('gbp_authority', 'GBP Authority', '#f59e0b', 2),
  ('strategy',      'Strategy',      '#14b8a6', 3)
on conflict (key) do nothing;

-- ---------------------------------------------------------------------------
-- Sections — the grouping of tasks within a client. Dominant kind is 'month'
-- ("July 2026"); also 'backlog' and arbitrary 'custom' sections. client_id is
-- null for the internal/agency board.
-- ---------------------------------------------------------------------------
create table if not exists task_sections (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid references clients(id) on delete cascade,
  name          text not null,
  kind          text not null default 'custom'
                  check (kind in ('month', 'backlog', 'custom')),
  period_month  date,                       -- first-of-month for kind='month'
  sort_order    integer not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- One section name per board, case-insensitive (drives month idempotency).
-- coalesce folds the null-client internal board into a single key space.
create unique index if not exists uq_task_sections_board_name
  on task_sections (coalesce(client_id::text, ''), lower(name));

create index if not exists idx_task_sections_client
  on task_sections (client_id, sort_order);

alter table task_sections enable row level security;

-- ---------------------------------------------------------------------------
-- Tasks. Subtasks are tasks with parent_task_id set (one model, one API).
-- ---------------------------------------------------------------------------
create table if not exists tasks (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid references clients(id) on delete cascade,
  section_id        uuid references task_sections(id) on delete set null,
  parent_task_id    uuid references tasks(id) on delete cascade,  -- set => SUBTASK
  name              text not null,
  description       text,                       -- markdown
  assignee_gid      text,                       -- Asana member gid (v1 identity; see header)
  assignee_name     text,                       -- cached display name
  status_key        text references task_statuses(key),
  category          text,                       -- task_categories.key (or raw label if unmatched)
  due_date          date,
  start_date        date,
  est_hours         numeric,
  completed         boolean not null default false,
  completed_at      timestamptz,
  sort_order        integer not null default 0, -- within section (or parent, for subtasks)
  source            text not null default 'manual',  -- manual | monthly | rank_drop | maps_alert | action_plan | content_run | ...
  source_ref        text,                       -- producer idempotency / auto-close key
  library_task_name text,                       -- which library task it derives from (by name)
  created_by        uuid references profiles(id) on delete set null,
  deleted_at        timestamptz,                -- soft delete (Trash)
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists idx_tasks_client_section
  on tasks (client_id, section_id, sort_order) where deleted_at is null;
create index if not exists idx_tasks_assignee_open
  on tasks (assignee_gid) where completed = false and deleted_at is null;
create index if not exists idx_tasks_parent
  on tasks (parent_task_id);
create index if not exists idx_tasks_due_open
  on tasks (due_date) where completed = false and deleted_at is null;
-- Producer idempotency: one live task per (source, source_ref). Completed tasks
-- keep the key (a resolved signal must not re-create its task); trashed ones
-- release it.
create unique index if not exists uq_tasks_source_ref
  on tasks (source, source_ref) where source_ref is not null and deleted_at is null;

alter table tasks enable row level security;

-- ---------------------------------------------------------------------------
-- Task Library default subtask checklists (PRD §6.9). Keyed by library task
-- NAME, case-insensitive — see header for why this is not an id FK.
-- ---------------------------------------------------------------------------
create table if not exists task_library_subtasks (
  id            uuid primary key default gen_random_uuid(),
  library_name  text not null,
  name          text not null,
  sort_order    integer not null default 0,
  created_at    timestamptz not null default now()
);

create index if not exists idx_task_library_subtasks_name
  on task_library_subtasks (lower(library_name), sort_order);

alter table task_library_subtasks enable row level security;

-- ---------------------------------------------------------------------------
-- Collaboration: comments, attachments, activity, watchers (PRD §6.10).
-- ---------------------------------------------------------------------------
create table if not exists task_comments (
  id          uuid primary key default gen_random_uuid(),
  task_id     uuid not null references tasks(id) on delete cascade,
  author_id   uuid not null references profiles(id) on delete cascade,
  body        text not null,                  -- markdown; @mentions parsed to user ids
  mentions    jsonb,                          -- [profile_id, ...] for fast notify
  created_at  timestamptz not null default now(),
  edited_at   timestamptz,
  deleted_at  timestamptz
);

create index if not exists idx_task_comments_task
  on task_comments (task_id, created_at);

alter table task_comments enable row level security;

create table if not exists task_attachments (
  id           uuid primary key default gen_random_uuid(),
  task_id      uuid not null references tasks(id) on delete cascade,
  comment_id   uuid references task_comments(id) on delete cascade,
  file_name    text not null,
  storage_path text not null,                 -- bucket 'task-attachments'
  mime_type    text,
  size_bytes   bigint,
  uploaded_by  uuid references profiles(id) on delete set null,
  created_at   timestamptz not null default now()
);

create index if not exists idx_task_attachments_task
  on task_attachments (task_id);

alter table task_attachments enable row level security;

create table if not exists task_activity (
  id         uuid primary key default gen_random_uuid(),
  task_id    uuid not null references tasks(id) on delete cascade,
  actor_id   uuid references profiles(id) on delete set null,
  kind       text not null,                   -- created|status_changed|assigned|due_changed|commented|completed|reopened|...
  detail     jsonb,                           -- {from, to} etc.
  created_at timestamptz not null default now()
);

create index if not exists idx_task_activity_task
  on task_activity (task_id, created_at);

alter table task_activity enable row level security;

create table if not exists task_watchers (
  task_id    uuid not null references tasks(id) on delete cascade,
  user_id    uuid not null references profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (task_id, user_id)
);

alter table task_watchers enable row level security;

-- ---------------------------------------------------------------------------
-- Saved views + per-user notification prefs (PRD §6.7 / §6.11).
-- ---------------------------------------------------------------------------
create table if not exists task_saved_views (
  id         uuid primary key default gen_random_uuid(),
  owner_id   uuid references profiles(id) on delete cascade,  -- null = shared/global
  name       text not null,
  config     jsonb not null,                  -- {scope, filters, group_by, sort}
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table task_saved_views enable row level security;

create table if not exists task_notification_prefs (
  user_id    uuid primary key references profiles(id) on delete cascade,
  prefs      jsonb not null default '{}'::jsonb,  -- {assigned: true, mention: true, due: true, ...}
  updated_at timestamptz not null default now()
);

alter table task_notification_prefs enable row level security;

-- ---------------------------------------------------------------------------
-- Widen async_jobs.job_type for the native task jobs (preserves the FULL live
-- set as read from production on 2026-07-11 — wider than any repo migration).
-- ---------------------------------------------------------------------------
alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'silo_dedup', 'gsc_ingest',
    'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank', 'keyword_market',
    'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan', 'maps_report',
    'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
    'local_seo_reoptimize_page', 'service_page_plan', 'rank_location_derive',
    'brand_scan', 'brand_report', 'notification_dispatch', 'reopt_plan',
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp',
    'review_intel', 'backlink_intel', 'content_intel', 'local_relevance',
    'syndication_scan', 'syndication_item', 'freeze_check', 'citation_check',
    'page_backlink_intel', 'strategy_review', 'maps_image_backfill',
    'brand_voice_scan', 'icp_scan', 'asana_push', 'competitor_intel',
    'gbp_metrics_ingest', 'internal_link_analyze', 'internal_link_apply',
    'rank_keyword_report', 'local_seo_action', 'backlink_snapshot',
    'content_batch_item',
    'task_month_generate', 'task_due_sweep'
  ]));
