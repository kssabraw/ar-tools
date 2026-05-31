# AR Tools — Handoff

**Branch:** `claude/youthful-clarke-Pzz3O`
**Date:** 2026-05-31
**Scope of this handoff:** the in-progress **Local SEO (#2) full-port (Plan C)** on this branch, what's landed vs. still pending, the current state of the suite, and prioritized next steps.

> Read `CLAUDE.md` first for project conventions and the authoritative current-state summary, and `docs/suite-architecture-and-roadmap-v1_0.md` for suite scope, the locked decision log, and the phased plan. The detailed port plan is `docs/local-seo-integration-plan-PlanC-v1.md`; the live C1 checklist is `docs/local-seo-port-C1-progress.md`. This file ties them together.

> **Branch lineage note:** the previous handoff covered `claude/gracious-bell-BbkY5` (logo upload, RLS fix, CLAUDE.md refresh). **All of that is merged** — PR #10 (gracious-bell) and PR #11 (migration reconciliation) are in the history this branch builds on. This handoff supersedes it.

---

## 1. What this branch contains

Five commits ahead of `origin/main`, oldest → newest:

| Commit | Type | Summary |
|---|---|---|
| `610b333` | docs | **Plan C integration plan (draft)** — `docs/local-seo-integration-plan-PlanC-v1.md`. File-by-file scope for the Local SEO full port, derived from a full read of `/local-seo-writer` + suite conventions. |
| `f05a3a7` | docs | **Plan C decisions locked** — C-poll (no SSE), core-only scope, **no `clients` schema change**. (See §2.) |
| `30e5e1a` | feat(local-seo) | **Vendored NLP engine baseline** + the C1 seam-edit checklist. Raw copy of the source service as the diff baseline. |
| `ff1e4a5` | feat(local-seo) | **C1 engine port** — suite-ified the NLP service (drop FastAPI/CORS/slowapi, config repoint, auth/usage no-ops, C-poll conversion) + new `router.py`. |
| `2c1b597` | fix(local-seo) | **Define `_drain_to_result`** — the C-poll drainer that replaces SSE streaming in the two long-running handlers. |

All pushed to `origin/claude/youthful-clarke-Pzz3O`. **No PR opened** (none requested).

---

## 2. Locked decisions for the Local SEO port (Plan C — Full Port)

Recorded in `docs/local-seo-integration-plan-PlanC-v1.md`:

1. **Path C — Full port.** Move the NLP service into `pipeline-api` as a module; rebuild UI in suite style; one Supabase DB; drop the Deno edge functions. Most aligned with CLAUDE.md's locked decisions.
2. **C-poll, not SSE.** The source streams progress via Server-Sent Events; the suite has no SSE precedent. Generation/reoptimize become async-job + poll (reuse `async_jobs`/`job_worker`). Handlers return plain dicts.
3. **Core scope only.** Ship analyze / generate / score / reoptimize + saved pages. Defer press releases, planning, social posts, brand voice, business analysis, team/settings.
4. **No `clients` schema change.** Do **not** add `detected_icp` / `brand_voice` / `existing_pages` / `differentiators` to `clients` — those land later by a different method. v1 generation runs on existing GBP data + per-keyword SERP analysis only. (This removed the highest-risk data-design step.)
5. **Defaults:** keep HTML + JSON-LD output (not forced through the Google-Docs path); keep `claude-sonnet-4-6`; keep the existing mocked unit-test style (no `TestClient` harness as part of this port).

**No billing to remove** — the imported tree was already de-billed (only cosmetic disclaimer copy remains). Appendix A's Stripe warning doesn't match the actual import.

---

## 3. Local SEO C1 (backend core) — status: ENGINE PORTED, UNWIRED, UNVERIFIED

New module at `writer/pipeline-api/modules/local_seo/`:

- **`_service.py`** (ported from `local-seo-writer/services/nlp/main.py`, ~6.4k lines):
  - Dropped `FastAPI`/CORS/`slowapi`; replaced the app + limiter with inert `_RouteShim`/`_LimiterShim` so the upstream `@app.post`/`@limiter.limit` decorators stay (clean diff) but no-op, leaving handler functions directly callable.
  - Credentials repointed from `os.environ` → shared `config.settings` (`google_nlp_api_key`, `dataforseo_login/password`, `scrapeowl_api_key`, `anthropic_api_key`). **No new config keys.**
  - Auth/usage (`verify_api_key`, `_verify_jwt_get_user`, `_log_usage_direct`) neutralized to no-ops — pipeline-api is private-network; platform-api authenticates at the edge.
  - **C-poll conversion:** `_drain_to_result(worker)` added; `generate_page` + `reoptimize_page` now return dicts (0 SSE returns remain).
  - NLTK corpus download made best-effort (non-fatal on import).
- **`url_filter.py`** — vendored as-is.
- **`router.py`** — `APIRouter(prefix="/local-seo", tags=["local_seo"])` exposing the **5 core endpoints** with suite-style error handling; `SCHEMA_VERSION = "1.0"`. Deferred endpoints left inert, not exposed.
- **`requirements.txt`** — added `scikit-learn==1.5.2`.

**Verified (static only):** `py_compile` passes on all module files; AST check confirms the models/handlers `router.py` references exist.

### ⚠️ Caveats / not done (carry forward)
- **No runtime/import test.** This container has **no Python deps** (`sklearn`, `nltk`, `anthropic`…), so the module can't be imported or exercised here. **Must be smoke-tested in a deps env** (local `pip install`, or Railway). Treat C1 as "looks-right-but-unproven."
- **Intentionally UNWIRED.** `main.py` does not import `modules.local_seo`, so it's inert and can't break pipeline-api boot. Wire `app.include_router(local_seo_router)` **only after** an import smoke-test passes.
- **`__init__.py` is currently empty (0 bytes).** It should be `from .router import router`. Harmless while unwired (nothing imports it), but **must be fixed before wiring.** ← known bug, top of next-session list.
- **NLTK corpora** must be pre-baked into the pipeline-api Docker image (`python -m nltk.downloader stopwords punkt punkt_tab`) before deploy.
- **C1.1 follow-up:** route the engine's ~10 `anthropic.AsyncAnthropic(...)` call sites through the suite's shared `get_anthropic()` + `anthropic_max_concurrency` semaphore (pattern in `modules/brief/llm.py`) for shared 429 protection. Left as-is for C1 (behavior-identical to source).

---

## 4. Current state of the suite (big picture)

**Built and working** (on `origin/main`):
- **Pipeline API** (`writer/pipeline-api/`): five modules — `brief`, `sie`, `research`, `writer`, `sources_cited`. (Local SEO is a 6th, in-progress, unwired.)
- **Platform API** (`writer/platform-api/`): JWT auth; clients CRUD; file upload + parsing; website-scraper async worker (`job_worker` + `website_scraper` over `async_jobs`); orchestrator + run dispatch; run polling; briefs; silos (`silo_dedup`, `silo_promotion`); publish to Google Drive (`routers/publish.py`); users; **GBP** auto-fetch + review enrichment (`gbp_service`); **logo upload** (`POST /files/logo`).
- **Frontend** (`frontend/`): `Login`, `Home` (suite tiles), `Clients`, `ClientForm`, `ClientWorkspace`, `Runs`, `RunDetail`, `Silos`, `Articles`.

**Imported, integration IN PROGRESS:** `local-seo-writer/` (#2) — **Path C chosen**, C1 backend engine ported (this branch). The raw `/local-seo-writer` import stays until the port lands; removal is part of the cleanup phase.

**Not yet built:** Keyword research (#3, migrate), Organic rank tracker (#4), Maps/local-pack ranker (#5), Ranking-drop agent (#6), VA content scheduler (#7), plus the cross-cutting **GSC analytics layer**, **shared scheduler**, **SOP store**, **notifications service**.

Module `schema_version` source of truth is `writer/platform-api/services/orchestrator.py` (`EXPECTED_MODULE_VERSIONS`): brief `2.6`, sie `1.4`, research `1.1`, writer `1.7` (+ `-no-context`/`-degraded`), sources_cited `1.1`. (Local SEO `1.0` is **not** registered here — it's not an `orchestrate_run` stage; its version is asserted in its own router.)

---

## 5. Immediate next steps (resume the port here)

1. **Fix `__init__.py`** → `from .router import router` (currently empty).
2. **Smoke-test C1 in a deps env** — `pip install -r writer/pipeline-api/requirements.txt`, then import `modules.local_seo` and exercise `/analyze` + `/score-page` with mocked externals. Only after this passes:
3. **Wire into `main.py`** (`app.include_router(local_seo_router)`) and **pre-bake NLTK corpora** in the pipeline-api Dockerfile.
4. **C2 — platform-api + data:** `routers/local_seo.py` + `models/local_seo.py` (all `require_auth`); migrations for `keyword_analyses` + `generated_pages` keyed to `client_id` (real UTC timestamps); async-job wiring for generate/reoptimize (C-poll).
5. **C3 — frontend:** rebuild NewContent / GeneratedPage / PageScore / SavedPages in suite inline-style + TanStack Query; add a Local SEO dashboard tile; new routes in `App.tsx`.
6. **Cleanup (later):** remove `/local-seo-writer`, move its docs to `docs/modules/`, update CLAUDE.md (module table + repo layout) and roadmap Appendix A status.

(Carried over from the prior branch, still open: smoke-test logo upload in a deployed env; wire logo into the published Google Doc; decide the `TestClient` harness policy.)

---

## 6. Open decisions / blockers (need the user)

1. **Scheduler mechanism** (roadmap Open Item #1) — pg_cron vs Railway cron vs asyncio worker loop. **Must be decided before Phase 1**; CLAUDE.md requires confirming before adding any queue/scheduler-like infra.
2. **Maps geo-grid density** — points per location; primary DataForSEO cost driver.
3. **Notification channels** — email provider + Slack workspace/webhook details.
4. **Keyword research repo** — stack/data-model fit unknown until shared.
5. **CI/tests policy** — automated tests on push vs. manual (also gates the `TestClient` harness).

---

## 7. Minor known debt / loose ends

- **Local SEO `__init__.py` empty** (see §3) — fix before wiring.
- **C1 is statically-checked only** — no runtime proof until it runs with deps installed.
- Writer-module PRD's *canonical header version* still unverified across `docs/modules/` — worth a pinning pass.
- `README.md` lists a `/kw-research` location that doesn't exist yet (aspirational). Reconcile when #3 lands.
- **Migration version reconciliation (partly done).** PRs #10/#11 aligned the logo-bucket + RLS-fix migrations to their live `schema_migrations` versions. **Still divergent (pre-existing):** older `main` migrations use hand-authored `YYYYMMDD120000` timestamps that don't match live versions (e.g. `clients_gbp` is `20260530003510` live vs `20260530120000` local), and the live DB has migrations with **no local file** (`keyword_metrics`, `session_cost_breakdown`, `csv_exports`, `session_archive`). A full repo↔remote reconciliation is a separate task — adopt a convention (real UTC timestamps at author time) before doing it. The C2 Local SEO migrations should follow that convention from the start.
