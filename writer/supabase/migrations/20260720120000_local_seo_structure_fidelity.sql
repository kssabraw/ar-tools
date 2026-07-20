-- Migration: 20260720120000_local_seo_structure_fidelity.sql
-- Purpose: Persist the structural-fidelity verdict from the Local SEO generation
--          gate so layout adherence becomes a tracked metric (not just a log line).
--          The gate (services/local_seo_service._apply_structure_gate) scores each
--          generated page against the client's stored reference outline with the
--          deterministic page_structure_eval and attaches the verdict
--          ({composite, dimensions, notes}) to the result; this stores it.
--
--          Mirrors the engine_scores pattern (20260704120000):
--            1. local_seo_pages.structure_fidelity   — current verdict for the saved page.
--            2. local_seo_page_scores.structure_fidelity — per-run history.
--          Null on pages generated without a reference structure (gate didn't run)
--          and on reoptimize/standalone-score rows (no structural gate there yet).
--          Additive, nullable. RLS unchanged (service-role only).

alter table local_seo_pages
  add column if not exists structure_fidelity jsonb;

alter table local_seo_page_scores
  add column if not exists structure_fidelity jsonb;
