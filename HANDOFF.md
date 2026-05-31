# AR Tools — Handoff

**Branch:** `claude/gracious-bell-BbkY5`
**Date:** 2026-05-31
**Scope of this handoff:** work done on this branch (4 commits ahead of `origin/main`), the current state of the suite, and prioritized next steps.

> Read `CLAUDE.md` first for project conventions and the authoritative current-state summary, and `docs/suite-architecture-and-roadmap-v1_0.md` for suite scope, the locked decision log, and the phased plan. This file is the working handoff that ties those together.

---

## 1. What this branch contains

Four commits, oldest → newest:

| Commit | Type | Summary |
|---|---|---|
| `9c9db32` | fix(db) | **Profiles RLS infinite recursion (42P17).** New migration `writer/supabase/migrations/20260531181719_fix_profiles_rls_recursion.sql` rewrites the recursive policy so admin-role checks on `profiles` no longer self-reference. Applied to the live Supabase project. |
| `4d9fbaa` | feat(frontend) | **"Roadmap" affordance in the client form.** `ClientForm.tsx` now visually marks client fields that exist in the schema but aren't yet consumed by any module, so the team isn't misled into thinking they do something today. |
| `17544e3` | feat(clients) | **Client logo upload.** Replaced the logo-URL text box with a real file uploader (see §2). |
| `35cdb54` | docs(claude) | **Full CLAUDE.md refresh** to reflect the multi-module suite as it actually stands (paths, doc filenames/versions, schema-version table, current-state vs. greenfield build order). |

All four are pushed to `origin/claude/gracious-bell-BbkY5`. **No PR has been opened** (none requested).

---

## 2. Logo upload — feature detail

Goal: make a client's logo a real uploaded image (shown on the dashboard tile + client workspace), instead of a pasted URL.

**Decisions taken (with the user):** Supabase Storage + URL in DB · upload-only field · store now, wire into published content later.

- **Storage:** new **public** bucket `client-logos` — restricted to `image/jpeg` + `image/png`, 2 MB cap. Public so the tile's `<img src>` renders without auth. Created live **and** committed as migration `20260531200317_client_logos_bucket.sql`.
- **Backend:** `POST /files/logo` (`writer/platform-api/routers/files.py`), **admin-gated**. Validates content-type (`422` otherwise) and size (`413` over 2 MB), uploads bytes to the bucket under a `{uuid}.{ext}` key via the service-role key, returns the public URL. New `LogoUploadResponse` model.
- **Frontend:** `api.ts` gained a multipart `upload()` helper (the existing one was JSON-only). `ClientForm.tsx` now has a file picker with live preview, Replace/Remove, client-side type+size validation, and inline errors. The returned URL flows through the existing `clients.logo_url` field on save.
- **Tile/workspace:** no change needed — `Home.tsx` and `ClientWorkspace.tsx` already render `logo_url`.

**Verified:** bucket config confirmed live; frontend `tsc --noEmit` clean; backend syntax-checked; storage calls match pinned `supabase==2.9.1` (storage3 0.8.x).

**Not done / caveats (carry forward):**
- ⚠️ **Not runtime-tested end-to-end** — container has no installed deps and can't drive a real upload. Smoke-test the first real upload in a deployed env.
- ⚠️ **No automated test added.** The repo's tests are pure service-logic units (`unittest.mock`); there's no FastAPI `TestClient` harness, and `/files/upload` has no test either. Starting that harness is a deliberate open choice, not an oversight.
- ⚠️ **Logo is stored, not yet consumed in content creation** (e.g. inserted into the published Google Doc). This was an explicit "later" per the product decision — see §4.

---

## 3. Current state of the suite (big picture)

**Built and working** (mostly already on `origin/main`):
- **Pipeline API** (`writer/pipeline-api/`): all five modules — `brief`, `sie`, `research`, `writer`, `sources_cited`.
- **Platform API** (`writer/platform-api/`): JWT auth; clients CRUD; file upload + parsing; website-scraper async worker (`job_worker` + `website_scraper` over `async_jobs`); orchestrator + run dispatch; run polling; briefs; silos (`silo_dedup`, `silo_promotion`); publish to Google Drive (`routers/publish.py`); users; **GBP** auto-fetch + review enrichment (`gbp_service`).
- **Frontend** (`frontend/`): `Login`, `Home` (suite tiles), `Clients`, `ClientForm`, `ClientWorkspace`, `Runs`, `RunDetail`, `Silos`, `Articles`.

**Imported, integration deferred:** `local-seo-writer/` (Local SEO content module, #2) — pick integration option A/B/C from roadmap **Appendix A** before adapting it.

**Not yet built:** Keyword research (#3, migrate), Organic rank tracker (#4), Maps/local-pack ranker (#5), Ranking-drop agent (#6), VA content scheduler (#7), plus the cross-cutting **GSC analytics layer**, the **shared scheduler**, the **SOP store**, and the **notifications service**.

Module `schema_version` source of truth is `writer/platform-api/services/orchestrator.py` (`EXPECTED_MODULE_VERSIONS`): brief `2.6`, sie `1.4`, research `1.1`, writer `1.7` (+ `-no-context`/`-degraded`), sources_cited `1.1`.

---

## 4. Immediate follow-ups (from this branch)

Small, well-scoped, do-next items:

1. **Smoke-test logo upload in a deployed env** — upload a JPG and a PNG via the client form; confirm the tile + workspace render it and the URL persists on the `clients` row. Confirm the `422`/`413` paths.
2. **Wire the logo into published content** (the deferred half) — insert `clients.logo_url` at the top of the generated Google Doc in `routers/publish.py` / the Apps Script webhook. Keep it optional (skip cleanly when `logo_url` is null).
3. **Decide on a `TestClient` test harness** — if yes, add happy-path + validation tests for `/files/logo` (mock storage + auth dependency) and backfill `/files/upload`. If no, note that endpoints are manually verified.
4. **Open a PR** when ready (not yet requested). If/when opened, consider subscribing the session to PR activity to auto-handle CI/review.

---

## 5. Bigger next steps (suite roadmap)

Per `docs/suite-architecture-and-roadmap-v1_0.md` §7:

- **Phase 0 — Foundation** (largely in place): dashboard shell + tiles, Blog Writer re-homed as a tab, `clients.logo_url` branding ✅. Remaining Phase 0 polish, if any, rides on the current dashboard.
- **Phase 1 — Data spine:** shared scheduler → rankings data model + DataForSEO organic tracker (#4) → GSC ingestion (`gsc_metrics`) + per-client performance view → Maps ranker (#5).
- **Phase 2 — Intelligence & automation:** Ranking-drop agent (#6) over SOP store + Phase 1 data; VA content scheduler (#7) driving auto-generate → publish-to-Drive.
- **Parallel migrations (any time):** Local SEO (#2) integration depth; Keyword research (#3) when its repo is provided.

---

## 6. Open decisions / blockers (need the user)

1. **Scheduler mechanism** (roadmap Open Item #1) — pg_cron vs Railway cron vs asyncio worker loop. **Must be decided before Phase 1**, and CLAUDE.md requires confirming before adding any queue/scheduler-like infra.
2. **Maps geo-grid density** — points per location; primary DataForSEO cost driver.
3. **Notification channels** — email provider + Slack workspace/webhook details (for the alerts service).
4. **Local SEO integration option** — A/B/C from Appendix A.
5. **Keyword research repo** — stack/data-model fit unknown until shared.
6. **CI/tests policy** — automated tests on push vs. manual (also gates whether to build the `TestClient` harness).

---

## 7. Minor known debt / loose ends

- Writer-module PRD's *canonical header version* wasn't verified during the CLAUDE.md refresh — the doc list says "check the header." Worth pinning exact versions across `docs/modules/` in a future pass.
- `README.md` lists a `/kw-research` location that doesn't exist yet (aspirational). Reconcile when #3 lands.
- **Migration version reconciliation (partly done).** This branch's two migrations are now named to exactly match their live `supabase_migrations.schema_migrations` versions (`20260531181719_fix_profiles_rls_recursion`, `20260531200317_client_logos_bucket`), so the Supabase CLI sees them as already-applied. **Still divergent (pre-existing, not touched here):** older local migrations on `main` use hand-authored `YYYYMMDD120000`-style timestamps that don't match their live versions (e.g. `clients_gbp` is `20260530003510` live vs `20260530120000` local), and the live DB has migrations with **no local file** (`keyword_metrics`, `session_cost_breakdown`, `csv_exports`, `session_archive`) from other branches/sessions. A full repo↔remote migration reconciliation is a separate task — decide on a convention (real UTC timestamps at author time) before doing it.
