-- Fanout article planning: bulk keyword->cluster linkage in one round trip.
--
-- `persist_article_plan` linked keywords to their cluster with one PostgREST
-- UPDATE *per cluster* (each cluster has a distinct cluster_id, so `.in_()`
-- can't fold them together). At small plan sizes that was merely chatty; at
-- scale it is a hard wall.
--
-- The 2026-07-31 "tirzepatide" run (Nova Life Peptides) planned 4,043 clusters
-- over 4,423 active keywords. The write phase therefore issued ~4,100 sequential
-- requests on a single HTTP/2 connection and died partway through:
--
--   RemoteProtocolError: <ConnectionTerminated error_code:1, last_stream_id:8201>
--
-- (stream 8201 == request #4,101). The plan was left half-written — clusters and
-- linkage present, primary flags/drops/coverage-gaps missing, status stuck at
-- `error`. The two earlier runs for the same client survived only because they
-- were half the size (1,413 and 1,594 clusters).
--
-- This function takes the whole linkage set as one jsonb payload so the writer
-- can send it in chunks (~9 requests for 4.4k keywords instead of ~4,100),
-- removing the per-cluster request entirely.
--
-- Semantics match the loop it replaces, which always runs immediately after
-- `reset_article_planning` has cleared cluster_id / is_primary_for_cluster /
-- serp_top_urls for the session:
--   * cluster_id             — always assigned from the payload.
--   * is_primary_for_cluster — assigned explicitly (defaults false), so a row
--                              demoted between runs is corrected, not left set.
--   * serp_top_urls          — only written when the payload carries a non-null
--                              array, so a supporting keyword never clobbers a
--                              primary's captured SERP with null.
create or replace function fanout.bulk_link_keywords_to_clusters(p_rows jsonb)
returns integer
language plpgsql
as $function$
declare
  n integer;
begin
  update fanout.keywords k
     set cluster_id             = r.cluster_id,
         is_primary_for_cluster = coalesce(r.is_primary, false),
         serp_top_urls          = coalesce(r.serp_top_urls, k.serp_top_urls)
    from jsonb_to_recordset(coalesce(p_rows, '[]'::jsonb)) as r(
           keyword_id    uuid,
           cluster_id    uuid,
           is_primary    boolean,
           serp_top_urls text[]
         )
   where k.id = r.keyword_id;
  get diagnostics n = row_count;
  return n;
end;
$function$;

comment on function fanout.bulk_link_keywords_to_clusters(jsonb) is
  'Bulk-assign cluster_id / is_primary_for_cluster / serp_top_urls for a batch of '
  'keywords during article-plan persistence. Replaces one PostgREST UPDATE per '
  'cluster, which exhausted the HTTP/2 connection on large plans (>4k clusters).';

-- Matches the grants on the other fanout RPCs (claim_scheduled_runs,
-- increment_session_cost): the backend calls this with the service-role key only.
revoke all on function fanout.bulk_link_keywords_to_clusters(jsonb) from public;
grant execute on function fanout.bulk_link_keywords_to_clusters(jsonb) to service_role;
