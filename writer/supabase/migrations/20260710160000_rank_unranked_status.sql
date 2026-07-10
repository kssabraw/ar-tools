-- Purpose: Organic Rank Tracker (Module #4) — add the 'unranked' status.
--
-- A keyword that the DataForSEO fallback has looked up but that doesn't appear
-- in the SERP (the client's domain isn't in the top results) was previously
-- stored as 'no_data' — indistinguishable from a keyword that has never been
-- fetched. Split the two: 'unranked' = actively checked, ranks nowhere;
-- 'no_data' = added but not yet through a fetch. This lets coverage reflect
-- that such keywords ARE tracked. Status is still computed (never user-set).
alter table tracked_keywords
  drop constraint if exists tracked_keywords_status_check;

alter table tracked_keywords
  add constraint tracked_keywords_status_check
  check (status in ('climbing', 'stable', 'volatile', 'dropping',
                    'deindex_risk', 'unranked', 'no_data'));
