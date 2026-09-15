# PAA → SEO Neo — build orientation (module-scoped)

> **This is a module-scoped brief, not the suite authority.** The root
> `/CLAUDE.md` remains the suite's authoritative context and conventions — read
> it first. This file orients work on the **PAA → SEO Neo** initiative: adapting
> an external local-SEO content methodology into suite tooling. **v1 (the CONTENT
> HALF) is BUILT, merged, and LIVE in production**; **Phase 2 (the prep-sheet
> manifest — track / cost / QA / hand-off) is BUILT + MERGED** (PR
> [#1120](https://github.com/kssabraw/ar-tools/pull/1120), squash `813b323`; migration
> applied live) — see the module `HANDOFF.md`. PR [#1117](https://github.com/kssabraw/ar-tools/pull/1117), 2026-09-15:
> the `paa_sets` + `paa_items` tables (migration applied live), a PAA Content card
> in the workspace "Content Creation" section → `/clients/:id/paa-sets`, the three
> writing rules as reused writer constraints, the cannibalization guard, the
> "create PAA posts" action, and the manual scan/verify workflow doc. Tables +
> routes verified live in production (Supabase + PLATFORM `/openapi.json`). What
> shipped, the seams it reused, and the deferred phases live in the module
> `HANDOFF.md` next to this file. **The authority layer (SEO Neo / link blasts)
> remains OUT of scope and is never executed by the suite** (guardrails below).

## Read these first, in order

1. **`/CLAUDE.md`** (root) — suite context, stack decisions, conventions, the
   things-not-to-do list. Non-negotiable.
2. **`docs/reference/paa-seo-neo-master-reference.md`** — the **de-branded master
   synthesis** of the whole methodology (the two layers, the PAA join key, the
   seven seam bolts, the fixed order, the authority supply chain, the
   confidence/risk map, and a source-doc index). This is the domain authority for
   the initiative. On `main` (PR [#1110](https://github.com/kssabraw/ar-tools/pull/1110)).
3. **`docs/modules/paa-seo-neo-prd-v1_0.md`** — **the plan** (v1 = the content half;
   the reuse map verified against code in §7; the four §8 design forks now locked).
   This is the authority for *what v1 builds*. On `main` (PRs #1110 + [#1112](https://github.com/kssabraw/ar-tools/pull/1112)).
4. **`docs/modules/paa-seo-neo/HANDOFF.md`** (next to this file) — current state, the
   locked decisions, and the next action (owner greenlight of §10).
5. **The suite-mapping** below — which existing suite modules already cover parts
   of the methodology (verified against code in PRD §7 — the table below is the
   quick orientation; PRD §7 carries the verified anchors).

> ⚠️ The methodology's **source corpus** (the numbered SOPs 01–15, 07b/13b, and
> the `AI-CONTEXT_why-*` reasoning docs) is **NOT in this repo** — it lives in the
> owner's uploads. Only the single de-branded master reference (item 2) is
> committed. Earlier this session those source SOPs + reasoning docs were added to
> `docs/sops/` and `docs/agents/reasoning/` and then **erased per owner ruling** —
> *do not re-add them* unless explicitly asked. Cross-references in the master
> reference to those files are forward pointers, not in-repo links.

## What this initiative is (one paragraph)

An effort to build suite tooling around a **two-layer local-SEO content
methodology**: a **PAA content layer** (answer the exact question a buyer types,
one page per question, link high to the service page, syndicate across formats)
and an **SEO Neo authority layer** (links/trust that make the content rank). The
suite already automates large parts of the content layer; the authority layer is
mostly **off-platform, third-party, and partly gray/black-hat**. The scope is now
**decided**: v1 = the **content half** (a first-class PAA Set + the three writing
rules as reused writer constraints); the authority layer is **track / cost / QA /
manifest only, never executed**, and lands in a later phase. See the master
reference for the full system, the **PRD** for what v1 builds, and the HANDOFF for
the locked decisions.

## Suite-mapping (candidates for reuse — VERIFIED against code in PRD §7)

The methodology's steps map onto existing suite modules; v1 reuses these rather than
rebuild. The table below is quick orientation — **PRD §7 carries the verified code
anchors** (each row was checked against the current tree, 2026-09-15).

| Methodology step | Existing suite module (candidate) |
|---|---|
| PAA research (People Also Ask, geo-set) | Keyword Research SERP enrichment already pulls PAA (`services/keyword_research_serp.py`) |
| Blog per PAA (+ the "link high to the service page" rule) | Blog Writer pipeline (`writer/pipeline-api/`) + `writer_notes` seam |
| GBP post → blog | **GBP Posts** module (built, gated) |
| Social/content syndication | **Content Syndication** module |
| Cannibalization guard (the "~1,000 neighborhood pages" failure) | Local SEO **matrix scale gates** + content-word-set existing-page matching (#951/#953) |
| Single-variable re-scan / measurement | **Maps geo-grid** (Local Dominator) — already run single-variable |
| The verify/refresh cadence loop | **Response-episode tracking** |
| Costing/assigning the link-layer work | **Recipe Engine** (already costs SEO NEO / RD100 / GBP Blast) |
| The "prep sheet" hand-off (URL manifest) | **Not modeled** — the clearest net-new data object |
| Podcast/audio + video + influencer production | **No suite equivalent** — off-platform, human-proofed (07b/07c/13b) |

## Hard boundaries / guardrails (load-bearing — settle these in the plan, don't drift)

- **The suite NEVER executes link blasts.** GMBB Blast, RD 100, SEO Neo runs, Omega
  indexing, PBN/parasite building are **off-platform vendor work**. The suite's
  role is at most **track / cost / QA / hand off a manifest** — never run them.
  (Owner to confirm in the plan; treat as the default until told otherwise.)
- **Gray/black-hat tactics are out of scope for suite automation** — PBNs, spun
  tier content, directional-URL blasting, footprint management, parasites/EMDs.
  The suite prefers the white-hat path (real content, real citations, PRs, genuine
  engagement) where a choice exists.
- **Audio/video syndication stays manual.** Pictory / SoundCloud / Podbean /
  NotebookLM require human proofing and have no suite equivalent — track as a
  checklist, do not build a generator (low ROI, real risk).
- **Carry the confidence tags.** The methodology is one group's working model, not
  Google guidance; some of it is `[THEORY]`/`[BELIEF]` and disputed (e.g. the
  RD-100 100:1 rule). Any recommendation the suite makes from it must preserve
  those tags, never present them as settled best practice.

## Don't

- Don't re-add the source SOPs (07b/13b, 01–15) or the `AI-CONTEXT_why-*` reasoning
  docs to the repo — they were deliberately erased; only the master reference stays.
- Don't re-litigate locked scope or rebuild what shipped. v1 (the content half) is
  built + live (PR #1117); Phase 2 (the prep-sheet manifest — track/cost/QA/hand-off)
  is built + merged (PR #1120, PRD §11). Future work is **Phase 3** (the campaign
  object + the automated single-variable gate). Each phase needs its own owner
  greenlight before building — a merged/built phase is not a greenlight for the next.
- Don't wire this into any agent loader — the master reference lives in
  `docs/reference/` precisely so `sop_library` never ingests it.
- Don't design the suite to run or "automate" the link-layer blasts.
