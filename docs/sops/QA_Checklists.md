# QA Checklists — Deliverable Acceptance Criteria

**Current as of:** 12 July 2026
**Status:** 🚧 DRAFT — first-pass criteria captured from the owner's brain dump.
A few items flagged **⟨OPEN⟩** need one more answer before they're final.
**Purpose:** The human-authored acceptance bar the **QA Agent** grades each task
deliverable against — the "layer 2" standard (what a verdict *means* + what blocks),
distinct from the executable scorers that measure on-page content.
**Scope:** Per-task-type acceptance criteria for deliverables the automated on-page
scorer does **not** cover. On-page content (pages/blogs) is already governed by
`On_Page_Criteria_and_Coverage.md` — this doc only adds what that one can't see.

> **Cross-references:** module plan → `docs/modules/qa-agent-plan-v1_0.md` §3b
> (grounding & QA SOPs) · executable rubric → `On_Page_Criteria_and_Coverage.md`
> (bands, `<80` blocking-deficiency rule, verdict→action routing) · structural
> fidelity → `services/page_structure_eval.py` · task types → the live
> `asana_task_library`.

---

## How to read this doc

A QA verdict stacks two layers:
1. **Executable rubric** — *how* quality is measured (nlp `/score-page` 8-engine,
   `page_structure_eval`, content-quality R1–R7). Code; already built.
2. **This doc** — *what the result means + what blocks*, for deliverables with no
   scorer. The QA Agent reads the relevant section, grades the deliverable against it,
   and cites the section in its finding.

Each task carries **✅ Must-haves (blocking)** — any fail ⇒ verdict `fail`, bounce to
In Progress with the failed item as a rework subtask — and, where useful, advisory
notes. Blocking checks are kept small and **objectively checkable**.

---

## Cross-cutting requirements & open questions

These apply across the checks below and must be settled for the link-building / GBP
items to work at all:

1. **⟨OPEN⟩ Deliverable URL location.** Guest posts, niche edits, citations, press
   releases, and map embeds live on **external pages** — QA can only check a URL it can
   fetch, and there is **no deliverable-URL field on tasks today** (only `description`
   + attachments). **Decision needed:** where does the VA put the placement URL(s)
   before moving a task to For QA? Recommended: paste them into the task `description`
   (QA extracts URLs), or a dedicated "Deliverable link(s)" subtask. Until this is
   fixed, these checks return *needs-human*.
2. **⟨OPEN⟩ Target keyword source.** GBP Posts and Press Release check "the keyword."
   QA needs to know what that is per task — is it reliably the task **title**, or a
   separate field?
3. **Fail-open policy (decided).** Any external page that's blocked, unreachable, or
   unparseable ⇒ verdict *needs-human*, **never** an auto-bounce. Mirrors
   `citation_check`'s philosophy — don't fail good work because a site blocked the
   scraper.
4. **NAP matching is normalized, not exact (decided).** Compare against the client
   card's `business_name` / `address` / `phone` with normalization (abbreviations,
   phone formats, whitespace) so "St" vs "Street" or "+61" vs "0…" doesn't false-bounce.

---

## Group A — On-page content (already machine-graded; QA adds the extras)

Pages/blogs run through `/score-page` + R1–R7 + `On_Page_Criteria_and_Coverage.md`
(SEO + structure verdict). QA adds the checks the scorer can't see.

### Website Pages Posted — service / local landing / location pages
*(category: Content)*

- **✅ Must-haves (blocking):**
  - Internal link(s) to the correct money/service page present.
  - Meta title + meta description filled in.
  - Correct client info (name, contact, service area) — no stale/placeholder data.
  - Images present with alt text.
  - **Design fit for the page type** (owner: "both" — phased):
    - *Now — structural fit (blocking):* matches the expected layout for its page type
      (sections, heading order, block composition) vs the client's stored reference
      page structure, via `page_structure_eval`. A broken/wrong structure ⇒ bounce.
    - *Later phase — visual rendering (blocking when built):* the rendered page isn't
      visually broken (overlapping elements, broken CSS, images not loading). Requires
      a headless-browser screenshot + vision pass; deferred to a later QA phase.
- **🚫 Advisory:** brand-voice fit (noted, not blocking unless egregious).

### Blog Post (Title + body)
*(category: Content)*

- **✅ Must-haves (blocking):**
  - Title matches the assigned keyword / brief.
  - CTA present, pointing to the correct page.
- **🚫 Advisory:** brand-voice fit.

---

## Group B — Non-page deliverables (QA-graded from this doc)

### GBP Posts
*(category: GBP Authority)* — **status: final**

- **✅ Must-haves (blocking):**
  - Target keyword present in the body.
  - A CTA is present.
  - At least one emoji.
- Bounce if any are missing.

### GBP Blast
*(category: GBP Authority)* — **QA: DO NOT CHECK** (owner ruling).

### HyperLocal GBP Blast
*(category: GBP Authority)* — **QA: DO NOT CHECK** (owner ruling).

### Citations — "(Number) Citations"
*(category: Link Building)* — **status: final (pending the URL-location decision)**

- **✅ Must-haves (blocking):**
  - **NAP correctness:** sample **3** citations from the list; extract each page's NAP
    and compare (normalized) to the client card. If a sampled citation's NAP does not
    match the client's card ⇒ bounce.
- Liveness is already auto-checked by `citation_check` — not repeated here.
- Fail-open: a sampled page that can't be fetched/parsed ⇒ *needs-human*, not a bounce.

### Guest Posts
*(category: Link Building)* — **status: final (pending the URL-location decision)**

- **✅ Must-haves (blocking):**
  - The body content contains a link back to the client's site. If absent ⇒ bounce.

### Niche Edits
*(category: Link Building)* — **status: final (pending the URL-location decision)**

- **✅ Must-haves (blocking):**
  - The body content contains a link back to the client's site. If absent ⇒ bounce.

### Press Release
*(category: Link Building)* — **⟨OPEN⟩ confirm the corrected logic below**

- **✅ Must-haves (blocking) — bounce if ANY fail:**
  - Target keyword in the **title**.
  - Target keyword at least once in the **body**.
  - At least one link whose anchor is **not** the exact-match keyword (anti-over-optimization).
  - **NAP included.**
- *Note: the brain dump's "send-it-back" line repeated the must-have condition and
  dropped NAP — the above is the corrected negation. **Confirm this reads right.***

### Map Embeds
*(category: Link Building)* — **⟨OPEN⟩ clarify "RDF triple"**

- **✅ Must-haves (blocking) — bounce if ANY missing:**
  - The **"RDF triple"** — the assertion that *client X does service Y*.
    **⟨OPEN⟩:** does this mean literal structured data (JSON-LD / schema.org markup),
    or a plain-English sentence stating it? Checkability differs a lot.
  - **NAP included.**
  - **Map embed included** (a maps iframe/embed is present).

### Service Silo (the plan)
*(category: Content)* — **QA: DO NOT CHECK — hand off to SerMaStr** (owner ruling).
The silo plan's quality (right services, groupings, commercial intent) is a strategy
judgment, not a presence check. QA marks it out-of-scope and defers to the strategist.

---

## Group C — Process / ops tasks

- **Blog Post Scheduling** — **out of QA** (completion-only; the board tracks it).
- **SEO NEO Task** (catch-all) — **route to human review** (verdict `needs-human`;
  never auto-passed or auto-bounced).

---

## Per-client overrides

Agency-wide criteria live in this file. A single client's special requirement goes in
the in-app **SOP store** (per-client layer), which the QA Agent layers on top of this
doc at grade time. Note such overrides here only as a pointer.

- _[client → override summary → lives in SOP store]_
