-- Migration: 20260807180000_keyword_research_topical_relevance.sql
-- Purpose: Keyword Research — client-grounded topical research + Gemini semantic
--   relevance gate.
--
--   The module expanded seed keywords via DataForSEO Labs and cleaned the result
--   with token-based gates only. That let semantically off-topic keywords through
--   when they shared a seed word ("party" from "third party ...") and had no way to
--   tell a low-relevance keyword from a high one. This adds two things:
--
--   1. A per-keyword semantic RELEVANCE SCORE (0..1) — max cosine similarity of the
--      keyword's gemini-embedding-2 vector to a rich anchor set (the seeds + the
--      LLM-fanned-out seed intents + the client's own site topics). Off-topic
--      keywords are dropped below a floor; the score is stored on every surviving
--      keyword so the view can sort by it and nothing is silently lost.
--
--   2. The run's TOPIC RESEARCH blob — what grounded the relevance judgement and
--      broadened the expansion: the client's site topics, the fanned-out intents,
--      the anchor set, and the gate report. Stored on the run as JSONB so
--      re-opening a run is a cheap re-read (consistent with serp_intel).
--
--   topic_research shape (nullable — null when the pass was disabled/unavailable):
--     {
--       "enabled": true,
--       "site": {"source": "sitemap"|"google_index"|"none", "topics": ["...", ...]},
--       "intents": ["self-insured employers", "workers comp tpa", ...],
--       "expansion_seeds": ["tpa claims software", ...],
--       "anchors": ["third party claims administrator", ...],
--       "relevance": {"gate": "semantic"|"off"|"skipped", "floor": 0.5,
--                     "scored": 421, "dropped": 137, "kept": 284}
--     }
--
-- No RLS change: same service-role-only access as the rest of the module.

alter table keyword_research_runs
  add column if not exists topic_research jsonb;

alter table keyword_research_keywords
  add column if not exists relevance_score numeric;
