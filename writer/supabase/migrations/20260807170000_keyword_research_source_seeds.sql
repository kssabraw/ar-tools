-- Migration: 20260807170000_keyword_research_source_seeds.sql
-- Purpose: Keyword Research — per-keyword seed attribution, so a user can remove
--   ONE seed from a multi-seed run and take its keywords with it (without a
--   re-run / re-bill).
--
--   source_seeds records which of the run's seeds produced a keyword. A keyword
--   can come from several seeds (the pipeline dedupes across sources), so it is
--   an array; removing a seed drops it from every keyword's source_seeds and
--   deletes only the keywords left with no source. NULL = run-level / not tied to
--   a single seed (the batched keyword_ideas source has no per-seed attribution
--   from DataForSEO, and pre-migration rows) — those are never removed by a
--   single-seed removal, which is the safe default.
--
-- No RLS change: same service-role-only access as the rest of the module.

alter table keyword_research_keywords
  add column if not exists source_seeds text[];
