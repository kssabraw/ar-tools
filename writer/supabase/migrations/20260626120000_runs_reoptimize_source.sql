-- ============================================================
-- runs: add reoptimize_source_url
-- ============================================================
-- When the service-page planner finds a page already published on the client's
-- live site that ISN'T ranking in the top N for its keyword, the team can ask the
-- platform to reoptimize it. That spawns a normal service_page run, but tagged with
-- the live page's URL: the orchestrator scrapes + scores that page first and feeds
-- the deficiencies into the writer's first pass, so the generated page specifically
-- fixes where the live one falls short. Null for every other run. Additive.
-- ============================================================

alter table runs add column if not exists reoptimize_source_url text;
