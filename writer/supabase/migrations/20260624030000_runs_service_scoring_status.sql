-- ============================================================
-- runs: service-page scoring/reoptimization statuses
-- ============================================================
-- After a service_page run's writer completes, the orchestrator auto-scores
-- (nlp-api national mode) and may auto-reoptimize once. Two new non-terminal
-- statuses make those phases visible. Additive; existing rows unaffected.
-- ============================================================

alter table runs drop constraint if exists runs_status_check;
alter table runs add constraint runs_status_check check (status in (
  'queued',
  'brief_running', 'sie_running', 'research_running', 'writer_running',
  'sources_cited_running',
  'service_brief_running', 'service_writer_running',
  'service_scoring_running', 'service_reopt_running',
  'complete', 'failed', 'cancelled'
));
