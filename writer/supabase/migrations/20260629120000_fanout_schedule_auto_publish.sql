-- Fanout content scheduler: opt-in auto-publish on completion.
-- When set, the worker publishes each finished piece to the linked client's
-- Google Drive folder (a Google Doc via the suite's Apps Script webhook) right
-- after it generates — blog posts, Local SEO pages, and service pages. Best-
-- effort: a publish failure never fails the generation run. Additive +
-- backward-compatible: existing schedules default to false (no auto-publish).
alter table fanout.content_schedules
  add column if not exists auto_publish boolean not null default false;
