# Claude Code Context

This document gives you (Claude Code) the context to keep building **AR Tools**, an internal agency suite. **Read this first before any other action.**

> **Suite context (read alongside this file).** AR Tools is a **multi-module suite** — Blog Writer, Local SEO content, Keyword research, Organic + Maps rank trackers, a Ranking-drop agent, and a VA content scheduler — sharing one dashboard, one Supabase database, and one scheduler. For suite-level scope, the locked architectural decisions, and the phased roadmap, see **`docs/suite-architecture-and-roadmap-v1_0.md`** (this is the product/architecture authority for "how many tools is this"). The Blog Writer's engineering spec and module PRDs remain authoritative for that module's *internals*.

## What this project is

An internal agency suite for SEO/content work across multiple SMB clients. The team picks a client, then works across SEO modules from one dashboard. The first and most-built module is the **Blog Writer**, which generates SEO + AEO-optimized content through a five-module pipeline: enter a keyword for a configured client and the platform produces a publication-ready Markdown article (and can publish it as a Google Doc in the client's Drive folder).

This is **not** a customer-facing SaaS. There's no billing, no customer signup, no marketing site. Internal team use only.

## Current state (what's built vs. what's ahead)

Most of the original Blog Writer build is **done**. Don't treat this repo as greenfield — read the code before assuming something is unbuilt.

**Built and working:**

- **Pipeline API** (`writer/pipeline-api/`) — all five modules: `brief`, `sie`, `research`, `writer`, `sources_cited`.
- **Platform API** (`writer/platform-api/`) — JWT auth middleware; clients CRUD; file upload + parsing; website scraper async worker (`services/job_worker.py` + `services/website_scraper.py` polling `async_jobs`); orchestrator + run dispatch (`services/orchestrator.py`); run polling; briefs; silos (`services/silo_dedup.py`, `services/silo_promotion.py`); publish to Google Drive (`routers/publish.py` via Apps Script webhook); users; **Local SEO** backend (`routers/local_seo.py` + `services/local_seo_service.py`, calling the private `nlp-api`).
- **NLP API** (`writer/nlp-api/`) — private Railway service powering the Local SEO module: competitor SERP analysis (DataForSEO → ScrapeOwl → **TextRazor** entities — replaced Google Cloud NLP for cost + Wikipedia/Wikidata linking) and Claude page generation + 8-engine page scoring/auto-reoptimization. Ported from the imported ShowUP Local app; auth-less (private network only, like pipeline-api). See its `README.md` for what was stripped.
- **Suite features added since the original spec:** Google Business Profile (GBP) auto-fetch + review enrichment via DataForSEO/Outscraper (`services/gbp_service.py`), incl. paste-a-link/share-link resolution (`/clients/gbp/resolve`) and auto-fill of client name/website from a selected GBP; content silos (semantic dedup / auto-promotion); client workspace with content + rank-tracker sections; suite dashboard with per-client tiles, including **logo branding** (`clients.logo_url`, public `client-logos` storage bucket).
- **Organic Rank Tracker** (#4) — hybrid GSC + DataForSEO rank tracker on each client workspace. **Built (all milestones except alerting):** GSC service-account connection + verify-access (`services/gsc_service.py`, `routers/gsc.py`); daily GSC ingest → `gsc_query_daily` + weekly query×page → `gsc_query_page_daily`, with `sync_runs` observability (`services/gsc_ingest.py`); the **shared scheduler** — an in-process asyncio loop enqueuing jobs into `async_jobs` (`services/gsc_scheduler.py`); the materialized null date-axis `rank_keyword_metrics` + computed status taxonomy (`services/rank_materialize.py`, `services/rank_status.py`); the **automatic GSC→DataForSEO fallback** (client-anchored keywords; DataForSEO weekly live rank when GSC can't cover a keyword — `services/dataforseo_rank.py`); keyword market data CPC/volume/competition + est. value (`services/keyword_market.py`); canonical-URL resolution + Pages view; striking-distance discovery; deindex **URL Inspection** confirmation; historical backfill; per-keyword page breakdown; canonical pinning; CSV export. API in `routers/rank.py`. **Remaining: alerting** (gated on the notifications service). Authoritative doc: **`docs/modules/organic-rank-tracker-prd-v1_0.md`**.
- **Frontend** (`frontend/`) — shared React + Vite app: `Login`, `Home` (suite dashboard tiles), `Clients`, `ClientForm`, `ClientWorkspace`, `Runs`, `RunDetail`, `Silos`, `Articles`, `Rankings` (rank tracker — `components/rankings/`, dependency-free SVG charts).

**In active integration (not finished):**

- **Local SEO content** module (#2). **Phases 0–1 done:** the NLP service is rehomed into the suite (`writer/nlp-api/`, deployed private on Railway) and platform-api has the backend (`local_seo_pages` table, generate/list/get routes). **Phase 2 (frontend) and Phase 3 (page-template field) remain.** The raw import still lives at `/local-seo-writer` as the reference copy. Scope/decisions and phasing are in **`docs/modules/local-seo-module-integration-plan-v1_0.md`** (chosen path: C — full port; cut from v1: client-site brand-voice/ICP scraping, the keyword-worthiness "rankability" check, and billing; competitor SERP analysis **always runs first** — originally a per-page opt-in via a `run_analysis` flag, but that opt-out was removed; the flag now defaults to True in nlp-api, and platform-api only sets it False as a degraded fallback when its own analysis attempt fails).

**Not yet built (suite roadmap, in rough order):** Keyword research (migrate from existing repo), Ranking-drop agent, VA content scheduler, the **SOP store**, and the **notifications service**. (Maps / local-pack geo-grid ranker #5 is **built** — Local Dominator, `services/local_dominator.py` + `services/maps_grid.py` + `routers/maps.py` + `pages/MapsGeogrid.tsx`; pending a live smoke-test.) The roadmap doc has the full module table, groupings, and locked decisions. (Organic Rank Tracker #4 is built except alerting — see above; the **shared scheduler** is decided + built as the asyncio loop in `services/gsc_scheduler.py`; the **GSC analytics layer** is realized by the rank tracker's GSC ingest. Local SEO content #2 is mid-integration — see above.)

## The reference documents

Before writing code, read the ones relevant to your task. Note the exact filenames — several differ from older references.

1. **`docs/suite-architecture-and-roadmap-v1_0.md`** — Suite-level scope, the locked decision log (rank sources, GSC service-account auth, publish destination, etc.), shared infrastructure, and the proposed data model for unbuilt modules. The product/architecture authority for the suite.
2. **`docs/engineering-implementation-spec-v1_1.md`** — Primary implementation reference for the Blog Writer. Service topology, schema, API routes, orchestration patterns, file parsing, frontend architecture, deployment sequence.
3. **`docs/content-platform-prd-v1_4.md`** — Current product spec (supersedes `content-platform-prd-v1_3.md`, which is retained). Overall context, business rules, role permissions, brand-vs-SIE precedence rules.
4. **`docs/content-quality-prd-v1_0.md`** — Cross-cutting content quality requirements (R1–R7): semantic heading dedup, SERP sanitization, topic adherence, required structural elements (Key Takeaways / APP intro / CTA), brand context injection, paragraph length cap, external citation coverage.
5. **`docs/writer-module-v1_5-change-spec_2.md`** — Writer Module v1.5 update. Adds `client_context` input, brand voice distillation, brand-SIE reconciliation. Authoritative for those features.
6. **`docs/modules/`** — Individual module PRDs:
   - `content-brief-generator-prd-v2_0.md` (Brief Generator — now v2.0)
   - `SIE_PRD_Term_Entity_Module.md`
   - `research-citations-module-prd-v1_1_1.md`
   - `content-writer-module-prd-v1.3.md` (check the header for its canonical version)
   - `sources-cited-module-prd-v1_1.md`
   - `local-seo-module-integration-plan-v1_0.md` (Local SEO module #2 — scope, cut list, and Path-C phasing; authoritative for that integration)
   - `organic-rank-tracker-prd-v1_0.md` (Organic Rank Tracker #4 — hybrid GSC + DataForSEO, the auto-fallback, data model, and milestone status; authoritative for that module)

When docs conflict: the engineering spec wins for "how to build it," the product PRD wins for "what should it do," and the **content quality PRD overrides the module PRDs on R1–R7 acceptance criteria**. Where the suite roadmap and the older single-tool framing disagree on "how many tools is this," the roadmap wins.

## Stack decisions already made — do not change without asking

| Layer | Choice | Where it's specified |
|---|---|---|
| Languages | Python 3.11+ for both APIs | Engineering spec §1 |
| Web framework | FastAPI | Engineering spec §1 |
| HTTP client | `httpx` (async) | Engineering spec §13 |
| Supabase client | `supabase-py` v2 with service role key on backend | Engineering spec §13 |
| Job queue | Supabase `async_jobs` table + asyncio worker (no Redis, no pg-boss) | Engineering spec §7 |
| Background tasks | FastAPI `BackgroundTasks` (no Celery) | Engineering spec §6 |
| Frontend | React + Vite, in this repo at `/frontend`, deployed to **Netlify** (see `netlify.toml`) | `/frontend`, `netlify.toml` |
| State management | TanStack Query (no Redux/Zustand) | Engineering spec §10.5 |
| LLM provider | **Anthropic Claude** for module content generation | User decision |
| Embeddings | OpenAI `text-embedding-3-small` for SIE only | User decision |
| Rank / SERP data | **DataForSEO** for organic SERP; **Local Dominator** for Maps/local-pack **geo-grid** (Module #5 — supersedes DataForSEO geo-grid, user decision 2026-06-23); **Outscraper** for GBP search/details; DataForSEO for GBP review enrichment | Suite roadmap decision log |
| GSC analytics | Google Search Console via **service account** (no interactive OAuth) | Suite roadmap decision log |
| Publish destination | Google Doc in client's Drive folder via Apps Script webhook (CMS-ready later) | Suite roadmap decision log |
| Hosting | Railway with **three** services + private networking (`PLATFORM`, `pipeline`, `nlp`) | Engineering spec §2 |

## Infrastructure already provisioned

- Supabase project (`AR-Internal-Tools`, ref `wvcthtmmcmhkybcesirb`) with schema applied via migrations in `writer/supabase/migrations/`.
- Storage buckets: `files` (active), `article-assets` (v2 placeholder), `csv-snapshots`, `wordpress_images` (public), `client-logos` (public — client tile/workspace logos).
- First admin user in `auth.users` with `role = 'admin'` in `profiles`.
- GitHub repo cloned. Railway project (`ar-tools`) with **three** services and env vars set: `PLATFORM` (platform-api), `pipeline` (pipeline-api), and `nlp` (nlp-api, private-only — no public domain; reachable at `http://nlp.railway.internal:8080`). Note: the `nlp` service has **no deploy-time healthcheck** (a private service can't pass Railway's probe — see `writer/nlp-api/README.md`); `healthcheckPath` must stay empty.

- **Rank tracker env vars:** DataForSEO creds (`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`) are already set on `PLATFORM` (shared with GBP enrichment), so the DataForSEO rank + market paths work today. The GSC path needs `GOOGLE_SERVICE_ACCOUNT_KEY` (the full service-account key JSON) on `PLATFORM` — **not yet provisioned**; until it's set, the rank tracker runs in DataForSEO-only mode and GSC verify/ingest show a "not configured" state. Provisioning it requires creating a GCP service account + enabling the Search Console API (a dashboard step — stop and confirm with the user).

You should NOT need dashboard-level setup. If you think you do, stop and ask.

## Repository layout

```
/                            ← suite root
├── writer/                  ← backend services
│   ├── platform-api/        ← public-facing API (auth, clients, runs, publish, local-seo, …)
│   ├── pipeline-api/        ← private API (the five Blog Writer generation modules)
│   ├── nlp-api/             ← private API (Local SEO analysis + page generation/scoring)
│   └── supabase/migrations/ ← all suite migrations live here
├── frontend/                ← shared React + Vite app (Netlify) for the whole suite
├── local-seo-writer/        ← imported Local SEO app (raw reference copy; being ported into nlp-api)
└── docs/                    ← PRDs, specs, suite roadmap, module PRDs
```

### Backend code structure (per API)

```
writer/platform-api/
├── main.py                    ← FastAPI app, route registration, startup
├── config.py                  ← env var loading via pydantic-settings
├── routers/                   ← one file per resource
│     (clients, runs, briefs, silos, files, publish, users,
│      local_seo, gsc, rank)
├── services/                  ← business logic
│     (orchestrator, file_parser, job_worker, website_scraper,
│      gbp_service, silo_dedup, silo_promotion,
│      gsc_service, gsc_ingest, gsc_scheduler, rank_status,
│      rank_materialize, dataforseo_rank, keyword_market)
├── models/                    ← Pydantic request/response schemas
├── middleware/auth.py         ← JWT verification dependency (require_auth / require_admin)
├── db/supabase_client.py      ← supabase-py setup (service role key)
└── tests/                     ← pytest tests (service-logic units, mocked)

writer/pipeline-api/
└── modules/                   ← brief, sie, research, writer, sources_cited
```

## Conventions to follow

### Naming

- Modules and files: `snake_case.py`
- Classes: `PascalCase`
- Functions and variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Pydantic models: `PascalCase` ending in purpose (e.g., `ClientCreateRequest`, `RunDetailResponse`)

### Error handling

- Always raise `HTTPException` with a string error code in the detail (matches the standardized error envelope from Engineering Spec §5.0)
- Never expose stack traces to the frontend — log them server-side, return `internal_error` code
- Use `try/except` around external API calls; map provider errors to platform errors

### Logging

- Use `structlog` (or stdlib `logging` with JSON formatter) for structured JSON logs to stdout
- Always include `run_id` and `request_id` in log lines via context vars (Engineering Spec §13)
- Never log: JWTs, full brand guide text, API keys, user passwords

### Database access

- All Supabase calls from the backend use the **service role key** (not anon key) — RLS would block service operations
- Always wrap Supabase calls in try/except; map errors to user-friendly responses
- Schema changes go through migrations in `writer/supabase/migrations/` (apply to the live project via the Supabase MCP when working web-only)

### Module schema versions

The orchestrator validates `schema_version` from every pipeline response against `EXPECTED_MODULE_VERSIONS` (`writer/platform-api/services/orchestrator.py`). When you change a module, keep these in sync. Current values:

| Module | `schema_version` |
|---|---|
| Brief Generator | `2.7` |
| SIE | `1.4` |
| Research & Citations | `1.1` |
| Writer | `1.8` (also accepts `1.8-no-context` / `1.8-degraded`) |
| Sources Cited | `1.1` |

> These drift over time — treat `orchestrator.py` (`EXPECTED_MODULE_VERSIONS` / `WRITER_ACCEPTED_VERSIONS`) and each module's `SCHEMA_VERSION` constant as the source of truth, and update this table when you change them.

### Testing

- Write at least one happy-path test per module's core logic
- Mock external API calls (DataForSEO, ScrapeOwl, Anthropic, OpenAI, Google NLP) — never hit them in tests
- Existing tests are pure service-logic units mocked with `unittest.mock` (see `writer/platform-api/tests/`); there is no FastAPI `TestClient` harness yet
- For the Writer's brand-SIE reconciliation logic, build the test fixtures from the Writer v1.5 spec

## Things to ask before doing

These decisions are not in the docs — ask the user:

1. Specific Anthropic model selection per module (Sonnet vs Opus per task), where not already chosen in code
2. Specific prompt copy for distillation, reconciliation, website/GBP extraction (the docs describe behavior, not exact prompts)
3. Observability tooling beyond stdlib logging (Sentry, Better Stack, etc.) — planned for v2
4. Whether to add automated tests in CI on push, or rely on manual testing
5. Branch protection rules and PR requirements
6. Alerting/notifications delivery channels (in-app feed vs email/Slack + the provider/webhook details) before building the notifications service / rank-tracker alerting

> **Resolved:** the **shared scheduler** mechanism is decided — an in-process asyncio loop in platform-api (`services/gsc_scheduler.py`) that enqueues jobs into `async_jobs`; reuse it for future scheduled trackers rather than adding new infra.

## Things NOT to do without asking

- Don't change the service topology (e.g., split modules into separate Railway services)
- Don't add a queueing system beyond the `async_jobs` table
- Don't introduce new external dependencies (Redis, Celery, RabbitMQ, etc.)
- Don't add a caching layer in front of Supabase
- Don't change the brand-vs-SIE precedence rules
- Don't reverse a locked decision in the suite roadmap's decision log
- Don't expose the pipeline-api or nlp-api publicly — they must remain on Railway's private network (the `nlp` service is intentionally private + auth-less)
- Don't implement features marked "out of scope for v1" in the PRDs (e.g., live-to-CMS publishing)
- Don't re-add the Local SEO features cut from v1 (client-site brand-voice/ICP scraping, the keyword-worthiness "rankability" check, billing/credits) without agreement — see the integration plan
- Don't edit `/local-seo-writer` expecting it to ship — it's the raw reference copy; active Local SEO work goes in `writer/nlp-api/` plus the suite frontend/backend

## When you're stuck

If something seems underspecified or contradictory, stop and ask. The user has been deeply involved in spec design and prefers a quick clarifying question over a wrong assumption that's expensive to undo.

## How to communicate progress

After completing a meaningful chunk of work, summarize what you did, what you tested, and any open questions. Don't wait until everything is built to report status.
