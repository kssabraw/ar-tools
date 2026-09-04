-- Cost events view — the normalized spend/usage stream behind the admin Cost &
-- Usage Report (routers/cost_analytics.py), sibling to deliverable_events.
--
-- Money spent (and, where the generator records them, LLM tokens) is scattered
-- across per-deliverable rows in different shapes: a scalar total_cost_usd on
-- runs, a `cost_breakdown` JSONB {total,...} + `token_usage` JSONB
-- {input_tokens,output_tokens} on Local SEO / ecommerce pages, and a scalar
-- cost_usd on the research/autonomy runs. This view UNIONs the client-
-- attributable cost sources into one shape so the analytics service can sum
-- cost + tokens by type / client / team member over a date range from one read.
--
-- Columns: event_id, source, cost_type (granular key; labels in the service),
-- client_id, actor_id (creator profile, when recorded), actor_name (unused
-- here — kept for shape-parity with deliverable_events), occurred_at, cost_usd,
-- input_tokens, output_tokens (0 when the source doesn't record tokens).
--
-- This is a SPEND ledger: a row is included whenever a positive cost was
-- recorded, regardless of terminal status or soft-delete — money spent on a
-- failed/deleted item is still money spent. (Contrast deliverable_events, which
-- counts only produced work.) Tokens are only populated for the two LLM page
-- generators that store them.
--
-- Definer view; only service_role granted SELECT (admin-gated at the router).

create or replace view public.cost_events as

-- Blog / service / location content runs --------------------------------------
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
-- Local SEO pages (cost total + LLM tokens) -----------------------------------
select
    'local_seo:' || p.id,
    'local_seo_pages',
    case when p.mode = 'reoptimize' then 'local_seo_reoptimize' else 'local_seo_page' end,
    p.client_id,
    p.created_by,
    null::text,
    p.created_at,
    coalesce((p.cost_breakdown->>'total')::numeric, 0),
    coalesce((p.token_usage->>'input_tokens')::bigint, 0),
    coalesce((p.token_usage->>'output_tokens')::bigint, 0)
from public.local_seo_pages p
where coalesce((p.cost_breakdown->>'total')::numeric, 0) > 0

union all
-- Ecommerce pages (cost total + LLM tokens) -----------------------------------
select
    'ecommerce:' || e.id,
    'ecommerce_pages',
    case
        when e.mode = 'reoptimize'      then 'ecommerce_reoptimize'
        when e.page_type = 'collection' then 'ecommerce_collection'
        else 'ecommerce_product'
    end,
    e.client_id,
    e.created_by,
    null::text,
    e.created_at,
    coalesce((e.cost_breakdown->>'total')::numeric, 0),
    coalesce((e.token_usage->>'input_tokens')::bigint, 0),
    coalesce((e.token_usage->>'output_tokens')::bigint, 0)
from public.ecommerce_pages e
where coalesce((e.cost_breakdown->>'total')::numeric, 0) > 0

union all
-- Keyword research runs (paid DataForSEO) -------------------------------------
select
    'kw_research:' || k.id,
    'keyword_research_runs',
    'keyword_research',
    k.client_id,
    null::uuid,
    null::text,
    k.created_at,
    coalesce(k.cost_usd, 0),
    0::bigint,
    0::bigint
from public.keyword_research_runs k
where coalesce(k.cost_usd, 0) > 0

union all
-- Keyword topic research runs -------------------------------------------------
select
    'kw_topic:' || t.id,
    'keyword_topic_research_runs',
    'keyword_topic_research',
    t.client_id,
    null::uuid,
    null::text,
    t.created_at,
    coalesce(t.cost_usd, 0),
    0::bigint,
    0::bigint
from public.keyword_topic_research_runs t
where coalesce(t.cost_usd, 0) > 0

union all
-- Domain intelligence snapshots (paid Labs) -----------------------------------
select
    'domain_intel:' || d.id,
    'domain_intel_snapshots',
    'domain_intel',
    d.client_id,
    null::uuid,
    null::text,
    d.captured_at,
    coalesce(d.cost_usd, 0),
    0::bigint,
    0::bigint
from public.domain_intel_snapshots d
where coalesce(d.cost_usd, 0) > 0

union all
-- Autonomy executor runs ------------------------------------------------------
select
    'autonomy:' || a.id,
    'autonomy_runs',
    'autonomy_run',
    a.client_id,
    null::uuid,
    null::text,
    a.created_at,
    coalesce(a.cost_usd, 0),
    0::bigint,
    0::bigint
from public.autonomy_runs a
where coalesce(a.cost_usd, 0) > 0;

grant select on public.cost_events to service_role;
