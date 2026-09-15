# PAA → SEO Neo — build handoff (module-scoped)

> Companion to `CLAUDE.md` in this folder. This tracks **current state, open
> decisions, and next action** for the PAA → SEO Neo initiative. Root `/HANDOFF.md`
> is the suite-wide changelog; this file is scoped to this initiative.

## Status (2026-09-15) — Phase 2 (prep-sheet manifest) BUILT · draft PR · migration applied live

> **Phase 2 — the prep-sheet manifest + link-layer track/cost/QA (the "seam")** is
> built to the PRD §11 build order on branch `claude/paa-seo-neo-phase2-manifest`
> (draft PR). The owner settled the four Phase-2 design forks and greenlit the build
> (2026-09-15). What shipped:
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

## Next action — Phase 2 SHIPPED (draft PR); the next build is Phase 3 (needs its own owner greenlight)

Phase 2 (the prep-sheet manifest) is built to PRD §11 on
`claude/paa-seo-neo-phase2-manifest` (draft PR; migration applied live). **A merged
phase is not a greenlight for the next** — Phase 3 is its own scoped build the owner
greenlights separately (PRD §6). Do NOT start Phase 3 unprompted.

**Phase 3 — the Service PAA Campaign object + the automated single-variable gate.**
The full orchestration: target service → PAA set → blog runs → GBP posts →
syndication → manifest → an **automated** scan→moved/drill/HALT gate (v1 documents
this as a *manual* workflow — see `single-variable-scan-verify-workflow.md`) →
tracked link-layer bundle → re-scan on cadence. Introduces the campaign state
machine; reuses response-episodes for the verify loop.

**Permanent guardrails (never, any phase — PRD §9):** the suite never executes link
blasts (SEO Neo / GMBB Blast / RD 100 / Omega / PBNs); no audio/video/influencer
generator (checklist rows only); the master reference is never wired into
`sop_library`; anything user-facing carries the `[PROVEN]`/`[THEORY]`/`[BELIEF]`
confidence tags.

**When Phase 2 IS greenlit, the v1 seams to build on:** `services/paa_sets_service.py`
already links each PAA item to its `run_id` + `gbp_post_id` + `post_url` (the raw
material a manifest collects); `recipe_engine.py` already costs the RD-family / GBP
Blast / DAS work; the QA Agent + `docs/sops/` playbooks exist. Read PRD §5 (the seam
preview) + §6 (phasing) first.

## Gotchas (specific to this initiative)

- **The master reference's `§11 Document map` and `§12 gaps` point at source files
  that are not in the repo.** They're forward pointers to the owner's corpus, not
  broken in-repo links — by design.
- **Numeric vs descriptive SOP naming.** The source uses numeric SOPs (04b, 05,
  07c…); the repo's own SOP library (`docs/sops/`) uses descriptive filenames. If
  any source SOP is ever imported, reconcile the naming + cross-refs in one pass.
- **CI note (unrelated to this initiative):** `test_pace_interventions.py::test_decide_scan_action_lifecycle`
  is a known date-dependent test that has intermittently gone red on `main` (it was
  cited as red on PR #1110's docs-only pytest). It **passed** in PR #1117's CI and
  locally on 2026-09-15 (full platform-api suite green, 6016 passed), so it did not
  affect the v1 build — but treat it as a latent date-bomb, not a stable green.

## Definition of done (for THIS handoff step)

- [x] Full corpus read + analyzed (minus SOP 07c).
- [x] De-branded master reference committed (`docs/reference/…`, PR #1110).
- [x] Module scaffolding (`CLAUDE.md` + `HANDOFF.md`) created.
- [x] Owner settles the four open decisions above.
- [x] Plan / PRD written for the chosen v1 scope (`docs/modules/paa-seo-neo-prd-v1_0.md`).
- [x] Owner greenlit the v1 build order (§10), 2026-09-15.
- [x] **v1 built** — the content half, per §10 (migration applied live; content
      surface + writer constraints + cannibalization guard + create-posts action +
      scan/verify doc + tests; on `claude/paa-seo-neo-v1-build-vakcd3`).
