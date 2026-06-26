-- ============================================================
-- module_outputs.module: allow the service-page modules
-- ============================================================
-- The original CHECK only listed the five blog-pipeline modules, but the
-- service-page pipeline persists its own module_outputs rows: `service_brief`
-- and `service_writer` (the two generation stages), `service_score` (the nlp-api
-- 8-engine score), and `source_page_score` (the score of an existing LIVE page
-- being reoptimized). Without this, the very first service-page module insert
-- violates module_outputs_module_check. Widen the constraint to cover them.
-- Additive — no existing rows change.
-- ============================================================

alter table module_outputs drop constraint if exists module_outputs_module_check;
alter table module_outputs add constraint module_outputs_module_check
  check (module in (
    'brief', 'sie', 'research', 'writer', 'sources_cited',
    'service_brief', 'service_writer', 'service_score', 'source_page_score'
  ));
