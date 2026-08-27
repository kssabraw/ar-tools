-- =============================================================================
-- Confidence scores for the additional-research name sources.
--
-- The site-scrape (source='site_scrape') and web-search (source='web_search')
-- fallbacks find owner/manager names that are lower-trust than an Outscraper
-- pull, so each such contact now carries a 0-100 `confidence` + a
-- High/Medium/Low `confidence_band` on ONE shared scale, computed deterministically
-- (site scrape) or blended deterministic + model self-rating (web search) — see
-- api/services/name_confidence.py.
--
-- Nullable: Outscraper contacts leave them NULL (their trust is a different
-- thing — a validated email, not a researched name). The band is stored beside
-- the raw score so the UI need not re-derive the thresholds.
-- =============================================================================

alter table prospect_contact
  add column if not exists confidence integer
    check (confidence is null or (confidence >= 0 and confidence <= 100)),
  add column if not exists confidence_band text
    check (confidence_band is null or confidence_band in ('high', 'medium', 'low'));
