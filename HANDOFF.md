# AR Tools — Handoff

**Date:** 2026-06-21
**State:** everything below is **merged to `main` and deployed** (PRs #20, #21, #22). No feature branch is left in flight; the only open work is the TextRazor *activation/calibration* and the standing items in §6–§8.
**Scope of this handoff:** this session shipped four things — (1) **Brand Voice** + (2) **ICP/Differentiators** as converged client-level assets, (3) repaired a set of **nlp constants dropped in the Phase-0 rehome** that were silently 502'ing score/generate/reoptimize/press-release, and (4) swapped the entity provider **Google Cloud NLP → TextRazor**.

> Read `CLAUDE.md` first for conventions + current-state summary, `docs/suite-architecture-and-roadmap-v1_0.md` for suite scope/decisions, and `docs/modules/local-seo-module-integration-plan-v1_0.md` for the Local SEO plan. This file ties them to the latest state.

---

## 1. What this session shipped (all merged to `main`)

| PR | Title | What |
|---|---|---|
| **#20** | `Fix nlp-api: restore constants dropped in the Phase-0 rehome` | Restored `SCORE_MODEL`, `_SCORE_SYSTEM_PROMPT`, `_MODEL_PRICING`, `GENERATION_MODEL`, `_GEN_SYSTEM_PROMPT`, `_REOPT_SYSTEM_PROMPT`, `_PRESS_RELEASE_SYSTEM_PROMPT` (verbatim from `local-seo-writer/services/nlp/main.py`); added the missing `import anthropic` in `/find-page-for-keyword`; built `seo_checklist` in the reoptimize loop. **F821 in nlp-api → 0.** |
| **#21** | `Brand Voice + ICP/Differentiators — converged client-level assets` | Two new client-knowledge modules, end-to-end (store + generation + convergence bridge + UI). |
| **#22** | `Swap entity provider: Google Cloud NLP → TextRazor` | Full replacement of the entity pipeline. |

**The nlp repairs (#20) are the most important takeaway.** The Phase-0 rehome (`00ae38e`) carried the *functions* but dropped a block of module-level constants, so `/score-page`, `/generate-page`, `/reoptimize-page`, `/augment-page`, and `/press-release` raised `NameError → HTTP 502` on every call. This was latent because nlp-api has no test harness. Proven via AST (no assignment), `ruff F821`, and `git log -S` (never in the file's history). **If anyone reports "Local SEO scoring/generation was broken before 2026-06-21," this is why.**

---

## 2. Brand Voice + ICP — the convergence model (Option A)

These two re-add capabilities the Local SEO v1 plan had **cut** (`brand-voice`/`ICP` scraping) — done deliberately, per the user, and **converged** so one client-level asset feeds **both** the Blog Writer and Local SEO.

**Decision (Option A):** the structured JSON is the single source of truth; the legacy free-text columns become a *rendered view*.
- `clients.brand_voice` JSONB — `{ source, raw_text, current_voice, recommended_voice, recommended_accepted, writer_execution_guide, generated_at, edited_at }`.
- `clients.detected_icp` JSONB — `{ source, raw_text, segments, reasoning, generated_at, edited_at }`; `clients.differentiators` JSONB (array). One `detected_icp.source` governs supersede for both.
- **Provenance/supersede:** `source: "user" | "app"`. A user-authored *structured* voice/ICP blocks an auto-scan unless `force=true`; a `raw_text`-only entry can still be enriched (the scan preserves it). The UI badge treats any `raw_text` as user-authored.
- **Migrations (live + verified):** `20260621120000_clients_brand_voice.sql`, `20260621130000_clients_icp_differentiators.sql` — both applied to `wvcthtmmcmhkybcesirb` and seeded from existing `brand_guide_text` / `icp_text`.

**Wiring:**
- nlp-api: `POST /analyze-brand-voice` + `POST /analyze-business` (these *engines* already existed but were orphaned — no endpoint/persistence/UI). ICP scan includes opt-in **title/H1 enrichment** (`_enrich_pages_with_titles`, time-bounded). `_build_brand_voice_text` / `_build_icp_text` now also render `raw_text`.
- platform-api: `services/brand_voice_service.py` + `routers/brand_voice.py`; `services/icp_service.py` + `routers/icp.py`. Routes: `GET` / `POST …/scan` (heartbeat-SSE) / `PUT`, all behind `require_auth`, per-user rate-limited via a forwarded `X-User-ID` (added to `_post_nlp`).
- **Convergence bridge:** `resolve_brand_guide_text` / `resolve_icp_text` render the structured asset into the Blog Writer's run-snapshot `brand_guide_text` / `icp_text` (differentiators folded into the ICP text), at all three snapshot sites (`runs.py` dispatch + rerun, `silo_promotion.py`). **No Writer-internals change.** The clients router keeps the structured asset in sync when the legacy free-text fields change.
- **Local SEO generate/social payloads** now pass `brand_voice` / `detected_icp` / `differentiators` to the generator (they were previously omitted — this completes the Local-SEO side of convergence).
- Frontend: `pages/BrandVoice.tsx`, `pages/Icp.tsx`, `components/{brandvoice,icp}/api.ts`, ClientWorkspace "Client setup" cards, routes `/clients/:id/brand-voice` and `/clients/:id/icp`.

---

## 3. TextRazor swap (entity analysis) — **NOT FULLY LIVE YET**

Replaced Google Cloud NLP with TextRazor in the SERP pipeline (cost + Wikipedia/Wikidata linking). **Structure preserved** — per-page de-dup → page-spread + relevance filter — only the source/field mapping changed, and the downstream `google_entities` field name is **kept** so zone targets / rubric / deterministic engine / ICP are untouched.

- Mapping: `relevanceScore` → the `mean_salience` slot; `entityId` = grouping key; `matchedText` (most common) = `name`; `wikidataId` → `mid` (+ new `wiki_link`); mentions grouped by `entityId`.
- Thresholds: `ENTITY_MIN_PAGE_SPREAD` unchanged (the dominant, provider-agnostic filter). The old `0.40` salience cutoff **does not transfer** → replaced by `ENTITY_MIN_RELEVANCE` (env `TEXTRAZOR_MIN_RELEVANCE`, default lenient **`0.1`**) + optional `ENTITY_MIN_CONFIDENCE`. `get_textrazor_entities` **logs the relevance distribution** of page-spread-qualifying entities for calibration.

### ⚠️ Two things are NOT done — pick these up next
1. **The key is staged, not applied.** `TEXTRAZOR_API_KEY` was set on the `nlp` service via the Railway agent but only *staged* — the post-merge deploy log still shows `WARNING - TEXTRAZOR_API_KEY not set`. **Until it's committed (via `accept-deploy`, or re-set + redeploy), TextRazor is inert: `get_textrazor_entities` returns `[]`, so the entity signal is missing entirely** (graceful — scoring/generation still run, entity coverage defaults to its neutral value, no crash). **This was awaiting user go-ahead to redeploy when the session ended.**
2. **Threshold not calibrated.** `0.1` is a placeholder. Once the key is live, run one real Local SEO `/analyze` (or score), read the `nlp` log line `TextRazor calibration: N page-spread-qualifying entities; mean relevance (desc): [...]`, and set a tuned `TEXTRAZOR_MIN_RELEVANCE`.

---

## 4. Verification status (read this before trusting anything live)

- **All checks were static/offline:** `py_compile`, `ruff` (F821=0 in nlp-api), `mypy`/`eslint` on new code, the platform-api pytest suite (**83 passing**), `tsc -b` + `vite build`, and AST byte-identity checks on the restored nlp constants. New aggregation logic (TextRazor) was exercised against a **mocked** response.
- **Nothing was live-tested.** The build sandbox has **no `ANTHROPIC_API_KEY` and an egress allowlist** (e.g. `api.textrazor.com` is blocked, returns `403 Host not in allowlist`). Real provider calls only happen on Railway. So: the nlp repairs, the brand-voice/ICP scans, and the TextRazor swap have **not** been exercised against live providers from here.
- **Sandbox dep gaps** (not bugs): `openai`, `supabase`, `python-multipart` aren't installed in the build env, so some imports/tests fail here but pass with `pip install -r requirements.txt`. `pip install --ignore-installed PyJWT supabase` was needed for the platform tests.

---

## 5. Infra / deploy state

- **Railway (`ar-tools`): 4 services** — `nlp`, `PLATFORM`, `pipeline`, `info-site-kw-research-cluster` (the separate keyword-research app), env `production` (`7bd2e88e-…`), project `2c718e53-…`.
- **All three suite services redeployed** off the merges and reported **SUCCESS** (latest `nlp` deploy = `6025459`, the #22 merge). The TextRazor *code* is live; the *key* is not (see §3).
- **`nlp` keys present:** `ANTHROPIC_API_KEY`, `SCRAPEOWL_API_KEY`, `DATAFORSEO_LOGIN/PASSWORD`, `GOOGLE_NLP_API_KEY` (now unused — removable after TextRazor is confirmed), `TEXTRAZOR_API_KEY` (**staged, not applied**). `SCORE_MODEL`/`GENERATION_MODEL` are **not** env vars (code constants → sonnet default); their absence is expected.
- Railway gotchas still apply (from the prior handoff): private-only `nlp` ⇒ **keep `healthcheckPath` empty**; Dockerfile binds `::`; don't double-trigger deploys; SSE routes need buffering off.

---

## 6. ⚠️ Open security / cost items (flagged, not yet actioned)

1. **`nlp` has a PUBLIC domain** — `nlp-production-0e3c.up.railway.app:8080` — but the service is **auth-less by design** ("private network only" per CLAUDE.md). If that domain is internet-reachable, anyone who finds it can hit `/generate-page`, `/score-page`, `/analyze`, etc. and **burn Anthropic + DataForSEO + ScrapeOwl + TextRazor credits**. The #20 repairs made those endpoints *more* functional, so this matters more now. **Verify reachability and remove the public domain (or add auth) — highest-priority loose end.**
2. **Rotate the TextRazor key** — it was pasted into the chat transcript this session. The working value is in Railway; rotate once cutover is confirmed.
3. After TextRazor is confirmed working, **remove `GOOGLE_NLP_API_KEY`** from `nlp` (no longer read).

---

## 7. Immediate next steps

1. **Finish TextRazor (§3):** apply the staged `TEXTRAZOR_API_KEY` (redeploy `nlp`), run one real `/analyze`, read the calibration log line, set a tuned `TEXTRAZOR_MIN_RELEVANCE`, confirm entity counts are sane. Then rotate the key + drop `GOOGLE_NLP_API_KEY`.
2. **Close the `nlp` public-domain exposure (§6.1).**
3. **Live smoke-test the repaired nlp endpoints** — `/score-page` + `/generate-page` against the deployed PLATFORM→nlp path with an authenticated request. These were 502'ing before #20; a real call is the only true proof they're fixed (couldn't be done from the sandbox).
4. **Click-test Brand Voice + ICP** end-to-end (scan → review → accept → generate) — built/typed-clean but not exercised live.

---

## 8. Open decisions / standing debt (carried forward)

- **SERP analysis cache (`keyword_analyses`) still does not exist.** Every `/analyze` and `run_analysis:true` generate re-runs the full DataForSEO→ScrapeOwl→(now TextRazor) pipeline (2–4 min, recurring cost). SYSTEM_OVERVIEW/Foundation calls for caching `AnalysisResponse` by `(keyword, location)`; this is the highest-value infra still unbuilt and would speed up Score My Page + generation.
- **Vertical wording** — the brand-voice/ICP/score prompts say "local service business" verbatim. Fine for local clients, slightly off for non-local Blog-Writer clients; left verbatim per the "keep prompts exact" rule. Parameterizable later.
- **Manual editing is freeform `raw_text`** for both brand voice + ICP; per-field structured editing is a future enhancement.
- **`seo_checklist` in `/reoptimize-page`** was a latent bug present in the reference copy too; fixed by mirroring generate-page's `_build_seo_checklist(...)` call — worth a sanity check on a live reoptimize run.
- **Scheduler mechanism**, **Maps geo-grid density**, **notification channels**, **Keyword-research repo migration**, **CI on push** — all still open from prior handoffs.
- **Local SEO Phase 3 — page-template field** — still not started (the original request from the prior session).
- Pre-existing: `public.sie_cache` has RLS disabled (advisory); migration-timestamp convention mismatch; `README.md` references a non-existent `/kw-research` path.
