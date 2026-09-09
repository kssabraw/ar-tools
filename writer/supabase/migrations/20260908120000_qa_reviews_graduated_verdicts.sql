-- Migration: 20260908120000_qa_reviews_graduated_verdicts.sql
-- Purpose: graduated QA verdicts (owner ruling 2026-09-08). The QA agent's
--          verdict is no longer binary pass/fail — a blocking failure now
--          splits by SEVERITY into 'revisions' (fixable; the pre-ruling fail
--          behaviour — Rework subtasks + self-re-QA loop) vs 'fail' (a
--          CRITICAL check failed OR too many blocking checks failed; escalates
--          to a human, no self-loop). 'advisory' is a clean pass that only
--          tripped non-blocking recommendations. Widen the verdict CHECK to
--          admit the two new values alongside the original four.
--
--          Additive + backward-compatible: existing rows (pass/fail/needs_human
--          /skipped) all still satisfy the new constraint, so no data migration.
--          The verdict-assignment logic lives in qa_signals.build_verdict.

alter table qa_reviews drop constraint if exists qa_reviews_verdict_check;
alter table qa_reviews add constraint qa_reviews_verdict_check
  check (verdict in ('pass', 'advisory', 'revisions', 'fail', 'needs_human', 'skipped'));
