-- Migration: 20260622140000_clients_local_seo_page_template.sql
-- Purpose: Local SEO module (#2) Phase 3 — per-client default "page template".
-- Stores a reference page URL whose section structure newly generated Local SEO
-- pages should mirror (overridable per page on the New Page form).
-- See docs/modules/local-seo-module-integration-plan-v1_0.md (Phase 3).

alter table clients
  add column if not exists local_seo_page_template_url text;
