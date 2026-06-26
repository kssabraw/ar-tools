-- WordPress direct-publish target (#3) — per-client credentials for publishing
-- finished content straight to the client's WordPress site via the WP REST API
-- using an Application Password (WordPress core 5.6+, no plugin required).
--
--   wordpress_site_url     → the site root, e.g. "https://acmehvac.com"
--                            (the REST base is derived: <site>/wp-json/wp/v2)
--   wordpress_username     → the WP user the Application Password belongs to
--   wordpress_app_password → the Application Password (a secret; never returned
--                            to the frontend — the API exposes only a
--                            `wordpress_app_password_set` boolean)
alter table clients add column if not exists wordpress_site_url text;
alter table clients add column if not exists wordpress_username text;
alter table clients add column if not exists wordpress_app_password text;

-- Track a Local SEO page's WordPress publish target (separate from the Google
-- Doc columns added in 20260622150000_local_seo_pages_published.sql).
alter table local_seo_pages add column if not exists published_url text;
