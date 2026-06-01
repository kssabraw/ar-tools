# AR Tools — Handoff

**Branch:** `claude/intelligent-knuth-3Qb01`
**Date:** 2026-06-01
**Scope of this handoff:** this session's work — GBP input improvements, pytest setup, and the **Local SEO module integration (Phases 0–1)** — plus current state and next steps. All work below is merged to `main` (PRs #12–#18).

> Read `CLAUDE.md` first for project conventions and the authoritative current-state summary, `docs/suite-architecture-and-roadmap-v1_0.md` for suite scope/decisions, and `docs/modules/local-seo-module-integration-plan-v1_0.md` for the Local SEO plan. This file ties them to the in-flight work.

---

## 1. What shipped this session (all merged to `main`)

| PR | Type | Summary |
|---|---|---|
| #12 | feat(gbp) | **GBP URL / share-link / place-ID input.** `/clients/gbp/resolve` resolves a full Maps URL, `maps.app.goo.gl`/`goo.gl` short link (expanded server-side), bare place_id, feature/Google ID, CID, or free text → the existing Outscraper details path. New "or paste a link" field in `GbpPicker.tsx`. |
| #13 | test | **pytest setup.** `platform-api/pyproject.toml` (`asyncio_mode=auto`) + `requirements-dev.txt` for both APIs (pytest, pytest-asyncio). The suite could not run tests before. Verified `test_gbp_resolve.py` 9/9 green. |
| #14 | feat(gbp) | **Auto-fill from GBP.** Attaching a GBP fills the client Name + Website fields — only when empty (never overwrites typed input). |
| #15 | feat(local-seo) | **Phase 0 — NLP service rehomed** into the suite at `writer/nlp-api/` (see §2). |
| #16 | fix(local-seo) | Dropped the deploy healthcheck from the nlp service (see §3 — deploy gotcha). |
| #17 | feat(local-seo) | **Phase 1 — platform-api backend** for local SEO pages (see §2). |
| #18 | docs(claude) | CLAUDE.md refreshed for the nlp service + Local SEO integration. |

---

## 2. Local SEO module (#2) — integration status

**Chosen path: C (full port) into the suite.** Plan + scope authority: `docs/modules/local-seo-module-integration-plan-v1_0.md`.

**v1 scope (agreed):**
- ✅ Keep: competitor SERP + client-page scraping (analysis), full page scoring + auto-reoptimization.
- ❌ Cut: client-site **brand-voice** scraping, client-site **ICP** detection, the keyword-worthiness **"rankability"** check, all **billing/credits**.
- Analysis is an **explicit per-page opt-in** — `/generate-page` and the suite API take a **required `run_analysis` bool** (no default).
- ➕ Deferred to Phase 3: a **page-template** field the writer must follow.

**Phase 0 — NLP service rehomed (DONE).** `writer/nlp-api/` (ported from `/local-seo-writer/services/nlp`). Auth layer removed (private network only, like pipeline-api); the 3 cut endpoints removed; analysis gated behind `run_analysis`. Deployed as the Railway **`nlp`** service, **private-only** (no public domain), reachable at `http://nlp.railway.internal:8080`. Dead helper fns from the removed endpoints remain unreferenced — flagged for a later cleanup pass.

**Phase 1 — platform-api backend (DONE).** 
- Migration `local_seo_pages` (FK `clients.id`; RLS enabled to match sibling tables) — **applied live**.
- `config.nlp_api_url`, `services/local_seo_service.py` (builds the NLP payload from the client's GBP data, streams the `/generate-page` SSE, persists), `routers/local_seo.py`:
  - `POST /clients/{id}/local-seo/generate`
  - `GET /clients/{id}/local-seo/pages`
  - `GET /local-seo/pages/{page_id}`
- Live on PLATFORM (clean startup confirmed).

**Phase 2 — frontend (NOT STARTED).** Wire the existing **"Create Local SEO Content"** workspace card (currently the dead "Setup in progress" stub at `frontend/src/pages/ClientWorkspace.tsx:76`) → a generate form (keyword + location + the **required** analysis choice) → a generated-page view (HTML + content-gaps panel + score). Rebuild in the suite's inline-style system (not Tailwind).

**Phase 3 — page-template field (NOT STARTED).** Add `page_template` to the NLP `GeneratePageRequest` + inject into the generation prompt/checklist; add the form field; optionally persist a per-client default.

---

## 3. Deploy gotchas worth remembering (Railway `nlp` service)

- **No deploy-time healthcheck.** A private-only service can't pass Railway's `/health` probe, so the deploy hangs forever in DEPLOYING. The fix was to **clear the service-level `healthcheckPath`** (it persisted from the original import's railway.json even after the file was changed — a removed JSON key doesn't clear a saved setting). Committing it required `accept-deploy` (the staged change wasn't taking). **Keep `healthcheckPath` empty.**
- **Private bind.** The Dockerfile binds `::` (IPv6) so Railway private networking can reach it. Don't change to `0.0.0.0`.
- **Don't double-trigger deploys.** Merging to `main` auto-deploys all main-tracking services; a simultaneous manual redeploy caused a multi-deploy deadlock that needed manual cancellation in the dashboard. Merge, then let the single auto-deploy run.
- The `nlp` service's 4 API keys (`DATAFORSEO_LOGIN/PASSWORD`, `SCRAPEOWL_API_KEY`, `GOOGLE_NLP_API_KEY`, `ANTHROPIC_API_KEY`) are **reference variables** from the `pipeline` service — they stay in sync.

---

## 4. Current infra state

- **Railway (`ar-tools` project): 3 services, all SUCCESS/online** — `PLATFORM`, `pipeline`, `nlp` (private-only).
- **Supabase** (`wvcthtmmcmhkybcesirb`): `local_seo_pages` table live with RLS; `OUTSCRAPER_API_KEY` + `DATAFORSEO_*` set on PLATFORM (added this session) so GBP search/details/reviews work.
- **Frontend** (Netlify): GBP paste-a-link + auto-fill shipped; no Local SEO UI yet.

---

## 5. Immediate next steps

1. **Phase 2 — Local SEO frontend** (the obvious next build).
2. **Phase 3 — page-template field** (the original request that started this thread).
3. **Runtime smoke-test the Local SEO backend end-to-end** — generate a page via the deployed PLATFORM → nlp path (needs an authenticated request; can't be done from the build sandbox). Confirms the SSE wiring + GBP→payload mapping + persistence for real.
4. **nlp dead-code cleanup** — remove the now-unreferenced helpers from the 3 cut endpoints (`_crawl_pages_for_brand_voice`, `analyze_brand_voice_with_anthropic`, `_rankability_score`, `_haversine_miles`, and their orphaned request models). Deferred to avoid risky deep deletions mid-port.

---

## 6. Open decisions / blockers (need the user)

1. **Page-scoring model** — nlp currently uses `claude-sonnet-4-6`; per CLAUDE.md, per-module model choice is an "ask first" item. Confirm before relying on it in production.
2. **Scheduler mechanism** (roadmap Open Item #1) — still unchosen; gates any scheduled tracker (Phase 1 of the broader roadmap).
3. **Maps geo-grid density**, **notification channels**, **Keyword-research repo** — still open from the prior handoff.
4. **CI/tests policy** — pytest now runs locally, but nothing runs it on push. Decide whether to add CI.

---

## 7. Known debt / loose ends

- **nlp dead code** (see §5.4).
- **Local SEO backend not runtime-tested** end-to-end (see §5.3).
- **Migration timestamp convention** — this session used a real UTC timestamp (`20260601022754_local_seo_pages.sql`); older `main` migrations still use hand-authored `YYYYMMDD120000` style. Full repo↔remote reconciliation remains a separate task (noted in prior handoffs).
- **Writer-module PRD canonical version** still unpinned across `docs/modules/`.
- `README.md` still references a `/kw-research` path that doesn't exist.
