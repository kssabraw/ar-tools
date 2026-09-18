# LLM cost instrumentation — capturing the unrecorded LLM spend

**Status:** Increment 1 (foundation + AI Visibility) built 2026-09-18. Increments 2–3 pending.

## Problem

The admin Cost & Usage report (`/cost-report`, `services/cost_analytics.py` over the
`cost_events` view) is a **partial ledger**: it only sums the sources wired into the
view — per-deliverable rows that already carry cost (runs, Local SEO / Ecommerce
pages, strategist reviews, QA, keyword-research *DataForSEO* cost, domain intel,
autonomy, LeadOff). Large swaths of LLM token spend write **no cost/token data
anywhere**, so they are invisible in the report *and* the database:

- **AI Visibility brand scans** — ~360 keyword×engine scans/month, each hitting an
  engine (OpenAI/Anthropic/Gemini/Perplexity/DataForSEO) + an OpenAI classifier
  (+ an OpenAI auto-diagnose on invisible cells). The single biggest gap.
- **Keyword / Topic Research LLM layers** — intent fan-out, the topic-strategist
  tool-loop, blog topics, seed suggestions, audience ICP. Only their DataForSEO
  cost is metered; the Anthropic tokens are not.
- **Conversational agents** — SerMaStr / PACE / DORA chat turns (Sonnet + web
  search + tools). Slack turns store nothing.
- **Ancillary** — Website Builder + Brand Guide generation, brand-voice/ICP scans,
  content-gap analysis, maps / rank-analysis narratives.

Measured 2026-09: recorded Anthropic-attributable spend ≈ ⅓ of the true Anthropic
bill, consistent with the owner's >$120 August figure vs ~$40 recorded. Historical
spend can't be recovered (tokens weren't stored) — this is **forward capture**.

## Architecture

A single shared ledger, `public.llm_usage` (migration `20260918130000`), one row per
instrumented LLM/paid-API call, UNIONed into `cost_events`. Purely **additive** —
none of these sources are in the view today, so no double-counting (keyword-research's
DataForSEO cost stays in `keyword_research_runs`; the Anthropic tokens recorded here
under a distinct `source` are separate money).

- `services/llm_pricing.py` (pure) — per-1M (input, output) rates. Anthropic list
  prices from the claude-api skill; OpenAI "Luna" confirmed. Unknown models capture
  **tokens** with cost 0 + `priced=false` until a rate is set (`register_prices`).
- `services/llm_usage.py` — best-effort `record(...)` (never raises; mirrors
  `qa_cost`), an ambient `usage_context(...)` contextvar (a caller wraps an operation
  once; leaf call sites inherit source/client/actor), and SDK-usage extractors
  (`anthropic_usage` / `openai_usage` / `gemini_usage` / `openai_usage_dict`).
- `cost_analytics.py` — labels the new cost types (`ai_visibility_scan`,
  `ai_visibility_suggest`, group "AI visibility") and the new providers/models
  (gpt-5.4/-mini, Gemini, Perplexity Sonar, DataForSEO) in `model_label_for`.

nlp-api has **no** Supabase client, so nlp-side LLM calls that aren't already
captured (brand-voice/ICP, content-gap) must return usage in their response and be
recorded by platform-api. pipeline-api + platform-api both write the ledger.

## Capture-site strategy

- Scattered explicit calls (AI Visibility engines) → `record(...)` at each site,
  inheriting the ambient `usage_context` set once at the job level.
- Deep agent loops (SerMaStr/PACE/DORA) → the shared `FailoverAsyncAnthropic` client
  is used by 15 services; combined with a `usage_context` set per turn it's the clean
  capture point.
- One-shot helper calls (maps/rank narratives, KW-research report_llm calls) →
  thread usage out of `report_llm.py`'s per-provider runners (benefits every caller).

## Sequencing

1. **AI Visibility (built).** `brand_scan.py` (6 engines + classifier), `brand_insights.py`
   (diagnose + suggestions). Job-level `usage_context`. DataForSEO records its exact
   `cost` field; token-only providers record tokens.
2. **KW / Topic Research LLM layers.** report_llm usage threading + the topic-strategist
   AsyncAnthropic loop.
3. **Conversational agents** (FailoverAsyncAnthropic contextvar capture) + remaining
   ancillary (website builder, brand guide, brand-voice/ICP, content-gap, narratives).

## Open item — pricing for non-Anthropic models

Confident rates: all Anthropic tiers (skill), `gpt-5.6-luna` (Luna), DataForSEO (exact
`cost` in the response). **Needs the owner's per-1M rates** to compute dollars (tokens
are captured regardless): `gpt-5.4`, `gpt-5.4-mini` (AI-Visibility chatgpt engine +
classifier + diagnose + suggestions), `gemini-3.5-flash`, Perplexity `sonar`. Add them
via `llm_pricing.register_prices({...})` or the module tables — no migration; the report
recomputes derived dollars on the next read (stored `cost_usd` stays as first written).
