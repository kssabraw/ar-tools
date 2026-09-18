-- LLM usage ledger — the capture point for LLM/paid-API spend that has no
-- natural per-deliverable row, so it never reached the cost_events view.
--
-- The existing cost_events sources each hang cost off a domain row (a run, a
-- page, a strategy_review). But large swaths of LLM spend have no such row:
--   * AI Visibility brand scans (6 engines + classifier + auto-diagnose per cell)
--   * Keyword / Topic Research LLM layers (only their DataForSEO $ is metered)
--   * the conversational agents (SerMaStr / PACE / DORA chat turns)
--   * Website Builder / Brand Guide generation, brand-voice/ICP scans, content-gap
--   * maps / rank-analysis narratives
-- so their token spend was invisible in the Cost & Usage report.
--
-- This ONE ledger captures a row per LLM (or paid-API) call for those sources and
-- is UNIONed into cost_events. It is purely ADDITIVE: none of these sources are in
-- the view today, so there is no double-counting with the per-domain branches.
-- (Keyword-research's DataForSEO cost stays in keyword_research_runs; the Anthropic
-- tokens recorded here under a distinct source are separate money.)
--
-- cost_usd is the computed dollar cost when the model's price is known; when it is
-- not (priced=false) the row still records tokens so volume is visible and the
-- dollars can be back-filled once the rate is set. service_role only (admin-gated
-- at the /cost-report router); RLS on with no policies.

create table if not exists public.llm_usage (
    id            uuid primary key default gen_random_uuid(),
    service       text not null,                 -- 'platform-api' | 'pipeline-api'
    source        text not null,                 -- cost_type key (labels live in the service)
    operation     text,                          -- finer label, e.g. 'engine:claude', 'classifier'
    provider      text not null,                 -- anthropic|openai|gemini|perplexity|dataforseo
    model         text,                          -- model id (null for non-model APIs like dataforseo)
    client_id     uuid references public.clients(id) on delete set null,
    actor_id      uuid,                           -- initiating profile, when known (else scheduled/automated)
    input_tokens  bigint not null default 0,
    output_tokens bigint not null default 0,
    cost_usd      numeric not null default 0,     -- computed; 0 when the model is unpriced (see priced)
    priced        boolean not null default true,  -- false → tokens captured, cost is a placeholder 0
    occurred_at   timestamptz not null default now(),
    metadata      jsonb not null default '{}'::jsonb
);

create index if not exists idx_llm_usage_occurred on public.llm_usage (occurred_at);
create index if not exists idx_llm_usage_source_occurred on public.llm_usage (source, occurred_at);
create index if not exists idx_llm_usage_client on public.llm_usage (client_id);

alter table public.llm_usage enable row level security;
grant select, insert on public.llm_usage to service_role;

-- Wire the ledger into cost_events as one more UNION branch. Only the branch is
-- added; every existing branch + the `model` column (migration 20260918120000)
-- is unchanged.
create or replace view public.cost_events as

select
    'run:' || r.id                          as event_id,
    'runs'                                   as source,
    r.content_type                          as cost_type,
    r.client_id                             as client_id,
    r.created_by                            as actor_id,
    null::text                              as actor_name,
    coalesce(r.completed_at, r.created_at)  as occurred_at,
    r.total_cost_usd::numeric               as cost_usd,
    coalesce((select sum((mo.token_usage->>'input_tokens')::bigint)::bigint
              from public.module_outputs mo where mo.run_id = r.id), 0::bigint) as input_tokens,
    coalesce((select sum((mo.token_usage->>'output_tokens')::bigint)::bigint
              from public.module_outputs mo where mo.run_id = r.id), 0::bigint) as output_tokens,
    'mixed'::text                            as model
from public.runs r
where coalesce(r.total_cost_usd, 0) > 0

union all
select
    'local_seo:' || p.id, 'local_seo_pages',
    case when p.mode = 'reoptimize' then 'local_seo_reoptimize' else 'local_seo_page' end,
    p.client_id, p.created_by, null::text, p.created_at,
    coalesce((p.cost_breakdown->>'total')::numeric, 0),
    coalesce((p.token_usage->>'input_tokens')::bigint, 0),
    coalesce((p.token_usage->>'output_tokens')::bigint, 0),
    coalesce(nullif(p.token_usage->>'model', ''), nullif(p.cost_breakdown->>'claude_model', ''), 'claude-sonnet-4-6')
from public.local_seo_pages p
where coalesce((p.cost_breakdown->>'total')::numeric, 0) > 0

union all
select
    'ecommerce:' || e.id, 'ecommerce_pages',
    case
        when e.mode = 'reoptimize'      then 'ecommerce_reoptimize'
        when e.page_type = 'collection' then 'ecommerce_collection'
        else 'ecommerce_product'
    end,
    e.client_id, e.created_by, null::text, e.created_at,
    coalesce((e.cost_breakdown->>'total')::numeric, 0),
    coalesce((e.token_usage->>'input_tokens')::bigint, 0),
    coalesce((e.token_usage->>'output_tokens')::bigint, 0),
    coalesce(nullif(e.token_usage->>'model', ''), nullif(e.cost_breakdown->>'claude_model', ''), 'claude-sonnet-4-6')
from public.ecommerce_pages e
where coalesce((e.cost_breakdown->>'total')::numeric, 0) > 0

union all
select
    'kw_research:' || k.id, 'keyword_research_runs', 'keyword_research',
    k.client_id, null::uuid, null::text, k.created_at, coalesce(k.cost_usd, 0), 0::bigint, 0::bigint,
    null::text
from public.keyword_research_runs k
where coalesce(k.cost_usd, 0) > 0

union all
select
    'kw_topic:' || t.id, 'keyword_topic_research_runs', 'keyword_topic_research',
    t.client_id, null::uuid, null::text, t.created_at, coalesce(t.cost_usd, 0), 0::bigint, 0::bigint,
    null::text
from public.keyword_topic_research_runs t
where coalesce(t.cost_usd, 0) > 0

union all
select
    'domain_intel:' || d.id, 'domain_intel_snapshots', 'domain_intel',
    d.client_id, null::uuid, null::text, d.captured_at, coalesce(d.cost_usd, 0), 0::bigint, 0::bigint,
    null::text
from public.domain_intel_snapshots d
where coalesce(d.cost_usd, 0) > 0

union all
select
    'autonomy:' || a.id, 'autonomy_runs', 'autonomy_run',
    a.client_id, null::uuid, null::text, a.created_at, coalesce(a.cost_usd, 0), 0::bigint, 0::bigint,
    null::text
from public.autonomy_runs a
where coalesce(a.cost_usd, 0) > 0

union all
select
    'leadoff:' || l.id, 'leadoff_spend', 'leadoff_' || coalesce(nullif(l.action, ''), 'other'),
    null::uuid, l.user_id, null::text, l.created_at, coalesce(l.est_cost, 0), 0::bigint, 0::bigint,
    null::text
from public.leadoff_spend l
where coalesce(l.est_cost, 0) > 0

union all
select
    'strategist:' || s.id, 'strategy_reviews', 'strategist_review',
    s.client_id, null::uuid, null::text, coalesce(s.completed_at, s.created_at),
    round(
        (coalesce((s.token_usage->>'input_tokens')::numeric, 0) / 1000000.0)
            * (case when lower(coalesce(s.model, '')) like '%haiku%' then 1.00
                    when lower(coalesce(s.model, '')) like '%opus%'  then 5.00
                    else 3.00 end)
      + (coalesce((s.token_usage->>'output_tokens')::numeric, 0) / 1000000.0)
            * (case when lower(coalesce(s.model, '')) like '%haiku%' then 5.00
                    when lower(coalesce(s.model, '')) like '%opus%'  then 25.00
                    else 15.00 end)
    , 6),
    coalesce((s.token_usage->>'input_tokens')::bigint, 0),
    coalesce((s.token_usage->>'output_tokens')::bigint, 0),
    coalesce(nullif(s.model, ''), 'claude-sonnet-4-6')
from public.strategy_reviews s
where coalesce((s.token_usage->>'input_tokens')::bigint, 0)
    + coalesce((s.token_usage->>'output_tokens')::bigint, 0) > 0

union all
select
    'qa:' || q.id, 'qa_reviews', 'qa_review',
    q.client_id, null::uuid, null::text, q.created_at,
    coalesce(q.cost_usd, 0),
    coalesce((q.token_usage->>'input_tokens')::bigint, 0),
    coalesce((q.token_usage->>'output_tokens')::bigint, 0),
    'claude-haiku-4-5-20251001'::text
from public.qa_reviews q
where coalesce(q.cost_usd, 0) > 0
    or coalesce((q.token_usage->>'input_tokens')::bigint, 0)
     + coalesce((q.token_usage->>'output_tokens')::bigint, 0) > 0

union all
-- LLM usage ledger — the newly-instrumented sources (AI Visibility, etc.) -------
select
    'llm:' || u.id, 'llm_usage', u.source,
    u.client_id, u.actor_id, null::text, u.occurred_at,
    coalesce(u.cost_usd, 0),
    coalesce(u.input_tokens, 0),
    coalesce(u.output_tokens, 0),
    coalesce(nullif(u.model, ''), u.provider)
from public.llm_usage u
where coalesce(u.cost_usd, 0) > 0
    or coalesce(u.input_tokens, 0) + coalesce(u.output_tokens, 0) > 0;

grant select on public.cost_events to service_role;
