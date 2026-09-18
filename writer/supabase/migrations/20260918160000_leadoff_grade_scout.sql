-- LeadOff on-demand grader — scout-from-a-grade.
--
-- Lets a live-graded (off-board) market be "scouted" (Pass-2 deepen: referring
-- domains + review velocity + demand trend + competitor brand footprint) without
-- a board row. The scout's WORK is unchanged and still writes the shared
-- market_scanner caches; only its competitor INPUT is sourced from the grade row
-- (leadoff_grades.grade.competitors) instead of the board's serp_top5, and its
-- resulting enrichment SUMMARY is stored back here so the grade card can show it.
--
-- No new job type (reuses leadoff_scout) and no spend-action change (reuses
-- 'scout') — the payload just carries grade_id.

alter table public.leadoff_grades
    add column if not exists scout jsonb;   -- {enrichment, competitors, summary, scouted_at}
