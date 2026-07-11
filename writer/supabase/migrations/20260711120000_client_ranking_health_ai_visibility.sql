-- Extend the suite-dashboard ranking-health aggregate with an AI VISIBILITY axis
-- so each client tile can show Organic + Maps + AI Visibility side by side.
--
-- Unlike organic/maps rank (lower position = better), AI visibility is a share
-- percentage where HIGHER is better: the fraction of tracked keyword × engine
-- answers that mentioned the brand, in a scan batch. We compare the client's
-- FIRST completed scan batch to its most recent one, mirroring the per-batch
-- visibility_pct that brand_service.compute_trends produces:
--   * only status = 'completed' rows count, and
--   * an AI feature that didn't fire (feature_present = false) is excluded — it's
--     not a miss (matches the scan-trend rollup + brand_alerts).
-- A batch's time is the earliest created_at within it; visibility_pct is
-- 100 * mentions_found / rows. The Python layer derives the up/down direction.
--
-- Aggregated in SQL so one call still covers every client for all three axes.

-- The return signature gains three columns, so the old function must be dropped
-- before the new one is defined (Postgres won't change an OUT-param row type).
drop function if exists public.client_ranking_health();

create or replace function public.client_ranking_health()
returns table (
  client_id              uuid,
  organic_first_avg      numeric,
  organic_latest_avg     numeric,
  organic_keyword_count  integer,
  maps_first_avg         numeric,
  maps_latest_avg        numeric,
  maps_scan_count        integer,
  brand_first_pct        numeric,
  brand_latest_pct       numeric,
  brand_batch_count      integer
)
language sql
stable
as $$
  with kw as (
    select tk.id as keyword_id, tk.client_id
    from tracked_keywords tk
    where tk.active = true
  ),
  metr as (
    select m.keyword_id, m.date,
           coalesce(m.gsc_position, m.tracked_rank::numeric) as pos
    from rank_keyword_metrics m
    join kw on kw.keyword_id = m.keyword_id
    where coalesce(m.gsc_position, m.tracked_rank::numeric) is not null
  ),
  kw_first as (
    select distinct on (keyword_id) keyword_id, pos
    from metr
    order by keyword_id, date asc
  ),
  kw_last as (
    select distinct on (keyword_id) keyword_id, pos
    from metr
    order by keyword_id, date desc
  ),
  organic as (
    select kw.client_id,
           avg(kf.pos)                                          as organic_first_avg,
           avg(kl.pos)                                          as organic_latest_avg,
           count(*) filter (where kl.pos is not null)           as organic_keyword_count
    from kw
    left join kw_first kf on kf.keyword_id = kw.keyword_id
    left join kw_last  kl on kl.keyword_id = kw.keyword_id
    group by kw.client_id
  ),
  scans as (
    select s.id, s.client_id,
           row_number() over (partition by s.client_id order by s.completed_at asc)  as rn_first,
           row_number() over (partition by s.client_id order by s.completed_at desc) as rn_last,
           count(*)     over (partition by s.client_id)                              as scan_count
    from maps_scans s
    where s.status = 'complete' and s.completed_at is not null
  ),
  scan_avg as (
    select r.scan_id, avg(r.average_rank) as avg_rank
    from maps_scan_results r
    where r.average_rank is not null
    group by r.scan_id
  ),
  maps as (
    select s.client_id,
           max(s.scan_count)::int                                  as maps_scan_count,
           max(case when s.rn_first = 1 then sa.avg_rank end)      as maps_first_avg,
           max(case when s.rn_last  = 1 then sa.avg_rank end)      as maps_latest_avg
    from scans s
    left join scan_avg sa on sa.scan_id = s.id
    where s.rn_first = 1 or s.rn_last = 1
    group by s.client_id
  ),
  brand_batch as (
    select h.client_id,
           coalesce(h.scan_batch_id::text, '_') as batch,
           min(h.created_at)                                       as batch_at,
           100.0 * count(*) filter (where h.mention_found) / count(*) as vis_pct
    from brand_mention_history h
    where h.status = 'completed' and coalesce(h.feature_present, true) = true
    group by h.client_id, coalesce(h.scan_batch_id::text, '_')
  ),
  brand_first as (
    select distinct on (client_id) client_id, vis_pct
    from brand_batch
    order by client_id, batch_at asc
  ),
  brand_last as (
    select distinct on (client_id) client_id, vis_pct
    from brand_batch
    order by client_id, batch_at desc
  ),
  brand as (
    select b.client_id,
           count(*)::int                                                          as brand_batch_count,
           (select vis_pct from brand_first f where f.client_id = b.client_id)    as brand_first_pct,
           (select vis_pct from brand_last  l where l.client_id = b.client_id)    as brand_latest_pct
    from brand_batch b
    group by b.client_id
  )
  select
    c.id as client_id,
    o.organic_first_avg,
    o.organic_latest_avg,
    coalesce(o.organic_keyword_count, 0)::int as organic_keyword_count,
    mp.maps_first_avg,
    mp.maps_latest_avg,
    coalesce(mp.maps_scan_count, 0)::int as maps_scan_count,
    br.brand_first_pct,
    br.brand_latest_pct,
    coalesce(br.brand_batch_count, 0)::int as brand_batch_count
  from clients c
  left join organic o  on o.client_id  = c.id
  left join maps    mp on mp.client_id = c.id
  left join brand   br on br.client_id = c.id;
$$;
