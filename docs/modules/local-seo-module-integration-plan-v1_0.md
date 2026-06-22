# Local SEO Content Module — Integration & Implementation Plan (v1.0)

**Authored:** 2026-06-01 · **Status:** plan approved, **no code written yet** · **Module #2 (suite roadmap)**

> Read alongside **`docs/suite-architecture-and-roadmap-v1_0.md`** (Appendix A — Local SEO import assessment and the A/B/C integration options) and the imported app's own context at **`/local-seo-writer/CLAUDE.md`**. This document records the agreed scope and phasing for the **first version** of the suite-integrated Local SEO module.

---

## 1. Product summary

A **per-client** Local SEO module on each client's workspace. The user picks a keyword + location; the module generates a location-optimized page using the client's existing GBP data, analyzes competitor SERPs + client pages for SEO signals, and scores the generated page for quality (auto-improving to a target).

No billing, no brand-voice scraping, no keyword-worthiness advisory (see §2).

The source app is **ShowUP Local** (`kssabraw/showup-local`), imported raw into this repo at `/local-seo-writer`. The Python NLP microservice in that copy (`services/nlp/`) is complete and reusable; the frontend `src/lib/` was **not** included in the import, so the suite frontend is rebuilt rather than copied.

---

## 2. Scope (final, agreed)

### ✅ Keep (runs automatically, as today)
- **Competitor SERP scraping + client-page scraping** → analysis: related keywords, quadgrams, Google NLP entities (the `/analyze` pipeline: DataForSEO → ScrapeOwl → TF-IDF → n-grams → Google NLP).
- **Page scoring** — the full 8-engine composite score **plus** the auto-reoptimization loop (`MAX_AUTO_PASSES=4`, target 90+). This judges **page quality** and stays intact.
- **Generation** from the client's stored GBP data (`business_name, gbp_category, address, phone, website, hours, gbp_description, reviews`).

### ❌ Cut from this version
| Cut | Where it lives (NLP service / frontend) |
|---|---|
| ~~**Rankability / keyword-worthiness check**~~ — **RE-ADDED** as the **Map-Pack Rankability Report** per its own build-ready PRD (deterministic map-pack score: category match, distance, review gap, branded-name count, SAB penalty). Backend `nlp-api /check-rankability` + platform-api `/clients/{id}/local-seo/rankability`; frontend `RankabilityReport`. The source app's per-user monthly cap / `purchase-rankability-pack` billing was **not** ported (internal-only, no billing). | `/check-rankability`, `_rankability_score()`, `RankabilityRequest`/`RankabilityResponse`; frontend `handleCheckRankability`, `rankability` state, `RankabilityResult` type |
| **Brand voice generation** (crawls the client's own site) | `_crawl_pages_for_brand_voice()`, `/analyze-brand-voice`, `analyze_brand_voice_with_anthropic()`; `LocationDetailView` Brand Voice tab |
| **ICP detection** (crawls the client's own site) | `/analyze-business` → `detected_icp` / `differentiators`; related UI |
| **Stripe / credits billing** | `purchase-credit-pack`, `purchase-press-release-pack`, `purchase-rankability-pack` edge functions, `credit_balance` / credit-transaction logic |

> **Important distinction (the source of earlier confusion):** "page scoring" (post-generation, page-quality, KEEP) is a **different feature** from the "rankability check" (pre-generation, keyword-worthiness advisory, CUT). The page-scoring engine's internal `geographic_legitimacy` and `gbp_maps` weights judge the generated **page** and therefore **stay** — only the upfront keyword-worthiness advisory is removed. `brand_voice` / `detected_icp` are `Optional` on `GeneratePageRequest`, so generation handles their absence cleanly.

### ➕ Add (Phase 3)
- **Page template** field — the user supplies a page structure the writer must follow; injected into the generation prompt/checklist.

---

## 3. Integration path: **C — full port into the suite**

Per Appendix A, Path C = rebuild the UI in the suite's frontend style and move the backend logic into the suite's Railway/FastAPI model. Chosen because it's the only path that delivers a **true per-client, in-suite** module (like the Blog Writer) and **lands entirely inside `ar-tools`** (Paths A and B require the separate `showup-local` repo + its own Supabase/Railway, which are out of scope for in-repo work).

Cross-cutting (any path, per Appendix A): drop billing; the NLP microservice lifts into the suite's Railway services; reconcile `business_profiles` → `clients`.

---

## 4. Phased build

### Phase 0 — Rehome the NLP service *(gating dependency, highest risk)*
- Add `services/nlp` (complete in the vendored copy) as a **third Railway service** on the private network.
- **Strip cut features:** rankability, brand-voice, business-analysis endpoints + their Anthropic calls.
- **Auth swap:** use the suite's JWT model; remove the edge-function / `X-API-Key` path and the usage-log/billing hooks.
- **Env vars:** DataForSEO, ScrapeOwl, Google NLP, Anthropic — most already exist on the `pipeline` service.
- Risk concentrated here: private networking, auth swap, env config.

### Phase 1 — Backend in platform-api
- **Migration** (`writer/supabase/migrations/`): new `local_seo_pages` table — port of `generated_pages`, **FK → `clients.id`** instead of ShowUP's `business_profiles`. Columns: `content_html, schema_json, page_title, content_gaps (jsonb), composite_score, composite_status, mode, keyword, location`, timestamps, `client_id`.
- **Router** `routers/local_seo.py`:
  - `POST /clients/{id}/local-seo/generate`
  - `GET  /clients/{id}/local-seo/pages`
  - `GET  /local-seo/pages/{page_id}`
- **Service** `services/local_seo_service.py` — orchestrates the NLP service (injecting the client's GBP fields server-side from `clients`) and persists results. Page scoring + reoptimize remain on.
- **Models** mirroring the (trimmed) `GeneratePageRequest` / `GeneratePageResponse`.

### Phase 2 — Frontend in the shared app
- Wire the existing **"Create Local SEO Content"** workspace card (currently the dead "Setup in progress" stub at `frontend/src/pages/ClientWorkspace.tsx:76`) to a real route.
- New pages in the suite's **inline-style** system (not Tailwind/shadcn):
  - **Generate form** — keyword + location; business data auto-pulled from the client.
  - **Generated-page view** — rendered HTML + content-gaps panel + score.
- No Brand Voice / ICP / Rankability UI to build (simpler than the original app).

### Phase 3 — Page template
- Add `page_template` to the generation request + inject into the prompt / `_build_seo_checklist()`.
- Add the form field; optionally persist a **per-client default template**.

---

## 5. Sequencing & delivery
- **One PR per phase.** Phase 0 first — everything depends on it.
- Multi-day effort overall.

---

## 6. Open items to settle (before/within Phase 0)
1. **NLP service auth** — confirm it should use the suite's existing `require_auth` JWT (assumed yes).
2. **`business_profiles` → `clients` mapping** — the client *is* the business; GBP already lives on `clients`. Field mapping done in Phase 1.
3. **Page-scoring model** — currently `claude-sonnet-4-6`; per `CLAUDE.md`, per-module model choice is an "ask first" item — confirm before Phase 1.

---

## 7. Notes / provenance
- This plan supersedes the "deferred, no path chosen" status in Appendix A by selecting **Path C** with the scope cuts in §2. Appendix A remains the import/assessment record.
- The vendored copy's frontend is missing `src/lib/` (`nlp-client.ts`, `nlp-types.ts`), so the frontend is **rebuilt** in the suite, not ported file-for-file. The **backend NLP service is complete** and is the primary reusable asset.
- AR Tools' Blog Writer has its own brand-voice system on `clients`; if on-brand local pages are wanted later, that existing client brand context could feed generation instead of re-deriving voice. Out of scope for v1.
