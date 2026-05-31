# Local SEO Module (#2) — Plan C (Full Port) Integration Plan

**Status:** DECISIONS LOCKED — ready for C1 · **Authored:** 2026-05-31 · **Branch:** `claude/youthful-clarke-Pzz3O`
**Decision targeted:** Appendix A **Path C — Full Port** (rebuild UI in suite style; move backend logic into FastAPI; one Supabase DB; drop edge functions + billing surface).

> This is a **plan only**. No code has been written. It supersedes the high-level Appendix A sketch with a file-by-file scope based on a full read of the source (`/local-seo-writer`) and the target suite conventions.

### Decision log (resolved 2026-05-31)

| # | Question | Resolution |
|---|---|---|
| 1 | SSE vs async-job polling (§3.3) | **C-poll** — convert generation/reoptimize to `async_jobs` + polling (reuse existing worker). No SSE. |
| 2 | v1 scope (§4, §6) | **Core only** — analyze / generate / score / reoptimize + saved pages. Defer press releases, planning, social posts, brand voice, team/settings. |
| 3 | Extend `clients` table (§5.1) | **No.** Do **not** add `detected_icp`, `brand_voice`, `existing_pages` (or `differentiators` / analysis-status) to `clients`. These business-analysis fields are added later by a different method. v1 generation runs on existing GBP data + SERP analysis only. |
| 4 | Output format (§9 Q4) | **Default:** keep HTML + JSON-LD as the deliverable; do not force into the Google-Docs/Markdown publish path. |
| 5 | Generation model (§9 Q5) | **Default:** keep source pin `claude-sonnet-4-6`. |
| 6 | Test harness (§9 Q6) | **Default:** keep existing mocked service-logic unit style; do not stand up the FastAPI `TestClient` harness as part of this port. |

---

## 0. TL;DR

Plan C moves the **ShowUP Local** NLP service (~6,600 lines of Python) into `writer/pipeline-api`, exposes it through new `writer/platform-api` routers, folds its schema into the shared `AR-Internal-Tools` Supabase DB (reconciling `business_profiles` → `clients`), rebuilds its ~15 React views in the suite's plain-inline-style frontend, and **deletes** the Deno edge functions and all billing/credits remnants.

**This is a large effort** (the source NLP service alone is ~2× the size of any single existing pipeline module). The plan is therefore **staged into phases** so we can land a working core first and defer the long tail (press releases, social posts, planning).

**Single most important architectural decision in this plan:** Local SEO is **not** a stage of the blog `orchestrate_run` pipeline. It is its own interactive workflow. We model it as a **new top-level module** with its own service endpoints, its own platform routers, and its own frontend section — sharing only the `clients` roster, auth, config, and Railway/Supabase infrastructure.

---

## 1. Why it isn't "a 6th pipeline stage"

| Blog Writer pipeline | Local SEO app |
|---|---|
| One-shot: keyword → linear 5 stages → done | Interactive: analyze → human review → generate → score → reoptimize (loop) |
| Output: Markdown article | Output: HTML page + JSON-LD schema |
| Orchestrated server-side, polled by UI | Many user-initiated actions, SSE-streamed |
| No per-step user choices | User picks: existing page vs new, ICP, reoptimize sections |
| Single deliverable per run | Many deliverables: pages, scores, social posts, press releases |

Forcing it into `orchestrate_run()` would break both models. Instead we reuse the *patterns* (module structure, `schema_version`, auth, cost tracking, inline styling) without reusing the *linear orchestrator*.

---

## 2. Target architecture (after port)

```
writer/pipeline-api/
└── modules/local_seo/                 ← NEW (ported from services/nlp/main.py)
      ├── router.py                     ← FastAPI endpoints (analyze, generate, score, …)
      ├── pipeline.py                   ← /analyze pipeline orchestration
      ├── generation.py                 ← /generate-page + /reoptimize-page (SSE)
      ├── scoring.py                    ← 8 scoring engines (7 Claude + 1 Python)
      ├── serp.py                       ← DataForSEO SERP fetch + domain blocklist
      ├── scrape.py                     ← ScrapeOwl two-pass scraper
      ├── nlp_entities.py               ← Google NLP entity analysis
      ├── keywords.py                   ← TF-IDF related keywords + quadgrams
      ├── checklist.py                  ← _build_seo_checklist + zone targets + ICP detect
      ├── prompts.py                    ← _GEN_SYSTEM_PROMPT, scoring/reopt prompts
      ├── llm.py                        ← reuse brief/llm.py get_anthropic() pattern
      └── url_filter.py                 ← ported as-is

writer/platform-api/
├── routers/local_seo.py               ← NEW: CRUD for analyses + generated pages, proxy to pipeline
├── models/local_seo.py                ← NEW: Pydantic request/response schemas
└── services/ (no new long-running worker required for v1)

frontend/src/pages/local-seo/          ← NEW section, suite inline-style
├── LocalSeoHome.tsx                    ← module landing (was DashboardView)
├── NewContent.tsx                      ← keyword/location → analyze → generate
├── GeneratedPage.tsx                   ← page display + content gaps + actions
├── PageScore.tsx                       ← scoring + reoptimize
└── SavedPages.tsx                      ← list/filter generated pages

writer/supabase/migrations/
└── 20260601HHMMSS_local_seo_*.sql      ← NEW: tables folded into shared DB
```

**Deleted entirely:** `local-seo-writer/supabase/functions/` (4 Deno edge fns), `local-seo-writer/src/` (Lovable frontend, replaced), the standalone `services/nlp` deploy config once ported. The `/local-seo-writer` directory is removed after the port lands (its docs move to `docs/modules/`).

---

## 3. Backend port — NLP service → pipeline-api module

### 3.1 What ports cleanly (low risk)
The pure-Python analysis core has **no edge-function or Supabase coupling** and lifts almost verbatim:
- DataForSEO SERP fetch + `SKIP_DOMAINS` blocklist + bold-term extraction
- ScrapeOwl two-pass (no-JS then JS-retry) scraper
- `extract_zones()` HTML parsing (BeautifulSoup)
- TF-IDF related keywords + quadgram extraction (scikit-learn, NLTK, numpy)
- Google NLP entity analysis
- The 8 scoring engines (7 Claude-scored via prompts + `_compute_serp_signal_coverage` Python-deterministic)
- `_build_seo_checklist`, zone targets, ICP detection, RDFa markup, phone linkify

**New dependencies for pipeline-api** `requirements.txt`: `scikit-learn`, `nltk`, `numpy`, `beautifulsoup4`. (Anthropic, httpx already present.)

### 3.2 What must be rewired (medium risk)
- **Auth:** Drop the dual-mode `X-API-Key` / `_verify_jwt_get_user` logic. The pipeline-api is on Railway's **private network** and is only ever called by platform-api (same as existing modules). So Local SEO endpoints become **unauthenticated internal endpoints** like `/brief`, `/sie`, etc. The user-facing auth happens once, at the platform-api router (`require_auth`).
- **LLM client:** Replace the module's own Anthropic client with the suite's `get_anthropic()` + global concurrency semaphore (`anthropic_max_concurrency`) from the `brief/llm.py` pattern, so Local SEO shares the same 429-protection.
- **Usage logging:** Drop `_log_usage_direct()` / `usage_log` writes from the service. Cost is already tracked the suite way — each endpoint returns `cost_usd`, persisted by platform-api.
- **Config:** All needed keys already exist in `pipeline-api/config.py` (`dataforseo_login/password`, `scrapeowl_api_key`, `google_nlp_api_key`, `anthropic_api_key`). **No new pipeline-api config keys required.**
- **Model pin:** Source uses `claude-sonnet-4-6`. Keep that (consistent with other modules) unless you want to revisit per CLAUDE.md "ask before model selection."

### 3.3 SSE streaming — RESOLVED: C-poll
`/generate-page` and `/reoptimize-page` stream Server-Sent Events for progress in the source. The suite has **no SSE precedent** — the blog pipeline uses async-job polling instead.

**Decision: C-poll.** Drop SSE. Generation and reoptimize become platform-api **async jobs** (reuse the existing `async_jobs` table + `job_worker`) and the frontend polls for status like the Runs view does. The pipeline-api Local SEO endpoints run synchronously (request → full result) behind the worker; the worker writes the finished page to `generated_pages` and flips job status. This honors the locked "no new queue / no new pattern" decisions and matches the existing progress-bar UX family. The source's internal progress percentages are discarded (we surface coarse job states: queued → running → complete/failed).

### 3.4 `schema_version` registration
Add Local SEO endpoints' response metadata with `schema_version: Literal["1.0"]`. Register in `orchestrator.py` **only if** we route any call through the orchestrator's validation helper; since Local SEO is not an `orchestrate_run` stage, we instead validate the version in the new platform-api router. Document the version in CLAUDE.md's module-version table.

---

## 4. Platform-API surface (new)

New `routers/local_seo.py` (registered in `main.py` alongside the other 7 routers), all `Depends(require_auth)`:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/local-seo/analyze` | Run keyword+location analysis (proxy to pipeline); upsert `keyword_analyses` cache |
| `GET`  | `/local-seo/analyses` | List/cache-check analyses for a client |
| `POST` | `/local-seo/generate` | Start page generation (async job in C-poll) |
| `GET`  | `/local-seo/pages` | List generated pages (filter by client/keyword) |
| `GET`  | `/local-seo/pages/{id}` | Page detail + content gaps + score |
| `POST` | `/local-seo/pages/{id}/score` | (Re)score an existing page |
| `POST` | `/local-seo/pages/{id}/reoptimize` | Reoptimize loop (async job in C-poll) |
| `POST` | `/local-seo/check-rankability` | Map-pack feasibility check |
| `POST` | `/local-seo/related-pages` | Related-keyword expansion suggestions |

Conventions followed: `HTTPException` + string error codes, Pydantic models in `models/local_seo.py`, `get_supabase()` service-role access, structured logging with `request_id`.

**Deferred to a later phase (not in v1 router):** brand-voice extraction, social-post generation, press-release workflow, business-website analysis (overlaps existing `website_scraper`).

---

## 5. Data model — fold into shared Supabase

### 5.1 Reconciliation: `business_profiles` → `clients` — RESOLVED: no `clients` changes
The suite already has a rich `clients` table (with GBP fields added in `20260530003510_clients_gbp.sql`). `business_profiles` overlaps heavily (GBP place_id, category, rating, reviews, hours, lat/lng). **Plan: do not create a parallel `business_profiles` table, and do not extend `clients`.**

**Decision (Q3): the `clients` schema is NOT modified in this port.** The business-analysis-derived fields (`detected_icp`, `brand_voice`, `existing_pages`, `differentiators`, analysis status) are **explicitly out of scope** here — they will be added later by a different method. v1 Local SEO generation therefore uses **only** the business context already on `clients` (GBP place_id, categories, rating, review_count, reviews, hours, lat/lng, description) plus the per-keyword competitor SERP analysis. The source's FACTUAL-ACCURACY rules already degrade gracefully when ICP/brand-voice/differentiator context is absent, so no enrichment fields are required for a working core.

This removes what was previously the highest-risk data-design step. The only schema additions are the two new satellite tables below, both keyed to `client_id`.

### 5.2 New tables (ported, de-billed)
- `keyword_analyses` — analysis cache, **rekeyed** from `business_id` → `client_id`. Unique `(client_id, keyword, location)`.
- `generated_pages` — generated HTML/JSON-LD pages, rekeyed to `client_id`.

### 5.3 Dropped tables (not ported in Plan C)
- `usage_log` — superseded by suite cost tracking on module outputs.
- `team_members` — conflicts with suite identity (Supabase Auth + `profiles.role`). Drop.
- `profiles` — suite already has its own; do not import ShowUP's.
- `press_releases`, `press_release_reports`, `notifications` — **deferred** with the press-release feature (Phase 3). Not dropped permanently, just out of v1.

### 5.4 Migration mechanics
New migrations in `writer/supabase/migrations/` using **real UTC timestamps** (per the migration-reconciliation convention adopted in PR #11). Apply to live project via Supabase MCP. Update the frontend types after.

---

## 6. Frontend port — rebuild in suite style

The source is **Tailwind + shadcn/ui** with **state-based nav** (`Index.tsx` swaps views). The suite is **plain inline styles** + **React Router** + **TanStack Query** + typed `lib/api.ts`. So this is a **rebuild, not a copy** — we keep the UX flows and rewrite the presentation.

New routes in `App.tsx` (under the existing protected `Layout`):
- `/local-seo` → `LocalSeoHome`
- `/local-seo/new` → `NewContent`
- `/local-seo/pages` → `SavedPages`
- `/local-seo/pages/:id` → `GeneratedPage`
- `/local-seo/pages/:id/score` → `PageScore`

Each page uses `useQuery`/`useMutation` against the new `/local-seo/*` endpoints via `api.ts`. A **module tile** is added to the suite dashboard (`Home.tsx`) and/or the client workspace, consistent with how the Blog Writer is surfaced.

**v1 scope:** the analyze → generate → score → reoptimize core + saved-pages list. **Deferred:** Planning, Score-My-URL standalone, Press Releases, Admin syndication, Settings/Team, Social posts.

---

## 7. Billing / credits / Stripe removal

Good news confirmed by source read: **there is no live Stripe/credits/billing code** in the imported copy — it was already an internal tool. Remaining cleanup is cosmetic:
- Remove "API costs are estimates / billing may vary" disclaimer copy from ported UI.
- Drop `usage_log` writes (done as part of §3.2).
- No `purchase-*` edge functions exist in the import to delete (they were excluded/never imported).

(Appendix A's A.5 warned about Stripe; the actual imported tree is already de-billed. Worth noting the discrepancy.)

---

## 8. Phased delivery plan

| Phase | Scope | Rough size |
|---|---|---|
| **C1 — Backend core** | Port NLP analysis + generation + scoring into `pipeline-api/modules/local_seo`; new deps; rewire auth/LLM/config; unit tests with mocked DataForSEO/ScrapeOwl/NLP/Anthropic | Large |
| **C2 — Data + platform API** | `clients` reconciliation migration; `keyword_analyses` + `generated_pages` migrations; `routers/local_seo.py` + `models/local_seo.py`; async-job wiring (C-poll) | Medium |
| **C3 — Frontend core** | Rebuild NewContent / GeneratedPage / PageScore / SavedPages in suite style; dashboard tile; API client methods + types | Medium-large |
| **C4 — Long tail (optional/deferred)** | Planning, Score-My-URL, brand voice, social posts | Medium |
| **C5 — Press releases (deferred)** | press_releases + reports + notifications tables, workflow, admin syndication | Medium |
| **Cleanup** | Delete `/local-seo-writer`; move its docs to `docs/modules/`; update CLAUDE.md (module table, schema-version row, repo layout), roadmap Appendix A status → "Path C chosen, in progress" | Small |

Recommendation: land **C1–C3** as the first reviewable milestone (a working, integrated Local SEO page generator on the shared client roster), then decide on C4/C5.

---

## 9. Open questions — ALL RESOLVED

See the **Decision log** at the top of this document. Q1→C-poll, Q2→core only, Q3→no `clients` changes, Q4→keep HTML/JSON-LD, Q5→keep `claude-sonnet-4-6`, Q6→keep mocked unit-test style. No open blockers remain for C1.

---

## 10. Risks & notes

- **Size:** the NLP service is ~6,600 lines — the largest single thing in the suite. Splitting it into the module files in §2 (rather than one mega-file) is part of the port, adding effort but paying off in maintainability.
- ~~**`clients` reconciliation** is the highest-risk design step~~ — **removed by Q3 decision.** The `clients` schema is untouched; the two new tables are additive only, lowering migration risk substantially.
- **Two test-double surfaces** (DataForSEO, ScrapeOwl, Google NLP, Anthropic) must all stay mocked in tests per CLAUDE.md.
- **No new external dependencies of the forbidden kind** (Redis/Celery/queues) — C-poll reuses the existing `async_jobs` table, honoring the locked decisions.
- **Locked-decision compliance:** single FastAPI backend ✅, one Supabase DB ✅, no edge functions ✅, inline-style frontend ✅, DataForSEO for SERP ✅ — Plan C is the path most aligned with CLAUDE.md's locked decisions.
```
