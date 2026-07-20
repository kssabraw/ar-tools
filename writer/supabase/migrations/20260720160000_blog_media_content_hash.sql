-- Article-revision cost control: the content hash the assets were generated
-- from. On republish, an unchanged article short-circuits (no re-render / no
-- new paid image calls); a changed article regenerates.
alter table blog_media_assets add column if not exists content_hash text;
