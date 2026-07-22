-- Content Scheduler: per-batch GitHub auto-publish.
--
-- When true, each blog_post item in the batch, after it finishes generating,
-- enqueues the `blog_github_publish` media pipeline (hero + inline images per the
-- image-generation SOP) and commits the article + image bytes to the client's
-- GitHub repo in one commit. This closes the gap where a scheduled post was only
-- ever GENERATED (a draft run) and still needed a manual publish — so for opted-in
-- batches "complete" and "live" become the same thing, with nothing to reconcile.
--
-- Additive + backwards-compatible: defaults false, so existing batches keep the
-- old generate-only behaviour until explicitly opted in.

alter table content_batches
  add column if not exists github_publish boolean not null default false;

comment on column content_batches.github_publish is
  'When true, blog_post items in this batch auto-publish to the client''s GitHub repo '
  '(via the blog media SOP: hero + inline images, atomic commit) right after they generate.';
