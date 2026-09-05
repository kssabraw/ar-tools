-- cost_events, part 3: surface the newly-captured tokens/cost.
--   * runs branch now sums module_outputs.token_usage per run (blog pipeline
--     tokens; cost was already r.total_cost_usd).
--   * strategist branch derives an ESTIMATED cost from its recorded tokens ×
--     the model's list price (Sonnet $3/$15, Haiku $1/$5, Opus $5/$25 per 1M —
--     mirrors pipeline-api/modules/brief/cost.py). This is the #2 backfill: it
--     applies to all past + future strategist rows on read, no stored column.
--   * new qa_reviews branch (cost + tokens the QA agent now records).
-- CREATE OR REPLACE keeps the same output columns.

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
              from public.module_outputs mo where mo.run_id = r.id), 0::bigint) as output_tokens
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
select
    'leadoff:' || l.id, 'leadoff_spend', 'leadoff_' || coalesce(nullif(l.action, ''), 'other'),
    null::uuid, l.user_id, null::text, l.created_at, coalesce(l.est_cost, 0), 0::bigint, 0::bigint
from public.leadoff_spend l
where coalesce(l.est_cost, 0) > 0

union all
-- Strategist: estimated cost = tokens × model list price (Sonnet default) ------
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
    coalesce((s.token_usage->>'output_tokens')::bigint, 0)
from public.strategy_reviews s
where coalesce((s.token_usage->>'input_tokens')::bigint, 0)
    + coalesce((s.token_usage->>'output_tokens')::bigint, 0) > 0

union all
-- QA reviews (cost + tokens the agent now records) ----------------------------
select
    'qa:' || q.id, 'qa_reviews', 'qa_review',
    q.client_id, null::uuid, null::text, q.created_at,
    coalesce(q.cost_usd, 0),
    coalesce((q.token_usage->>'input_tokens')::bigint, 0),
    coalesce((q.token_usage->>'output_tokens')::bigint, 0)
from public.qa_reviews q
where coalesce(q.cost_usd, 0) > 0
    or coalesce((q.token_usage->>'input_tokens')::bigint, 0)
     + coalesce((q.token_usage->>'output_tokens')::bigint, 0) > 0;

grant select on public.cost_events to service_role;
