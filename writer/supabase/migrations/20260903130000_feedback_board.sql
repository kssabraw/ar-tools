-- Feedback Board — an internal, admin-only board for logging bugs and a
-- "wishlist" of desired new modules / capabilities of existing modules.
--
-- This is agency-internal product feedback, deliberately SEPARATE from the
-- native client task board (which is client-delivery work): it has its own
-- lightweight status workflow, priority, free-text labels, and threaded
-- comments. Admin-only at the API (routers/feedback.py depends on require_admin),
-- so RLS is enabled with NO policies — the backend reaches it with the service
-- role key, matching the goal_escalations / notifications convention.

create table if not exists public.feedback_items (
    id           uuid primary key default gen_random_uuid(),
    -- 'bug' = something broken; 'wishlist' = a new module / capability request.
    kind         text not null check (kind in ('bug', 'wishlist')),
    title        text not null,
    body         text,
    -- Shared workflow for both kinds (neutral labels that read for either):
    --   new        — just logged, not yet looked at
    --   triaged    — reviewed / accepted (a bug confirmed, a wish planned)
    --   in_progress— being worked on
    --   done        — fixed / shipped
    --   declined    — won't fix / won't build
    status       text not null default 'new'
                   check (status in ('new', 'triaged', 'in_progress', 'done', 'declined')),
    priority     text not null default 'medium'
                   check (priority in ('low', 'medium', 'high', 'critical')),
    -- Free-text tags: module name, area, etc. Filterable in the UI.
    labels       text[] not null default '{}',
    created_by   uuid references public.profiles(id) on delete set null,
    -- Stamped when status first reaches a terminal state (done/declined).
    resolved_at  timestamptz,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create index if not exists feedback_items_kind_status
    on public.feedback_items (kind, status);

create index if not exists feedback_items_created_at
    on public.feedback_items (created_at desc);

create table if not exists public.feedback_comments (
    id         uuid primary key default gen_random_uuid(),
    item_id    uuid not null references public.feedback_items(id) on delete cascade,
    author_id  uuid references public.profiles(id) on delete set null,
    body       text not null,
    created_at timestamptz not null default now()
);

create index if not exists feedback_comments_item
    on public.feedback_comments (item_id, created_at);

alter table public.feedback_items enable row level security;
alter table public.feedback_comments enable row level security;
