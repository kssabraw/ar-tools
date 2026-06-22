# AR Tools — Handoff

## ⏩ Update — 2026-06-22 · **Competitive SERP Snapshot** (latest)

A diagnostic **SERP snapshot** store for the rank tracker — captured **weekly**
alongside the DataForSEO rank refresh so a pre-drop baseline always exists when
investigating a ranking drop later. **Backend-only** (no viewer UI by design —
retrieved on request via the API). **Merged to `main` and deployed** (PR **#53**,
squash) — PLATFORM redeploy **runtime startup verified clean** via Railway logs
(`job_worker.started` + `gsc_scheduler.started` + `Application startup complete`,
no Traceback); migration **applied** to `wvcthtmmcmhkybcesirb`. Runs on the
DataForSEO paths whose creds are already on PLATFORM, so it's **operational today**.

**What it captures**, per tracked keyword per capture: the **AI Overview**
(presence, text, cited sources); the **SERP feature inventory** ("enhancements":
local pack/GBP, PAA, discussions/forums, featured snippet, … — item types present
+ captured detail); the **query intent** (DataForSEO Labs search-intent); and the
**top organic results** (url / domain / rendered **title + description** /
position), each enriched with **referring domains + URL Rating** (DataForSEO
Backlinks page rank 0–1000, the UR-equivalent) — **including the client's own
ranking/canonical page** (an extra row if it ranks below the captured depth).

**Decisions (confirmed with user before building):** UR = DataForSEO page rank
(no new vendor); Backlinks API in scope, ~11 lookups/keyword, cost OK; stored
dated snapshots per keyword; **auto weekly capture**; **store-only + retrieval API**
(users don't need routine access).

**Data sources (all DataForSEO, reusing the `dataforseo_rank.py` Basic-auth
pattern):** SERP advanced (`serp/google/organic/live/advanced`) → AIO + organic +
features; Labs `search_intent/live` → intent; `backlinks/summary/live` per target
URL → referring domains + page rank. Per-URL / per-keyword failures are isolated
(snapshot degrades to `partial`; a SERP failure stores a `failed` marker row).

**Code:** `services/serp_snapshot.py` (pure parse helpers + async orchestrator +
`enqueue_serp_snapshot` / `run_serp_snapshot_job`); wired into
`gsc_scheduler.enqueue_due_serp_snapshots` (weekly branch) + `job_worker`
(`serp_snapshot` job type). Retrieval routes in `routers/rank.py`:
`GET /tracked-keywords/{id}/serp-snapshots`, `GET /serp-snapshots/{id}`, and an
on-demand `POST /tracked-keywords/{id}/serp-snapshot` (enqueues a single-keyword
capture). Models in `models/rank.py`. Config: `serp_snapshot_depth` (20),
`serp_snapshot_top_n` (10 — how many top results get the pricier Backlinks call).

**Migration (applied; filename = recorded version):** `…232017_serp_snapshots`
— `serp_snapshots` + `serp_snapshot_results`, widened `async_jobs.job_type`. RLS
on, no client-facing policies.

**Verification:** `import main` + full suite **220 passed** on the **pinned**
`fastapi==0.115.0` / `pydantic==2.9.2` (the #43 process). Live providers not
exercised from the sandbox (DataForSEO calls only run on Railway) — first real
weekly capture is the live proof.

**Note on cost:** the weekly pass snapshots **every** active keyword for every
client (≈1 SERP + 1 intent + up to 11 backlinks calls each). Cost was approved;
if it needs throttling later, gate `enqueue_due_serp_snapshots` (e.g. priority
keywords only) — the same tiering open question as the DataForSEO "Today" rank.

---

## ⏩ Update — 2026-06-22 · **Rank-tracker reports**

Client **reporting** is built on top of the rank tracker — on-demand, scheduled, and optionally delivered as a Google Doc. All merged to `main` and deployed (PRs **#47**, **#48**, **#50**), each verified live (PLATFORM clean startup, `gsc_scheduler.started`). Sits on the rank-tracker section below.

**What shipped:**
- **On-demand printable report (#47).** A **Reports** tab → "Generate now" / open any saved report → a clean, branded print view (`pages/RankReport.tsx`) with a **Print / Save as PDF** button (scoped `@media print` CSS isolates it from app chrome — no PDF dependency). Sections: branded header (logo + client + date + mode/location), KPI summary incl. **total estimated monthly value**, status rollup, GSC trend charts (avg position + clicks/impressions), Improving / Needs-attention highlights, top opportunities by est. value, full keyword table. Adapts for DataForSEO-only clients (drops GSC-only sections).
- **Scheduled reports + in-app archive (#48).** Per-client `rank_report_config`: **as_needed / weekly+weekday / monthly+day / every 7·14·30 days**. The shared scheduler (`gsc_scheduler.enqueue_due_reports`) checks daily via `rank_report.is_report_due` (month-end clamp; never twice a day) and enqueues a `rank_report` job that **snapshots** the report data into `rank_reports` (so a dated report keeps its as-of numbers). `RankReport` renders either live or a stored snapshot (`/clients/:id/rankings/report/:reportId`).
- **Google Doc delivery (#50).** Optional per-client toggle (`rank_report_config.deliver_google_doc`) auto-publishes scheduled + generated reports as a **Google Doc in the client's Drive folder**, reusing the Apps Script publish webhook (the locked delivery rail). `rank_report.render_report_markdown` (pure) → `publish_report_doc` POSTs `{folder_id, title, content}` to `GOOGLE_APPS_SCRIPT_URL`, stores `doc_url` on the report. Any saved report can be published on demand (`POST /rank-reports/{id}/publish`); UI shows **"To Doc" / "View Doc"**. Requires the client to have a Drive folder set (Client → Edit).

**Code:** `services/rank_report.py`; report routes in `routers/rank.py` (`report-schedule` GET/PUT, `reports` GET/POST, `rank-reports/{id}` GET/DELETE, `rank-reports/{id}/publish` POST); frontend `pages/RankReport.tsx` + `components/rankings/RankReports.tsx`.

**Migrations (applied to `wvcthtmmcmhkybcesirb`; filenames = recorded versions):** `…214725_rank_reports` (`rank_report_config` + `rank_reports` + job_type `rank_report`), `…215804_rank_report_delivery` (`deliver_google_doc` + `doc_id/doc_url/delivered_at`). RLS on, no client-facing policies.

**Delivery options status:** in-app archive + Google Doc = built. **Email = deliberately deferred** — needs the suite **notifications service** (unbuilt) + an email-provider/from-address decision. That same decision unblocks rank-drop **alerting**; building the notifications service once lights up both.

**Process note (carried from the #43 incident):** every backend change since is import-/test-verified against the **pinned** `fastapi==0.115.0` / `pydantic==2.9.2` before merge (latest suite run **206 passed**), and each merge's PLATFORM deploy is confirmed via Railway logs for a clean runtime startup — not just a green build.

---

## ⏩ Update — 2026-06-22 · **Organic Rank Tracker shipped** (supersedes the scheduler + `sie_cache` RLS items in §8)

The **Organic Rank Tracker (Module #4)** is **built and live in production** — M1–M4 complete **except alerting**. Hybrid **GSC + DataForSEO** with an automatic per-keyword fallback. All merged to `main` and deployed (PRs **#36**, **#43** hotfix, **#44**). Authoritative doc: **`docs/modules/organic-rank-tracker-prd-v1_0.md`**.


**The model.** Keywords are **client-anchored** (a GSC property is optional). Source is auto-selected **per keyword**: **GSC** where the site ranks *and* GSC is connected; **DataForSEO (weekly)** otherwise — no accessible property, or the site doesn't rank for the term so GSC has nothing. DataForSEO writes `tracked_rank` only; **never reconciled** with GSC's averaged `gsc_position`. The weekly DataForSEO job skips GSC-covered keywords, so spend scales with the gaps.

**What shipped (PR #36):**
- **M1 connection** — service-account GSC (`gsc_properties`, verify-access). **M2 sync** — daily ingest → `gsc_query_daily` + `sync_runs`; the **in-process asyncio scheduler** (`services/gsc_scheduler.py`) is the **decided shared-scheduler mechanism** — enqueues jobs into `async_jobs`, reuse it for future trackers. **M3** — materialized null date-axis `rank_keyword_metrics` + computed status taxonomy (`rank_status.py` / `rank_materialize.py`); tabbed Overview/Keywords/Settings UI; **dependency-free SVG charts** (inverted-Y with visible gaps — no charting lib, React-19-safe). **M4** — `keyword_market` (CPC/volume/competition + est-monthly-value ROI), weekly query×page `gsc_query_page_daily` → canonical-URL resolution + Pages view, striking-distance discovery, deindex **URL Inspection** confirmation (`tracked_keywords.index_status`).
- New services: `gsc_service, gsc_ingest, gsc_scheduler, rank_status, rank_materialize, dataforseo_rank, keyword_market`; routers `gsc`, `rank`. Frontend `pages/Rankings.tsx` + `components/rankings/`.

**Follow-ups shipped same session:** historical GSC backfill (Settings, ~16mo), per-keyword **page breakdown** + "+N pages" chip, **canonical-URL pinning** UI, **CSV export**, **all actions opened to any authenticated team member** (no admin gates), keyword add via type/paste/**CSV import**, and a **per-client tracking location** (city/region/country via the existing `LocationAutocomplete` — `clients.rank_tracking_location[_code]`, PR #44) that drives the DataForSEO ranks + market data. GSC metrics stay national-aggregate (Google limitation); geo-grid local-pack is Module #5.

**⚠️ Production incident (PR #43) — lesson logged.** Merging #36 crash-looped **all of platform-api** on startup: two `DELETE` endpoints used `status_code=204` with a `-> None` return, which **FastAPI 0.115.0 (the pinned prod version)** rejects at import (`AssertionError: Status code 204 must not have a response body`). The sandbox's *newer* FastAPI didn't surface it. Fixed to match the codebase's working pattern (`routers/users.py`: `response_class=Response`, return `Response(status_code=204)`). **Lesson: verify imports/tests against the *pinned* `requirements.txt` versions, not whatever the sandbox happens to have** — done for all later work (198 tests pass on `fastapi==0.115.0` / `pydantic==2.9.2`). Prod recovery confirmed via Railway logs (clean startup, `gsc_scheduler.started`).

**Migrations (all applied to `wvcthtmmcmhkybcesirb`; filenames reconciled to the apply-time recorded versions per `MIGRATIONS.md`):** `…181919_gsc_properties`, `…181933_gsc_ingest_storage`, `…183357_rank_tracker_keywords`, `…185307_keywords_client_anchor`, `…185948_keyword_market`, `…191240_gsc_query_page_daily`, `…191831_keyword_index_status`, `…203200_sie_cache_enable_rls`, `…211331_clients_rank_tracking_location`. All RLS-on, **no client-facing policies** (service-role only — the `async_jobs` pattern).

**Housekeeping done:** `CLAUDE.md` updated (rank-tracker current state, services/routers, the resolved scheduler decision, `GOOGLE_SERVICE_ACCOUNT_KEY` note); **`public.sie_cache` RLS enabled** — closes the long-standing §8 advisory item (was disabled on the live DB despite the original migration; service-role-only, no policies); migration ledger + reconciliation log updated in `writer/supabase/MIGRATIONS.md`.

**⚠️ Provisioning still required for the GSC path:** set **`GOOGLE_SERVICE_ACCOUNT_KEY`** (full service-account key JSON) on the **PLATFORM** Railway service, and create the GCP service account + enable the **Search Console API** (a dashboard step — confirm with the user). Until then the tracker runs **DataForSEO-only** (works **today** — DataForSEO creds were already set on PLATFORM); GSC verify/ingest/URL-Inspection show a "not configured" state.

**Still pending by design:**
- **Alerting** (deindex/drop → email/Slack/in-app) — gated on the **notifications-channel decision** (in-app feed vs email/Slack + provider/webhook details). The detection (`deindex_risk`/`dropping` status) already runs; only the outbound hook is unbuilt.
- **Module #5 — Maps / local-pack ranker** (geo-grid). This is the *only* thing the per-client tracking location does **not** cover — the organic tracker is national/city point-in-time SERP, not a grid of points around a business.

**Verified & deployed:** backend **198 tests** on the pinned stack; frontend `npm run build` clean. Production confirmed live from the latest commit — PLATFORM (Railway) clean startup, `ar-internal.netlify.app` deploy `ready` on `d353afa`. (Tell users to **hard-refresh** to clear the cached bundle.)

---

## ⏩ Update — 2026-06-22 (supersedes the TextRazor open items in §3/§6/§7 below)

TextRazor is **live, calibrated, and secured**, and the **Local SEO module is feature-complete** (location autocomplete, SERP caching, page templates, Google-Doc publishing). All of today's work is merged to `main` and deployed (PRs #23–#33).

**TextRazor — done.**
- **Activated:** `TEXTRAZOR_API_KEY` had been *staged* (not committed) — committed via Railway `accept-deploy` + redeploy. nlp startup now logs `TEXTRAZOR_API_KEY is set`.
- **Concurrency bug fixed (#25):** live runs returned 0 entities — TextRazor's per-plan concurrent-request cap rejected all-but-~2 of the per-page fan-out with `401`. `fetch_textrazor_entities` now runs behind an `asyncio.Semaphore` (`TEXTRAZOR_MAX_CONCURRENCY`, default 2) + retries 401/403/429 with backoff. A real `roof restoration` / Melbourne analyze then returned all 13 pages `200` → **5 entities**.
- **Calibration:** distribution `[0.93, 0.53, 0.44, 0.35, 0.12]`. `TEXTRAZOR_MIN_RELEVANCE` **kept at the default 0.1** — the page-spread filter is the dominant signal and 5 is a healthy, focused set; no env change needed. (One-keyword sample; revisit if more keywords show noise.)
- **Key NOT rotated** — user deferred (§6.2 still open if desired).

**Security / cost (§6) — closed.**
- nlp **public domain removed** → private-only (`nlp.railway.internal`; PLATFORM already used that). No more internet-exposed auth-less nlp.
- `GOOGLE_NLP_API_KEY` **removed** from nlp (unused post-swap). Redeploy verified healthy.

**Local SEO location robustness (#23, #24) — new.** Mistyped areas silently degraded generation (DataForSEO `200` + 0 results → no competitors, no TextRazor). Fixed with: an **area typeahead** (`GET /clients/{id}/local-seo/locations`, DataForSEO `locations/{country}` scoped to the client's country, in-memory cached — `services/locations_service.py`); a **server-side validation backstop** (`resolve_location`: trust a picked `location_code`, else match the typed name → attach code, else `400` + suggestions); and `location_code` threaded through the **generate** path (`GeneratePageRequest` + its inline analysis — previously dropped). Frontend `LocationAutocomplete` combobox + DataForSEO task-error diagnostics. Tests: platform-api **91 passing**.

**UI (#26).** The localseo `Spinner` never animated because `index.css` (which declares the `spin` keyframe) **isn't imported anywhere** in the app; the Spinner now injects its own keyframe. Analyze/check buttons show "Analyzing competitors…".

**SERP analysis caching (#29) + review hardening (#30).** SERP analysis (DataForSEO+ScrapeOwl+TextRazor, ~20 pages, 2–4 min) was re-run on every analyze/score/generate. It depends only on (keyword, location), so it's now cached and **shared across clients**. `keyword_analyses` table (migration `20260622120000`, RLS-on/service-role-only); `services/analysis_cache.py` with a **14-day TTL** (`analysis_cache_ttl_days`, 0 disables); `_get_or_compute_analysis` used by analyze/generate/score (generate & score pass the cached analysis to nlp so it skips its inline re-scrape); a **`force_refresh`** flag + "Refresh competitor data" checkbox. Review hardening (#30): generate/score **degrade gracefully** when analysis can't be computed (don't hard-fail — `required=False`), `analyze` still propagates; **single-flight** lock collapses concurrent identical misses; cache hits flagged `from_cache` with cost zeroed; idempotent migration; `score` forwards `user_id`.

**Local SEO Phase 3 — page template (#31).** Mirror an existing page's section structure: per-page field + optional **per-client default** (`clients.local_seo_page_template_url`, migration `20260622140000`). nlp `GeneratePageRequest.page_template_url`/`_html`; `_extract_template_outline` scrapes the reference (SSRF-guarded) → H1/H2/H3 outline → injected as a STRUCTURE-OVERRIDE block that supersedes the default 13 sections while keeping AEO rules + JSON-LD; degrades to default if unfetchable. `PUT /clients/{id}/local-seo/page-template-default`.

**Local SEO publishing (#33).** Generated pages now **publish to a Google Doc in the client's Drive folder**, reusing the blog writer's Apps Script webhook (the locked publish destination). `services/html_to_markdown.py` (stdlib HTML→Markdown, no new dep) → `publish_page` POSTs to `GOOGLE_APPS_SCRIPT_URL` with the client's `google_drive_folder_id` → persists `published_doc_id/url/at` (migration `20260622150000`, additive — the in-app page is the source of truth and is unchanged). `POST /local-seo/pages/{id}/publish`; "Publish to Google Doc" / "View Google Doc" in the page view. Prereq: client must have a Drive folder set (Client → Edit), accessible to the Apps Script's Google account.

**Local SEO module is now feature-complete.** Verified our nlp `/generate-page` writer matches the ShowUP Local `CONTENT_WRITER` spec (13 sections, 14 AEO rules, Sonnet 4.6 @ 16k, 8-engine 85/15 scoring, RDFa/JSON-LD) — only deltas are the intentional suite adaptations (TextRazor, no billing, auth at platform layer, caching, location_code). Reoptimizer + GBP-social-posts paths traced end-to-end and confirmed wired (GBP posts are **generate-only** — not auto-posted to Google Business Profile).

**Tests:** platform-api **118 passing** (analysis_cache, locations, page-template, html_to_markdown, publish, degrade/single-flight units).

**New debt / still open.**
- `index.css` unimported → base resets (`box-sizing`, `margin:0`) don't apply suite-wide — left as-is (importing would shift layouts); decide separately.
- TextRazor key rotation still deferred.
- **Local SEO live-verification debt:** only `analyze` + `generate` are live-proven. Not yet live-tested: score, reoptimize, find-page, related-pages, GBP social posts, page-template, **publish**.
- Reoptimize doesn't reuse the SERP cache; some entry paths reoptimize without SERP context (degrades, not breaks). `score` force-refresh not exposed in UI. No DOMPurify on rendered HTML (first-party).
- Not built (out of v1 / separate): **GBP post auto-publishing**, live-CMS/WordPress publishing.
- Everything in §8 below still stands.

---

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
