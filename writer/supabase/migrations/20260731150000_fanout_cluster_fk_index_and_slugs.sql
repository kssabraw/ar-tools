-- Fanout: index the clusters->keywords FK, and bulk-assign cluster slugs.
--
-- (1) MISSING FK INDEX -----------------------------------------------------
--
-- `clusters.primary_keyword_id` references `keywords.id` but has no index, so
-- every keyword DELETE seq-scans the whole clusters table to prove nothing
-- references it. `regate` rebuilds a session's keyword pool by deleting all of
-- its rows, which makes that cost catastrophic. Measured on the live
-- tirzepatide session (30,355 keywords, clusters already removed):
--
--   Trigger clusters_primary_keyword_id_fkey: time=15750.195 calls=30355
--   Execution Time: 16229.921 ms
--
-- against an inherited statement_timeout of 8s — so re-gating any large session
-- fails with 57014 before it starts. With the index the same delete runs in
-- 377ms (trigger 285ms), a 43x improvement.
--
-- Plain (not partial) index: gap-placeholder clusters carry a null
-- primary_keyword_id, and FK equality lookups never match nulls anyway, so the
-- nulls cost a little space and a partial index buys nothing but risk of the
-- planner declining it. The table is small, so a non-CONCURRENT build is fine.
create index if not exists clusters_primary_keyword_id_idx
  on fanout.clusters (primary_keyword_id);

comment on index fanout.clusters_primary_keyword_id_idx is
  'Supports the clusters_primary_keyword_id_fkey check fired by every keywords '
  'DELETE. Without it a regate on a large session seq-scans clusters 30k+ times '
  'and blows the 8s statement_timeout.';


-- (2) BULK SLUG ASSIGNMENT --------------------------------------------------
--
-- `ensure_session_slugs` writes one UPDATE per cluster. That is the same
-- per-row HTTP pattern that exhausted the HTTP/2 connection at ~4.1k requests
-- in the article-plan linkage (fixed in #529). It has been masked so far only
-- because the unpaged read feeding it truncates at PostgREST's 1000-row cap —
-- so it never issued more than 1000 requests, and never slugged more than 1000
-- clusters. Paging that read (this same change) removes the mask, so the write
-- must be batched at the same time or a 4k-cluster session walks straight into
-- the connection wall.
create or replace function fanout.bulk_set_cluster_slugs(p_rows jsonb)
returns integer
language plpgsql
as $function$
declare
  n integer;
begin
  update fanout.clusters c
     set slug = r.slug
    from jsonb_to_recordset(coalesce(p_rows, '[]'::jsonb)) as r(
           cluster_id uuid,
           slug       text
         )
   where c.id = r.cluster_id
     and c.slug is distinct from r.slug;
  get diagnostics n = row_count;
  return n;
end;
$function$;

comment on function fanout.bulk_set_cluster_slugs(jsonb) is
  'Bulk-assign clusters.slug for a batch of clusters during ensure_session_slugs. '
  'Replaces one PostgREST UPDATE per cluster, which would exhaust the HTTP/2 '
  'connection once the feeding read is paged past 1000 rows.';

revoke all on function fanout.bulk_set_cluster_slugs(jsonb) from public;
grant execute on function fanout.bulk_set_cluster_slugs(jsonb) to service_role;
