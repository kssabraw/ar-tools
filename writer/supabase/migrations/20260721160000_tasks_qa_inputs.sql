-- Migration: 20260721160000_tasks_qa_inputs.sql
-- Purpose: make QA foolproof for an untrained VA by replacing hidden
--          conventions with first-class, labeled task fields:
--            - deliverable_url: the page URL QA reviews (was: a subtask that
--              had to be NAMED 'Deliverable links', or a URL buried in the
--              description).
--            - qa_keyword: the target keyword QA checks placement of (was: a
--              'KW:'/'Keyword:' marker or the task-name convention).
--          Both remain OPTIONAL — the old conventions still work as fallbacks,
--          so nothing existing breaks; these just give a VA an obvious box to
--          type in.
--
-- Nullable, no default. No CHECK (free text / URL).

alter table tasks add column if not exists deliverable_url text;
alter table tasks add column if not exists qa_keyword text;

comment on column tasks.deliverable_url is
  'The live page URL QA reviews for this task (first-class replacement for the "Deliverable links" subtask convention).';
comment on column tasks.qa_keyword is
  'The target keyword QA checks on-page placement of (first-class replacement for the KW:/task-name convention).';
