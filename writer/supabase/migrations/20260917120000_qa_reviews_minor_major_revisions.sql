-- Migration: 20260917120000_qa_reviews_minor_major_revisions.sql
-- Purpose: finer QA revisions tiers (owner ruling 2026-09-17). The graduated
--          verdict's single fixable band 'revisions' (added 2026-09-08) splits
--          by COUNT into 'minor_revisions' (one quick, non-critical blocking
--          fix) and 'major_revisions' (several). Both route identically (For
--          Revision lane + Rework subtasks + self-re-QA loop); the split is a
--          severity/legibility + notification-urgency signal. The
--          minor/major boundary is qa_signals.DEFAULT_MINOR_REVISION_MAX /
--          settings.qa_minor_revision_max (default 1). Verdict logic lives in
--          qa_signals.build_verdict.
--
--          'revisions' is RETAINED in the CHECK (not dropped) for two reasons:
--          (1) deploy-window safety — during the rollout old code may still emit
--          it against the new constraint; (2) it stays valid for any straggler.
--          Existing rows are data-migrated to 'major_revisions' below so the
--          UI/aggregators see the new vocabulary.

alter table qa_reviews drop constraint if exists qa_reviews_verdict_check;
alter table qa_reviews add constraint qa_reviews_verdict_check
  check (verdict in (
    'pass', 'advisory', 'minor_revisions', 'major_revisions', 'revisions',
    'fail', 'needs_human', 'skipped'
  ));

-- Rename existing fixable-band rows to the new default (the pre-split
-- 'revisions' behaviour is 'major_revisions'). A single-issue historical row
-- can't be re-derived as minor without re-running its checks, so the
-- conservative rename is to major.
update qa_reviews set verdict = 'major_revisions' where verdict = 'revisions';
