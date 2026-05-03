-- PRD v2.6 — Brief cache decision UX.
--
-- Add `brief_force_refresh` column to the `runs` table so the user
-- can choose at run-create / rerun time whether to reuse the cached
-- brief (default) or regenerate it from scratch. Mirrors the existing
-- `sie_force_refresh` pattern.
--
-- Frontend flow: when the user submits a run for a keyword that has a
-- cached brief, the dashboard prompts "reuse cached brief from N days
-- ago, or regenerate?" and writes the answer into this column. The
-- orchestrator forwards the value into BriefRequest.force_refresh,
-- which the pipeline-api's brief cache lookup honors.

ALTER TABLE runs
  ADD COLUMN IF NOT EXISTS brief_force_refresh boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN runs.brief_force_refresh IS
  'When true, the brief generator skips its 7-day cache lookup and produces a fresh brief. Set by the run-create / rerun UX when the user explicitly chose to regenerate.';
