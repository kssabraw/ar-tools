# PAA → SEO Neo — build orientation (module-scoped)

> **This is a module-scoped brief, not the suite authority.** The root
> `/CLAUDE.md` remains the suite's authoritative context and conventions — read
> it first. This file orients work on the **PAA → SEO Neo** initiative: adapting
> an external local-SEO content methodology into suite tooling. The initiative is
> **at the analysis/planning stage — there is no PRD, no build, and no code yet.**
> Current state + open decisions live in the module `HANDOFF.md` next to this file.

## Read these first, in order

1. **`/CLAUDE.md`** (root) — suite context, stack decisions, conventions, the
   things-not-to-do list. Non-negotiable.
2. **`docs/reference/paa-seo-neo-master-reference.md`** — the **de-branded master
   synthesis** of the whole methodology (the two layers, the PAA join key, the
   seven seam bolts, the fixed order, the authority supply chain, the
   confidence/risk map, and a source-doc index). This is the domain authority for
   the initiative. Committed in PR [#1110](https://github.com/kssabraw/ar-tools/pull/1110) (draft).
3. **`docs/modules/paa-seo-neo/HANDOFF.md`** (next to this file) — current state,
   open decisions blocking the plan, and next action.
4. **The suite-mapping** below — which existing suite modules already cover parts
   of the methodology (so a plan reuses, not rebuilds).

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
mostly **off-platform, third-party, and partly gray/black-hat**. The scope of what
the suite should actually *build* is **not yet decided** — that is what the plan
(next) settles. See the master reference for the full system; see the HANDOFF for
the open scope decisions.

## Suite-mapping (candidates for reuse — NOT yet verified against code)

The methodology's steps map onto existing suite modules. A plan should reuse these
rather than rebuild. (Verify each against current code before relying on it.)

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
- Don't build anything before the plan/PRD exists and the scope + off-platform
  boundary are owner-confirmed (this file is scaffolding, not a green light).
- Don't wire this into any agent loader — the master reference lives in
  `docs/reference/` precisely so `sop_library` never ingests it.
- Don't design the suite to run or "automate" the link-layer blasts.
