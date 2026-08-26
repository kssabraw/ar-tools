-- LeadOff GBP Placement Advisor — calibration freeze (plan §8).
--
-- Freeze the market's placement zone set into the create-client prediction
-- vector, alongside the existing `proximity` freeze, so the post-client geo-grid
-- can later grade whether the advisor's high-score zones actually corresponded
-- to better local-pack outcomes — the loop that eventually earns the dollar
-- layer (§8) and calibrates the demand/pressure weights. Read-only
-- instrumentation: nothing here feeds back into scoring or the board grade.
alter table public.leadoff_predictions
  add column if not exists placement jsonb;
