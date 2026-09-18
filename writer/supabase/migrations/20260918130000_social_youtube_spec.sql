-- Social Media module — correct the seeded `youtube` platform spec for POSTING.
--
-- The row was seeded (20260905120000) as "v1 analyze-only … no video generation"
-- with max_images 1. Queue #3 makes YouTube a real poster: a YouTube post is a
-- VIDEO + a required title (mapped via platform_configurations.youtube by the
-- adapter), with NO images. requires_image is already false (correct — a YT post
-- is a video, not an image). The video-required / title-required / no-images rules
-- are enforced deterministically in code (publish.validate_post, keyed on
-- platform == 'youtube'); this migration only corrects the stale spec-row DATA so
-- the DB is self-honest:
--   * max_images 1 -> 0 (YouTube posts carry no images)
--   * notes -> the real "video + required title" poster description
-- char_limit stays 5000 (it bounds the caption, which maps to the video DESCRIPTION).
-- Idempotent: an update, only when the row exists.
update social_platform_specs
set max_images = 0,
    notes = 'YouTube: uploads an existing video (one video, no images); the caption maps to the video description (<=5000). A YouTube post REQUIRES a title via platform_configurations.youtube (distinct from the caption); privacy_status defaults server-side (public); made_for_kids/tags/category via platform_metadata.',
    updated_at = now()
where platform = 'youtube';
