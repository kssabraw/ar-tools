-- Token/cost capture for the Cost & Usage report, part 2 (owner request):
--   #3 instrument going forward:
--     * module_outputs.token_usage — the blog pipeline records per-request cost
--       but not tokens; add a JSONB {input_tokens, output_tokens} the orchestrator
--       now persists so blog runs report token usage (cost was already recorded).
--     * qa_reviews.token_usage + qa_reviews.cost_usd — QA recorded neither; the
--       QA agent now sums its (cheap Haiku) calls and persists both.
-- (#2 strategist estimated cost is computed on-read in the cost_events view; it
--  needs no column — see 20260904160100.)

alter table public.module_outputs
    add column if not exists token_usage jsonb;

alter table public.qa_reviews
    add column if not exists token_usage jsonb,
    add column if not exists cost_usd numeric;
