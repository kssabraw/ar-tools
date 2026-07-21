-- Migration: 20260720170000_tasks_qa_rubric.sql
-- Purpose: let a task carry an EXPLICIT QA rubric (qa-agent-plan), so the QA
--          reviewer no longer has to infer it from the task NAME (which forced
--          teams to title a task "Website Pages Posted" to get the right
--          checklist). A dropdown on the task drawer sets this; when it's null,
--          qa_signals.rubric_for falls back to the old name-matching, so every
--          existing task keeps working unchanged.
--
-- Nullable, no default (null = "auto-detect from the task name"). No CHECK
-- constraint on the value — the allowed rubric set lives in
-- services/qa_signals.py (RUBRIC_KEYS) and is validated at the API, so new
-- rubrics don't require a migration to widen a constraint.

alter table tasks add column if not exists qa_rubric text;

comment on column tasks.qa_rubric is
  'Explicit QA rubric key (qa_signals RUBRIC_*); null = auto-detect from the task name.';
