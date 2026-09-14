-- Coverage Audit: the radius (miles) the location axis is hard-bounded to, around
-- the business center (GBP coords, else the geocoded business address). 5 or 10;
-- NULL on rows that predate the feature (treated as unbounded on read).
ALTER TABLE public.coverage_audits
  ADD COLUMN IF NOT EXISTS radius_miles smallint;
