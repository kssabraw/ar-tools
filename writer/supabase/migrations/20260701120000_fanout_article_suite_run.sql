-- Fan-out blog articles are mirrored into the suite as first-class blog runs
-- (public.runs + module_outputs) when the Fan-out session is client-linked, so
-- they show up in Saved Articles and are publishable (Google Docs / WordPress)
-- like a natively-generated blog post. Record the mirrored run id back on the
-- Fan-out article for traceability. Additive + backward-compatible: null means
-- "not mirrored" (e.g. an owner-global session with no client).
alter table fanout.article_outputs
  add column if not exists suite_run_id uuid;

comment on column fanout.article_outputs.suite_run_id is
  'The mirrored suite blog run (public.runs.id) for this article when the session is client-linked; null otherwise.';
