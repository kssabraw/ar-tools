-- Record when a scheduled article generated successfully but its opt-in publish
-- (WordPress / Google Drive) failed. Without this, a generated-but-unpublished
-- piece read as a clean `complete` and the publish failure was swallowed silently
-- (the failure mode behind the Nova Life Peptides scheduled posts never going
-- live — SiteGround's anti-bot was 400-ing the WP REST publish). The content
-- scheduler now writes the reason here and emits a `content_publish_failed`
-- notification. Nullable + additive; existing rows and the success path are
-- unaffected.
alter table fanout.scheduled_article_runs
  add column if not exists publish_error text;
