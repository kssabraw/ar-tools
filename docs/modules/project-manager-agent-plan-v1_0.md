# Project Manager Agent — Module Plan v1.0

**Status:** Proposed · **Sibling to:** SerMaStr (the Search Marketing Strategist,
`seo-strategist-agent-plan-v1_0.md`) · **Rides:** the native task manager
(`in-app-task-manager-prd-v1_0.md`) + the SerMaStr assistant infrastructure
(`services/slack_assistant/`) · **Authored:** 2026-07-11

> **Working name:** "PMaStr" (Project Manager). Naming is an open decision (§10) —
> what matters is that it is a **distinct persona/voice** from SerMaStr, not a
> distinct system. Throughout this doc it's "the PM".

---

## 1. Purpose & position

The agency has **SerMaStr**, a Search Marketing *Strategist*: weekly, deliberative,
owner-facing, *proposes-never-executes*. It answers "is the campaign winning, and
what should we change?"

It does **not** answer the day-to-day delivery questions: *Is the work getting
done? Is anything stuck? Is anyone overloaded? What should this VA do today?* Those
are **project-management** questions — a different job with a different safety
envelope, cadence, audience, and cost. Asking SerMaStr to also do PM work is the
mistake this module avoids.

The PM is the operational counterpart to the strategist. It watches the **native
task board** (built + merged: `tasks`/`task_sections`/`task_activity` etc.) and
keeps delivery moving — surfacing stuck/overdue/unassigned work, flagging pace and
overload, and (confirm-gated) actually *doing* the small PM moves: reassign, bump a
due date, nudge an assignee, generate the month.

### Why separate the PM from SerMaStr (decision record)

| | **SerMaStr (Strategist)** | **PM** |
|---|---|---|
| Core verb | **Proposes**, never executes (§3 hard rule) | **Executes** (confirm-gated) — that's the point |
| Cadence | Weekly + escalation events | **Daily** + on-demand |
| Audience | Owners (Kyle/Ryan) | VAs + leads |
| Question | "Are we winning? What should change?" | "Is the work getting done? What's stuck?" |
| Context | Huge — every module, SOP corpus, forecasts | Tiny — board state, workload, due dates |
| Model / cost | Sonnet + drill-downs + 25k digest (~$/run) | Haiku-tier + a small board digest (~¢/run) |
| Signal it emits | Strategic decisions | Operational nudges |

Merging these erodes SerMaStr's *proposes-never-executes* guardrail (a PM must
execute), bloats an already-large strategist prompt with task-chasing noise, and
crosses the two signals so the owner reading strategy also gets nagged about
overdue subtasks. **Two personas, one set of rails.** (Rejected alternative: a
standalone PM service — violates the suite's "no new infra" rule; everything the PM
needs already exists.)

### What is NOT an agent (the 80% that stays deterministic)

The suite's proven pattern is *deterministic where possible, LLM only for
judgment*. The task manager already covers most PM duties **without any model**:

| PM duty | Already built (deterministic) |
|---|---|
| Plan the month | `task_monthly.generate_month_for_client` + Recipe Engine |
| Assign work | capacity-aware `distribute_tasks` auto-distribution |
| Create work from events | `task_producers` (rank drop / maps / action_plan / content_run → tasks, auto-closed on resolve) |
| Chase due dates | daily `task_workload.run_due_sweep` digest |
| Spot overload | daily `task_workload.run_workload_alert` |

The genuinely-missing PM pieces are **more determinism, not more intelligence**
(§3): staleness, month-pace, producer backlog. Those are rules — like the
`response_episodes` verify-loop — and land **before** any LLM persona. The LLM only
enters to **prioritize, phrase, and act on** what the deterministic layer surfaces.

---

## 2. Architecture

The PM is a thin judgment layer on top of a new **deterministic PM-signal layer**,
both riding existing infrastructure. **Zero new infra** (the locked suite rule): no
new service, queue, scheduler, or notification channel.

```
  ┌─────────────────────────── deterministic (no LLM) ───────────────────────────┐
  │ services/pm_signals.py  — pure signal builders over the task_* tables:        │
  │   • staleness    (days in current status vs per-status thresholds)            │
  │   • month_pace   (per client: % complete vs % of month elapsed)               │
  │   • workload     (reuse task_workload.build_team_workload)                     │
  │   • untriaged    (unassigned / no-due-date open tasks; untouched producer     │
  │                   tasks — a rank-drop task nobody has opened)                  │
  │   • due          (reuse task_workload due-sweep selection)                    │
  └───────────────────────────────────────────────────────────────────────────────┘
             │ feeds ▼                                        ▲ reads (free)
  ┌───────────────────────── judgment (LLM, cheap) ──────────┴────────────────────┐
  │ services/pm_agent.py  — the PM persona:                                        │
  │   • daily PM sweep   → one digest per team/lead (what needs a human)           │
  │   • conversational   → a persona on the SerMaStr interpret() loop             │
  │   • VA daily brief   → "what should I work on?" (per-person, via identity)     │
  │  + PM actions in the SerMaStr _ACTIONS registry (execute, confirm-gated)       │
  └───────────────────────────────────────────────────────────────────────────────┘
```

### Triggers (event-driven / scheduled — never always-on)

- **Daily PM sweep** — once/day on the shared `gsc_scheduler` loop (the
  `response_episodes.run_episode_sync` / due-sweep pattern), gated on
  `pm_agent_enabled`. Emits at most one digest when something needs a human.
- **On-demand conversational** — any Slack/`/assistant` message the router routes
  to the PM persona (see §4). No schedule.
- **VA daily brief** — either pulled ("what's on my plate?") or an optional
  per-VA morning push (config `pm_daily_brief_push`, default off for v1).
- **No new escalation hooks** — the PM *hands off* to SerMaStr for strategy (§5),
  it doesn't own escalations.

### Inputs (pre-digested — the PM never reasons over raw tables)

Exactly like the strategist reads a digest, not raw tables: `pm_signals.build_board_digest(client_id | None)`
returns the standard PM envelope — per client, the current-month section's
progress, the stuck/overdue/unassigned lists (capped + sorted), per-member
workload, and untouched producer tasks. Portfolio mode (no client) rolls these to
counts + the top offenders, mirroring `build_portfolio_context()`.

### Drill-down / actions (where the PM *executes* — the key difference)

New confirm-gated entries in the SerMaStr `_ACTIONS` registry (same `_pending`
reply-*yes* flow, same `stage` hook that names the exact target before confirming):

| action | does | gating |
|---|---|---|
| `reassign_task` | move a task to another roster member | confirm (names task + from→to) |
| `set_task_due` / `bump_task_due` | set/shift a due date | confirm |
| `nudge_assignee` | post a reminder to the assignee (via notifications / their linked login) | confirm |
| `generate_client_month` | run `task_monthly` for a client now | confirm |
| `unblock_task` | move a `blocked` task back to `in_progress` (+ note) | confirm |

All resolve the target **before** the confirm (the Asana-task-action pattern:
`match_open_tasks`/`match_named`, exact-beats-substring, 0→list, >1→ask which).
Free reads (board digest, "what's stuck") need no confirm. The `paid` flag in
`_ACTIONS` already means "confirm-gated" (spend **or** side effect) — PM writes use
it for the side effect.

### Output surfaces

1. **Daily PM digest** via `notifications.emit(kind="pm_digest", …)` — in-app feed +
   Slack, the existing pipe. One message: "3 things need a human today: …".
2. **Conversational** — answers in Slack + the `/assistant` page, PM persona voice.
3. **A "Delivery" card** on the client workspace + a suite-level **PM board health**
   read (optional v1.1 UI; the digest + chat cover v1).

---

## 2b. The deterministic signal layer (`services/pm_signals.py`)

The heart of the module — pure, unit-tested, no LLM, no paid calls. Every signal is
a rule over data the task manager already writes.

**Staleness.** A task's *days-in-current-status* = today − the `created_at` of its
latest `task_activity` row of kind `status_changed` (fallback: the task's
`created_at`). Per-status thresholds (config, defaults):
`blocked` → 3d, `in_review`/`sent_to_client` → 5d, `in_progress` → 10d,
`not_started` in a past-half month → flag. A task past its threshold is **stale**;
the digest names it, its assignee, and how long. (Mirrors the `response_episodes`
clock — a deterministic age check, not a model call.)

**Month-pace.** Per client, for the current-month `task_sections` row:
`pct_complete` (done top-level tasks / total) vs `pct_elapsed` (day-of-month /
days-in-month). `behind` when `pct_complete + grace < pct_elapsed` (grace 0.15, the
goals-pace precedent). Emits "IHBS: July 70% elapsed, board 30% done — behind."

**Workload.** Reuse `task_workload.build_team_workload` verbatim (per-member open
hours vs capacity, same-day due clustering, overload flags). The PM adds the
*who-to-rebalance-to* read: the member with the most remaining capacity
(`distribute_tasks`'s input), so a reassign suggestion is grounded.

**Untriaged.** Open tasks with no assignee, or no due date, past a grace window; and
**untouched producer tasks** — a `source in (rank_drop, maps_alert, action_plan)`
task still in the initial status with zero `task_activity` beyond `created`, i.e. an
auto-created alarm nobody has opened. These are the PM's highest-value catches
(work the system created that would otherwise rot).

**Due.** Reuse the due-sweep selection (`task_workload.select_due_tasks`) so the PM
and the standalone due-sweep never disagree.

All pure builders return the **standard PM envelope** so the persona and the UI read
one shape. Unit-tested like `test_response_episodes` / `test_task_manager`.

---

## 3. The PM persona (`services/pm_agent.py`)

A cheap judgment layer. It never re-derives the deterministic numbers (same rule as
the strategist: "cite the digest, never compute your own") — it **prioritizes,
phrases, and offers to act**.

- **Daily sweep** → `pm_signals.build_board_digest()` (portfolio) → one LLM call
  (Haiku-tier, `pm_agent_model`) that ranks the surfaced items and writes a short
  "what needs a human today" digest with **offered actions** (each a reply-*yes*
  action from §2). Empty/nothing-actionable → posts nothing (the strategist's
  "confirmatory reviews post nothing" rule).
- **Conversational PM** → registered as a persona on the shared `interpret()` loop.
  A message like "what's stuck on Acme?" / "move the GBP task to Ivy, it's been
  blocked a week" routes to the PM persona, which answers from the board digest and
  can stage the action. Reuses SerMaStr's whole stack (signature verify, in-thread
  memory, `_pending` confirm, streaming).
- **VA daily brief** → "what should I work on today?" Answered from **that person's**
  My Tasks — now possible because the **identity bridge** (`asana_team_members.profile_id`,
  merged 2026-07-11) links a Slack/suite user to their roster member. Resolve the
  asker → their `profile_id` → their `my_gid` → `bucket_by_due` → a prioritized list
  (overdue first, then due-today, then the highest-priority open work). No identity
  link → falls back to "which person?" (the My-Tasks picker behavior).

**New context provider** for the shared registry: `_ctx_delivery(supabase, client_id,
today)` in `services/slack_assistant/context.py` — the per-client board digest
(month pace, stuck count, overdue count, unassigned count), so **SerMaStr too** can
see delivery health when answering "how's the campaign going" (append to
`_CONTEXT_PROVIDERS`; the doc's own extension recipe). This is the one place the two
personas share data — read-only, both directions safe.

---

## 4. Boundaries between the PM and SerMaStr (who owns what)

Hard-coded routing + prompt boundaries so the two never collide:

- **PM owns:** task state, assignment, due dates, workload, month pace, stuck work,
  "what should I do today", generating the month. It **executes** these.
- **SerMaStr owns:** campaign health, what work to *invent* (proposals),
  strategy/priorities/budgets/forecasts, SOP-grounded advice. It **proposes**.
- **Handoff, PM → strategist:** when a delivery problem is really a *strategy*
  problem (e.g. a client is behind pace **because** the plan is wrong, or a stuck
  task needs a senior call), the PM does **not** decide — it surfaces "this looks
  like a strategy question — want me to run a strategist review?" and offers the
  existing `run_strategy_review` action. The strategist's §3 passthrough/halt rules
  are unchanged.
- **Handoff, strategist → PM:** when an **approved** strategist proposal becomes a
  task (already built: `asana_push.push_proposal` → native task), the PM picks it up
  as ordinary board work from then on. Clean seam, no overlap.
- **Router rule (pure, testable):** a message is PM-shaped when it's about task
  state/assignment/due/workload/"today"/"stuck"/"overdue"; strategy-shaped when it's
  about performance/changes/priorities/why. Ambiguous → the existing SerMaStr
  clarifying-question behavior. (A generous regex gate like `wants_sop_grounding`,
  plus the named-client/portfolio gates already in place.)

---

## 5. Data model & config

**No new tables for v1.** Everything reads existing task/roster/activity data.
Optional (v1.1) `pm_snooze` table so a lead can mute a specific stale-task flag for
N days (avoids re-nagging on a known-parked task) — deferred until asked for.

**Config (`config.py`), all with safe defaults:**

```
pm_agent_enabled            = False   # master gate (parallel-run safe, like native_tasks_enabled)
pm_agent_model              = "claude-haiku-4-5-20251001"   # cheap; strategist stays Sonnet
pm_agent_max_tokens         = 1200
pm_daily_sweep_hour_utc     = <ingest hour>   # rides the scheduler tick
pm_daily_brief_push         = False   # per-VA morning push (v1 = pull-only)
# staleness thresholds (days in status)
pm_stale_blocked_days       = 3
pm_stale_review_days        = 5
pm_stale_in_progress_days   = 10
pm_month_pace_grace         = 0.15
pm_digest_max_items         = 8       # cap the daily digest
```

**Notification kinds:** `pm_digest` (daily), reusing the existing `notifications`
pipe. Per-person routing (a VA's own nudges to *them*) is the piece the identity
bridge unblocks but the notifications service doesn't fully deliver yet (still
agency-level) — v1 routes PM nudges to the shared channel tagged with the assignee's
name; true per-user inbox is a shared follow-up with the strategist (both want it).

**Async/scheduler:** the daily sweep runs **inline** on the `gsc_scheduler` tick
(like `run_episode_sync` / `run_trend_sweep` / `run_offpage_sweep`) — DB-reads-only,
no new job type needed. A conversational action that generates a month reuses the
existing `task_month_generate` job.

---

## 6. Cost model

- **Deterministic layer:** free (DB reads on the shared scheduler).
- **Daily sweep:** one Haiku-tier call/day/board (portfolio = 1 call), only when
  something's actionable → typically a few cents/day agency-wide.
- **Conversational:** one cheap call per question (same as SerMaStr Q&A but
  smaller context + cheaper model).
- Contrast: a strategist run is Sonnet + drill-downs + 25k digest. Keeping PM work
  off the strategist is the cost win, not just the design win.

---

## 7. Phasing (deterministic value first)

**Phase 0 — deterministic signal layer.** `services/pm_signals.py` (staleness,
month-pace, workload reuse, untriaged/producer-backlog, due reuse) + the standard
envelope + unit tests. Wire the **daily digest** deterministically first (no LLM):
a plain templated "N stuck, N overdue, N unassigned, these clients behind pace"
message via `notifications.emit(kind="pm_digest")`, gated on `pm_agent_enabled`.
*Acceptance:* on real board data the digest names the right stuck/overdue/behind
items; zero LLM; green tests; posts nothing when all clear.

**Phase 1 — PM actions.** The confirm-gated `_ACTIONS` (reassign / set-due /
unblock / generate-month / nudge), each staged to name its target. *Acceptance:*
"move X to Ivy" from Slack reassigns X after a reply-*yes* that names X + Ivy.

**Phase 2 — the persona.** `pm_agent.py` daily sweep upgraded to the ranked/phrased
LLM digest + the conversational PM persona on `interpret()` + the `_ctx_delivery`
provider for SerMaStr. *Acceptance:* "what's stuck on Acme?" answers from the
digest; the daily digest reads like a PM, not a dump; empty → silent.

**Phase 3 — VA daily brief.** Per-person "what should I work on?" via the identity
bridge; optional morning push. *Acceptance:* a linked VA asks and gets *their* real
prioritized list; an unlinked user is asked which person.

**Phase 4 (optional) — UI.** A "Delivery" workspace card + a suite PM board-health
view. The digest + chat make this optional.

---

## 8. Non-goals (v1 cut list)

- Time tracking / actual hours (the task manager is estimate-only).
- Gantt/dependencies/critical-path (out of the task manager v1 too).
- Auto-executing without confirmation (every write is reply-*yes* gated — the PM
  acts, but a human always approves, mirroring the approval-in-the-middle loop).
- Owning escalations or strategy (that's SerMaStr; the PM hands off).
- A second notification channel or per-user inbox (shared follow-up; v1 tags the
  shared channel).
- Cross-client capacity planning from the workbook (the workload view's known
  follow-up; not PM-specific).

---

## 9. Open decisions (defaults chosen; flag to change)

1. **Name.** "PMaStr" vs a plainer "PM" vs folding it in as SerMaStr's "PM mode".
   Recommendation: a distinct name/voice for signal hygiene; wiring is shared.
2. **One persona or two on the same channel?** v1: same Slack channel + `/assistant`,
   routed by message shape. If the two voices blur, give the PM its own channel.
3. **Daily brief: pull-only or push?** v1 pull-only (`pm_daily_brief_push=False`) —
   turn on per-VA push once per-user notification routing lands.
4. **Model tier.** Haiku-tier proposed for cost; bump to Sonnet only if the ranking
   quality disappoints.
5. **Snooze.** Ship the `pm_snooze` table now or wait for the first "stop nagging me
   about that parked task"? Default: wait (v1.1).

---

## 10. What already exists to build on (starting point)

- **Task manager** (merged): `services/task_service.py` (CRUD + `get_statuses` +
  `bucket_by_due` + `close_task_by_source`), `task_monthly.py`, `task_workload.py`
  (`build_team_workload` / `run_due_sweep` / `select_due_tasks`), `task_producers.py`,
  `task_collab.py`; tables `tasks`/`task_sections`/`task_statuses`/`task_activity`
  (the staleness source) etc.
- **Identity bridge** (merged 2026-07-11): `asana_team_members.profile_id` +
  `/tasks/mine` `my_gid` resolution — the VA-brief foundation.
- **SerMaStr rails**: `services/slack_assistant/` (`_CONTEXT_PROVIDERS`,
  `_ACTIONS`, `_pending` confirm, `interpret()`, streaming); `notifications.emit`;
  the shared `gsc_scheduler` inline-sweep pattern (`run_episode_sync`).
- **Precedents to copy**: `response_episodes` (deterministic clock + daily sync),
  the Asana-task SerMaStr actions (stage-then-confirm target resolution),
  `strategy_digest` (provider registry + "cite the digest, never compute").
