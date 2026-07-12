# QA Checklists — Deliverable Acceptance Criteria

**Current as of:** 12 July 2026
**Status:** 🚧 DRAFT — worksheet awaiting the owner's brain dump. Blocking/advisory
checks under each **Group B** task are placeholders to be filled in.
**Purpose:** The human-authored acceptance bar the **QA Agent** grades each task
deliverable against — the "layer 2" standard (what a verdict *means* + what blocks),
distinct from the executable scorers that measure on-page content.
**Scope:** Per-task-type acceptance criteria for deliverables the automated on-page
scorer does **not** cover. On-page content (pages/blogs) is already governed by
`On_Page_Criteria_and_Coverage.md` — this doc only adds what that one can't see.

> **Cross-references:** module plan → `docs/modules/qa-agent-plan-v1_0.md` §3b
> (grounding & QA SOPs) · executable rubric → `On_Page_Criteria_and_Coverage.md`
> (bands, `<80` blocking-deficiency rule, verdict→action routing) · task types →
> the live `asana_task_library`.

---

## How to read this doc

A QA verdict stacks two layers:
1. **Executable rubric** — *how* quality is measured (nlp `/score-page` 8-engine,
   `page_structure_eval`, content-quality R1–R7). Code; already built.
2. **This doc** — *what the result means + what blocks*, for deliverables with no
   scorer. The QA Agent reads the relevant section, grades the deliverable against it,
   and cites the section in its finding.

Each task below carries two lists:
- **✅ Must-haves (blocking)** — any fail ⇒ verdict `fail`; the task bounces to
  In Progress with the failed item as a rework subtask.
- **🚫 Send-it-back (advisory unless marked blocking)** — the mistakes that actually
  come up; noted in findings, and promoted to blocking where marked.

Keep the blocking set **small and objectively checkable**; push taste/judgment items
to advisory so QA stays a first-pass filter, not a gatekeeper on style.

---

## Group A — On-page content (already machine-graded; brain-dump only the extras)

These run through `/score-page` + R1–R7 + `On_Page_Criteria_and_Coverage.md`, which
own the SEO + structure verdict. QA only *adds* the checks the scorer can't see. Leave
blank to accept the scorer verdict as-is.

### Website Pages Posted — service / local landing / location pages
*(category: Content · SEO+structure already graded — add only the extras)*

- **✅ Must-haves (beyond the SEO score):**
  - _[e.g. internal links to the correct money/service page present]_
  - _[e.g. meta title + description filled in]_
  - _[…]_
- **🚫 Send-it-back:**
  - _[e.g. wrong city / stale client details]_
  - _[…]_

### Blog Post (Title + body) — Blog Post Title
*(category: Content · SEO+structure already graded — add only the extras)*

- **✅ Must-haves (beyond the SEO score):**
  - _[e.g. title matches the assigned keyword/brief]_
  - _[e.g. brand voice matches the client]_
  - _[…]_
- **🚫 Send-it-back:**
  - _[…]_

---

## Group B — Needs your brain dump (no scorer exists — the real authoring)

> Fill in ✅ and 🚫 for each. Free-type plain English; format/precision doesn't
> matter — I'll normalize it. Do the ones where bad work slips through today first.

### GBP Posts
*(category: GBP Authority)*

- **✅ Must-haves (blocking):**
  - _[…]_
- **🚫 Send-it-back:**
  - _[…]_

### GBP Blast
*(category: GBP Authority)*

- **✅ Must-haves (blocking):**
  - _[…]_
- **🚫 Send-it-back:**
  - _[…]_

### HyperLocal GBP Blast
*(category: GBP Authority)*

- **✅ Must-haves (blocking):**
  - _[…]_
- **🚫 Send-it-back:**
  - _[…]_

### Citations — "(Number) Citations"
*(category: Link Building · note: liveness is auto-checked by `citation_check`; brain-dump the **quality** bar — NAP consistency, directory relevance/authority)*

- **✅ Must-haves (blocking):**
  - _[…]_
- **🚫 Send-it-back:**
  - _[…]_

### Guest Posts
*(category: Link Building)*

- **✅ Must-haves (blocking):**
  - _[…]_
- **🚫 Send-it-back:**
  - _[…]_

### Niche Edits
*(category: Link Building)*

- **✅ Must-haves (blocking):**
  - _[…]_
- **🚫 Send-it-back:**
  - _[…]_

### Press Release
*(category: Link Building · note: nlp-api has a press-release generator — some structure may be checkable automatically; brain-dump the editorial bar)*

- **✅ Must-haves (blocking):**
  - _[…]_
- **🚫 Send-it-back:**
  - _[…]_

### Map Embeds
*(category: Link Building)*

- **✅ Must-haves (blocking):**
  - _[…]_
- **🚫 Send-it-back:**
  - _[…]_

### Service Silo (the plan)
*(category: Content · the silo plan itself — right services, sensible groupings, commercial intent)*

- **✅ Must-haves (blocking):**
  - _[…]_
- **🚫 Send-it-back:**
  - _[…]_

---

## Group C — Process / ops tasks (proposed: NOT QA targets — confirm)

These are "did you do it," not "is it good" — the board already tracks completion, so
there is nothing for QA to *grade*. Listed here only for a decision: leave out of QA,
or (if a quality dimension exists) promote to Group B with criteria.

- **Blog Post Scheduling** — _decision: out of QA? [yes / promote — criteria]_
- **Blog Post Title** *(if handled purely as a naming step)* — folded into Blog Post above
- **Service Silo** *(if handled purely as an ops step)* — see Group B
- **SEO NEO Task** (catch-all) — _decision: out of QA? [yes / promote]_

---

## Per-client overrides

Agency-wide criteria live in this file. A single client's special requirement
("this client insists on X") does **not** go here — it goes in the in-app
**SOP store** (per-client layer), which the QA Agent layers on top of this doc at
grade time. Note such overrides here only as a pointer, not the full text.

- _[client → override summary → lives in SOP store]_
