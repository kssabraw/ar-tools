# PACE — Project Assignment, Coordination & Execution Agent — Module Plan v1.3

**Status:** Phases 0–4 **built + live** (behind `pace_enabled`, enabled in
production 2026-07-12) · Phases 5–7 **built** (v1.3 full-PM scope, PR #340) · **Sibling
to:** SerMaStr (`seo-strategist-agent-plan-v1_0.md`) · **Rides:** the native task
manager (`in-app-task-manager-prd-v1_0.md`) + the SerMaStr assistant
(`services/slack_assistant/`) · **Authored:** 2026-07-11 · **Revised:** 2026-07-11
(v1.1 after review #1, v1.2 after review #2), 2026-07-12 (v1.3 full-PM scope)

> **Revision note (v1.3 — full-PM scope).** Owner direction (2026-07-12): PACE must
> act as a full delivery **project manager** — assign work to the *correct* party
> (role/skill matching, not just capacity), watch hours + overdue (**built**), set up
> monthly boards (**built**), and **write PM reports**. This revision adds:
> **(a)** a role/skill **competency model** + a deterministic **workload-aware
> placement engine** (§4.6) that auto-assigns one-off + approved tasks to the best-fit
> **skilled, eligible, least-loaded** member — with an **overload fallback** (hold +
> flag when the skilled pool is at capacity);
> **(b)** the **approval → PACE placement hook** (an approved SerMaStr proposal is
> auto-placed, §5);
> **(c)** **PACE delivery reports** (§4.7 — throughput / overdue / capacity-utilization
> / month-completion; internal-facing; deterministic + optional narrative);
> **(d)** **dedicated-channel routing** (§10.2 resolved — PACE gets its own channel).
> Phases 0–4 are **built + merged** (PR #335); the above are **new Phases 5–7** (§8).
> **Design guardrail:** deterministic *system* placement (the same class as the
> already-shipping monthly `distribute_tasks`) is distinct from LLM-*initiated* writes,
> which stay authorized + actor-bound + reply-*yes* gated (§9).

> **Name (resolved).** **PACE — Project Assignment, Coordination & Execution.**
> (Was the working name "PMaStr"; open naming decision now closed.) Positioning:
> **SerMaStr determines what should be done; PACE keeps it moving.**
>
> **Revision note (v1.2 — after review #2).** Review #2 rated v1.1 ~90% build-ready
> and asked for one more pass on **execution + security** details. All six essential
> items are now designed, each verified against source; §13 maps them 1:1.
> 1. **Two-way persona tool isolation** (§4.1) — v1.1 gave PACE a restricted allowlist
>    but left SerMaStr the "full registry", which (if PACE actions join the global
>    `_ACTIONS`) would let the strategist see `reassign_task`/etc. — breaking the
>    boundary. Added an explicit `PERSONA_ACTIONS` scope map; the strategist scope
>    **excludes** PACE writes, PACE's scope includes `run_strategy_review` as the one
>    handoff exception (resolves a §4.1↔§5 contradiction).
> 2. **Actor-bound confirmations** (§3.3) — `_pending` stores `{action, client_id, args}`
>    with **no requester**; anyone who replies "yes" in the thread executes it. Every
>    pending entry now stores the requesting `ActionContext`; the confirming actor must
>    match (admin takeover is the explicit exception). Same for the web `pending_token`.
> 3. **Explicit web auth threading** (§3.1) — `handle_chat(...)` has no `auth`/actor
>    param today; the router has `auth` but doesn't pass it in. Spec now threads an
>    `ActionContext` from the router through `handle_chat` → `interpret`.
> 4. **Pre-client-resolution routing** (§4.1) — the current flows resolve a client
>    *before* mode selection, so "what should I work on?" would misroute. Added the
>    explicit routing order: actor → pending → intent → **personal-brief bypass** →
>    client/portfolio → persona.
> 5. **Actor through monthly generation** (§3.2) — `enqueue_task_month`/
>    `generate_month_for_client`/`create_task` drop `created_by`, so a PACE-triggered
>    month can't be audited. Spec threads `actor_id` the whole async path; scheduled
>    generation uses a null/system actor.
> 6. **Atomic digest dedupe** (§6) — the query-guard has a rolling-deploy TOCTOU race.
>    Switched to a nullable **unique `notifications.dedupe_key`** now (tiny migration).
>
> Plus the smaller fixes: due-date-weighted pace **formula** (§2b), real `nudge_assignee`
> **delivery** via `<@slack_user_id>` (§4.2), corrected **unblock-history** source (§4.2),
> and business-days = Mon–Fri no-holidays (§2b). Verified against source: `_pending` has
> no actor; `handle_chat` has no auth param; monthly `create_task` omits `created_by`.

---

## 1. Purpose & position

SerMaStr is a Search Marketing *Strategist*: weekly, deliberative, owner-facing,
*proposes-never-executes* — "is the campaign winning, and what should we change?"

It does not answer the delivery questions: *Is the approved work getting done? Is
anything stuck? Is anyone overloaded? What should this VA do today?* Those are
project-management questions — a different job with a different safety envelope.

**PACE** is the operational counterpart. It watches the **native task board** and keeps
delivery moving — surfacing stuck/overdue/unassigned work and pace/overload, and
(authorized + confirm-gated) doing the small moves: reassign, bump a due date, unblock,
generate the month.

### Why separate PACE from SerMaStr (decision record)

| | **SerMaStr (Strategist)** | **PACE** |
|---|---|---|
| Core verb | **Proposes**, never executes | **Executes** (authorized + confirm-gated) |
| Cadence | Weekly + escalations | **Daily** + on-demand |
| Audience | Owners (Kyle/Ryan) | VAs + leads |
| Question | "Are we winning? What should change?" | "Is the approved work getting done?" |
| Context | Huge — every module, SOP corpus | Tiny — board state, workload, due dates |
| Model / cost | Sonnet + drill-downs + 25k digest | Haiku-tier + a small board digest |
| Tools | Strategist scope (no PACE writes) | PACE scope (writes + handoff) — §4.1 |

Merging these erodes the *proposes-never-executes* guardrail, bloats the strategist
prompt with task-chasing noise, and crosses the two signals. **Two personas, one set of
rails.** (Rejected: a standalone PM service — violates "no new infra".)

### What is NOT an agent (the 80% that stays deterministic)

The task manager already covers most PM duties **without any model**: monthly generation
+ Recipe Engine (plan), capacity-aware `distribute_tasks` (assign), `task_producers`
(create-from-events, auto-close), `run_due_sweep` (chase), `run_workload_alert`
(overload). The missing pieces are **more determinism, not intelligence** — staleness,
month-pace, unacted-on producer backlog (§2b). Those land first; the LLM only
prioritizes, phrases, and (authorized) acts.

---

## 2. Architecture

Zero new infra. A deterministic **signal layer** + a thin persona on existing rails.

```
  ┌──────────────────── deterministic (no LLM, no paid calls) ───────────────────┐
  │ services/pm_signals.py — pure builders over task_* tables (unit-tested):      │
  │   staleness · month_pace (heuristic) · workload (reuse) · untriaged +         │
  │   unacted-on producer tasks · due (reuse task_workload.select_due_tasks)      │
  │   → the standard PACE envelope                                                │
  └───────────────────────────────────────────────────────────────────────────────┘
        │ feeds ▼                                              ▲ reads (free)
  ┌──────────────────── judgment (LLM, cheap, restricted) ─────┴──────────────────┐
  │ services/pace_agent.py — the PACE persona:                                     │
  │   daily digest (INFORMATIONAL) · conversational (own prompt/model/tools)       │
  │   · personal brief (web first; Slack after identity mapping)                   │
  │  + PACE actions in a PERSONA-SCOPED allowlist, actor-authorized + actor-bound   │
  │    confirm                                                                     │
  └───────────────────────────────────────────────────────────────────────────────┘
```

### Triggers
- **Daily digest** — once/workday, inline on `gsc_scheduler`, gated on `pace_enabled`,
  **atomically deduped** (§6). One agency-level digest, grouped by client, capped at
  `pace_digest_max_items`.
- **On-demand conversational** — PACE-routed messages (§4.1).
- **Personal brief** — pull-only in v1 (`pace_daily_brief_push=False`); web first.

### Inputs
`pm_signals.build_board_digest(client_id | None)` returns the standard envelope; PACE
never reasons over raw tables. Portfolio (no client) rolls to counts + top offenders.

---

## 2b. The deterministic signal layer (`services/pm_signals.py`)

Pure, unit-tested, no LLM/paid calls. **Configurable-workflow-safe**: keyed off status
**category** + `is_initial`/`is_done`, never hardcoded status keys.

**Staleness.** *days-in-current-status* = today − the `created_at` of the task's most
recent **status-clock-reset** activity, where a reset is `created` | `status_changed` |
`reopened` (completed tasks excluded; `reopened` matters because `reopen_task` emits
`reopened`, not `status_changed` — verified — so a long-idle task reopened today must read
*fresh*). Thresholds: a **JSON map keyed by status key** with a **coarse-category
fallback** (`pace_stale_thresholds`, §6): default by category — `blocked` 3d,
`in_progress` 10d; per-key overrides for review-ish states (`in_review`/`sent_to_client`
5d). *(Recommendation, §13: also have `task_service.reopen_task` emit a `status_changed`
so all consumers see one clock — but the signal must not depend on it.)*

**Month-pace (a heuristic, labeled as such).** Per client's current-month section:
- **Before ≥ half the tasks have due dates** → calendar proxy: `pct_complete`
  (done top-level / total) vs `pct_elapsed` in **business days** (Mon–Fri, **no holiday
  calendar in v1**). Flag when `pct_complete + grace < pct_elapsed`.
- **Once ≥ half the top-level tasks have due dates** → **due-date-weighted expected
  progress** (build-ready formula):
  ```
  expected_complete = (dated tasks with due_date <= today) / (all top-level tasks with due dates)
  actual_complete   = (completed dated tasks)              / (all top-level tasks with due dates)
  behind  ⇔  actual_complete + grace < expected_complete
  ```
Suppressions in both modes: don't flag in the **first 3 business days** of the month;
don't flag boards under `pace_month_pace_min_tasks` (default 4). Grace
`pace_month_pace_grace` (0.15). It is a *pace hint*, never a definitive verdict.

**Workload.** Reuse `task_workload.build_team_workload` verbatim. For reassignment PACE
produces a **candidate list**, not a pick: eligible members ranked by remaining capacity,
**filtered** to active members and (where known) service-type/client eligibility. The
human chooses (§4.2).

**Untriaged + unacted-on producer tasks.** Open tasks with no assignee or no due date past
a grace window; and **unacted-on producer tasks** — `source in (rank_drop, maps_alert,
action_plan)` still in the initial status whose only `task_activity` is `created` (nobody
has assigned, changed, or commented). *Named "unacted-on", not "untouched/unopened":
viewing writes no activity, so this can't claim "nobody looked".* The highest-value catch.

**Due.** Reuse `task_workload.select_due_tasks` so PACE and the standalone sweep agree.

All builders return the **standard PACE envelope**; unit-tested (incl. the reopen,
first-3-days, and dated-vs-undated month-pace edges).

---

## 3. Identity & authorization (prerequisite for any PACE action)

**Confirmation is not authorization**, and **staging-time authorization is not
confirmation-time authorization** (§3.3). Identity + permissions ship **before** PACE
actions (§8).

### 3.1 Actor context — resolved once per turn, threaded end to end
```
ActionContext = { profile_id, role, slack_user_id?, channel?, source }   # source: 'web' | 'slack'
```
- **Web (`/assistant`)** — JWT-authenticated. **Required (not free) threading:** the
  router (`routers/assistant.py`) builds the context from `auth` and passes it in —
  `handle_chat` currently takes `(message, history, sticky_client_id, pending_token,
  on_event)` with **no actor**, so it gains an `action_context` param that flows into
  `interpret`:
  ```python
  ctx = ActionContext(profile_id=auth["user_id"], role=auth["role"], source="web")
  await assistant_chat.handle_chat(..., action_context=ctx)
  ```
- **Slack** — the handler ignores `event.user` today. **New: a Slack→profile map** —
  `profiles.slack_user_id` (unique, nullable) + an admin linking step (a Team-page field;
  self-serve `/pace link <email>` later) — thread `event.user` → `profiles.slack_user_id`
  → `ActionContext`. An **unmapped** Slack user is an anonymous reader: reads per channel
  policy, **all writes refused** ("link your Slack account first").

### 3.2 Role → action matrix (enforced in code, not just prompt)
Roles: the existing `client < team_member < staff < admin` (`ROLE_RANK`).

| Action | VA (`team_member`) | Lead (`staff`) | Admin |
|---|---|---|---|
| Read own tasks / personal brief | ✅ | ✅ | ✅ |
| Read full client board | via policy | ✅ | ✅ |
| Update **own** task status | ✅ | ✅ | ✅ |
| Nudge **self** | ✅ | ✅ | ✅ |
| Nudge **someone else** | ❌ | ✅ | ✅ |
| Reassign tasks | ❌ | ✅ | ✅ |
| Change **someone else's** due date | ❌ | ✅ | ✅ |
| Unblock arbitrary task | ❌ | ✅ | ✅ |
| Generate client month | ❌ | via policy | ✅ |

Enforcement is in the action layer: `stage(action_context, client_id, args)` /
`run(action_context, client_id, args)` — a permission check gates **staging** (refused
before the confirm, with a reason). **Every write records the actor** on
`task_activity.actor_id`. This includes the async monthly path, which is **actor-threaded
end to end** (v1.1 promised auditing but the path dropped it — verified):
```
enqueue_task_month(client_id, target, trigger="pace", actor_id=ctx.profile_id)
  → job payload {client_id, month, trigger, actor_id}
  → run_task_month_job
  → generate_month_for_client(client_id, target, actor_id=…)
  → create_task(..., created_by=actor_id) + create_subtasks(..., created_by=actor_id)
```
Scheduled monthly generation passes `actor_id=None` (a system actor).

### 3.3 Actor-bound confirmations (the confirmation is protected, not just the request)
`_pending` currently stores `{action, client_id, args}` keyed by `(channel, thread_ts)` —
**no requester** — so a staff member can stage a reassignment and a **VA in the thread**
can reply "yes" and execute it. Fix: the pending entry stores the requesting
`ActionContext`; on confirm, the **confirming actor must match the requester** (resolve
the confirmer's identity the same way — Slack `event.user`→profile, or the web session).
A mismatch is refused ("only the person who requested this can confirm it"); **admin is
the explicit takeover exception**. The web `pending_token` path stores + re-checks the
requester identically. (Default: same-actor; no silent cross-actor execution.)

---

## 4. The PACE persona (`services/pace_agent.py`)

### 4.1 A real persona split + two-way tool isolation
`interpret()` today = one system prompt, one model, one action registry, shared tools.
PACE needs a **persona dimension** *and* **explicit per-persona action scopes** — because
if PACE's write actions simply join the global `_ACTIONS`, the strategist's "full
registry" would include them, breaking the boundary:
```python
PERSONA_ACTIONS = {
    "strategist": { *existing analysis/report/approved-proposal actions* },   # NO PACE writes
    "pace": {
        "reassign_task", "assign_task", "set_task_due", "bump_task_due",   # assign_task (v1.3, §4.6)
        "nudge_assignee", "generate_client_month", "unblock_task",
        "generate_pace_report",  # v1.3 (§4.7)
        "run_strategy_review",   # the ONE handoff exception (resolves §4.1↔§5)
    },
}
interpret(question, client, context, history, *, persona,           # 'pace' | 'strategist'
          model=pace_model, max_tokens=pace_max_tokens,
          system_prompt=PACE_SYSTEM, tools=PERSONA_ACTIONS[persona], action_context=…)
```
- **Restricted, isolated both ways** — PACE never sees backlink/profile-edit/keyword/
  report tools; the strategist never sees PACE operational writes.
- **Cheaper model** — `pace_model` (Haiku-tier); strategist stays Sonnet.

**Routing order (runs BEFORE client resolution, not just before prompt selection).**
Current flows resolve a client first (Slack: no client → portfolio; web: named/sticky
client → client mode), which would misroute "what should I work on?" So:
```
1. Resolve actor (ActionContext).
2. Handle a pending confirmation (actor-bound, §3.3).
3. Classify intent (PACE vs strategist; personal-brief vs board vs strategy).
4. If PERSONAL BRIEF → bypass client resolution; read cross-client My Tasks for the actor.
5. Else resolve client vs portfolio (existing logic).
6. Select persona prompt + context + PERSONA_ACTIONS[persona].
```

### 4.2 PACE actions (persona-scoped, actor-authorized, actor-bound confirm)
Each: permission-checked at stage (§3.2), target-resolved before the confirm
(`match_open_tasks`/`match_named`), stored with the requester (§3.3), then reply-*yes*:

| action | does | min role |
|---|---|---|
| `reassign_task` | move a task to another member (from a capacity+eligibility candidate list) | staff |
| `assign_task` (v1.3) | auto-place an unassigned task on the correct **skilled, eligible, least-loaded** member (§4.6); holds + flags if that pool is over capacity | staff |
| `generate_pace_report` (v1.3) | build a PACE delivery report (per-client or portfolio, §4.7) | staff |
| `set_task_due` / `bump_task_due` | set/shift a due date | staff (own task: team_member) |
| `nudge_assignee` | remind an assignee (delivery below) | staff (self: team_member) |
| `generate_client_month` | run `task_monthly` now (actor-threaded, §3.2) | admin (policy: staff) |
| `unblock_task` | restore the task's **pre-blocked** status, else ask | staff |

- **`unblock_task` history source (corrected):** find the `task_activity` `status_changed`
  row whose `detail.to` == the blocked status; restore its **`detail.from`**. (Not "the
  most recent `status_changed.to`" — that's the current status.) If no such row / ambiguous
  → **ask** which status. Never hardcode `in_progress`.
- **`nudge_assignee` delivery (real, not a name tag):** post to the shared channel with a
  genuine Slack mention built from the assignee's `profiles.slack_user_id` → `<@U…>`. No
  Slack mapping for that assignee → **in-app notification only**, and the reply says so
  (or refuses if in-app is disabled) — never a plain-text name that pings nobody.

### 4.3 Daily digest — INFORMATIONAL (Option A)
`notifications.emit` posts a standalone channel message; it does not open an assistant
thread or stage `_pending` (one action per `(channel, thread_ts)`). So the digest **states
problems + the exact command to run**; actions are invoked explicitly in the assistant:
> *PACE daily · 3 items need a human*
> • *IHBS* — "GBP categories" blocked 9 days (Minda). → `@PACE unblock GBP categories on IHBS`
> • *Acme* — behind pace (due-weighted; heuristic).
> • *First Class Roofing* — rank-drop task unacted-on 4 days (unassigned). → `@PACE assign it`
> Deep links: `/clients/:id/tasks`.

No reply-*yes* from the digest. (Options B "thread-per-action" and C "Block Kit buttons
with signed action IDs" are later; C is best UX but needs interactive-endpoint infra.)

### 4.4 Personal brief
"What should I work on today?" from **that person's** My Tasks. **Web first** (JWT →
`profile_id` → linked `asana_team_members` → `my_gid` → `bucket_by_due`). **Slack only
after §3.1's mapping.** No mapping → "link your Slack account first". Reached via the
routing bypass (§4.1 step 4), so it's never restricted to a sticky/named client.

### 4.5 Shared read for the strategist
Add `_ctx_delivery(supabase, client_id, today)` to `_CONTEXT_PROVIDERS` — the per-client
board digest — so SerMaStr *sees* delivery health. Read-only; the one safe shared seam.

### 4.6 Workload-aware assignment with role/skill matching (the "correct party") — v1.3
The gap today: monthly *template* tasks auto-distribute by `distribute_tasks`, but
**one-off and approved tasks land unassigned**, and distribution is **capacity-only**
(round-1 review #10) — it doesn't know *who can do what*. v1.3 adds a competency layer +
a deterministic placement engine.

**Competency model (additive schema).** Each task carries a `category_key` (seeded:
`content`, `link_building`, `gbp_authority`, `strategy`). Add a per-member competency map:
```
task_member_skills(member_gid → asana_team_members, category_key → task_categories,
                   weight int default 1, is_primary bool default false)
```
A normalized table, editable on the **Workload/Team page** beside capacity + the
suite-user link. A member with **no** skill rows is treated as a **generalist** (eligible
for any category) so the feature degrades safely on day one (no roster setup required).

**Placement algorithm (`services/pm_assign.pick_assignee(task, …)` — pure, unit-tested):**
1. `category = task.category_key` (missing ⇒ any).
2. **Candidate pool** = active members ∩ **client-eligible** (existing
   `asana_client_projects.auto_assignee_gids`; empty ⇒ all active) ∩ **skilled**
   (a `task_member_skills` row for `category`, **or** generalist).
3. **Rank** by remaining weekly capacity (`build_team_workload`: `weekly_hours −
   committed est. hours`), then `is_primary` for the category, then fewest open tasks,
   then stable gid order.
4. **Pick the top** ⇒ the correct party.
5. **Overload fallback:** if every candidate is **over** capacity (remaining < the task's
   est. hours, or already negative), do **not** force it — leave unassigned, set the
   task's placement flag, and PACE surfaces it ("*Acme* — approved work couldn't be
   placed; the content team is at capacity this week → reassign or defer"). Config
   `pace_placement_overload = hold | least_over` (default `hold`).
6. **No skilled candidate** ⇒ widen to eligible-ignoring-skill with a note; still none ⇒
   unassigned + flag.

**Where placement runs:**
- **Approval hook** (§5) — `asana_push.push_proposal` calls `pick_assignee` after creating
  the (previously unassigned) task.
- **Producer tasks** — optionally auto-place `rank_drop` / `maps_alert` / `action_plan`
  tasks (`pace_autoplace_producers`, default **off** first).
- **Conversational** — a new `assign_task` action ("PACE, assign the GBP task") auto-picks,
  vs `reassign_task` where a human names the person. The auto-pick still shows the choice
  behind the actor-bound reply-*yes*.

**Safety framing.** Deterministic placement is **distribution, not an LLM decision** — the
same class as `distribute_tasks`, which already assigns without a per-task confirm. The LLM
never picks the person; it only *invokes* placement. Every placement writes `task_activity`
(actor = system or the requester) and is freely re-assignable. LLM-*initiated* one-off
writes stay confirm-gated (§9).

### 4.7 PACE delivery reports (`services/pace_report.py`) — v1.3
PACE's internal **PM status report** — distinct from the client-facing Client Reporting
module (that one is owner-friendly + external). Audience: leads/owners. Deterministic core
over `pm_signals` + `task_workload` + `task_service`, with an optional Haiku narrative:
- **Month completion** — done vs planned per client (the pace read, as a number).
- **Throughput** — tasks completed this period, by category and by person.
- **Overdue & stuck** — overdue count, the oldest, blocked-N-days.
- **Capacity utilization** — per member: committed vs `weekly_hours`, over/under.
- **Backlog health** — unassigned + unacted-on producer tasks.

Scope: per-client **or** portfolio. Delivery: in-app + Slack now; **PDF via the shared
`client_report.render_pdf`** later (reuse, not new infra). Cadence: on-demand
(`generate_pace_report`, PACE-scoped action) + optional weekly on the scheduler
(`pace_report_weekday`, default off). Pure builders unit-tested.

---

## 5. Boundaries & handoff with SerMaStr
- **PACE owns** (executes): task state, assignment, due dates, workload, month pace, stuck
  work, "what should I do today", generating the month.
- **SerMaStr owns** (proposes): campaign health, what work to *invent*, strategy/
  priorities/budgets/forecasts, SOP-grounded advice.
- **PACE → strategist:** a delivery problem that's really a *strategy* problem → PACE
  surfaces it and offers `run_strategy_review` (the one strategist action in PACE's
  scope, §4.1); it does not decide.
- **Strategist → PACE (v1.3 — the closest thing to the owner's loop):** an **approved**
  proposal becomes a task *and is auto-placed* by PACE's engine (§4.6) — the correct
  **skilled, eligible, least-loaded** party — or **held + flagged** if that pool is at
  capacity. PACE owns it as board work thereafter. This realizes "SerMaStr sends the
  request → PACE assigns it out, or holds if the team's overloaded" **with the human
  approval preserved in the middle** (SerMaStr still proposes-never-executes; the approval
  is the gate, placement is deterministic).
- **Router rule (pure, testable):** PACE-shape vs strategy-shape gates the persona (§4.1).

---

## 6. Data model & config

**Schema (small, additive):**
- `profiles.slack_user_id text unique` (nullable) — the Slack→profile map (§3.1).
- `notifications.dedupe_key text unique` (nullable) — **atomic** digest idempotency
  (§4.3). The digest inserts with `dedupe_key = "pace_digest:<YYYY-MM-DD>:portfolio"`; a
  duplicate insert (e.g. rolling-deploy overlap) hits the unique constraint and is a no-op.
  Chosen over the v1.1 query-guard, which has a TOCTOU race. Existing notifications keep a
  null key (unique ignores nulls).
- `task_member_skills(member_gid, category_key, weight, is_primary)` (v1.3) — the role/skill
  competency map (§4.6), editable on the Workload page. **No rows for a member ⇒ generalist**
  (eligible for any category), so day-one placement works before anyone fills it in.
- Optional (later) `pace_snooze` (client_id, task_id, kind, until) — deferred.

**Config (`config.py`) — build-ready (types/defaults/env):**
```
pace_enabled: bool = False                     # PACE_ENABLED — master gate
pace_model: str = "claude-haiku-4-5-20251001"  # PACE_MODEL
pace_max_tokens: int = 1200                    # PACE_MAX_TOKENS
pace_digest_weekday_only: bool = True          # workdays only (Mon–Fri)
pace_digest_max_items: int = 8                 # cap the daily digest
pace_daily_brief_push: bool = False            # per-VA morning push (v1 pull-only)
pace_month_pace_grace: float = 0.15
pace_month_pace_min_tasks: int = 4
pace_stale_thresholds: dict = {                # by status KEY; category fallback below
    "blocked": 3, "in_review": 5, "sent_to_client": 5, "in_progress": 10,
}
pace_stale_category_fallback: dict = {"blocked": 3, "in_progress": 10}
# --- v1.3 full-PM scope ---
pace_slack_channel: str = ""                   # PACE_SLACK_CHANNEL — dedicated PACE channel (empty ⇒ shared, routed by shape)
pace_autoplace_producers: bool = False         # auto-place rank_drop/maps_alert/action_plan tasks (§4.6)
pace_placement_overload: str = "hold"          # hold | least_over — when the skilled pool is at capacity (§4.6)
pace_report_weekday: int | None = None         # weekly PACE report DOW (None ⇒ on-demand only, §4.7)
pace_report_model: str = "claude-haiku-4-5-20251001"  # optional report narrative
```
The digest runs on the **existing scheduler tick at `gsc_ingest_hour_utc`** (no new hour
setting). **Timezone: UTC**, matching every other suite sweep; a team-timezone digest hour
is a later refinement. **Business days = Mon–Fri, no holiday calendar in v1.**

**Notifications:** `kind="pace_digest"`, existing pipe + the `dedupe_key`. Per-user
delivery (a VA's own nudges routed to *them*) still needs the per-user inbox the
notifications service lacks — a **shared follow-up with the strategist**; until then
`nudge_assignee` uses a real `<@slack_user_id>` mention or in-app-only (§4.2).

**No hardcoded status keys** anywhere — all logic via `status.category`/`is_initial`/
`is_done` + the override map.

---

## 7. Cost model
Deterministic layer: free. Daily digest: template-only in Phase 0B (zero LLM); one
Haiku-tier call/workday agency-wide once the persona phrases it (Phase 3), only when
actionable. Conversational: one cheap call/question. Keeping PACE off Sonnet is the win.

---

## 8. Phasing (identity/permissions before actions)

> **Phases 0–4 are BUILT + merged** (PR #335; live behind `pace_enabled`, enabled in
> production 2026-07-12). **Phase 5 (placement) is BUILT** (this PR — `task_member_skills` +
> `pm_assign` + approval hook + `assign_task` + Workload-page competency editor). **Phase 6
> (delivery reports) is BUILT** (this PR — `pace_report` + `generate_pace_report` action +
> `GET .../pace-report` + Workload Reports card + optional weekly digest). **Phase 7
> (dedicated channel) is BUILT** (this PR — `pace_slack_channel` + channel-scoped inbound
> routing + digest/report channel targeting). **All v1.3 phases are now built.**

**Phase 0A — deterministic reads.** `pm_signals.py` (reopen-aware staleness, overdue,
unassigned, missing-due-date, unacted-on producer tasks, dual-mode month-pace heuristic,
workload reuse). Unit-tested. No notifications. *Acceptance:* pure builders return the
right items incl. the reopen / first-3-days / dated-vs-undated edges; green tests.

**Phase 0B — durable informational digest.** One agency-level, client-grouped, capped-8,
template-only digest per workday via `notifications.emit` + the **unique `dedupe_key`**.
Deep links, no reply-*yes*. *Acceptance:* validated on production data; runs once/day even
across a mid-day/rolling deploy (constraint-guaranteed); silent when all-clear.

**Phase 1 — identity & permissions.** `profiles.slack_user_id` + linking; `ActionContext`
(web threaded through `handle_chat`; Slack after mapping); the role→action matrix;
**actor-bound confirmations**; actor audited on all writes incl. the monthly async path.
*Acceptance:* an unauthorized/unmapped request is refused before any confirm; a confirm
from a different actor than the requester is refused; a simulated month records its actor.

**Phase 2 — PACE action registry.** The persona-scoped allowlist actions, target-resolved
+ permission-checked + actor-bound confirm; configurable-status semantics; `unblock`
restores the pre-blocked status (from the into-blocked activity) or asks; `nudge` delivers
a real mention. *Acceptance:* "move X to Ivy" from an authorized lead reassigns after a
same-actor reply-*yes*; from a VA it's refused; strategist never exposes these actions.

**Phase 3 — PACE persona/router.** `pace_agent.py`: PACE prompt, Haiku model, PACE-only
context + `PERSONA_ACTIONS`, the pre-client-resolution router incl. PACE portfolio + the
personal-brief bypass, explicit `run_strategy_review` handoff, LLM-phrased digest ranking.
*Acceptance:* "what's stuck on Acme?" answers in a PACE voice; "what should I work on?"
bypasses client resolution; strategy-shaped asks route to SerMaStr.

**Phase 4 — personal brief.** Web `/tasks/mine`-backed brief first; Slack brief only after
Phase 1's mapping; push default-off. *Acceptance:* a linked person gets *their* list; an
unmapped Slack user is told to link.

---

### v1.3 full-PM phases (proposed)

**Phase 5 — role/skill placement engine.** `task_member_skills` migration + a Workload-page
competency editor; the pure `pm_assign.pick_assignee` (skilled ∩ eligible, least-loaded,
overload fallback); the **approval hook** (`push_proposal` auto-places its task); the
`assign_task` conversational action; optional producer auto-placement (flag-gated).
*Acceptance:* an approved proposal lands on the correct skilled/eligible/least-loaded
member; when that pool is over capacity the task is held + flagged (not force-assigned); a
generalist-only roster (no skill rows) still places; pure `pick_assignee` unit-tested incl.
the overload + no-skilled-candidate edges.

**Phase 6 — PACE delivery reports.** `services/pace_report.py` deterministic builders
(completion / throughput / overdue-&-stuck / capacity-utilization / backlog) + optional
Haiku narrative; the `generate_pace_report` PACE action + optional weekly scheduler hook.
*Acceptance:* a per-client report reflects live board data; portfolio rolls up; builders
unit-tested; delivery best-effort per channel.

**Phase 7 — dedicated PACE channel.** `pace_slack_channel` + channel-scoped routing: in the
PACE channel PACE answers **every** message (delivers on delivery asks, defers strategy to
SerMaStr) and **SerMaStr is excluded there**; in every other channel PACE stays out. The
daily digest + any report deliveries route to that channel when set. *Acceptance:* a message
in the PACE channel is answered by PACE regardless of shape; the same message in the SerMaStr
channel is untouched by PACE; empty `pace_slack_channel` ⇒ today's shared-channel shape
routing (backward-compatible).

---

## 9. Non-goals (v1)
Time tracking; Gantt/dependencies; **auto-executing LLM-*initiated* writes without
authorization or confirmation** — every *conversational* write is authorized, actor-bound,
and reply-*yes* gated; **deterministic system placement** (monthly `distribute_tasks` + the
v1.3 approval-hook placement, §4.6) assigns without a per-task confirm — the same class as
the already-shipping monthly distribution — and is fully audited + freely re-assignable, so
it is **not** an "agent auto-executing" hole. Also out: owning strategy/escalations; a
per-user notification inbox (shared follow-up with the strategist); Block Kit interactive
buttons (Option C, later); holiday-aware business days; cross-client capacity planning from
the workbook; **skill/role auto-detection** (competencies are human-curated on the Workload
page, §4.6).

---

## 10. Open decisions (defaults chosen; flag to change)
1. **Name — resolved: PACE.**
2. **One channel or two — resolved (v1.3): two.** PACE gets a **dedicated channel**
   (`pace_slack_channel`, Phase 7) — it owns that channel and defers strategy, and SerMaStr
   is excluded there (VA-facing PACE vs owner-facing SerMaStr). Shared-channel shape-routing
   remains the fallback when `pace_slack_channel` is empty.
3. **Digest frequency — resolved:** one agency-level deterministic digest per workday,
   grouped by client, capped at 8, no per-client/per-VA push.
4. **Model tier** — Haiku-tier; bump only if ranking quality disappoints.
5. **Slack linking UX** — admin Team-page field first; self-serve `/pace link` later.
6. **`unblock` default** — restore pre-blocked status when unambiguous, else ask.
7. **Snooze table** — wait for the first "stop nagging me" (v1.1+).

---

## 11. What already exists to build on
- **Task manager** (merged): `task_service` (`get_statuses` incl. `category`/`is_initial`/
  `is_done`, `bucket_by_due`, `close_task_by_source`, `task_activity.actor_id`,
  `create_task(created_by=…)`), `task_monthly`, `task_workload`
  (`build_team_workload`/`select_due_tasks`), `task_producers`, `task_collab`.
- **Identity bridge** (merged 2026-07-11): `asana_team_members.profile_id` +
  `/tasks/mine` `my_gid` — the *profile→member* half; §3.1 adds the *Slack→profile* half.
- **SerMaStr rails**: `services/slack_assistant/` (modular:
  `helpers/prompts/context/actions/llm`), `_CONTEXT_PROVIDERS`, `_ACTIONS`, `_pending`
  (gains a requester), `interpret()` (gains `persona`/`action_context`), streaming;
  `assistant_chat.handle_chat` (gains `action_context`); `notifications.emit`; the
  `gsc_scheduler` inline-sweep pattern.
- **Precedents**: `response_episodes` (deterministic clock + daily sync), the Asana-task
  actions (stage-then-confirm target resolution), `strategy_digest` (provider registry).

---

## 12. Review response — round 1 → resolution
| # | Review point | Resolution |
|---|---|---|
| 1 | No authorization model | §3 `ActionContext` + role→action matrix; permission-checked at stage; actor audited. |
| 2 | Slack identity doesn't exist | §3.1 `profiles.slack_user_id` + linking; web now, Slack brief gated on mapping. |
| 3 | Digest can't offer reply-yes | §4.3 Option A informational digest. |
| 4 | Persona = real refactor | §4.1 `persona` dimension + restricted allowlist + pre-prompt router. |
| 5 | Hardcoded status keys | §2b/§4.2/§6 via `category`/`is_initial`/`is_done` + override map. |
| 6 | Reopen breaks staleness | §2b clock resets on `created`/`status_changed`/`reopened`. |
| 7 | Digest not idempotent | §6 (superseded by round-2 #6 — now the unique `dedupe_key`). |
| 8 | "Untouched" ≠ unopened | §2b renamed **unacted-on producer task**. |
| 9 | Month pace heuristic | §2b labeled + suppressions. |
| 10 | Capacity ≠ correct assignee | §2b/§4.2 candidate list. |
| 11 | Digest frequency inconsistent | §10.3 resolved. |
| 12 | Config not build-ready | §6 exact types/defaults/env. |

## 13. Review response — round 2 → resolution
| # | Review point | Resolution |
|---|---|---|
| 1 | Tool separation must work both ways | §4.1 `PERSONA_ACTIONS` — strategist scope excludes PACE writes; PACE scope adds `run_strategy_review` as the sole handoff (fixes the §4.1↔§5 contradiction). |
| 2 | Confirmations must be actor-bound | §3.3 pending entry stores the requester; confirming actor must match (admin takeover excepted); web `pending_token` too. Verified `_pending` has no actor. |
| 3 | Web auth not threaded into chat | §3.1 `ActionContext` built at the router, threaded through `handle_chat`→`interpret`. Verified `handle_chat` has no auth param. |
| 4 | Router before client resolution | §4.1 explicit order; personal-brief bypasses client resolution. |
| 5 | Monthly gen can't audit actor | §3.2 `actor_id` threaded enqueue→job→generate→`create_task(created_by)`; scheduled = null actor. Verified `create_task` omits `created_by`. |
| 6 | Dedupe not race-safe | §6 nullable **unique `notifications.dedupe_key`** now (replaces the query-guard). |
| 7 | Unblock-history wording | §4.2 restore `detail.from` of the into-`blocked` activity, else ask. |
| 8 | Define due-weighted pace | §2b concrete formula + business-days = Mon–Fri, no holidays. |
| 9 | `nudge_assignee` needs delivery | §4.2 real `<@slack_user_id>` mention; in-app-only / refuse when unmapped. |
| — | Rename | **PACE — Project Assignment, Coordination & Execution**, applied throughout. |
