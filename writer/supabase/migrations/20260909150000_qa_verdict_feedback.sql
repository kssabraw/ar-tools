-- QA verdict-accuracy feedback loop.
--
-- Records, per QA review, whether the humans' subsequent handling of the task
-- UPHELD or OVERTURNED the verdict — the measurement half of QA. A daily sweep
-- (services/qa_feedback.run_qa_feedback_sweep) reads the task's later status
-- changes + any re-reviews and classifies the disposition; nothing here is set
-- at review time. Reuses qa_reviews (one disposition per review) rather than a
-- new table.
--
-- human_disposition:
--   pending          — not yet decided (still in flight)
--   upheld           — humans acted consistently with the verdict
--   overturned       — humans contradicted the verdict (see disposition_direction)
--   resolved_accept  — a needs_human review the humans resolved as shippable
--   resolved_reject  — a needs_human review the humans resolved as not shippable
--   not_applicable   — skipped/handoff reviews (no deliverable judgement)
-- disposition_direction (only on overturned):
--   too_strict       — QA flagged (fail/revisions) a deliverable humans shipped anyway (false alarm)
--   too_lenient      — QA passed a deliverable humans then bounced / a re-review flagged (missed defect)

alter table qa_reviews
  add column if not exists human_disposition     text,
  add column if not exists disposition_direction text,
  add column if not exists disposition_signal    text,
  add column if not exists disposition_at        timestamptz;

-- Rollup reads filter by rubric + verdict + disposition over a recent window.
create index if not exists idx_qa_reviews_disposition
  on qa_reviews (rubric, verdict, human_disposition);

-- The sweep re-scans not-yet-terminal reviews (null / pending) within its window.
create index if not exists idx_qa_reviews_disposition_pending
  on qa_reviews (created_at)
  where human_disposition is null or human_disposition = 'pending';
