# nlp-api — Local SEO NLP service (suite)

Python/FastAPI microservice powering the suite's **Local SEO Content** module
(roadmap module #2). Ported from the imported ShowUP Local app
(`/local-seo-writer/services/nlp`) per the Path-C plan in
`docs/modules/local-seo-module-integration-plan-v1_0.md`.

## Phase 0 changes vs. the imported original

- **Auth layer removed.** The original used `X-API-Key` (edge-function proxy) +
  Supabase-JWT-direct + usage logging. This service follows the suite's
  private-service model (same as `pipeline-api`): **no app-level auth — it runs
  on Railway's private network only**, and `platform-api` verifies the user JWT
  before calling it. Removed: `verify_api_key`, `_verify_jwt_get_user`,
  `_log_usage_direct`, the `NLP_API_KEY` / `SUPABASE_*` env reads, and the
  `X-API-Key`/`Security`/`APIKeyHeader` imports.
- **Cut endpoints** (per the v1 scope): `/analyze-business` (site-scrape ICP),
  `/analyze-brand-voice` (site-scrape brand voice), `/check-rankability`
  (keyword-worthiness advisory).
- **Analysis is opt-in.** `/generate-page` now takes a required `run_analysis`
  bool. When no cached `serp_analysis` is supplied AND `run_analysis` is false,
  generation runs with **no competitor scrape**. When true, it runs the inline
  SERP analysis as before.
- **IPv6 bind** (`--host ::`) so Railway private networking can reach it.

## Endpoints (kept)

`/analyze`, `/health`, `/find-page-for-keyword`, `/score-page`,
`/augment-page`, `/generate-page`, `/reoptimize-page`, `/reoptimize-section`,
`/related-pages`, `/generate-social-posts`, `/generate-press-release`.

> Note: page scoring + auto-reoptimization (`/score-page`, `/reoptimize-*`)
> are **kept** — they judge page quality. Only the upfront rankability /
> keyword-worthiness advisory was removed.

## Environment variables

| Var | Purpose |
|---|---|
| `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` | SERP fetch |
| `SCRAPEOWL_API_KEY` | competitor/client page scraping |
| `TEXTRAZOR_API_KEY` | entity analysis (replaced Google Cloud NLP) |
| `TEXTRAZOR_MIN_RELEVANCE` | optional — entity relevance cutoff (default `0.1`; calibrate on live keywords) |
| `TEXTRAZOR_MIN_CONFIDENCE` | optional — disambiguation-confidence floor (default `0` = off) |
| `ANTHROPIC_API_KEY` | generation + page scoring |

No `NLP_API_KEY` / `SUPABASE_*` needed (auth removed).

## Deploy

Railway service, Dockerfile builder, private networking. Matches the
`pipeline` service pattern: **no deploy-time healthcheck** (Railway's
healthcheck probe can't reach a private-only service, which fails the
deploy even when the app is healthy), `restartPolicyType = ALWAYS`. The
app logs `Application startup complete` + `Uvicorn running on [::]:8080`
on boot.
