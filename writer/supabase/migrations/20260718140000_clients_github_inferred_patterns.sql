-- Inferred URL/slug conventions of a client's EXISTING site (SOP "Importing an
-- Existing Site — Precedence & Detection"). System-populated by the pattern
-- discovery job (repo Git tree + sitemap → services/slug_inference.py); NOT a
-- user field. Shape:
--   {"content_paths": {"blog_post": "src/content/news", ...},
--    "url": {"separator": "-", "trailing_slash": true, "extension": "",
--            "prefixes": {"blog_post": "news", "location_page": "service-areas"}},
--    "inferred_at": "<iso8601>", "source": "repo_tree|sitemap"}
-- Precedence (SOP "site always wins"): resolve_github_path prefers
-- content_paths here over the per-client github_content_paths override and the
-- single github_content_path default.
alter table public.clients
  add column if not exists github_inferred_patterns jsonb not null default '{}'::jsonb;
