# QA Agent — Operator & Capability Manual (as-built v1.0)

**Status:** the QA Agent is fully built and merged to `main` (2026-07-12), dormant
behind `QA_ENABLED` except the on-demand button. This manual is written **as-built** —
it describes what the code actually does today, not the plan. For the design record and
the decision history, see the plan (`qa-agent-plan-v1_0.md`); for the grading criteria
themselves, see the SOP (`docs/sops/QA_Checklists.md`). **When they disagree with this
manual, the code wins — this doc is kept in step with it.**

---

## 1. What it is (the one-paragraph model)

The QA Agent is an automated first-pass reviewer of **task deliverables**. When a task
reaches the **In QA** column, QA finds the thing that was produced (a page, a GBP post, a
citation batch, a guest post…), runs a fixed checklist for that deliverable type, and
either **passes** it, **bounces** it back with a concrete rework list, or flags it for a
**human** when it can't judge safely. It is deliberately **deterministic**: the pass/fail
verdict is always computed from presence checks in code — an LLM is used only to *phrase*
findings and for two narrow visual/semantic judgements, and it can never overturn the
verdict. QA sits alongside the two other agents: **SerMaStr** decides *what work to do*,
**PACE** keeps work *moving*, and **QA** judges whether *the work that got done is good* —
before it reaches the client.

---

## 2. Capabilities — every deliverable type and every check

QA routes a task to exactly one **rubric** by matching the task's library/template name
(or, for content runs, the producer source). Matching is case-insensitive substring, first
match wins, in this order:

| Task name contains… | Rubric | What QA does |
|---|---|---|
| `hyperlocal gbp blast` | **skip** | Not checked (owner ruling) |
| `gbp blast` | **skip** | Not checked (owner ruling) |
| `blog post scheduling` | **skip** | Not checked (ops task, not a deliverable) |
| `service silo` | **handoff** | Out of QA — defers to SerMaStr (a strategy judgement) |
| `seo neo` | **generic** | Flag for human review |
| `gbp post` | **gbp_posts** | Keyword + CTA + emoji |
| `citation` | **citations** | Sampled NAP match |
| `guest post` | **guest_posts** | Link back to client |
| `niche edit` | **niche_edits** | Link back to client |
| `press release` | **press_release** | Keyword + anchor + NAP |
| `map embed` | **map_embeds** | Assertion + NAP + embed |
| `website pages posted` | **website_page** | Meta/links/images + design fit |
| `blog post` | **blog_article** | Structural R-checks |
| *(a content-run producer task)* | **blog_article** | (wins regardless of name) |
| *(anything else)* | **generic** | Flag for human review — QA never guesses a standard |

Each rubric produces a list of **checks**; each check is **blocking** (can fail the review)
or **advisory** (noted, never fails). Exact checks as built:

### GBP Posts (`gbp_posts`)
The post copy is read from the task's `Deliverable links` subtask description, else the task
description. All three blocking:
- **Target keyword present in the body** — the note shows which keyword was used.
- **A CTA is present** — imperative contact/action phrase (call, book, get a quote, …) or a `tel:` link.
- **At least one emoji.**

### Citations (`citations`)
Reads the citation **Google Sheet** listed on the task, samples `qa_citation_sample` (3) URLs
via a deterministic spread (first / middle / last — same rows every re-run), fetches each,
and per sampled page:
- **NAP matches the client card** (blocking) — normalized name + (phone or address) match. A
  sampled page that can't be fetched reads *could not verify*, not a fail.

### Guest Posts (`guest_posts`) / Niche Edits (`niche_edits`)
Fetches the single placement URL from the task; one blocking check:
- **Link back to the client's site** — an anchor whose href contains the client's domain.

### Press Release (`press_release`)
Fetches the PR URL(s) from the task's **Google Sheet**; bounce if **any** of these four fail:
- **Target keyword in the title.**
- **Target keyword in the body.**
- **At least one non-exact-match anchor** — guards over-optimization (not every link is exact-match keyword).
- **NAP included.**

### Map Embeds (`map_embeds`)
Reads placement URLs (usually from a **.txt attachment**), fetches each; bounce if **any** missing:
- **Plain-English "client provides service" sentence** — grammatically-correct assertion, judged by one Claude vision-less text call (Haiku).
- **NAP included.**
- **Map embed present** — a Google Maps `<iframe>`.

### Website Pages Posted (`website_page`)
Fetches the live page URL. Blocking unless noted:
- **Meta title present.**
- **Meta description present.**
- **Internal link to the client's site.**
- **Images have alt text.**
- **Client name on the page** *(advisory — service pages legitimately vary)*.
- **Design fit — structural** — layout (sections, heading order, block composition) vs the
  client's stored reference page structure (`page_structure_eval`). Below
  `qa_structural_threshold` (70) it reads *could not verify*, not a fail, because page-type
  attribution is heuristic.
- **Design fit — visual, layer 1: asset integrity** — every stylesheet + image (up to
  `qa_asset_check_cap`, 12) is liveness-checked; a hard **404/410** on any is a **fail** (a
  dead stylesheet breaks the render). Bot-blocks / timeouts / 5xx are fail-open.
- **Design fit — visual, layer 2: rendered screenshot** *(when `qa_visual_enabled`)* — the
  page is captured via DataForSEO and judged by a Claude vision call for mechanical breakage
  (overlapping/clipped elements, unstyled HTML, collapsed layout). Only **high-confidence
  broken** fails; low confidence / capture failure reads *could not verify*.

### Blog Post (`blog_article`)
Reads the finished article markdown from the content run (`sources_cited` output). Blocking
unless noted:
- **Key Takeaways section present.**
- **CTA present.**
- **No duplicate headings.**
- **Paragraphs within length cap** *(advisory — flags regressions past 150 words)*.
- **External citations present** *(advisory)*.
- **Target keyword present** *(advisory, only if a keyword is known)*.

---

## 3. How a review is decided (the verdict fold)

The verdict is **pure code** (`qa_signals.build_verdict`), never the LLM's:

1. Any **blocking** check failed (`ok == False`) → **`fail`**.
2. Else any **blocking** check couldn't be verified (`ok == None`) → **`needs_human`**
   (fail-open — QA never guesses).
3. Else → **`pass`**.

Advisory checks never change the verdict; failed advisories ride along as notes. Skip/handoff
rubrics short-circuit to `skipped`; generic rubrics to `needs_human`.

**Fail-open is the core safety rule:** anything QA can't verify — a blocked page, a missing
deliverable link, no keyword on the task, missing creds, an unreadable sheet — becomes
`needs_human`, *never* an automatic rejection of good work.

---

## 4. What happens to the task (outcomes)

| Verdict | Board effect | Notification |
|---|---|---|
| **pass** | Stays in In QA by default (`qa_pass_status` empty). Set `qa_pass_status="sent_to_client"` to auto-advance. Verdict on the activity feed. | Silent unless `qa_notify_on_pass` |
| **fail** | Bounced to `qa_fail_status` (In Progress) + one **`Rework: <failed check>`** subtask per failed check (`qa_fail_creates_subtasks`). | Warning |
| **needs_human** | Stays put — a person decides. | Warning |
| **skipped** | Stays put; recorded. | None |

**The self-closing rework loop:** the `Rework:` subtasks are real work items, so when the VA
ticks them all off, the board's auto-advance moves the task **back to In QA**, which re-runs
QA automatically. Fix → re-review → pass, with no human dispatch in between. (The prefix is
`Rework:` and not `QA fix:` on purpose — "qa" would trip the task board's process-marker
classifier and break the loop.)

---

## 5. How QA fires (triggers)

1. **Automatic — entering In QA** (gated on `qa_enabled`). When a task's status changes to
   `in_qa` — including the board's own auto-advance when the last work subtask is ticked — QA
   enqueues one review. This is the main path: finish the work, and QA runs unprompted.
2. **On-demand — the Run QA button** in the task drawer's QA panel. Works **regardless of
   `qa_enabled`** — the flag gates only the automatic trigger. Good for trialing before go-live.
3. **Conversational — via PACE.** "PACE, run QA on the roof-repair GBP post for Acme" →
   resolves the task, confirms, and kicks the review (`run_qa_review`, min role `team_member`,
   actor-bound confirm).
4. **Producer auto-queue** *(opt-in, `qa_autoqueue_producers`, default off)*. A completed
   content run's "Review & publish" task is moved straight to In QA so generated content is
   QA'd before a human touches it.

Reviews run as background `qa_review` jobs, one per task, each well under the worker's stale
timeout.

---

## 6. Where results show up (surfaces)

- **Task drawer — QA panel.** Latest verdict badge (Passed / Failed / Needs a human / Not
  QA-checked), the rubric, a score when one exists, the per-check breakdown (✓/✗/? with
  blocking-vs-advisory and notes), the examined URLs as clickable links, collapsible review
  history, and the **Run QA** button.
- **Notifications** (`kind="qa_result"`). Fail and needs-human post a warning to the client's
  feed (+ Slack when configured); clean passes are silent by default. Deduped to **one per
  task + verdict + day** so a task failing repeatedly pings once.
- **SerMaStr assistant.** A `qa` context module feeds the last-30-day verdicts (counts +
  what needs attention) into answers — ask "how did QA go for Acme this week" and it reads
  real reviews rather than re-judging.
- **Activity feed.** Every review writes a `qa_result` activity row on the task.

---

## 7. Team conventions (what the VAs need to do)

QA can only check a deliverable it can find. Three habits feed it; none of them *break*
anything if missed (QA falls back to `needs_human`), but they're what let QA work
automatically instead of punting to a person.

1. **Target keyword → the task name.** Already how the team works. QA reads the keyword as the
   task name minus the template name (`GBP Posts — emergency roof repair`, or a task renamed to
   just the keyword). A bare template name ⇒ keyword checks read "could not verify."
   *(Override: a `Keyword: <term>` line in the description wins if ever needed.)*
2. **Placement URLs → a `Deliverable links` subtask.** For guest posts, niche edits, citations,
   press releases, map embeds. Paste the live URL(s), the sheet link, or attach the .txt file
   there. QA reads that subtask, .txt attachments, and the task description. No links ⇒
   "needs a human — no deliverable links found."
3. **A `Live URL` column in citation/PR sheets.** QA reads the sheet via its public CSV export
   and looks for a header like `Live URL`, `Citation URL`, `URL`, or `Link`. A clearly-named
   column ⇒ QA reads the right cells; otherwise it guesses the most-URL-shaped column.

**Don't paste a Google *Doc* draft** as the deliverable link — Docs/Slides/Forms links route
to `needs_human` (their rendered HTML would false-fail checks); link the **live placement**.

---

## 8. Cost model

The deterministic layer is **free** — HTML fetches, parsing, NAP matching, keyword/CTA/emoji
checks, sheet CSV reads, asset HEAD checks, structural fidelity. Paid calls, all cheap and
bounded:

| Spend | When | Roughly |
|---|---|---|
| Haiku narrative | Once per **fail / needs-human** review (skipped on gathering-only outcomes and on pass) | ~1 cheap call |
| Haiku assertion judge | Once per map-embed page | ~1 cheap call |
| DataForSEO screenshot + Haiku vision | Once per **website-page** review, when `qa_visual_enabled` | fractions of a cent + 1 cheap call |
| Citation fetches | Up to `qa_citation_sample` (3) HTTP GETs | free |

No Sonnet anywhere; no headless browser in the image (the screenshot is a DataForSEO call).
Passing reviews are nearly free.

---

## 9. Configuration reference (`config.py`, env-overridable)

| Setting | Default | What it does |
|---|---|---|
| `qa_enabled` | `False` | Master gate for the **automatic** In-QA trigger. The Run QA button works regardless. |
| `qa_trigger_status` | `in_qa` | The status whose entry enqueues a review. |
| `qa_pass_status` | `""` | Where a passing task goes. Empty = stay in In QA. Set e.g. `sent_to_client` to auto-advance. |
| `qa_fail_status` | `in_progress` | Bounce target on a failed review. |
| `qa_fail_creates_subtasks` | `True` | Create `Rework:` subtasks from failed checks. |
| `qa_notify_on_pass` | `False` | Notify on clean passes (off = silent). |
| `qa_citation_sample` | `3` | Citations sampled per review. |
| `qa_fetch_timeout_seconds` | `20.0` | Per-fetch HTTP timeout. |
| `qa_max_urls_per_review` | `5` | Cap on external fetches per review. |
| `qa_assertion_model` | Haiku | Map-embed assertion-sentence judge. |
| `qa_structural_threshold` | `70.0` | Structural fidelity floor; below = needs-human, not fail. |
| `qa_recheck_cooldown_minutes` | `30` | Skip an **automatic** re-trigger within this window of a **passed** review (flap guard; pass-only; manual bypasses). |
| `qa_narrative_enabled` | `True` | SOP-cited Haiku phrasing on fail/needs-human. |
| `qa_narrative_model` | Haiku | Narrative model. |
| `qa_narrative_max_tokens` | `500` | Narrative length cap. |
| `qa_sop_budget_chars` | `16000` | SOP grounding budget (fits both QA_Checklists + On-Page Criteria whole). |
| `qa_autoqueue_producers` | `False` | Auto-move completed content-run review tasks to In QA. |
| `qa_visual_enabled` | `True` | The paid screenshot + vision layer of the page visual check (asset integrity always runs). |
| `qa_visual_model` | Haiku | Vision judge model. |
| `qa_visual_max_tokens` | `400` | Vision reply cap. |
| `qa_asset_check_cap` | `12` | Asset HEAD checks per page review. |

---

## 10. Turning it on & tuning

**Go-live:** set `QA_ENABLED=true` on the PLATFORM Railway service. Before flipping, trial the
**Run QA** button on a few real tasks (a GBP post, a citations task) and socialize the three
conventions in §7. There is no DB step — both migrations (`qa_reviews` + the enqueue unique
index) are already applied live.

**Common tuning (all config, no code):**
- Too many pages bounced on structure → lower `qa_structural_threshold` or accept it stays
  needs-human (it already never auto-fails on structure alone).
- Want passes to move straight to the client → `qa_pass_status="sent_to_client"`.
- Vision check too noisy or you want to save the pennies → `qa_visual_enabled=false` (asset
  integrity still runs free).
- Sampling too few/many citations → `qa_citation_sample`.
- Slower/blocked sites timing out → raise `qa_fetch_timeout_seconds`.

---

## 11. Troubleshooting / graceful degradation

Everything below produces **`needs_human`** (never a false fail):

| Symptom | Cause |
|---|---|
| "no deliverable links found" | No `Deliverable links` subtask / URL on the task (§7.2). |
| Keyword check "could not verify" | Bare template name, no keyword derivable (§7.1). |
| "screenshot unavailable" | DataForSEO creds missing, or capture failed. Asset integrity still ran. |
| "deliverable link can't be graded" | A Google Doc draft link, or an unreachable sheet — link the live placement. |
| Sheet read empty | Sheet not shared "anyone with the link", or no URL-ish column. |
| NAP "NOT found" on a real match | Client card `business_name`/`address`/`phone` missing or very different from the page. |

Operational safety already built in: reviews are best-effort (a QA failure never breaks the
task board); a task completed/trashed while its review was queued is skipped; concurrent
enqueues are deduped at the DB (one live job per task); a passed task dragged out-and-back
doesn't re-pay the review within the cooldown.

---

## 12. Boundaries (who owns what)

- **QA** judges *this deliverable* against a fixed rubric, and opens the finding (the bounce +
  rework subtasks). It does **not** chase, reassign, or decide strategy.
- **PACE** owns the resulting rework as board work — chasing, reassigning, keeping it moving.
  (QA opens the finding; PACE keeps it moving.)
- **SerMaStr** owns strategy — what work to invent, priorities, and the judgement calls QA
  hands off (e.g. Service Silo plans). A systemic quality *pattern* QA surfaces (every page
  failing the same check) is a strategy signal SerMaStr acts on.

---

## 13. Where the code lives

- `services/qa_signals.py` — pure rubric layer (routing, all checks, NAP matching, sheet
  parsing, verdict fold, conventions). Unit-tested (`tests/test_qa_signals.py`).
- `services/qa_service.py` — orchestration (trigger, enqueue, deliverable gathering, the
  review job, outcome application, narrative synthesis).
- `services/qa_visual.py` — the visual page-rendering check (screenshot + vision). Unit-tested
  (`tests/test_qa_visual.py`).
- `routers/tasks.py` — `POST /tasks/{id}/qa` (on-demand) + `GET /tasks/{id}/qa-reviews`.
- `frontend/src/components/tasks/QaPanel.tsx` — the drawer panel.
- Grounding: `docs/sops/QA_Checklists.md` (the acceptance standard) + `On_Page_Criteria_and_Coverage.md`.
- Data: `qa_reviews` table + the `qa_review` async job type (migrations `20260712233000`,
  `20260712235500`).

---

*Kept as-built. Change the code → change this manual. For why-it's-built-this-way, read the
plan doc; for the grading criteria, read the SOP.*
