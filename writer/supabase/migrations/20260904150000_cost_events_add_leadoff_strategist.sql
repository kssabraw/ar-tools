-- Extend cost_events (migration 20260904140000) with two more spend/usage
-- sources, per owner request:
--   * LeadOff paid market-research actions (leadoff_spend) — real USD spend,
--     pre-client (no client_id → the "No client / internal" bucket), attributed
--     to the user who ran it.
--   * SerMaStr strategist runs (strategy_reviews) — LLM token usage. These record
--     tokens but NOT a dollar cost, so cost_usd is 0 and the row is included on
--     token usage instead of on cost. (QA reviews record neither cost nor tokens,
--     so there is nothing to fold in for QA until the agent is instrumented.)
--
-- CREATE OR REPLACE keeps the exact same output columns as 20260904140000 and
-- only appends UNION branches; the view stays a spend/usage ledger.

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
    0::bigint                               as input_tokens,
    0::bigint                               as output_tokens
from public.runs r
where coalesce(r.total_cost_usd, 0) > 0

union all
select
    'local_seo:' || p.id, 'local_seo_pages',
    case when p.mode = 'reoptimize' then 'local_seo_reoptimize' else 'local_seo_page' end,
    p.client_id, p.created_by, null::text, p.created_at,
    coalesce((p.cost_breakdown->>'total')::numeric, 0),
    coalesce((p.token_usage->>'input_tokens')::bigint, 0),
    coalesce((p.token_usage->>'output_tokens')::bigint, 0)
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
    coalesce((e.token_usage->>'output_tokens')::bigint, 0)
from public.ecommerce_pages e
where coalesce((e.cost_breakdown->>'total')::numeric, 0) > 0

union all
select
    'kw_research:' || k.id, 'keyword_research_runs', 'keyword_research',
    k.client_id, null::uuid, null::text, k.created_at, coalesce(k.cost_usd, 0), 0::bigint, 0::bigint
from public.keyword_research_runs k
where coalesce(k.cost_usd, 0) > 0

union all
select
    'kw_topic:' || t.id, 'keyword_topic_research_runs', 'keyword_topic_research',
    t.client_id, null::uuid, null::text, t.created_at, coalesce(t.cost_usd, 0), 0::bigint, 0::bigint
from public.keyword_topic_research_runs t
where coalesce(t.cost_usd, 0) > 0

union all
select
    'domain_intel:' || d.id, 'domain_intel_snapshots', 'domain_intel',
    d.client_id, null::uuid, null::text, d.captured_at, coalesce(d.cost_usd, 0), 0::bigint, 0::bigint
from public.domain_intel_snapshots d
where coalesce(d.cost_usd, 0) > 0

union all
select
    'autonomy:' || a.id, 'autonomy_runs', 'autonomy_run',
    a.client_id, null::uuid, null::text, a.created_at, coalesce(a.cost_usd, 0), 0::bigint, 0::bigint
from public.autonomy_runs a
where coalesce(a.cost_usd, 0) > 0

union all
-- LeadOff paid market-research actions (pre-client; attributed to the runner) --
select
    'leadoff:' || l.id,
    'leadoff_spend',
    'leadoff_' || coalesce(nullif(l.action, ''), 'other'),
    null::uuid,
    l.user_id,
    null::text,
    l.created_at,
    coalesce(l.est_cost, 0),
    0::bigint,
    0::bigint
from public.leadoff_spend l
where coalesce(l.est_cost, 0) > 0

union all
-- SerMaStr strategist runs — token usage only (no dollar cost recorded) --------
select
    'strategist:' || s.id,
    'strategy_reviews',
    'strategist_review',
    s.client_id,
    null::uuid,
    null::text,
    coalesce(s.completed_at, s.created_at),
    0::numeric,
    coalesce((s.token_usage->>'input_tokens')::bigint, 0),
    coalesce((s.token_usage->>'output_tokens')::bigint, 0)
from public.strategy_reviews s
where coalesce((s.token_usage->>'input_tokens')::bigint, 0)
    + coalesce((s.token_usage->>'output_tokens')::bigint, 0) > 0;

grant select on public.cost_events to service_role;
