-- Migration: 20260807150000_keyword_research_serp_intel.sql
-- Purpose: Keyword Research — persist the SERP-enrichment intelligence on a run.
--   The run now (optionally) makes one live Google SERP call per analyzed seed,
--   yielding People-Also-Ask questions (also folded into the keyword universe)
--   and the competitive landscape (top organic domains across the seeds + who is
--   cited in the AI Overview). That derived intelligence is stored as a single
--   JSONB blob on the run so re-opening a run is a cheap re-read (no re-billing),
--   consistent with the module's existing "persist a run" design.
--
--   serp_intel shape (nullable — null when the pass was disabled/unavailable):
--     {
--       "enabled": true,
--       "seeds_analyzed": ["emergency plumber", ...],
--       "competitors": [{domain, appearances, best_position, seeds:[...],
--                        sample_title, sample_url, aio_cited, is_client}],
--       "aio": {seeds_with_aio, seeds_analyzed, sources:[{domain,url,title,count}]},
--       "paa": ["how much does an emergency plumber cost", ...]
--     }
--
-- No RLS change: same service-role-only access as the rest of the module.

alter table keyword_research_runs
  add column if not exists serp_intel jsonb;
