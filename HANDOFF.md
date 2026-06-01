# AR Tools — Handoff

**Branch:** `claude/compassionate-mccarthy-dvnrw` (pushed; **not merged**, no PR opened yet)
**Date:** 2026-06-01
**Scope of this handoff:** this session's work — **Local SEO module Phase 2** (frontend + full platform-api passthrough, the full ShowUP flow minus rankability) plus the adversarial-review hardening that followed (all HIGH/MEDIUM/LOW issues). Builds directly on the prior session's Phases 0–1 (now merged to `main`, PRs #12–#18).

> Read `CLAUDE.md` first for project conventions and the authoritative current-state summary, `docs/suite-architecture-and-roadmap-v1_0.md` for suite scope/decisions, and `docs/modules/local-seo-module-integration-plan-v1_0.md` for the Local SEO plan. This file ties them to the in-flight work.

---

## 1. What this session shipped (commits on `claude/compassionate-mccarthy-dvnrw`)

| Commit | Type | Summary |
|---|---|---|
| `9cb6dd1` | feat(local-seo) | **Phase 2** — full Local SEO frontend + platform-api passthrough routes (see §2). |
| `7ac9b67` | fix(local-seo) | **HIGH** review fixes — nlp error mapping + heartbeat-SSE for long ops (see §4). |
| `c1cbc29` | fix(local-seo) | **MEDIUM** review fixes — related-pages per-row actions; open-saved loading view. |
| `b50ef16` | fix(local-seo) | **LOW** review fixes — ticker leak guard; Deficiency type; removed reoptimize double-scoring. |

**Not merged.** Everything is on the feature branch awaiting review/merge. No PR was opened (per the "don't open a PR unless asked" rule). When merging: see the deploy notes in §5 — **the `nlp` service must be redeployed** for the §4-#8 change.

---

## 2. Local SEO module (#2) — integration status

**Chosen path: C (full port) into the suite.** Plan + scope authority: `docs/modules/local-seo-module-integration-plan-v1_0.md`.

**v1 scope (agreed):**
- ✅ Keep: competitor SERP + client-page scraping (analysis), full page scoring + auto-reoptimization.
- ❌ Cut: client-site **brand-voice** scraping, client-site **ICP** detection, the keyword-worthiness **"rankability"** check, all **billing/credits**.
- Analysis is an **explicit per-page opt-in** — generate takes a **required `run_analysis` bool** (no default).
- ➕ Deferred to Phase 3: a **page-template** field the writer must follow.

**Phase 0 — NLP service rehomed (DONE, prior session).** `writer/nlp-api/`, private-only on Railway at `http://nlp.railway.internal:8080`. Every endpoint the suite needs already exists there (`/analyze`, `/find-page-for-keyword`, `/score-page`, `/related-pages`, `/generate-page`, `/reoptimize-page`, `/generate-social-posts`); `/check-rankability` was stripped.

**Phase 1 — platform-api backend (DONE, prior session).** `local_seo_pages` table (live, RLS); `config.nlp_api_url`; original generate/list/get.

**Phase 2 — frontend + full passthrough (DONE this session, on branch).**
- **platform-api** (`routers/local_seo.py`, `services/local_seo_service.py`, `models/local_seo.py`) — auth-gated proxies to the private nlp service; owns persistence. The 7 POST **action** routes are **heartbeat-SSE** (see §4-#3); GET/DELETE are plain JSON:
  - `POST /clients/{id}/local-seo/generate` · `/analyze` · `/find-page` · `/score` · `/related-pages` · `/reoptimize` · `/social-posts`
  - `GET /clients/{id}/local-seo/pages` · `GET /local-seo/pages/{id}` · `DELETE /local-seo/pages/{id}`
  - `reoptimize` persists a `mode='reoptimize'` row; uses the nlp-surfaced score (no redundant re-score — §4-#8).
- **frontend** (suite inline-style system, not Tailwind): new page `pages/LocalSeoContent.tsx` (New Page form with service + area + **required** analysis choice; optional site-scan & analysis-preview; Saved Pages tab with view/delete) and `components/localseo/` (`GeneratedPageView`, `PageScoreView`, `AnalysisResultsView`, `Spinner`, `types`, `shared`, `api`). Route `/clients/:id/local-seo` added in `App.tsx`; the **"Create Local SEO Content"** workspace card now links to it (was the dead "Setup in progress" stub). `lib/api.ts` gained a `stream()` SSE consumer.
- **nlp** (`writer/nlp-api/main.py`): no new endpoints. `/reoptimize-page` and `/generate-page` now **surface `composite_score`/`composite_status`** in their `done` events (added `_status_for_score`).

**Adaptations from ShowUP Local (intentional):**
- The business selector collapses to **the client** (GBP lives on the client row).
- **Location is a plain text field** — the suite has no DataForSEO `location` table (confirmed via Supabase), so `location_code` is omitted and DataForSEO falls back to `location_name`.
- **Rankability removed** entirely.
- No `keyword_analyses` cache table in the suite → analysis isn't cached between calls (every `analyze` / `run_analysis:true` generate re-scrapes; recurring DataForSEO/ScrapeOwl cost — noted debt).

**Phase 3 — page-template field (NOT STARTED).** Add `page_template` to the nlp `GeneratePageRequest` + inject into the generation prompt/checklist; add the form field; optionally persist a per-client default.

---

## 3. Tests / checks (this session)

- **platform-api: 57 passing.** New `tests/test_local_seo_service.py` (payload mapping, business-field fallbacks, generate persistence, find/score guards, related passthrough, reoptimize surfaced-score vs fallback) and `tests/test_sse.py` (done / HTTPException→error / masked internal_error).
- **frontend:** `tsc` clean, `eslint` clean, `vite build` OK.
- Install note: the sandbox needed `pip install --ignore-installed cffi PyJWT` before `pip install -r requirements.txt -r requirements-dev.txt` would import (broken system `_cffi_backend`).

---

## 4. Review hardening — what the fixes were (for reviewers)

The Phase-2 build was reviewed adversarially; all findings are fixed on-branch.

- **#1/#2 (HIGH)** — `_post_nlp` now wraps `response.json()`: a `200` with a non-JSON/truncated body is mapped to `502 local_seo_provider_error` instead of leaking a 500. `reoptimize_page`'s re-score guard widened to `except Exception` so a failed (non-essential) re-score never discards the successful rewrite.
- **#3 (HIGH)** — long POSTs (generate/score/reoptimize/analyze can run 1–5 min sending no bytes) could be dropped by a load-balancer idle timeout. New `sse.py` `sse_response` runs the op as a background task, emits a heartbeat every 10s, then a final `done`/`error` SSE event; the 7 action routes use it. Frontend `lib/api.stream()` reads the stream, ignores heartbeats, resolves with the final result — so component call sites are unchanged. On client disconnect the task is left running so persistence still completes.
- **#4 (MEDIUM)** — related-pages "Act on N selected" only ever processed one item before the view unmounted; replaced with honest per-row action buttons.
- **#5 (MEDIUM)** — opening a saved page reused the multi-minute "Creating…" UI; added a distinct lightweight `loading` view.
- **#6 (LOW)** — `startTicker` now clears any prior interval (no leak on rapid re-submit).
- **#7 (LOW)** — `Deficiency` type corrected to match nlp (`issues`/`score`/`recommendations`, no singular `issue`); related list renders `issues`.
- **#8 (LOW)** — reoptimize no longer makes a second `/score-page` LLM call; it consumes the score the nlp loop already computed (surfaced in §2), falling back to a re-score only for older nlp builds (rollout-safe).

---

## 5. Deploy gotchas worth remembering (Railway `nlp` service)

- **nlp redeploy required for §4-#8.** The surfaced `composite_score`/`composite_status` (and the skipped reoptimize re-score) only take effect once `writer/nlp-api/main.py` is redeployed. It's **deploy-order-safe** (platform falls back when the fields are absent), but generated/reoptimized pages won't show the status band, and reoptimize will keep double-scoring, until nlp is updated.
- **SSE buffering.** The 7 action routes return `text/event-stream` with `X-Accel-Buffering: no` + `Cache-Control: no-cache`. If a future proxy buffers responses, the heartbeat keepalive is defeated — keep buffering off on that path.
- **No deploy-time healthcheck.** A private-only service can't pass Railway's `/health` probe → **keep `healthcheckPath` empty** (it persists as a saved setting; clearing it needed `accept-deploy`).
- **Private bind.** The Dockerfile binds `::` (IPv6) for Railway private networking. Don't change to `0.0.0.0`.
- **Don't double-trigger deploys.** Merge to `main`, then let the single auto-deploy run (a simultaneous manual redeploy caused a multi-deploy deadlock).
- The `nlp` service's 4 API keys (`DATAFORSEO_LOGIN/PASSWORD`, `SCRAPEOWL_API_KEY`, `GOOGLE_NLP_API_KEY`, `ANTHROPIC_API_KEY`) are **reference variables** from the `pipeline` service.

---

## 6. Current infra state

- **Railway (`ar-tools`): 3 services online** — `PLATFORM`, `pipeline`, `nlp` (private-only). **`nlp` and `PLATFORM` need a redeploy** to pick up this branch once merged.
- **Supabase** (`wvcthtmmcmhkybcesirb`): `local_seo_pages` live with RLS; `OUTSCRAPER_API_KEY` + `DATAFORSEO_*` set on PLATFORM. ⚠️ Advisory (pre-existing, not from this work): `public.sie_cache` has **RLS disabled** — surfaced for the user to decide on (needs policies before enabling).
- **Frontend** (Netlify): Local SEO UI is built on this branch (not yet deployed/merged).

---

## 7. Immediate next steps

1. **Review & merge** `claude/compassionate-mccarthy-dvnrw` (open a PR when ready). Remember the nlp redeploy (§5).
2. **Runtime smoke-test the full Local SEO flow end-to-end** — still not done. Exercise generate / find-page / score / reoptimize / related / social against the deployed PLATFORM→nlp path with an authenticated request (can't be done from the build sandbox). Confirms the SSE plumbing (both platform↔nlp and browser↔platform), GBP→payload mapping, scoring, and persistence for real.
3. **Phase 3 — page-template field** (the original request that started this thread).
4. **nlp dead-code cleanup** — remove the now-unreferenced helpers from the 3 cut endpoints (`_crawl_pages_for_brand_voice`, `analyze_brand_voice_with_anthropic`, `_rankability_score`, `_haversine_miles`, orphaned request models).

---

## 8. Open decisions / blockers (need the user)

1. **Page-scoring model** — nlp uses `claude-sonnet-4-6`; per CLAUDE.md, per-module model choice is an "ask first" item. Confirm before relying on it in production.
2. **Scheduler mechanism** (roadmap Open Item #1) — still unchosen; gates any scheduled tracker.
3. **Maps geo-grid density**, **notification channels**, **Keyword-research repo** — still open from prior handoffs.
4. **CI/tests policy** — pytest runs locally (57 green), but nothing runs it on push. Decide whether to add CI.

---

## 9. Known debt / loose ends

- **Local SEO not runtime-tested** end-to-end (see §7.2).
- **No analysis caching** in the suite — every `analyze` / `run_analysis:true` generate re-scrapes competitors (no `keyword_analyses` table). Real recurring API cost.
- **Generated HTML is rendered via `dangerouslySetInnerHTML`** without DOMPurify (first-party content from our own nlp pipeline, same trust level as the blog writer's output; no dep added).
- **nlp dead code** (see §7.4).
- **Migration timestamp convention** — `20260601022754_local_seo_pages.sql` uses a real UTC timestamp; older `main` migrations use `YYYYMMDD120000`. Full repo↔remote reconciliation is a separate task.
- **Writer-module PRD canonical version** still unpinned across `docs/modules/`.
- `README.md` still references a `/kw-research` path that doesn't exist.
