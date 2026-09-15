# PAA → SEO Neo — build handoff (module-scoped)

> Companion to `CLAUDE.md` in this folder. This tracks **current state, open
> decisions, and next action** for the PAA → SEO Neo initiative. Root `/HANDOFF.md`
> is the suite-wide changelog; this file is scoped to this initiative.

## Status (2026-09-15) — PLAN MERGED · DECISIONS LOCKED · BUILD GREENLIT (v1 = content half)

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

## Next action — BUILD v1 (in a fresh build session)

Greenlit. Build the **content half** to PRD §10, on a fresh feature branch off the
latest `main`, following suite conventions. Order:

1. `paa_sets` + `paa_items` migration (`writer/supabase/migrations/`; fields per PRD
   §4.1 — incl. `geo_mode` default `geo`, nullable `service_page_url`, item `slug` +
   nullable `run_id`/`post_url`).
2. The PAA-set card in the workspace **Content Creation** section (`ClientWorkspace.tsx`),
   own route (e.g. `/clients/:id/paa-sets`): pull PAA (reuse `keyword_research_serp`)
   → select ~4 → save.
3. The three writer constraints (reuse `writer_notes` + a deterministic title/H2 check
   + the `local_seo_matrix.ensure_internal_links` pattern for the service-page link).
4. Cannibalization guard (reuse `site_page_index` token match + `local_seo_matrix`
   `scale_gates` / `MATRIX_SIGNOFF_THRESHOLD`).
5. The "create the PAA posts" action → N blog runs + matching GBP posts + syndication,
   all seeded from the exact PAA string.
6. Document the manual single-variable scan/verify workflow (Maps geo-grid +
   response-episodes) — no new state machine in v1.
7. Tests: pure helpers + the writer-constraint enforcement, mocked per `tests/`.

**Do NOT drift into later phases** — no prep-sheet manifest, no link-layer
tracking/costing/QA, no campaign object/automated gate, no audio/video generator, no
`sop_library` wiring. Guardrails in the PRD §9 are permanent.

## Gotchas (specific to this initiative)

- **The master reference's `§11 Document map` and `§12 gaps` point at source files
  that are not in the repo.** They're forward pointers to the owner's corpus, not
  broken in-repo links — by design.
- **Numeric vs descriptive SOP naming.** The source uses numeric SOPs (04b, 05,
  07c…); the repo's own SOP library (`docs/sops/`) uses descriptive filenames. If
  any source SOP is ever imported, reconcile the naming + cross-refs in one pass.
- **CI note (unrelated to this initiative):** `pytest` is red on `main` due to a
  pre-existing date-dependent test (`test_pace_interventions.py::test_decide_scan_action_lifecycle`,
  fails on every PR from 2026-09-15). PR #1110's red pytest is that, not the docs.
  The one-line fix is known but intentionally not bundled (owner wanted only the
  master doc).

## Definition of done (for THIS handoff step)

- [x] Full corpus read + analyzed (minus SOP 07c).
- [x] De-branded master reference committed (`docs/reference/…`, PR #1110).
- [x] Module scaffolding (`CLAUDE.md` + `HANDOFF.md`) created.
- [x] Owner settles the four open decisions above.
- [x] Plan / PRD written for the chosen v1 scope (`docs/modules/paa-seo-neo-prd-v1_0.md`).
- [x] Owner greenlit the v1 build order (§10), 2026-09-15.
- [ ] **v1 built** — the content half, per §10 (next session; schema first).
