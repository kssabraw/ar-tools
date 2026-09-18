# LLM cost instrumentation — capturing the unrecorded LLM spend

**Status:** Increments 1–5 built 2026-09-18 (foundation + AI Visibility + KW/Topic-research LLM layers + the conversational agents + the ancillary sources: maps/rank-analysis narratives, Brand Guide generation, Content Gap, Website Builder theme+core-pages + the **brand-voice / ICP scans** via an nlp-api change). Only the Website-Builder nlp page-generation usage remains (lower priority).

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
2. **KW / Topic Research LLM layers (built).** `report_llm.py`'s 12 per-provider runners
   record via `_rec` (gated by the ambient context); the KW-research + topic-research jobs
   wrap their run in a `usage_context`; the topic-strategist's direct Anthropic loop records
   each round.
3. **Conversational agents (built).** `_one_llm_call` (the SerMaStr/PACE/DORA funnel) takes
   an optional `usage_meta` and records per call (including each pause_turn continuation);
   `interpret` / `interpret_portfolio` (SerMaStr), `interpret_pace` (PACE), and `interpret_dora`
   (DORA) pass their source + client. Actor attribution for chat turns is a follow-up (the
   brain functions don't currently receive the initiating profile).
4. **Ancillary (built, platform-side).** Each wraps its generate call in a `usage_context`
   so the report_llm calls record (maps/rank narratives, Brand Guide synthesis, Website
   Builder theme `assign_roles` + `generate_core_page`); the Brand Guide **vibe** read is a
   direct Anthropic call recorded explicitly; **Content Gap** records the nlp `/score-page`
   `token_usage` it already receives. Sources: `maps_report`, `rank_analysis`, `brand_guide`,
   `content_gap`, `website_builder`.
5. **Brand-voice / ICP scans (built — the one nlp-api change).** `analyze_brand_voice_with_anthropic`
   (up to 3 Haiku calls) and `analyze_business_with_anthropic` (1 Haiku call) now sum their
   Claude usage and return it; `BrandVoiceResponse` / `BusinessAnalysisResponse` gained a
   `token_usage` field (lifted OUT of the voice/ICP blob so it's never persisted into the
   client record). platform-api `brand_voice_service` / `icp_service` record it after the nlp
   call (sources `brand_voice_scan` / `icp_scan`).
6. **Deferred (lower-priority).** Recording the nlp page-generation usage for Website Builder's
   service/location/matrix pages (it returns usage, same pattern as Content Gap).

## Open item — pricing for non-Anthropic models

Confident rates: all Anthropic tiers (skill), `gpt-5.6-luna` (Luna), DataForSEO (exact
`cost` in the response). **Needs the owner's per-1M rates** to compute dollars (tokens
are captured regardless): `gpt-5.4`, `gpt-5.4-mini` (AI-Visibility chatgpt engine +
classifier + diagnose + suggestions), `gemini-3.5-flash`, Perplexity `sonar`. Add them
via `llm_pricing.register_prices({...})` or the module tables — no migration; the report
recomputes derived dollars on the next read (stored `cost_usd` stays as first written).
