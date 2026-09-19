-- Social Media P5 (slice a.1) — a storyboard's exported Google Doc URL.
--
-- A storyboard is a shoot-ready brief; exporting it as a Google Doc into the client's
-- Drive folder is how the suite hands off deliverables. Persist the resulting Doc URL so
-- the exported brief is re-openable from the UI and a re-export (dedupe_by_name) is
-- idempotent. Additive + nullable — an un-exported storyboard is unaffected.

alter table social_storyboards
  add column if not exists doc_url text;
