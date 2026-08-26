-- WHIT Posting — add the third page type 'local_seo'. A local SEO page uses the
-- same 33 ACF fields + writer as a city page (2-level under the silo:
-- /florida/<page>/), but the leaf is a freely-named page/keyword rather than a
-- city.
alter table wheelhouse_pages drop constraint if exists wheelhouse_pages_page_type_check;
alter table wheelhouse_pages add constraint wheelhouse_pages_page_type_check
  check (page_type in ('service', 'city', 'local_seo'));
