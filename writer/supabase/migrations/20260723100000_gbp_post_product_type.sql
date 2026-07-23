-- Migration: 20260723100000_gbp_post_product_type.sql
-- Purpose: add a 'product' post type to the GBP Posts module.
--
--   The GBP UI offers four post types — Updates, Offers, Events, Products — but
--   Google's localPosts v4 API only accepts topicType STANDARD | EVENT | OFFER |
--   ALERT. **Product posts are NOT creatable through any Business Profile API**
--   (they live in the GBP Product Editor, which has no public write API). So a
--   'product' post here is a product-framed **Update**: it publishes as a
--   STANDARD localPost (image + Shop/Order CTA + product-spotlight copy), the
--   same approach commercial GBP tools use. The topic_type→API mapping lives in
--   services/gbp_posts_api.build_local_post_body (product → STANDARD).
--
--   Widens the topic_type CHECK on both tables to include 'product'. Additive.

alter table gbp_posts drop constraint if exists gbp_posts_topic_type_check;
alter table gbp_posts
  add constraint gbp_posts_topic_type_check
  check (topic_type in ('standard', 'event', 'offer', 'product'));

alter table gbp_post_schedules drop constraint if exists gbp_post_schedules_topic_type_check;
alter table gbp_post_schedules
  add constraint gbp_post_schedules_topic_type_check
  check (topic_type in ('standard', 'event', 'offer', 'product'));
