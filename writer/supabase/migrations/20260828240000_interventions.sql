-- Intervention-outcome loop (services/interventions.py) — the measurement half
-- of SerMaStr's decide+assign flow. One ledger row per goal-linked, in-scope
-- (link-building / reoptimization) proposal or native task, carrying the target
-- metric's baseline and, at its 6-week mark, a worked/partial/no_effect verdict.
-- Ships dark behind settings.intervention_tracking_enabled (default False).

create table if not exists public.interventions (
    id            uuid primary key default gen_random_uuid(),
    client_id     uuid not null references public.clients(id) on delete cascade,
    -- Which hook registered it. A shared source_ref lets the proposal-approve
    -- and native-task-done hooks converge on ONE row (idempotent).
    source        text not null check (source in ('strategy_proposal', 'native_task')),
    source_ref    text not null unique,
    tactic_type   text not null check (tactic_type in ('link_building', 'reoptimization')),
    goal_id       uuid references public.campaign_goals(id) on delete set null,
    -- {keyword, keyword_id, page_url, goal_type, target_value}
    target        jsonb not null default '{}'::jsonb,
    -- {value, metric, direction, measured_at} snapshotted when work landed.
    baseline      jsonb not null default '{}'::jsonb,
    applied_at    timestamptz not null default now(),
    verdict       text check (verdict in ('worked', 'partial', 'no_effect')),
    evaluated_at  timestamptz,
    next_check_at timestamptz,
    checks        jsonb not null default '[]'::jsonb,  -- append-only recheck history
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create index if not exists interventions_client_idx
    on public.interventions (client_id, created_at desc);

-- The daily sweep claims open (unverified) rows past their next_check_at.
create index if not exists interventions_due_idx
    on public.interventions (next_check_at)
    where verdict is null;

-- The task-shape carrier for the native-task registration hook: a nullable
-- jsonb the strategist-proposal push stamps ({tactic_type, keyword, page_url,
-- source_ref}) so a completed task can register/confirm its intervention. Null
-- for every ordinary task (default → the loop simply doesn't apply).
alter table public.tasks
    add column if not exists target jsonb;

comment on table public.interventions is
    'Intervention-outcome loop: goal-linked link-building/reoptimization work with a baseline and a 6-week worked/partial/no_effect verdict (services/interventions.py).';
comment on column public.tasks.target is
    'Optional intervention target for the outcome loop ({tactic_type, keyword, page_url, source_ref}); null for ordinary tasks.';
