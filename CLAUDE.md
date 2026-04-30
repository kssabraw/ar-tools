# Claude Code Context

This document gives you (Claude Code) the context to continue building the Content Generation Platform after the initial setup phase. **Read this first before any other action.**

## What this project is

An internal agency tool that generates SEO + AEO-optimized blog content for multiple SMB clients. The team enters a keyword for a configured client; the platform produces a publication-ready Markdown article through a five-module pipeline.

This is **not** a customer-facing SaaS. There's no billing, no customer signup, no marketing site. Internal team use only.

## The four reference documents

Before writing code, read these in this order:

1. **`/docs/engineering-spec-v1_1.md`** — Your primary implementation reference. Covers service topology, schema, API routes, orchestration patterns, file parsing, frontend architecture, deployment sequence.
2. **`/docs/platform-prd-v1_3.md`** — Product spec. Read for overall context, business rules, role permissions, brand-vs-SIE precedence rules.
3. **`/docs/writer-module-v1_5-change-spec.md`** — Required Writer Module update. Adds `client_context` input, brand voice distillation, brand-SIE reconciliation.
4. **`/docs/modules/`** — Individual module PRDs. Read each before implementing that module.

When you encounter conflicting information across docs, the engineering spec wins for "how to build it" and the product PRD wins for "what should it do."

## Stack decisions already made — do not change without asking

| Layer | Choice | Where it's specified |
|---|---|---|
| Languages | Python 3.11+ for both APIs | Engineering spec §1 |
| Web framework | FastAPI | Engineering spec §1 |
| HTTP client | `httpx` (async) | Engineering spec §13 |
| Supabase client | `supabase-py` v2 with service role key on backend | Engineering spec §13 |
| Job queue | Supabase `async_jobs` table + asyncio worker (no Redis, no pg-boss) | Engineering spec §7 |
| Background tasks | FastAPI `BackgroundTasks` (no Celery) | Engineering spec §6 |
| Frontend | Lovable (React + Vite); managed in a separate Lovable project | Engineering spec §10 |
| State management | TanStack Query (no Redux/Zustand) | Engineering spec §10.5 |
| LLM provider | **Anthropic Claude** for module content generation | User decision |
| Embeddings | OpenAI `text-embedding-3-small` for SIE only | User decision |
| Hosting | Railway with two services + private networking | Engineering spec §2 |

## What's already done before you start

- Supabase project created
- Database schema applied via migrations in `/supabase/migrations/`
- Storage buckets `files` (active) and `article-assets` (placeholder for v2) created
- First admin user exists in `auth.users` with `role = 'admin'` in `profiles`
- GitHub repo created and cloned
- Railway project created with two empty services configured (`platform-api`, `pipeline-api`)
- Environment variables set in both Railway services
- Reference docs in `/docs/`

You should NOT need to do dashboard-level setup. If you do, stop and ask.

## What you build

Order of build:

1. **Pipeline API skeleton + Brief Generator endpoint** — start here. No upstream dependencies. Test with Postman against Railway after deploy.
2. **Pipeline API: SIE module** — second-easiest. Has 7-day cache logic.
3. **Pipeline API: Research & Citations module** — depends on Brief output structure.
4. **Pipeline API: Content Writer module v1.5** — most complex. Implements brand voice distillation, brand-SIE reconciliation, regex-based banned-term enforcement. Read `/docs/writer-module-v1_5-change-spec.md` thoroughly before starting.
5. **Pipeline API: Sources Cited module** — small, runs after Writer.
6. **Platform API: skeleton + auth middleware** — JWT verification using Supabase JWT secret.
7. **Platform API: clients CRUD + file upload + parsing** — admin-gated routes.
8. **Platform API: website scraper async worker** — polls `async_jobs` table, calls ScrapeOwl + Anthropic for extraction.
9. **Platform API: orchestrator + run dispatch** — the heart of the system. `asyncio.gather` for Brief+SIE parallel; sequential for the rest.
10. **Platform API: polling endpoint + run management** — supports the frontend's run status display.
11. **End-to-end test from Postman** — see Engineering Spec §12 Phase 4. Do this before touching the frontend.
12. **Lovable frontend** — built in a separate Lovable project, connects to platform-api public URL.

## Conventions to follow

### Code structure

```
platform-api/
├── main.py                    ← FastAPI app, route registration, startup
├── config.py                  ← env var loading via pydantic-settings
├── routers/                   ← one file per resource (clients.py, runs.py, etc.)
├── services/                  ← business logic (orchestrator.py, file_parser.py, etc.)
├── models/                    ← Pydantic request/response schemas
├── middleware/auth.py         ← JWT verification dependency
├── db/supabase_client.py      ← supabase-py setup
└── tests/                     ← pytest tests
```

Mirror this structure in `pipeline-api/`.

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

- All Supabase calls from the backend use the **service role key** (not anon key)
- Never use the anon key on the backend — RLS would block service operations
- Always wrap Supabase calls in try/except; map errors to user-friendly responses

### Module schema versions

- The orchestrator validates `schema_version` from every pipeline API response against `EXPECTED_MODULE_VERSIONS` (Engineering Spec §6.5)
- When you implement each module, return the correct `schema_version` in its output:
  - Brief Generator: `"1.7"`
  - SIE: `"1.0"`
  - Research & Citations: `"1.1"`
  - Writer: `"1.5"` (or `"1.5-no-context"` / `"1.5-degraded"` per fallback rules)
  - Sources Cited: `"1.1"`

### Testing

- Write at least one happy-path test per module endpoint
- Mock external API calls (DataForSEO, ScrapeOwl, Anthropic, OpenAI, Google NLP) — never hit them in tests
- For the Writer's brand-SIE reconciliation logic, build the seven test fixtures from Writer v1.5 spec §9.2

## Things to ask before doing

These decisions are not in the docs — ask the user:

1. Specific Anthropic model selection per module (Sonnet vs Opus per task)
2. Specific prompt copy for distillation, reconciliation, website extraction (the docs describe behavior, not exact prompts)
3. Whether to include observability tooling beyond stdlib logging (Sentry, Better Stack, etc.) — currently planned for v2
4. Whether to add automated tests in CI on push, or rely on manual testing for v1
5. Branch protection rules and PR requirements
6. Specific Lovable component library / design system

## Things NOT to do without asking

- Don't change the service topology (e.g., split modules into separate Railway services)
- Don't add a queueing system beyond the `async_jobs` table
- Don't introduce new external dependencies (Redis, Celery, RabbitMQ, etc.)
- Don't add a caching layer in front of Supabase
- Don't change the brand-vs-SIE precedence rules
- Don't expose the pipeline-api publicly — it must remain on Railway's private network
- Don't implement features marked "out of scope for v1" in the PRDs

## When you're stuck

If something seems underspecified or contradictory, stop and ask. The user has been deeply involved in spec design and prefers a quick clarifying question over a wrong assumption that's expensive to undo.

## How to communicate progress

After completing each numbered build step above, summarize what you did, what you tested, and any open questions. Don't wait until the entire system is built to report status.
