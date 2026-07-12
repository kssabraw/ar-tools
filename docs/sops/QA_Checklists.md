# QA Checklists — Deliverable Acceptance Criteria

**Current as of:** 12 July 2026
**Status:** ✅ Criteria finalized from the owner's brain dump. Google-Sheet reading
resolved (public link-share → CSV export, no credentials; cross-cutting #1). Ready as
QA-agent grounding; remaining work is the module build itself.
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
In Progress with the failed item as a rework subtask — plus advisory notes where useful.
Blocking checks are kept small and **objectively checkable**.

---

## Cross-cutting requirements

1. **Deliverable links — a "Deliverable links" subtask (decided).** The VA records the
   placement location(s) on a **`Deliverable links` subtask** before the task reaches
   **In QA** (the trigger status — the plan's "For QA" was superseded by the existing
   `in_qa` workflow status; see the plan's build note). The *format* varies by
   deliverable, and QA opens the container to get the URLs to check:

   | Deliverable | Where the links live | What QA does |
   |---|---|---|
   | **Map Embeds** | a **.txt file** (task attachment) | read the txt, extract the placement URL(s) |
   | **Citations** | a **Google Sheet** | read the sheet, sample 3 URLs |
   | **Press Release** | a **Google Sheet** | read the sheet, get the PR URL(s) |
   | **Guest Posts** | a single URL in the subtask | fetch that URL |
   | **Niche Edits** | a single URL in the subtask | fetch that URL |

   > **Reading Google Sheets (resolved).** Citations + PR point at a Google Sheet, so QA
   > reads it — but **no credentials / no service account are needed**: these sheets are
   > already shared **"anyone with the link → Viewer"** (required so the *client* can see
   > them too), so QA reads them via the **public CSV export**
   > (`https://docs.google.com/spreadsheets/d/<id>/export?format=csv`). The same sharing
   > setting serves both the client-visibility need and QA's read access.
   > **The one reliability requirement:** a **known column** holds the live URL (e.g. a
   > `Live URL` / `Citation URL` header) so QA reads the right cells instead of guessing
   > at layout. A private sheet (no public link) would fall back to *needs-human*.

2. **Target keyword source (decided; refined 2026-07-12).** The keyword is **entered
   into the task name** (owner confirmation). QA reads it as the name minus the
   template name — both shapes work: `GBP Posts — emergency roof repair` and a task
   fully renamed to the keyword (the library link identifies the type). A
   `Keyword: <term>` line in the description remains an explicit override, and blog
   articles fall back to the run's keyword automatically. A bare template name
   ("GBP Posts") ⇒ the keyword checks read "could not verify" ⇒ *needs-human*, never
   a guess. The QA panel's check notes show which keyword was used, so a wrong pick
   is visible at a glance.

3. **Fail-open policy (decided).** Any external page/sheet that's blocked, unreachable,
   or unparseable ⇒ verdict *needs-human*, **never** an auto-bounce. Mirrors
   `citation_check` — don't fail good work because a site blocked the scraper.

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
*(category: GBP Authority)* — **final**

- **✅ Must-haves (blocking), bounce if any missing:**
  - Target keyword present in the body.
  - A CTA is present.
  - At least one emoji.

### GBP Blast
*(category: GBP Authority)* — **QA: DO NOT CHECK** (owner ruling).

### HyperLocal GBP Blast
*(category: GBP Authority)* — **QA: DO NOT CHECK** (owner ruling).

### Citations — "(Number) Citations"
*(category: Link Building)* — **final** · links: **Google Sheet** (cross-cutting #1)

- **✅ Must-haves (blocking):**
  - **NAP correctness:** sample **3** citations from the sheet; extract each page's NAP
    and compare (normalized) to the client card. Any sampled NAP that does not match
    the client's card ⇒ bounce.
- Liveness is already auto-checked by `citation_check` — not repeated here.
- Fail-open: a sampled page that can't be fetched/parsed ⇒ *needs-human*, not a bounce.

### Guest Posts
*(category: Link Building)* — **final** · links: **single URL in the subtask**

- **✅ Must-haves (blocking):**
  - The body content contains a link back to the client's site. If absent ⇒ bounce.

### Niche Edits
*(category: Link Building)* — **final** · links: **single URL in the subtask**

- **✅ Must-haves (blocking):**
  - The body content contains a link back to the client's site. If absent ⇒ bounce.

### Press Release
*(category: Link Building)* — **final (confirmed)** · links: **Google Sheet**

- **✅ Must-haves (blocking) — bounce if ANY fail:**
  - Target keyword in the **title**.
  - Target keyword at least once in the **body**.
  - At least one link whose anchor is **not** the exact-match keyword (anti-over-optimization).
  - **NAP included.**

### Map Embeds
*(category: Link Building)* — **final** · links: **.txt file** (task attachment)

- **✅ Must-haves (blocking) — bounce if ANY missing:**
  - **The assertion sentence** — a **grammatically-correct plain-English sentence**
    stating the client provides the service (e.g. "Amazing Rankings provides SEO
    services in Sydney"). Not structured data — a real sentence, and it must read
    correctly. (LLM-judged.)
  - **NAP included.**
  - **Map embed included** (a maps iframe/embed is present on the page).

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
