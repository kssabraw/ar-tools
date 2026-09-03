-- Token / Claude-spend profiler (read-only) for the AR Tools suite.
--
-- Rolls up the ALREADY-METERED per-generation cost the app persists, so you can
-- size where Claude spend goes and measure a cost lever before/after — with zero
-- API spend. Run in the Supabase SQL editor (project AR-Internal-Tools) or via
-- psql. Change the '30 days' windows to taste.
--
-- COVERAGE / BLIND SPOTS (read before trusting the totals):
--   * local_seo_pages / ecommerce_pages.cost_breakdown  → COMPLETE per-page Claude
--     $ (accumulated across every generate/score/trim/fix/voice pass) + DataForSEO.
--   * module_outputs.cost_usd                           → service_writer/score/brief
--     are metered; the BLOG modules (brief/sie/research/writer/sources_cited)
--     currently record $0 — blog-pipeline Claude spend is NOT captured here.
--   * strategy_reviews.token_usage                      → strategist (priced below
--     at Sonnet 4.6 $3/$15; adjust if strategist_model changes).
--   * fanout.sessions.cost_breakdown                    → article_planning (Opus)
--     + article_generation (Sonnet) are Claude; expand/silo/rank checks are
--     DataForSEO/OpenAI.
--   * NOT persisted anywhere (invisible to this script): report_llm one-shots,
--     the interactive agents (Slack/PACE/QA/DORA), brand scans, GBP posts, QA
--     reviews. For the authoritative org total use the Anthropic Console → Usage,
--     or the Usage & Cost Admin API grouped by model/api_key.

-- 1) nlp page generation — real per-page Claude $ (output-heavy) + DataForSEO.
with pages as (
  select 'local_seo_pages' w, created_at, cost_breakdown from local_seo_pages where cost_breakdown is not null
  union all
  select 'ecommerce_pages' w, created_at, cost_breakdown from ecommerce_pages where cost_breakdown is not null
)
select w as workload,
       (created_at >= now() - interval '30 days') as last_30d,
       count(*) as pages,
       round(sum(nullif(cost_breakdown->>'claude','')::numeric),2)  as claude_usd,
       round(sum(nullif(cost_breakdown->>'total','')::numeric),2)   as total_usd,
       round(avg(nullif(cost_breakdown->>'claude','')::numeric),4)  as avg_claude_per_page,
       sum(nullif(cost_breakdown->>'claude_input_tokens','')::numeric)::bigint  as in_tok,
       sum(nullif(cost_breakdown->>'claude_output_tokens','')::numeric)::bigint as out_tok
from pages group by w, last_30d order by w, last_30d desc;

-- 2) Blog/service pipeline — per-module cost (blog modules currently read $0).
select module,
       count(*) n,
       round(sum(coalesce(cost_usd,0))::numeric,2) usd
from module_outputs
where created_at >= now() - interval '30 days'
group by module order by usd desc nulls last;

-- 3) Strategist — from token_usage jsonb, priced at Sonnet 4.6 ($3 in / $15 out).
select (created_at >= now() - interval '30 days') as last_30d,
       count(*) n,
       sum(nullif(token_usage->>'input_tokens','')::numeric)::bigint  in_tok,
       sum(nullif(token_usage->>'output_tokens','')::numeric)::bigint out_tok,
       round(sum(nullif(token_usage->>'input_tokens','')::numeric)*3/1e6
           + sum(nullif(token_usage->>'output_tokens','')::numeric)*15/1e6, 2) as est_usd
from strategy_reviews where token_usage is not null
group by last_30d order by last_30d desc;

-- 4) Fanout — Claude phases (article_planning=Opus, article_generation=Sonnet)
--    vs non-Claude (expand/silo_discovery/rank checks = DataForSEO/OpenAI).
select
  round(sum(nullif(cost_breakdown->>'article_planning','')::numeric),2)   as claude_planning_opus,
  round(sum(nullif(cost_breakdown->>'article_generation','')::numeric),2) as claude_generation_sonnet,
  round(sum(nullif(cost_breakdown->>'expand','')::numeric),2)             as nonclaude_expand,
  round(sum(nullif(cost_breakdown->>'silo_discovery','')::numeric),2)     as nonclaude_silo,
  round(sum(coalesce(actual_cost_usd,0))::numeric,2)                      as session_total
from fanout.sessions where created_at >= now() - interval '30 days';
