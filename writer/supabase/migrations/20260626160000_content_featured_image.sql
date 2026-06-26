-- Manual image picker (#3, WordPress publishing) — a featured/hero image per
-- content item. The image is uploaded to the public `wordpress_images` bucket;
-- its public URL is stored here. On WordPress publish it is sideloaded into the
-- client's WP media library and set as the post's featured image; on Google Docs
-- publish it is rendered as a hero image at the top of the doc.
alter table runs add column if not exists featured_image_url text;
alter table local_seo_pages add column if not exists featured_image_url text;
