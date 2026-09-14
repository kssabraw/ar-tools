-- Coverage Audit: optional operator-supplied sitemap URL for the site scan.
-- When set, discovery crawls this sitemap (or sitemap-index) verbatim instead of
-- guessing robots.txt + conventional paths — fixes sites whose sitemap lives at a
-- non-standard path and lets a VA point straight at a large site's index. Persisted
-- on the run so an edit-service-axis re-run reuses it. Nullable; no default.
ALTER TABLE public.coverage_audits
    ADD COLUMN IF NOT EXISTS sitemap_url text;
