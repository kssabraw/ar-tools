-- Per-run editorial notes typed by the user on the New Run form
-- ("mention Zero Down Supply Chain Services as one of the top 10 best").
-- Threaded into the Writer's section/intro/conclusion prompts as guidance.
-- Deliberately NOT part of the brief: the brief is client-agnostic and
-- globally cached, so per-run/per-client guidance can never enter it.
alter table runs add column if not exists writer_notes text;
