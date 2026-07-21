# QA Agent — Quality Assurance for Task Deliverables — Module Plan v1.0

> **📖 Looking for how it works today?** This is the **design/plan** doc (plan-as-written
> + build-note corrections). For the **as-built operator & capability reference** — every
> rubric, every check, config, cost, conventions, ops — read **`qa-agent-manual-v1_0.md`**.

**Status:** **ALL PHASES BUILT** (2026-07-12, feature-complete; dormant behind `qa_enabled`
default False except the on-demand Run QA button — see the build notes below). **Sibling to:** SerMaStr
(`seo-strategist-agent-plan-v1_0.md`) and PACE (`project-manager-agent-plan-v1_0.md`).
**Rides:** the native task manager (`in-app-task-manager-prd-v1_0.md`), the nlp-api
8-engine scorer + content-quality R1–R7, the SerMaStr assistant rails
(`services/slack_assistant/`), notifications, the shared scheduler. **Authored:** 2026-07-12.

> **BUILD NOTE (2026-07-12) — deviations from the plan as written, all recorded
> in code comments too:**
> 1. **`in_qa` replaces `for_qa` (§2 superseded).** Between authoring and build,
>    migration `20260712220000` added an **"In QA"** status (`in_qa`) to the live
>    workflow (Not Started → In Progress → **In QA** → Sent to Client → …), and
>    `task_service`'s auto-advance Rule B already moves a task there when its last
>    work item is ticked — with a code comment reserving "In QA → Sent to Client"
>    for this agent. So QA triggers on the EXISTING `in_qa` status
>    (`qa_trigger_status`); no new status row was added. The auto-pipeline this
>    buys: work items done → auto-advance to In QA → QA runs unprompted.
> 2. **Pass default = stay in In QA** (`qa_pass_status=""`), verdict on the
>    activity feed + optional notification — NOT the plan's "advance to In Review":
>    the reshaped workflow makes In Review a client-rejected-rework *exception*
>    status, and auto-moving to Sent to Client would claim a send that hasn't
>    happened. Config can advance passes (`qa_pass_status="sent_to_client"`).
> 3. **Fail bounces to In Progress with "QA fix: …" rework subtasks** — and since
>    those subtasks ARE work items, ticking them all auto-advances the task back
>    to In QA, which re-runs QA: the rework loop closes itself.
> 4. **Structural design-fit is needs_human, not auto-fail**, below
>    `qa_structural_threshold` — page-type attribution to a stored reference is
>    heuristic, and a wrong-reference comparison must not bounce good work.
> 5. **Phases 3–4 are now BUILT** (follow-up builds, 2026-07-12): the **drawer UI**
>    (`components/tasks/QaPanel.tsx` — verdict card, per-check breakdown, history,
>    Run QA with bounded polling); the **SOP-grounded narrative** — fail/needs_human
>    reviews get one Haiku call (`qa_narrative_*` config) that phrases the
>    deterministic findings with QA_Checklists / On-Page-Criteria citations via the
>    new `sop_library` `qa` domain + `qa_sops_text()` (no _ORCHESTRATOR in the
>    budget) — the verdict is never the LLM's to change, and any failure falls back
>    to the deterministic narrative; the **conversational surface** — §5's "qa
>    PERSONA_ACTIONS scope" was **amended**: rather than a full third persona, QA's
>    one operational action `run_qa_review` lives in **PACE's** scope
>    (kicking a review is board ops — "PACE keeps it moving"; judging stays in
>    qa_service; `_MATRIX` min-role team_member, actor-bound confirm like every PACE
>    write), and a read-only **`qa` context provider** (`_ctx_qa`) feeds recent
>    verdicts into the SerMaStr assistant context; and the **producer auto-queue**
>    (Phase 4) — `qa_autoqueue_producers` (default off) moves a completed content
>    run's "Review & publish" task straight to In QA.
> 6. **The visual page-rendering check is BUILT** (final phase, 2026-07-12 —
>    `services/qa_visual.py`): the checklist's "design fit — visual" for posted
>    pages, WITHOUT bundling Chromium into the Railway image. Two layers on the
>    `website_page` rubric: a **free asset-integrity check** (`asset_urls_of` +
>    `_broken_assets` — every stylesheet/image HEAD-checked, hard 404/410 ⇒
>    blocking fail, bot-blocks/timeouts fail-open per the citation_check
>    philosophy) and a **rendered screenshot** via DataForSEO `page_screenshot`
>    (existing creds, fractions of a cent) judged by a Claude vision call
>    (`qa_visual_model`, Haiku). Verdict discipline preserved: the vision judge
>    returns {broken, confidence, issues}; only **high-confidence** breakage maps
>    to a blocking fail — low confidence, unparsable output, oversized captures,
>    or any infra failure read needs_human (fail-open). Pillow downscales
>    captures that exceed vision-input limits. Config: `qa_visual_enabled`
>    (default on) / `qa_visual_model` / `qa_visual_max_tokens` /
>    `qa_asset_check_cap`. Pure helpers unit-tested (`tests/test_qa_visual.py`).
>    **The QA Agent module is now feature-complete against this plan.**
>
> **What shipped:** migration `20260712233000` (`qa_reviews` + `qa_review` job
> type), `services/qa_signals.py` (pure rubric layer, unit-tested —
> `tests/test_qa_signals.py`), `services/qa_service.py` (trigger, gathering —
> pages / link-shared-sheet CSV / .txt attachments —, the review job, outcome
> application), the `update_task` hook, `POST /tasks/{id}/qa` +
> `GET /tasks/{id}/qa-reviews`, and the `qa_*` config block. On-demand QA works
> with the flag off; `qa_enabled` gates only the automatic status trigger.

> **BUILD NOTE (2026-07-20) — dedicated QA chat surface (owner request).** A
> conversational QA persona now lives in the sidebar as its own `/qa` page, the
> reviewer sibling of SerMaStr's `/assistant` and PACE's `/pace`. This is an
> *addition on top of* §5's decision (which folded QA's `run_qa_review` into
> PACE rather than spinning up a persona) — it does **not** disturb that:
> - **Scoped to the `/qa` surface only.** Unlike PACE, QA is NOT wired into the
>   shared Slack `handle_message` / `/assistant/chat` first-refusal chain (that
>   would create a three-way routing contest). `routers/qa.py` calls
>   `services/qa_agent.py::maybe_handle_web(..., force=True)` directly, so
>   SerMaStr + PACE routing are byte-for-byte unchanged.
> - **New bare-URL QA capability** (resolves open decision #6's "QA this page"
>   gap): `qa_service.review_url(url, client, rubric)` runs the real
>   deterministic checks against any live URL with **no task and nothing
>   persisted** (read-only), reusing the same page/citation/link/press/map-embed
>   checks as the task rubrics via the shared `_website_page_checks` helper.
> - **Two chat tools:** `qa_url` (runs inline, read-only) and `run_qa_review`
>   (the existing task-review job — confirm-gated + actor-bound, reusing
>   `pace_auth`). Recent-verdict questions answer from the same `_ctx_qa` /
>   `qa_reviews` data the strategist reads.
> - **Gated on its own flag** `qa_chat_enabled` (default False, separate from
>   `qa_enabled`) so the chat ships dark; `GET /qa/status` hides the sidebar
>   entry until it's on. Model `qa_chat_model` (Sonnet, PACE-parity for
>   enumeration) / `qa_chat_max_tokens`. Pure helpers unit-tested
>   (`tests/test_qa_agent.py`).
> **What shipped:** `services/qa_agent.py` (persona), `routers/qa.py`
> (`/qa/status` `/qa/chat` `/qa/chat/stream` `/qa/brief`), `qa_service.review_url`
> + `resolve_url_rubric`, the `qa_chat_*` config block, and the frontend
> `pages/Qa.tsx` + `components/QaChat.tsx` + sidebar entry. No migration (bare-URL
> reviews are inline-only; `qa_reviews.task_id` stays NOT NULL).

> **Positioning (the three-agent picture).**
> **SerMaStr** determines *what should be done*. **PACE** keeps it *moving*.
> **QA** decides whether *what got done is actually good* — before it reaches the client.
> Three personas, one set of rails. QA is the third instance of the suite's
> deliberate persona split, and it is designed the same way PACE is: a **deterministic
> signal layer** does the heavy lifting for free, and a **thin, cheap persona** only
> phrases and prioritizes. QA is explicitly **not** folded into PACE.

---

## 1. Purpose & position

The task board has a client-review pipeline —
`In Progress → In Review → Sent to Client → Client Approved` — but there is **no gate
between "a VA marked it done" and "it goes in front of the client."** Quality today
depends on a human lead remembering to look. QA closes that gap: an automated first-pass
reviewer that scores a deliverable against the quality machinery the suite already owns,
passes the clean ones through, and opens a concrete rework finding on the rest.

### Why separate QA from PACE (decision record)

The owner's instinct — *"I don't want PACE to get overloaded then start getting timeout
errors"* — is correct, and it drives the architecture. PACE is deliberately built to be
**cheap and fast**: Haiku-tier, `pace_max_tokens=1200`, and a **tiny context** (board
metadata — statuses, workload, due dates). QA is a fundamentally different job.

| | **SerMaStr** | **PACE** | **QA (new)** |
|---|---|---|---|
| Core question | Are we winning? | Is the approved work getting **done**? | Is the work that got done **good**? |
| Reasoning over | every module + SOP corpus | board metadata | the **deliverable content itself** |
| Context size | huge | tiny | medium–large (fetch/read the artifact) |
| Cadence | weekly + escalations | daily + on-demand | **event-driven** (per deliverable) |
| Model / cost | Sonnet + drill-downs | Haiku + small digest | deterministic-first; cheap LLM synthesis |
| Core verb | proposes | executes (confirm-gated) | **judges** (read-only; opens findings) |

Folding QA into PACE would (a) blow PACE's Haiku cost model, (b) bloat its prompt with
content-review noise, and (c) — the timeout risk — put a heavy, **content-fetching** call
on PACE's shared once-a-workday scheduler sweep. This is the exact argument the PACE plan
makes for why PACE is split from SerMaStr ("merging erodes the guardrail, bloats the
prompt, and crosses the two signals"). QA is the third application of that rule.

### The real cause of timeouts (and how QA avoids it)

Timeouts don't come from *one agent conceptually owning too many jobs* — they come from
**one LLM call trying to do too much at once** (big context + many tool calls + content
fetching in a single request). QA neutralizes that the way the rest of the suite does:

1. **Deterministic layer does the heavy lifting, no LLM.** Most of QA is running scorers
   that already exist and thresholding them — the LLM only synthesizes a verdict.
2. **Per-deliverable async jobs, never one batch call.** Each QA review is its own
   `async_jobs` unit, so each stays far under the stale-job reaper's 30-min timeout —
   the same reason Local SEO bulk-create is per-page, not one 90-min batch job.

"Separate from PACE" and "won't time out" are therefore the **same** decision, reached the
same way PACE reaches it.

---

## 2. Trigger: the "For QA" status (owner requirement)

**A new task status `for_qa` ("For QA") is the primary trigger.** A VA finishing work
moves the task to **For QA** instead of straight to In Review; that transition enqueues the
QA review. QA then advances or bounces the task (§4.4).

New seed row in `task_statuses` (migration; keep the existing keys untouched, insert
between `in_progress` and `in_review`, renumber `sort_order` forward):

```
key='for_qa'  label='For QA'  color='#8b5cf6'  category='in_progress'
              is_initial=false  is_done=false  sort_order=… (before in_review)
```

- **Category `in_progress`** — a task in QA is still open, still counts against pace and
  workload, and PACE's staleness/month-pace signals treat it correctly with **no hardcoded
  keys** (they key off `category`/`is_initial`/`is_done`, so `for_qa` needs no PACE change).
- **The board gains a column** for it automatically (the board renders one column per
  status). Drag-to-`for_qa` on the Board view is the natural VA gesture; the List view's
  status dropdown works too.

**Trigger mechanics (reuse the producer pattern, don't invent a new one).** Task status
changes already emit a `status_changed` activity with `detail.to`. Add a QA producer hook
(`services/qa_producer.py`, mirroring `task_producers.py`) fired from
`task_service.update_task` after a status change: when `detail.to == 'for_qa'` **and** the
QA feature is enabled, enqueue one `qa_review` job for that task. Idempotent — a re-entry
into For QA that already has an open in-flight review is a no-op (guard on an existing
non-terminal `qa_reviews` row for the task).

**Secondary triggers** (all optional, same job):
- **On-demand** — a "Run QA" button on the task drawer, and a conversational
  `run_qa` action ("QA the Inner West page").
- **Producer opt-in** — when a `content_run` completes or a Local SEO page is generated,
  optionally auto-move its "Review & publish" task to For QA (`qa_autoqueue_producers`,
  default **off**) so generated content is QA'd before a human ever touches it.

---

## 3. Architecture

Zero new infra — the PACE shape exactly.

```
  ┌───────────────── deterministic (no LLM, existing scorers) ──────────────────┐
  │ services/qa_signals.py — resolve the deliverable + run the rubric for its    │
  │   artifact type (unit-tested plumbing; scorers already exist):              │
  │   • local_seo_page → nlp /score-page (8-engine) + page_structure_eval        │
  │   • blog article    → content-quality R1–R7 checks (headings/APP intro/CTA/  │
  │                        para-length/citation coverage/topic adherence)        │
  │   • generic         → acceptance-criteria checklist (LLM, see below)         │
  │   → per-dimension scores + a deterministic pass/fail against qa_pass_*        │
  └──────────────────────────────────────────────────────────────────────────────┘
        │ feeds ▼                                              ▲ reads (free)
  ┌───────────────── judgment (LLM, cheap, restricted) ────────┴─────────────────┐
  │ services/qa_agent.py — the QA persona:                                        │
  │   synthesize a short verdict + rank the top rework items from the scores      │
  │   (one cheap call per deliverable; NEVER re-computes numbers — cites them)    │
  │   + a QA-scoped conversational action set (run_qa; read-only otherwise)       │
  └──────────────────────────────────────────────────────────────────────────────┘
```

### The QA-signal layer (`services/qa_signals.py`) — deterministic, provider registry

A **rubric registry keyed by artifact type** (same extensibility seam as
`strategy_digest`'s provider registry). Each rubric returns a normalized envelope:

```
QAResult = {
  artifact_type, artifact_ref, dimensions: [{key, score, weight, issues[], recs[]}],
  composite: float, verdict: 'pass'|'fail'|'needs_human', threshold: float,
  blocking_issues: [...], measured_at,
}
```

- **`local_seo_page`** — reuse the nlp `/score-page` 8-engine composite (7 LLM engines +
  the deterministic SERP-signal engine) **plus** `page_structure_eval` for structural
  fidelity vs the client's stored reference page. Both already exist; QA orchestrates and
  thresholds them.
- **`blog_article`** — run the content-quality **R1–R7** acceptance checks (semantic
  heading dedup, APP intro, Key Takeaways, CTA presence, paragraph-length cap, external
  citation coverage, topic adherence). These are deterministic; the composite is
  rule-coverage, not an LLM score.
- **`generic`** (a manually-created task with no artifact link, or one carrying only a URL/
  attachment) — the LLM reads the deliverable against the task's title + acceptance
  notes and returns a checklist verdict. This is the one artifact type where the LLM
  scores; keep it clearly labeled `verdict='needs_human'`-leaning and low-stakes.

**Resolving the deliverable from the task.** The producer backbone already links a task to
its artifact via `source`/`source_ref` (e.g. `content_run` → run_id → the article;
Local SEO pages are first-class rows). QA follows that link. A task with **no resolvable
artifact** → `verdict='needs_human'` + a note ("no deliverable attached to QA") — never a
crash, never a false pass.

### The QA persona (`services/qa_agent.py`) — thin, cheap, read-only

One **cheap** LLM call per deliverable that takes the deterministic `QAResult` and emits a
plain-English verdict + the ranked top-N rework items. It **never re-computes scores** (it
cites `qa_signals` numbers verbatim — the same "LLM never counts" discipline used
throughout the suite). Model `qa_model` (Haiku-tier by default; bump to Sonnet only if
synthesis quality on generic reviews disappoints). Its conversational surface is
**read-only** apart from `run_qa` (enqueue a review) — QA opens findings, it does not move
other people's board work (that's PACE, §5).

---

## 3b. Grounding & QA SOPs — what QA judges against

The most common question about this design is *"don't I need to write QA SOPs?"* The answer
is **yes, but only for one of two layers** — and the biggest one is already written.

### Two layers: the executable rubric vs the SOP that interprets it

A QA verdict stacks two distinct things, and **SOPs own only the second**:

| Layer | *What it is* | *Who owns it* | *Author effort* |
|---|---|---|---|
| **1. Executable rubric** | *How* quality is measured — the actual scoring | nlp `/score-page` (8-engine), `page_structure_eval`, R1–R7 — **code, already built** | none (exists) |
| **2. The SOP** | What the scores *mean* + the pass bar + which deficiencies block + verdict→action routing | human-authored SOP text | some — but see below |

The LLM never grades in layer 1 (the engine does) and never *invents* the standard in layer
2 (it cites the SOP). This is the same discipline the rest of the suite uses — deterministic
measurement, SOP-grounded interpretation.

### The content-QA SOP already exists

For all on-page content — **blog posts, local landing, service, and location pages** — layer
2 is already written: **`docs/sops/On_Page_Criteria_and_Coverage.md`**, described in its own
header as *"the shared definition of what an on-page verdict is and means, so every consumer
interprets it identically."* It already fixes everything QA needs to route a page:

- **Bands:** `excellent ≥90 · good ≥80 · needs_improvement ≥70 · below_standard ≥60 · fail <60`.
- **Blocking-deficiency rule:** an engine scoring **`<80`** is a deficiency to fix.
- **Verdict → action routing:** what a failing verdict triggers.
- **Coverage boundaries:** which page types are QA targets at all (About/bio/contact are not).

So for content, QA authors **no new SOP** — it runs `/score-page`, then interprets the result
through this SOP, cited. A happy consequence: QA and SerMaStr grade against the *same* verdict
definition (the strategist already consumes this doc), so a QA fail and a strategist finding
can never disagree about what "good" is. QA's per-artifact `qa_pass_thresholds` (§6) must be
kept **consistent with this SOP's bands** — the SOP is the source of truth; the config is its
machine-readable mirror, not a competing standard.

### What you *would* author (the real, scoped SOP work)

Only the gaps `On_Page_Criteria_and_Coverage.md` doesn't cover:

1. **Non-page deliverable types** — the `generic` artifact (a GBP post, a citation batch, a
   one-off asset). No scorer grades these, so if you want QA to judge them you author a
   **per-category acceptance-checklist SOP** (template below). This is the genuine new authoring.
2. **"Soft" standards beyond the SEO score** — brand-voice fit, "did it actually fulfill the
   brief," agency formatting conventions. The scorer measures SEO/structure, not "does this
   read like *this* client." Encode these only if you want QA to enforce them; otherwise they
   stay a human's call at In Review.
3. **Per-client special requirements** — these do **not** go in a repo SOP. They go in the
   existing **`sop_store`** per-client override layer, which already takes precedence over the
   repo corpus (the same precedence SerMaStr uses). "This client insists on X" tunes that
   client's QA bar with zero change to the shared standard.

### The wiring (reuse SerMaStr's grounding, add nothing)

SOP retrieval already exists: `services/sop_library.py`'s `_RELEVANCE` map selects which SOP
docs are loaded (token-budgeted, citable) for a signal domain. QA plugs in by **adding a `qa`
domain** mapped to the relevant docs:

```python
# services/sop_library.py — _RELEVANCE (illustrative)
"qa": ["On_Page_Criteria_and_Coverage.md", "AIO_AEO_SOP.md"],   # + any new checklist SOPs
```

The `qa_review` job resolves the task's `category_key` → the domain(s) → `select_sops_text(...)`
→ the budgeted SOP block handed to the `qa_agent` synthesis call, which must cite doc + section
in its findings (same rule as the strategist). Per-client `sop_store` overrides are layered on
top exactly as they are for SerMaStr. **No new retrieval mechanism, no new infra.**

### Template for a new per-category QA-checklist SOP

For each non-page deliverable category you want QA to judge, a short doc keyed to the task
`category_key` (`content` / `link_building` / `gbp_authority` / `strategy`):

```
# QA Checklist — <Category>
Purpose: the acceptance bar QA grades a <category> deliverable against.
Applies to: tasks with category_key='<category>' and no automated on-page scorer.

## Blocking checks (any fail ⇒ verdict=fail, bounce with the failed item as rework)
- [ ] <objectively checkable requirement>
- [ ] <…>

## Advisory checks (fail ⇒ noted in findings, not blocking)
- [ ] <…>

## Routing
- pass  → advance to <status>       # defaults to qa_pass_status
- fail  → bounce to <status> + attach failed blocking checks as subtasks
```

The LLM reads the deliverable against the checklist and returns a pass/fail per line — it
grades against *your* written bar, never an invented one. Keep the blocking set small and
objective; push judgment-heavy items to advisory so QA stays a first-pass filter, not a
gatekeeper that blocks on taste.

---

## 4. The QA lifecycle

### 4.1 Data model (small, additive)
- **`task_statuses`** += the `for_qa` row (§2).
- **`qa_reviews`** — one row per review: `(id, task_id, client_id, artifact_type,
  artifact_ref, composite, verdict, threshold, dimensions jsonb, blocking_issues jsonb,
  narrative text, created_by, created_at)`. History is kept (a task can be QA'd, reworked,
  re-QA'd — the trend matters). Latest-per-task drives the drawer badge.
- **`async_jobs`** += `qa_review` job type (widen the CHECK preserving the full live set).

### 4.2 The `qa_review` job
`services/qa_service.py::run_qa_review_job(task_id)`:
1. Resolve the task + its artifact (`source`/`source_ref`).
2. Pick the rubric by artifact type; run the deterministic scorers → `QAResult`.
3. One `qa_agent` synthesis call → narrative + ranked rework list.
4. Persist a `qa_reviews` row; apply the outcome (§4.4).
5. Emit a notification (§4.5).

Best-effort + isolated per artifact; a scorer failure downgrades to `needs_human` with the
reason, never fails the task silently.

### 4.3 Pass / fail decision (deterministic, config-driven)
`verdict = pass` iff `composite ≥ qa_pass_threshold` **and** no `blocking_issues`.
Per-artifact-type threshold overrides in `qa_pass_thresholds` (a JSON map — Local SEO pages
already have a real-world "90+" bar from the nearme_intent rubric; blog R1–R7 is
all-required-checks-present). `needs_human` when the artifact is unresolvable or the rubric
is `generic`. **The LLM never sets the verdict** — it only phrases it.

### 4.4 Outcome → board action (configurable, safe defaults)
- **Pass** → advance the task out of For QA. Default target `qa_pass_status='in_review'`
  (a lead still eyeballs before the client sees it); a client can raise trust later by
  pointing it at `sent_to_client`. Records a `status_changed` activity (actor = QA system).
- **Fail** → **bounce** back to `qa_fail_status` (default `in_progress`) **and** attach the
  ranked rework findings as a comment + (optionally) checklist subtasks
  (`qa_fail_creates_subtasks`, default on) so the fix is concrete, not "try again." The
  task stays owned by its assignee.
- **needs_human** → leave the task in For QA, post the finding, and let a lead decide —
  QA declines to auto-move what it couldn't judge.

All thresholds/targets are config; **no hardcoded status keys** — resolve via
`category`/`is_done` + the override map, so a reconfigured workflow still works.

### 4.5 Surfaces
- **Task drawer** — a QA panel: latest verdict badge (pass/fail/needs-human), composite,
  per-dimension bars, the rework list, and review history; a "Run QA" button.
- **Board** — the For QA column (§2); a small pass/fail glyph on cards that have a review.
- **Notifications** (shared service, `kind="qa_result"`) — fail/needs-human post to the
  client's feed (+ Slack when configured); a clean pass is silent by default
  (`qa_notify_on_pass=false`) to avoid noise.
- **Conversational** — "how did QA go on the Inner West page?" reads the latest review;
  "QA the roof-repair article" enqueues one (`run_qa`).

---

## 5. Boundaries & handoff (with PACE and SerMaStr)

- **QA owns** (judges): running the rubric, the pass/fail verdict, opening the rework
  finding, advancing/bouncing the task **being reviewed**.
- **QA does NOT chase.** A QA-fail produces *board work* (the bounced task + rework
  subtasks). Chasing that rework — nudging, reassigning, watching it go stale — is **PACE's**
  job. Clean division: **QA judges quality and opens the finding; PACE keeps the resulting
  rework moving.** (Same handoff shape as "SerMaStr proposes → PACE places.")
- **QA ≠ SerMaStr.** QA judges *this deliverable* against a rubric; SerMaStr judges *the
  campaign*. A systemic quality pattern QA can't fix per-task (e.g. every page failing
  nearme_intent for a missing response-time fact) is a **strategy** signal — QA surfaces
  the pattern; SerMaStr owns the fix. QA never proposes campaign changes.
- **Tool isolation.** Extend PACE's `PERSONA_ACTIONS` map with a `"qa"` scope
  (`run_qa` + reads). PACE's and the strategist's scopes **exclude** QA; QA's scope
  excludes PACE writes and strategist analysis. Two more personas, still one rail.

---

## 6. Config (`config.py`) — build-ready (types/defaults/env)

```
qa_enabled: bool = False                       # QA_ENABLED — master gate
qa_model: str = "claude-haiku-4-5-20251001"    # QA_MODEL — synthesis only
qa_max_tokens: int = 1200                      # QA_MAX_TOKENS
qa_pass_threshold: float = 85.0                # default composite bar
qa_pass_thresholds: dict = {                   # per artifact_type override
    "local_seo_page": 90.0,                    # matches the nearme_intent 90+ bar
}
qa_pass_status: str = "in_review"              # where a passing task advances to
qa_fail_status: str = "in_progress"            # where a failing task bounces to
qa_fail_creates_subtasks: bool = True          # attach rework checklist on fail
qa_notify_on_pass: bool = False                # silent on clean pass
qa_autoqueue_producers: bool = False           # auto-move generated content to For QA
```

QA runs event-driven (the `for_qa` transition + on-demand), so it needs **no scheduler
hour**. Everything degrades safely when `qa_enabled=False`: the `for_qa` status still
exists and is usable as a plain column, it just doesn't trigger a review.

---

## 7. Phasing (rubrics before persona; deterministic before LLM)

**Phase 0 — the `for_qa` status + producer trigger.** Migration adds the status row +
`qa_reviews` table + `qa_review` job type; `qa_producer` fires on the transition (gated,
idempotent). No scoring yet — proves the seam end to end (moving a task to For QA enqueues
a job that no-ops cleanly). *Acceptance:* the transition enqueues exactly one job; re-entry
is a no-op; disabled → status usable, no job.

**Phase 1 — deterministic rubric layer.** `qa_signals.py` + the `local_seo_page` and
`blog_article` rubrics wired to the existing nlp `/score-page`, `page_structure_eval`, and
R1–R7 checks; deterministic pass/fail; persisted `qa_reviews`; **no LLM, no board move
yet** (verdict is recorded, not acted on). *Acceptance:* a real Local SEO page scores and
records a verdict matching a manual `/score-page`; a blog article records R1–R7 coverage;
pure threshold logic unit-tested incl. the blocking-issue and unresolvable-artifact edges.

**Phase 2 — outcome application.** Pass advances / fail bounces + rework findings (comment
+ optional subtasks) + notifications; all config-driven, no hardcoded keys.
*Acceptance:* a sub-threshold page bounces to `in_progress` with a concrete rework list; a
passing page advances to `in_review`; an unresolvable artifact stays For QA as
`needs_human`; every move is actor-audited.

**Phase 3 — QA persona + SOP grounding + conversational surface.** `qa_agent.py` synthesis
call grounded via `sop_library` (add the `qa` domain → `On_Page_Criteria_and_Coverage.md`
+ per-client `sop_store` overrides; findings cite doc + section, §3b); the QA drawer panel +
board glyph; `run_qa` on-demand action + the `"qa"` `PERSONA_ACTIONS` scope; `generic` rubric
(the one LLM-scored type) graded against a per-category checklist SOP. *Acceptance:* "QA the
X page" enqueues and answers in a QA voice citing the on-page SOP; the drawer shows the
verdict + rework list; QA never exposes PACE or strategist actions.

**Phase 4 (opt-in) — producer auto-queue.** `qa_autoqueue_producers` moves freshly
generated content to For QA so it's reviewed before a human sees it. *Acceptance:* a
completed content run lands its task in For QA and a review runs; flag-off preserves
today's behavior.

---

## 8. Non-goals (v1)
- **QA does not chase or reassign** — findings become board work; PACE owns the chase (§5).
- **No auto-publish on pass** — a pass advances the task *toward* the client (to In Review
  by default), it never sends to the client or publishes. Human gate preserved.
- **No campaign-level judgment** — systemic quality patterns are surfaced, not fixed;
  strategy stays with SerMaStr.
- **No new rubrics beyond the three artifact types** — new deliverable types are added by
  registering a rubric, not by expanding scope here.
- **The LLM never sets a verdict or a score** for the deterministic rubrics — it phrases
  and ranks only. (Generic is the sole LLM-scored type, and it leans `needs_human`.)
- No QA of non-content deliverables (link placements, citations) in v1 — those have their
  own liveness/imbalance monitors already.

---

## 9. What already exists to build on
- **Task manager:** `task_statuses` (with `category`/`is_initial`/`is_done`),
  `task_service.update_task` (emits `status_changed` with `detail.to`),
  `task_producers.py` + `close_task_by_source` (the producer/idempotency pattern),
  `task_activity.actor_id`, subtasks via `parent_task_id`.
- **Scorers (the QA backbone, already built):** nlp-api `/score-page` (8-engine composite,
  7 LLM + 1 deterministic SERP-signal) and the 5-engine service-page variant;
  `services/page_structure_eval.py` (deterministic structural fidelity); the content-quality
  **R1–R7** acceptance checks in the Blog Writer pipeline.
- **The content-QA SOP + grounding (already built, §3b):** `docs/sops/On_Page_Criteria_and_Coverage.md`
  (bands, the `<80` blocking-deficiency rule, verdict→action routing — the layer-2 standard for
  all on-page content); `services/sop_library.py` (`_RELEVANCE` domain retrieval — add a `qa`
  domain) + the per-client `sop_store` override layer. New authoring is scoped to per-category
  checklist SOPs for non-page deliverables.
- **Rails:** `services/slack_assistant/` (`PERSONA_ACTIONS` scoping, `interpret()`
  persona dimension — extend, don't fork), `notifications.emit`, the `async_jobs` worker,
  the strategy-digest **provider-registry** pattern (mirror it for the rubric registry).
- **Precedents:** PACE's deterministic-signal-layer + thin-persona split (this doc copies
  it); the per-item async-job decomposition from Local SEO bulk-create (the timeout fix).

---

## 10. Open decisions (defaults chosen; flag to change)
1. **`for_qa` position/category — chosen:** `in_progress` category, ordered before
   `in_review`. (Alternative: its own category — rejected; would force PACE signal changes
   for no benefit.)
2. **Pass target — chosen:** `in_review` (lead still eyeballs). Raise to `sent_to_client`
   per-client once trust in QA is established.
3. **Fail behavior — chosen:** bounce to `in_progress` + rework subtasks. (Alternative:
   keep in For QA with findings — rejected; hides failed work from the "done-ish" columns.)
4. **Model tier — chosen:** Haiku for synthesis. Bump only if generic-review quality
   disappoints.
5. **Producer auto-queue — chosen off** first; flip per-client once the human-in-For-QA
   flow is trusted.
6. **Generic-artifact QA — chosen:** LLM checklist, `needs_human`-leaning. Keep low-stakes
   until a real acceptance-criteria field exists on tasks.
7. **QA-SOP authoring scope — chosen (§3b):** content reuses the existing
   `On_Page_Criteria_and_Coverage.md` (no new SOP); new authoring is limited to per-category
   checklist SOPs for non-page deliverables + any per-client `sop_store` overrides. Open
   input for you: **which non-page categories (GBP posts, citations, reports) do you actually
   want QA to grade in v1** — each is one short checklist SOP, and any you skip simply stay a
   human call at In Review.
