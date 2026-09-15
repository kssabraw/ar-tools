# PAA → SEO Neo — build handoff (module-scoped)

> Companion to `CLAUDE.md` in this folder. This tracks **current state, open
> decisions, and next action** for the PAA → SEO Neo initiative. Root `/HANDOFF.md`
> is the suite-wide changelog; this file is scoped to this initiative.

## Status (2026-09-15) — Phase 3 (Service PAA Campaign + automated gate) BUILT · MERGED (PR #1125) · ships DARK

> **Phase 3 — the Service PAA Campaign object + the automated single-variable
> gate** is built to the PRD §12 build order (owner greenlit 2026-09-15; the four
> §12.2 forks locked below) and **merged to `main`** (PR
> [#1125](https://github.com/kssabraw/ar-tools/pull/1125); CI green — platform-api
> pytest + ruff/mypy + Netlify preview). It **ships DARK** behind
> `paa_campaign_enabled` (default off), so merging changed nothing until the owner
> flips the flag. What shipped:
> - **Locked forks (owner):** (1) autonomy = **hybrid propose-confirm** (the two
>   paid/content steps — the geo-grid scan + a drill round — are human-confirmed;
>   everything else auto-advances); (2) campaign **1:1 with one paa_set**, drilling
>   adds `drill_level` items to the SAME set (Phase-2 manifest reused unchanged);
>   (3) the service keyword is **auto-added to the Maps tracker** on campaign start;
>   (4) ships behind **`paa_campaign_enabled` (default off — dark)**. Smaller
>   defaults: maintenance re-scan **piggybacks scheduled scans** ($0); drill via
>   **PAA re-pull** (no LLM); **HALT = critical notification + best-effort
>   strategist escalation**.
> - **Data model** (migration `20260915170000_paa_campaigns.sql`, **applied live +
>   verified**): `paa_campaigns`
>   (1:1 `set_id` unique — state machine, drill_level, settle/next-action clocks,
>   baseline/current rank, last_scan_id, halted_reason, history log) +
>   `paa_items.drill_level`. **No new async-job type** (the sweep is inline; the
>   scan reuses `maps_scan`). RLS service-role.
> - **Pure core** `services/paa_campaign.py` (unit-tested `tests/test_paa_campaign.py`):
>   the gate evaluator (`evaluate_gate` → moved/drill/halt/no_data), cadence math,
>   the transition log, the next-action descriptor (confirm flags = the hybrid
>   posture), drill seeding, confidence-tagged copy.
> - **I/O** `services/paa_campaign_service.py` (`tests/test_paa_campaign_service.py`):
>   create (auto-add the Maps keyword + capture baseline), start (reuse v1
>   `create_posts`), the inline sweep `run_paa_campaign_sync()` (settle→scan_ready,
>   gate read over `maps_scan_results`, moved→maintenance + manifest refresh, HALT
>   notify + strategist escalation, rinse piggyback), confirm-scan (reuse
>   `enqueue_maps_scan`), propose/confirm-drill (reuse `pull_paa`).
> - **Scheduler** `_safe("paa_campaigns", run_paa_campaign_sync)` in the daily
>   block (self-gated). **API** `routers/paa.py` + `models/paa.py` (campaign CRUD,
>   start, confirm-scan, drill-preview/drill, reset — all 503 when the flag is off,
>   content steps freeze-gated). **Frontend** a **Campaign** panel on the PAA-set
>   detail (`pages/PaaSets.tsx`): state chip + next-action + the two confirm
>   buttons + the drill preview + a HALT banner + the timeline; renders nothing
>   when the flag is off. Config `paa_campaign_*`.
> - **Guardrails held (§9):** no authority execution (moved→handoff only builds the
>   Phase-2 manifest); no audio/video generator; the master reference is not wired
>   into `sop_library`; confidence tags in the UI; HALT is a STOP.
> - **Honest divergence (PRD §12.5):** `response_episodes` is alert-keyed/decline-
>   oriented, so the campaign carries its OWN settle/rinse clock (borrowing its
>   cadence constants) rather than force-fitting it; maintenance declines still
>   route through the existing episode machinery.
>
> **Activation (owner, when ready):** the migration is already applied live — just
> set `PAA_CAMPAIGN_ENABLED=true` on PLATFORM. **Not built (deferred):** full
> per-campaign autopilot (a future flag); auto-creating the next service's campaign.

## Prior status (2026-09-15) — Phase 2 (prep-sheet manifest) BUILT · MERGED (PR #1120) · migration applied live

> **Phase 2 — the prep-sheet manifest + link-layer track/cost/QA (the "seam")** is
> built to the PRD §11 build order and **merged to `main`** (PR
> [#1120](https://github.com/kssabraw/ar-tools/pull/1120), squash `813b323`; CI
> green — platform-api tests + lint/typecheck + Netlify preview). The owner settled
> the four Phase-2 design forks and greenlit the build (2026-09-15). What shipped:
> - **Data model** (migration `20260915160000_paa_manifests.sql`, **applied live +
>   verified**): `paa_manifests` (one per `paa_set`, unique `set_id`; roll-up
>   `cost_summary`/`qa_summary` + Sheet-export refs) + `paa_manifest_assets` (assets
>   first-class: `category` content/authority/media, `source` auto/seed/manual,
>   `qa_verdict`/`qa_review`, `cost_task_type`, `confidence_tag`). New `async_jobs`
>   type `paa_manifest_qa` (drift-proof CHECK widen). Both RLS-on, service-role.
> - **Pure core** `services/paa_manifest.py` (unit-tested `tests/test_paa_manifest.py`):
>   the seeded authority bundle (the 7 seam bolts, tracked-only, confidence-tagged),
>   the audio/video/influencer manual rows, content-row assembly from resolved v1
>   linkage, rebuild reconciliation (`merge_rows` — refresh auto rows, preserve
>   operator edits), the reused Recipe-Engine cost rollup (honest "not estimated"
>   for off-menu RD 100), the QA rollup, and the CSV/Sheet/JSON export rendering.
> - **I/O** `services/paa_manifest_service.py` (`tests/test_paa_manifest_service.py`):
>   build/refresh (resolves `runs.published_url` / `gbp_posts.search_url` /
>   syndication copies), asset CRUD, the `paa_manifest_qa` async job (reuses
>   `qa_service.review_url` per live content URL, gated on `qa_enabled` with v1's
>   deterministic checks as the free fallback), and the Google-Sheet export
>   (`google_docs.create_google_sheet` into the client's Drive folder).
> - **API** `routers/paa.py` (+ `models/paa.py`): build/get manifest, QA enqueue,
>   asset add/patch/delete, CSV/JSON export, Sheet export. **Frontend:** a **Prep
>   Sheet** section on the PAA-set detail expander (`pages/PaaSets.tsx`) — build/
>   rebuild, cost + QA summaries, the asset table grouped by category with editable
>   status on authority/media rows, Run QA, and the three export buttons.
> - **Guardrails held (§9):** no execute affordance on any authority row (status is
>   human-set only); no audio/video generator; the master reference is not wired into
>   `sop_library`; confidence tags carried into the UI + the export.
>
> **Not built (Phase 3):** the Service PAA Campaign object + the automated
> single-variable gate/verify state machine. Needs its own owner greenlight.

## Prior status (2026-09-15) — v1 (content half) BUILT · MERGED (PR #1117) · LIVE in production

> v1 is built to PRD §10, **merged to `main`** (PR [#1117](https://github.com/kssabraw/ar-tools/pull/1117), squash `9baaaa1`),
> and **verified live in production**: the `paa_sets` (11 cols) + `paa_items` (15
> cols) tables exist RLS-on in the Supabase project, and all six PAA routes are
> served by the live PLATFORM instance (checked against `/openapi.json` on the
> active deploy). The migration (`paa_sets` + `paa_items`) is **applied live**.
> What shipped: the two tables; a **PAA
> Content** card in the workspace "Content Creation" section → `/clients/:id/paa-sets`
> (pull PAA via `keyword_research_serp` → select ~4 → save); the three writer
> constraints (`services/paa_seo.compose_writer_notes` on the reused `writer_notes`
> seam + deterministic `check_exact_match` / `service_link_verdict` reusing
> `local_seo_matrix.check_internal_links`); the cannibalization guard
> (`site_page_index` token match + `local_seo_matrix.scale_gates` /
> `MATRIX_SIGNOFF_THRESHOLD`); the "create PAA posts" action (N blog runs + best-effort
> GBP drafts + syndication refresh, all seeded from the exact PAA string); the manual
> scan/verify workflow doc (`single-variable-scan-verify-workflow.md`); and pure +
> enforcement tests (`tests/test_paa_seo.py`, `tests/test_paa_sets_service.py`). No
> feature flag (a plain content surface). Guardrails (§9) held: nothing touches the
> SEO Neo authority layer, no `sop_library` wiring, no audio/video generator.

## Prior status (2026-09-15) — PLAN MERGED · DECISIONS LOCKED · BUILD GREENLIT (v1 = content half)

- **The whole external corpus has been read and analyzed** (except SOP 07c, Video —
  not provided). A complete "how it all works together" synthesis exists.
- **The master reference is on `main`:** `docs/reference/paa-seo-neo-master-reference.md`
  — a single **de-branded** synthesis (all source/person/group names removed;
  confidence tags + gray-hat caveat preserved). Merged in **PR [#1110](https://github.com/kssabraw/ar-tools/pull/1110)**.
- **The plan is on `main`:** `docs/modules/paa-seo-neo-prd-v1_0.md` — reuse-verified
  against current code (§7), v1 = the content half, link layer track/cost/QA only,
  audio/video checklist-only, confidence tags carried. Merged in **PR #1110**.
- **The four §8 design forks are settled** (owner, 2026-09-15) and reflected in the
  PRD (§4.1/§4.2/§8) — merged in **PR [#1112](https://github.com/kssabraw/ar-tools/pull/1112)**. See "§8 design forks — LOCKED" below.
- There is still **no schema, no code, no config, no migration** — nothing built yet.
  Nothing is wired into any agent (`sop_library` still never reads the reference).
- **The owner GREENLIT the v1 build (2026-09-15).** The next session builds v1 (the
  content half) to the PRD's **§10 build order** — schema first. See "Next action".

## What exists vs. what's missing

**In the repo (all on `main`):**
- `docs/reference/paa-seo-neo-master-reference.md` — the master synthesis.
- `docs/modules/paa-seo-neo-prd-v1_0.md` — the plan (v1 = content half; §8 forks locked).
- `docs/modules/paa-seo-neo/CLAUDE.md` + this `HANDOFF.md` — scaffolding.

**NOT in the repo (owner's uploads only — deliberately not committed):**
- The numbered source SOPs (01–15) + 07b (podcast) + 13b (footage/influencer).
- The `AI-CONTEXT_why-*` reasoning docs (whole-system, PAA, SEO Neo, seam, podcasts)
  and the integrated playbook.
- These were briefly added to `docs/sops/` + `docs/agents/reasoning/` this session,
  then **erased per owner ruling** ("we just need the one master document"). Do not
  re-add without an explicit ask.

**Genuinely missing from the source material:**
- **SOP 07c (Video)** — the production hub that supplies 07b's audio and 13b's
  footage. The one inferred (not sourced) seam.
- The **prep-sheet template** — referenced everywhere as the hand-off artifact,
  never provided as a file.

## Open decisions — SETTLED (owner, 2026-09-15)

1. **v1 scope → the content half first.** PAA set as a first-class research output +
   enforce the link-high / exact-match / one-question-one-post rules as writer
   constraints. (Full "Service PAA Campaign" object is deferred to Phase 3.)
2. **Off-platform boundary → track / cost / QA / manifest only.** The suite **never
   executes** link blasts (GMBB Blast, RD 100, SEO Neo, Omega, PBN). Confirmed as a
   permanent guardrail.
3. **Audio/video syndication → manual / checklist-tracked.** Never suite-generated.
4. **Plan delivery → the PRD doc** (`docs/modules/paa-seo-neo-prd-v1_0.md`).

## PRD §8 design forks — LOCKED (owner, 2026-09-15)

1. PAA Set home → **a new card in the workspace "Content Creation" section** (its own
   route; reuses `keyword_research_serp` for the pull) — not a Keyword Research tab.
2. Data model → **own tables `paa_sets` + `paa_items`** (one migration at build).
3. "Link high" service-page URL → **explicit field → `site_page_index` match → prompt.**
4. Naked vs geo PAA → **geo-modified default, `naked` per-set toggle** (`geo_mode`).

(Item 5 — the `keyword_research_serp` per-run PAA cap/cost — stays a build-time confirm.)

## Next action — Phase 3 MERGED (PR #1125); activate when the owner is ready

Phase 3 (the Service PAA Campaign + the automated single-variable gate) is built to
PRD §12 (owner greenlit + forks locked 2026-09-15) and **merged to `main`** (PR
[#1125](https://github.com/kssabraw/ar-tools/pull/1125); CI green). It ships **dark**
(default off), so nothing runs until the owner sets `PAA_CAMPAIGN_ENABLED=true` on
PLATFORM (the migration is already applied live). **The module's phased scope (§6) is
now complete** — the content half (v1), the prep-sheet manifest (Phase 2), and the
campaign object + automated gate (Phase 3) are all built and merged. Any further work
(full per-campaign autopilot; auto-creating the next-service campaign) is a new,
separately greenlit enhancement, not a continuation.

**Permanent guardrails (never, any phase — PRD §9):** the suite never executes link
blasts (SEO Neo / GMBB Blast / RD 100 / Omega / PBNs); no audio/video/influencer
generator (checklist rows only); the master reference is never wired into
`sop_library`; anything user-facing carries the `[PROVEN]`/`[THEORY]`/`[BELIEF]`
confidence tags.

**Seams Phase 3 built on (for reference):** the Phase-2 manifest
(`services/paa_manifest.py` + `services/paa_manifest_service.py`, tables
`paa_manifests`/`paa_manifest_assets`) is the campaign's asset ledger; the
single-variable gate reuses the **Maps geo-grid** single-keyword scan
(`local_dominator.enqueue_maps_scan` / `resolve_scan_keywords`) reading
`maps_scan_results`. The campaign carries its OWN settle/rinse clock (borrowing
`response_episodes`' cadence constants) rather than force-fitting that alert-keyed
table — see the honest divergence note in the status block above and PRD §12.5.

## Gotchas (specific to this initiative)

- **The master reference's `§11 Document map` and `§12 gaps` point at source files
  that are not in the repo.** They're forward pointers to the owner's corpus, not
  broken in-repo links — by design.
- **Numeric vs descriptive SOP naming.** The source uses numeric SOPs (04b, 05,
  07c…); the repo's own SOP library (`docs/sops/`) uses descriptive filenames. If
  any source SOP is ever imported, reconcile the naming + cross-refs in one pass.
- **CI note (unrelated to this initiative):** `test_pace_interventions.py::test_decide_scan_action_lifecycle`
  is a known date-dependent test that has intermittently gone red on `main` (it was
  cited as red on PR #1110's docs-only pytest). It **passed** in PR #1117's and
  PR #1120's CI and locally on 2026-09-15 (full platform-api suite green), so it did
  not affect either build — but treat it as a latent date-bomb, not a stable green.

## Definition of done

**v1 (the content half) + Phase 2 (the manifest) — DONE:**

- [x] Full corpus read + analyzed (minus SOP 07c).
- [x] De-branded master reference committed (`docs/reference/…`, PR #1110).
- [x] Module scaffolding (`CLAUDE.md` + `HANDOFF.md`) created.
- [x] Owner settled the four v1 decisions + greenlit the v1 build order (§10).
- [x] Plan / PRD written (`docs/modules/paa-seo-neo-prd-v1_0.md`; Phase-2 build order §11).
- [x] **v1 built + merged + live** — the content half (PR #1117, squash `9baaaa1`).
- [x] Owner settled the four Phase-2 forks + greenlit the Phase-2 build order (§11).
- [x] **Phase 2 built + merged** — the prep-sheet manifest (PR #1120, squash `813b323`;
      migration applied live; pure core + I/O + QA job + router + frontend + tests).

**Phase 3 (the campaign object + automated gate) — NOT STARTED** (needs its own
owner greenlight; see "Next action").
