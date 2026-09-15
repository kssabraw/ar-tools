# PAA → SEO Neo — build handoff (module-scoped)

> Companion to `CLAUDE.md` in this folder. This tracks **current state, open
> decisions, and next action** for the PAA → SEO Neo initiative. Root `/HANDOFF.md`
> is the suite-wide changelog; this file is scoped to this initiative.

## Status (2026-09-15) — SCOPE SETTLED · PLAN WRITTEN · STILL NO CODE

- **The whole external corpus has been read and analyzed** (except SOP 07c, Video —
  not provided). A complete "how it all works together" synthesis exists.
- **The master reference is committed:** `docs/reference/paa-seo-neo-master-reference.md`
  — a single **de-branded** synthesis (all source/person/group names removed;
  confidence tags + gray-hat caveat preserved). In **PR [#1110](https://github.com/kssabraw/ar-tools/pull/1110)** (draft, **unmerged**).
- **The four open decisions are settled** (owner, 2026-09-15) — see below.
- **The plan is written:** `docs/modules/paa-seo-neo-prd-v1_0.md` — reuse-verified
  against current code (§7), v1 = the content half, link layer track/cost/QA only,
  audio/video checklist-only, confidence tags carried.
- There is still **no schema, no code, no config, no migration** — the PRD is a plan,
  not a build. Nothing is wired into any agent (`sop_library` still never reads the
  reference).

## What exists vs. what's missing

**In the repo:**
- `docs/reference/paa-seo-neo-master-reference.md` — the master synthesis.
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

## Next action

- **Owner reviews `docs/modules/paa-seo-neo-prd-v1_0.md`** and greenlights (or
  redirects) the v1 build order (§10). Do **not** start implementation code, a
  migration, or agent wiring until that approval — this session is plan-only.

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
- [ ] Owner reviews + greenlights the v1 build order (§10). No code until then.
