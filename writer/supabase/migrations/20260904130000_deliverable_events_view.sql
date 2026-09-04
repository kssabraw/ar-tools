-- Deliverable events view — the single normalized event stream behind the
-- admin Activity Report (routers/deliverables_analytics.py).
--
-- The suite records "work produced" across ~15 tables, each with its own
-- schema, "produced" definition (a terminal status, a published_at, a
-- non-null-not-deleted row) and attribution column. This view UNIONs every
-- such source into one uniform shape so the analytics service can aggregate
-- counts by type / client / team member over a date range from a single read,
-- with the "what counts as produced" rules defined in exactly one place.
--
-- Columns:
--   event_id        stable, source-prefixed unique id
--   source          which table/system produced it
--   deliverable_type  granular type key (labels live in the service layer)
--   client_id       the owning client (nullable — e.g. unlinked tasks)
--   actor_id        profiles.id of the creator, when the source records one
--   actor_name      a free-text doer (task assignee) when there's no profile id
--   occurred_at     when it was produced (terminal ts, else created_at)
--
-- "Produced only" (owner ruling): every branch filters to completed / published
-- / live / non-deleted rows, never drafts, in-progress, or failed.
--
-- Definer view (Postgres 15 default): it runs with the owner's privileges, so
-- it can read the cross-schema fanout tables regardless of service_role grants
-- on that schema. Only service_role is granted SELECT (the API reads it with
-- the service key; it is admin-gated at the router).

create or replace view public.deliverable_events as

-- Blog / service / location content runs -------------------------------------
select
    'run:' || r.id                          as event_id,
    'runs'                                   as source,
    r.content_type                          as deliverable_type,
    r.client_id                             as client_id,
    r.created_by                            as actor_id,
    null::text                              as actor_name,
    coalesce(r.completed_at, r.created_at)  as occurred_at
from public.runs r
where r.status = 'complete'

union all
-- Local SEO pages (generate vs reoptimize) -----------------------------------
select
    'local_seo:' || p.id,
    'local_seo_pages',
    case when p.mode = 'reoptimize' then 'local_seo_reoptimize' else 'local_seo_page' end,
    p.client_id,
    p.created_by,
    null::text,
    p.created_at
from public.local_seo_pages p
where p.deleted_at is null

union all
-- Ecommerce pages (product / collection / reoptimize) ------------------------
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
    e.created_at
from public.ecommerce_pages e
where e.deleted_at is null

union all
-- Website builder pages (published, current) ---------------------------------
select
    'website_page:' || w.id,
    'website_pages',
    'website_page',
    s.client_id,
    null::uuid,
    null::text,
    coalesce(w.published_at, w.created_at)
from public.website_pages w
join public.websites s on s.id = w.website_id
where w.published_at is not null and w.superseded_at is null

union all
-- GBP posts (live) -----------------------------------------------------------
select
    'gbp_post:' || g.id,
    'gbp_posts',
    'gbp_post',
    g.client_id,
    g.created_by,
    null::text,
    coalesce(g.published_at, g.created_at)
from public.gbp_posts g
where g.status = 'live' and g.deleted_at is null

union all
-- Native task completions, by category (SEO NEO etc. = link_building) --------
-- Top-level only: subtasks are checklist markers, not deliverables. The doer
-- is the assignee; created_by is the fallback for an unassigned completion.
select
    'task:' || t.id,
    'tasks',
    'task_' || coalesce(nullif(t.category, ''), 'other'),
    t.client_id,
    t.created_by,
    t.assignee_name,
    coalesce(t.completed_at, t.updated_at, t.created_at)
from public.tasks t
where t.completed = true and t.deleted_at is null and t.parent_task_id is null

union all
-- Client reports -------------------------------------------------------------
select
    'client_report:' || c.id,
    'client_reports',
    'client_report',
    c.client_id,
    null::uuid,
    null::text,
    coalesce(c.completed_at, c.created_at)
from public.client_reports c
where c.status = 'complete'

union all
-- Keyword research reports ---------------------------------------------------
select
    'kw_research_report:' || k.id,
    'keyword_research_reports',
    'keyword_research_report',
    k.client_id,
    k.created_by,
    null::text,
    k.created_at
from public.keyword_research_reports k
where k.status = 'complete'

union all
-- Rank keyword (Organic Rank Analysis) reports -------------------------------
select
    'rank_report:' || rr.id,
    'rank_keyword_reports',
    'rank_keyword_report',
    rr.client_id,
    null::uuid,
    null::text,
    coalesce(rr.generated_at, rr.created_at)
from public.rank_keyword_reports rr
where rr.status = 'complete'

union all
-- Fanout keyword reports (client_id via the linked session, may be null) -----
select
    'fanout_report:' || f.id,
    'fanout_keyword_reports',
    'keyword_report_fanout',
    fs.client_id,
    f.created_by,
    null::text,
    f.generated_at
from fanout.keyword_reports f
left join fanout.sessions fs on fs.id = f.session_id
where f.status = 'complete'

union all
-- Maps geo-grid scans --------------------------------------------------------
select
    'maps_scan:' || m.id,
    'maps_scans',
    'maps_scan',
    m.client_id,
    null::uuid,
    null::text,
    coalesce(m.completed_at, m.created_at)
from public.maps_scans m
where m.status = 'complete'

union all
-- AI-visibility scans (one event per completed own-brand scan batch) ---------
select
    'brand_scan:' || b.scan_batch_id::text,
    'brand_mention_history',
    'ai_visibility_scan',
    b.client_id,
    null::uuid,
    null::text,
    min(b.created_at)
from public.brand_mention_history b
where b.status = 'completed'
  and b.is_competitor_scan = false
  and b.scan_batch_id is not null
group by b.scan_batch_id, b.client_id

union all
-- GSC research runs ----------------------------------------------------------
select
    'gsc_research:' || gr.id,
    'gsc_research_runs',
    'gsc_research',
    gr.client_id,
    null::uuid,
    null::text,
    coalesce(gr.completed_at, gr.created_at)
from public.gsc_research_runs gr
where gr.status = 'complete'

union all
-- Keyword research runs ------------------------------------------------------
select
    'kw_research:' || kr.id,
    'keyword_research_runs',
    'keyword_research',
    kr.client_id,
    null::uuid,
    null::text,
    kr.created_at
from public.keyword_research_runs kr
where kr.status = 'complete'

union all
-- Domain intelligence snapshots ----------------------------------------------
select
    'domain_intel:' || d.id,
    'domain_intel_snapshots',
    'domain_intel',
    d.client_id,
    null::uuid,
    null::text,
    d.captured_at
from public.domain_intel_snapshots d
where d.status = 'complete';

grant select on public.deliverable_events to service_role;
