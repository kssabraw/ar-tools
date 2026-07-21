-- Migration: 20260721140000_tasks_qa_page_type.sql
-- Purpose: let a website-page task carry an explicit QA page SUB-TYPE
--          (service / local_landing / location), so QA's structural
--          design-fit check compares the page against the MATCHING stored
--          reference structure (clients.page_structures[type]) instead of the
--          fixed service → local_landing → location fallback order. Picked via
--          the 'Page type' dropdown in the task drawer's QA panel.
--
-- Nullable, no default (null = auto / fall back to the priority order). No
-- CHECK — the allowed set lives in services/qa_signals.WEBSITE_PAGE_TYPES and
-- is validated at the API.

alter table tasks add column if not exists qa_page_type text;

comment on column tasks.qa_page_type is
  'Website-page sub-type for QA structural-fit reference selection (service/local_landing/location); null = auto.';
