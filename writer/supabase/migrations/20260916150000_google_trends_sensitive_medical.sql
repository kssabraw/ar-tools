-- Migration: 20260916150000_google_trends_sensitive_medical.sql
-- Purpose: flag medical-question / health-safety rising queries (owner ruling
--   2026-09-15 — "keep the medical question ones and just flag them").
--
--   The social classifier routes an informational-medical query (side effects,
--   dosage, symptoms, safety) to the SEO lane, NOT the social lane — correct, but
--   such a query is still a real (careful, authoritative) content opportunity. So
--   rather than let it disappear into the SEO lane unmarked, tag it `sensitive_medical`
--   (deterministic health-safety-intent wordlist, client-agnostic) so a reviewer
--   sees it flagged wherever the row shows. FLAG ONLY — lane routing is unchanged
--   (medical stays SEO); the badge is advisory (warn, not block).
--
-- Additive + nullable (old rows read as NULL/false → unflagged). Gated by
-- google_trends_social_flag_sensitive (default True).

alter table google_trends_keywords add column if not exists sensitive_medical boolean;
