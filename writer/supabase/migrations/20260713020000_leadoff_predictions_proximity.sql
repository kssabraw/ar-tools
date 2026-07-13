-- Proximity plan §3: capture the Distance-pillar read into the frozen
-- calibration prediction so the geo-grid can later grade whether
-- proximity_opportunity predicted the outcome (the loop that tunes the
-- score-enrichment weights).
alter table public.leadoff_predictions add column if not exists proximity jsonb;
