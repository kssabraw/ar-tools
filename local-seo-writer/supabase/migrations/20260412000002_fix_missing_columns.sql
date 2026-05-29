-- ── Unique constraint on generated_pages (business_id, keyword, location) ────
-- Prevents duplicate pages for the same business+keyword combo and enables
-- upsert patterns used in the frontend.
CREATE UNIQUE INDEX IF NOT EXISTS idx_generated_pages_business_keyword_location
  ON public.generated_pages (business_id, keyword, location);
