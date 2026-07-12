-- Migration: 20260712150000_demand_trend_same_month.sql
-- Purpose: the seasonal-confound fix for demand trends (scanner lesson #8):
--          a new ADDITIVE column market_scanner.demand_trend.growth_yoy_ss —
--          same-month YoY (trailing 3 months vs the same calendar months one
--          year earlier) computed from a 24-month pull.
--
-- ⚠ COORDINATED CACHE CONTRACT (app ↔ PowerShell tools): growth_yoy is NOT
-- redefined — it keeps its 12-month-window semantics (seasonal-confounded,
-- read with peak_months) so rows written by either toolchain stay mutually
-- readable. growth_yoy_ss is nullable: rows from a 12-month pull (or the
-- not-yet-updated PS tool) simply leave it null. The desktop
-- enrich_shortlist.py must gain the same date_from + growth_yoy_ss writer —
-- reference copy updated at docs/reference/leadoff-scanner/.
--
-- Note: demand_trend is scanner-owned (market_scanner_loader); this ALTER
-- runs via the admin connection (postgres holds loader membership since the
-- 2026-07-12 grants repair).

alter table market_scanner.demand_trend
  add column if not exists growth_yoy_ss double precision;
