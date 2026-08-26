-- Per-day property-level GSC traffic totals (impressions + clicks), aggregated in
-- Postgres so the client report's Performance-highlights comparisons read the same
-- property-wide source the campaign goals already use (gsc_query_daily), instead of
-- the per-keyword rank_keyword_metrics table (whose clicks/impressions can go stale
-- and produced a misleading "0 / -100%" row). Aggregating server-side keeps the
-- transfer to one row per day rather than one row per query×day (~thousands/day).
create or replace function public.gsc_property_daily_traffic(
  p_property_id uuid,
  p_from date
)
returns table (date date, impressions bigint, clicks bigint)
language sql
stable
as $$
  select date,
         coalesce(sum(impressions), 0)::bigint as impressions,
         coalesce(sum(clicks), 0)::bigint as clicks
  from public.gsc_query_daily
  where property_id = p_property_id
    and date >= p_from
  group by date
  order by date
$$;

grant execute on function public.gsc_property_daily_traffic(uuid, date) to service_role;
