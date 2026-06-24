-- Per-client ranking-health for the suite dashboard tiles: whether the client's
-- average ORGANIC position and average MAPS (local-pack geo-grid) rank improved
-- or worsened, comparing the most recent "run" to the first.
--
-- Lower rank/position numbers are better, so "improved" means the latest average
-- is a smaller number than the first.
--
-- ORGANIC has no discrete runs (continuous daily ingest), so per active tracked
-- keyword we take its earliest dated position and its latest dated position
-- (gsc_position, falling back to the DataForSEO tracked_rank), then average across
-- the client's keywords. MAPS has discrete scans, so we take the first and most
-- recent COMPLETED scan and average each scan's per-keyword average_rank.
--
-- Aggregated in SQL (not Python) so one call covers every client without pulling
-- the full metrics history into the app.

create or replace function public.client_ranking_health()
returns table (
  client_id              uuid,
  organic_first_avg      numeric,
  organic_latest_avg     numeric,
  organic_keyword_count  integer,
  maps_first_avg         numeric,
  maps_latest_avg        numeric,
  maps_scan_count        integer
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
  )
  select
    c.id as client_id,
    o.organic_first_avg,
    o.organic_latest_avg,
    coalesce(o.organic_keyword_count, 0)::int as organic_keyword_count,
    mp.maps_first_avg,
    mp.maps_latest_avg,
    coalesce(mp.maps_scan_count, 0)::int as maps_scan_count
  from clients c
  left join organic o  on o.client_id  = c.id
  left join maps    mp on mp.client_id = c.id;
$$;
