# Project Manager Agent — Module Plan v1.1

**Status:** Proposed · **Sibling to:** SerMaStr (`seo-strategist-agent-plan-v1_0.md`)
· **Rides:** the native task manager (`in-app-task-manager-prd-v1_0.md`) + the
SerMaStr assistant (`services/slack_assistant/`) · **Authored:** 2026-07-11 ·
**Revised:** 2026-07-11 (v1.1)

> **Working name:** "PMaStr". Naming is an open decision (§10) — what matters is a
> **distinct persona/voice** from SerMaStr, not a distinct system. Throughout: "the PM".
>
> **Revision note (v1.1 — after external review).** v1.0 got the *direction* right
> (separate operational persona, deterministic-first) but under-specified four things
> the review correctly flagged; this revision designs them explicitly, so **no PM
> *action* or *Slack personal brief* ships before its prerequisite exists**:
> 1. **Actor identity + authorization** (§3) — v1.0 let "confirm-gated" stand in for
>    "authorized". It isn't. Added an `ActionContext` + a role→action matrix; every PM
>    write threads and audits the actor.
> 2. **Digest ≠ reply-yes** (§4.3) — `notifications.emit` posts a standalone channel
>    message; it does not create an assistant thread or stage a `_pending` action, and
>    `_pending` holds exactly one action per `(channel, thread_ts)`. The daily digest is
>    now **informational** (Option A): it names problems + the exact command to run;
>    actions are invoked explicitly in the assistant.
> 3. **Persona is a real refactor** (§4.1) — `interpret()` today has one prompt, one
>    model, one action registry. The PM needs a `persona` dimension: its own prompt, a
>    **cheaper model**, a **restricted tool allowlist**, and a router that runs *before*
>    prompt/context selection (incl. a PM portfolio route).
> 4. **Durable scheduling + configurable-workflow semantics** (§2b/§6) — the digest
>    must dedupe durably (the scheduler's `last_run_date` is in-memory and resets on
>    deploy); staleness/unblock must key off status **category**, not hardcoded keys,
>    and treat `reopened`/`created` as clock resets.
>
> Verified against source: `reopen_task` emits `reopened` (not `status_changed`);
> action runners are `(name, client_id, args)` with no actor; the Slack handler never
> reads the event's `user`. §12 maps every review point → its resolution.

---

## 1. Purpose & position

The agency has **SerMaStr**, a Search Marketing *Strategist*: weekly, deliberative,
owner-facing, *proposes-never-executes*. It answers "is the campaign winning, and
what should we change?"

It does not answer the day-to-day delivery questions: *Is the approved work actually
getting done? Is anything stuck? Is anyone overloaded? What should this VA do today?*
Those are **project-management** questions — a different job with a different safety
envelope, cadence, audience, and cost.

The PM is the operational counterpart. It watches the **native task board** and keeps
delivery moving — surfacing stuck/overdue/unassigned work and pace/overload, and
(authorized + confirm-gated) doing the small PM moves: reassign, bump a due date,
unblock, generate the month.

### Why separate the PM from SerMaStr (decision record)

| | **SerMaStr (Strategist)** | **PM** |
|---|---|---|
| Core verb | **Proposes**, never executes | **Executes** (authorized + confirm-gated) |
| Cadence | Weekly + escalations | **Daily** + on-demand |
| Audience | Owners (Kyle/Ryan) | VAs + leads |
| Question | "Are we winning? What should change?" | "Is the approved work getting done?" |
| Context | Huge — every module, SOP corpus | Tiny — board state, workload, due dates |
| Model / cost | Sonnet + drill-downs + 25k digest | Haiku-tier + a small board digest |
| Tools | Full registry | **Restricted PM allowlist** (§4.1) |

Merging these erodes SerMaStr's *proposes-never-executes* guardrail, bloats the
strategist prompt with task-chasing noise, and crosses the two signals. **Two personas,
one set of rails.** (Rejected: a standalone PM service — violates "no new infra".)

### What is NOT an agent (the 80% that stays deterministic)

The task manager already covers most PM duties **without any model**: monthly generation
+ Recipe Engine (plan), capacity-aware `distribute_tasks` (assign), `task_producers`
(create-from-events, auto-close), `run_due_sweep` (chase), `run_workload_alert`
(overload). The genuinely-missing pieces are **more determinism, not intelligence** —
staleness, month-pace, unacted-on producer backlog (§2b). Those land first; the LLM only
prioritizes, phrases, and (authorized) acts on what the rules surface.

---

## 2. Architecture

Zero new infra (the locked rule). A new deterministic **signal layer** + a thin persona,
both on existing rails.

```
  ┌──────────────────── deterministic (no LLM, no paid calls) ───────────────────┐
  │ services/pm_signals.py — pure builders over task_* tables (unit-tested):      │
  │   staleness · month_pace (heuristic) · workload (reuse) · untriaged +         │
  │   unacted-on producer tasks · due (reuse task_workload.select_due_tasks)      │
  │   → the standard PM envelope                                                  │
  └───────────────────────────────────────────────────────────────────────────────┘
        │ feeds ▼                                              ▲ reads (free)
  ┌──────────────────── judgment (LLM, cheap, restricted) ─────┴──────────────────┐
  │ services/pm_agent.py — the PM persona:                                         │
  │   daily digest (INFORMATIONAL) · conversational PM (own prompt/model/tools)    │
  │   · personal brief (web first; Slack after identity mapping)                   │
  │  + PM actions in a RESTRICTED allowlist, actor-authorized + confirm-gated      │
  └───────────────────────────────────────────────────────────────────────────────┘
```

### Triggers
- **Daily digest** — once/workday, inline on `gsc_scheduler` (the `run_episode_sync`
  pattern), gated on `pm_agent_enabled`, **durably deduped** (§6). One agency-level
  digest, grouped by client, capped at `pm_digest_max_items` (§10 resolves the v1.0
  frequency inconsistency to exactly this).
- **On-demand conversational** — PM-routed messages (§4.1). No schedule.
- **Personal brief** — pull-only in v1 (`pm_daily_brief_push=False`); web first.

### Inputs
`pm_signals.build_board_digest(client_id | None)` returns the standard envelope; the PM
never reasons over raw tables (the strategist rule). Portfolio (no client) rolls to
counts + top offenders per client, like `build_portfolio_context()`.

---

## 2b. The deterministic signal layer (`services/pm_signals.py`)

Pure, unit-tested, no LLM/paid calls. Every signal is a rule over data the task manager
already writes. **Configurable-workflow-safe**: keyed off status **category** +
`is_initial`/`is_done`, never hardcoded status keys.

**Staleness.** *days-in-current-status* = today − the `created_at` of the task's most
recent **status-clock-reset** activity, where a reset is `created` | `status_changed` |
`reopened` (completed tasks are excluded entirely; `reopened` matters because
`reopen_task` emits `reopened`, not `status_changed` — a 6-month-old task reopened today
must read as *fresh*, not 6 months stale). Thresholds are a **JSON map keyed by
configured status key** with a **coarse-category fallback** (`pm_stale_thresholds`, §6):
default by category — `blocked` 3d, `in_progress` 10d; plus per-key overrides for the
review-ish states (`in_review`/`sent_to_client` 5d). A `not_started` task in the back
half of a month is flagged via month-pace, not a status timer. *(Recommendation, tracked
in §12: also have `task_service.reopen_task` emit a `status_changed` so every consumer
sees a uniform clock — but the signal layer must not depend on that.)*

**Month-pace (a heuristic, labeled as such).** Per client's current-month `task_sections`
row: `pct_complete` (done top-level / total) vs `pct_elapsed`. Because monthly tasks often
start with blank due dates and are scheduled later, this is a *pace hint*, not a verdict.
Suppressions: don't flag in the **first 3 business days** of the month; don't flag boards
under `pm_month_pace_min_tasks` (default 4); use **business days**; and **once ≥ half the
tasks have due dates**, compare completion against **due-date-weighted expected progress**
instead of raw calendar elapsed. Grace `pm_month_pace_grace` (0.15).

**Workload.** Reuse `task_workload.build_team_workload` verbatim. For reassignment the PM
produces a **candidate list**, not a pick: eligible members ranked by remaining capacity,
**filtered** to active members and (where known) service-type/client eligibility. Capacity
never auto-selects the replacement — the human chooses (§4.2).

**Untriaged + unacted-on producer tasks.** Open tasks with no assignee or no due date past
a grace window; and **unacted-on producer tasks** — `source in (rank_drop, maps_alert,
action_plan)` still in the initial status whose only `task_activity` is `created` (i.e.
nobody has assigned, changed, or commented on the auto-created alarm). *Named
"unacted-on", not "untouched/unopened": viewing a task writes no activity, so this signal
cannot and does not claim "nobody looked at it".* Highest-value catch — work the system
created that would otherwise rot.

**Due.** Reuse `task_workload.select_due_tasks` so the PM and the standalone due-sweep
never disagree.

All builders return the **standard PM envelope** so persona + UI read one shape.
Unit-tested like `test_response_episodes`/`test_task_manager`, including the reopen and
first-days-of-month edge cases.

---

## 3. Identity & authorization (the prerequisite for any PM action)

**Confirmation is not authorization.** The current assistant lets *any* channel member
invoke actions, and runners receive only `(client_id, args)` — no actor. A VA must not be
able to say "move all of Ivy's tasks to Minda" or "push this deadline two weeks" just
because they can type it and reply *yes*. So identity + permissions ship **before** PM
actions (§8), not after.

### 3.1 Actor context
Every PM read/action carries an `ActionContext`, resolved once per turn:
```
ActionContext = { profile_id, role, slack_user_id?, channel?, source }   # source: 'web' | 'slack'
```
- **Web (`/assistant`)** — already JWT-authenticated: `profile_id` + `role` come from the
  session (`require_auth`). Works today; the personal brief and role checks are available
  immediately on web.
- **Slack** — the handler currently ignores the event's `user`. **New: a Slack→profile
  mapping** is required (v1.0 wrongly implied the merged `asana_team_members.profile_id`
  bridge already covered this; it links a *profile* to a roster member, not a *Slack user*
  to a profile). Add `profiles.slack_user_id` (unique, nullable) + an admin linking step
  (self-serve "/pmastr link" or a Team-page field), and thread `event.user` →
  `profiles.slack_user_id` → `ActionContext`. An **unmapped** Slack user is treated as an
  anonymous reader: reads allowed per channel policy, **all writes refused** with "link
  your Slack account first".

### 3.2 Role → action matrix (enforced in code, not just prompt)
Roles are the suite's existing `client < team_member < staff < admin` (`ROLE_RANK`).

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

Enforcement lives in the action layer: `stage(action_context, client_id, args)` /
`run(action_context, client_id, args)` — a permission check gates staging (so an
unauthorized ask is refused *before* the confirm, with a clear reason), and every write
records the actor on `task_activity.actor_id` (already a column) for audit. This is an
additive signature change to the `_ACTIONS` contract; existing SerMaStr actions get a
permissive default context so they're unchanged until opted in.

---

## 4. The PM persona (`services/pm_agent.py`)

### 4.1 A real persona split on `interpret()`
`interpret()` today = one system prompt, one model/token budget, one action registry,
shared SOP/GSC/memory/admin tools. The PM needs a **persona dimension**:
```
interpret(question, client, context, history, *, persona='pm',
          model=pm_agent_model, max_tokens=pm_agent_max_tokens,
          system_prompt=PM_SYSTEM, tools=PM_TOOL_ALLOWLIST, action_context=…)
```
- **Router runs first** — before prompt/context/tool selection. A message is PM-shaped
  (task state/assignment/due/workload/"today"/"stuck"/"overdue") vs strategy-shaped
  (performance/why/priorities/budgets). Ambiguous → the existing clarifying-question
  behavior. Portfolio PM ("who's overloaded today?") routes to a **PM portfolio** prompt,
  not the strategist Director prompt.
- **Restricted tool allowlist** — the PM sees only PM tools (board reads + the §4.2
  actions). It must **not** see backlink reports, client-profile edits, keyword removal,
  AI-visibility competitor edits, report generation, etc. (`PM_TOOL_ALLOWLIST`).
- **Cheaper model** — `pm_agent_model` (Haiku-tier); strategist stays Sonnet.

This is the honest cost of "a second persona" (v1.0 undersold it). It is tractable because
`services/slack_assistant/` is already split into `helpers/prompts/context/actions/llm`
modules — the split is a `persona` parameter + a PM prompt + an allowlist + a pre-prompt
router, not a rewrite.

### 4.2 PM actions (restricted allowlist, actor-authorized, confirm-gated)
New `_ACTIONS` entries, each: permission-checked at stage (§3.2), target-resolved before
the confirm (the Asana-action pattern — `match_open_tasks`/`match_named`, exact-beats-
substring, 0→list, >1→ask), then reply-*yes*:

| action | does | min role |
|---|---|---|
| `reassign_task` | move a task to another member (from a capacity+eligibility candidate list) | staff |
| `set_task_due` / `bump_task_due` | set/shift a due date | staff (own: team_member) |
| `nudge_assignee` | remind an assignee | staff (self: team_member) |
| `generate_client_month` | run `task_monthly` now | admin (policy: staff) |
| `unblock_task` | move a `blocked` task **back to its previous status** (from activity) or **ask which** — never hardcode `in_progress` | staff |

`unblock_task` restores the last pre-`blocked` status from `task_activity` (the previous
`status_changed.to`), falling back to *asking* which status — because a blocked task may
belong in Not Started / In Review / With Client, not In Progress.

### 4.3 Daily digest — INFORMATIONAL (Option A)
`notifications.emit` posts a standalone channel message; it does not open an assistant
thread or stage `_pending` (which holds one action per `(channel, thread_ts)`). So the
digest **states problems + the exact command to run**, and actions are invoked explicitly
in the assistant:
> *PM daily · 3 items need a human*
> • *IHBS* — "GBP categories" blocked 9 days (Minda). → `@PMaStr unblock GBP categories on IHBS`
> • *Acme* — behind pace (July 70% elapsed, board 30% done, heuristic).
> • *First Class Roofing* — rank-drop task unacted-on 4 days (unassigned). → `@PMaStr assign it`
> Deep links: `/clients/:id/tasks`.

No reply-*yes* from the digest itself. (Options B "one thread per action" and C "Block Kit
buttons with signed action IDs" are noted for a later version; C is the best UX but needs
interactive-endpoint infra the suite doesn't have yet.)

### 4.4 Personal brief
"What should I work on today?" from **that person's** My Tasks. **Web first** (JWT gives
`profile_id` now) → `profile_id` → linked `asana_team_members` (identity bridge) → `my_gid`
→ `bucket_by_due` → prioritized list. **Slack only after §3.1's Slack→profile mapping
exists.** No mapping → "link your Slack account first".

### 4.5 Shared read for the strategist
Add `_ctx_delivery(supabase, client_id, today)` to `_CONTEXT_PROVIDERS` — the per-client
board digest (pace, stuck/overdue/unassigned counts) — so SerMaStr *sees* delivery health
when answering "how's the campaign going". Read-only; the one safe shared seam.

---

## 5. Boundaries & handoff with SerMaStr
- **PM owns** (executes): task state, assignment, due dates, workload, month pace, stuck
  work, "what should I do today", generating the month.
- **SerMaStr owns** (proposes): campaign health, what work to *invent*, strategy/
  priorities/budgets/forecasts, SOP-grounded advice.
- **PM → strategist:** a delivery problem that's really a *strategy* problem (behind pace
  *because the plan is wrong*; a stuck task needing a senior call) → the PM surfaces it and
  offers the existing `run_strategy_review` action; it does not decide. §3 halt rules
  unchanged.
- **Strategist → PM:** an **approved** proposal already becomes a task
  (`asana_push.push_proposal`); the PM owns it as board work from then on. Clean seam.
- **Router rule (pure, testable):** PM-shape vs strategy-shape gates the persona (§4.1).

---

## 6. Data model & config

**Schema:**
- `profiles.slack_user_id text unique` (nullable) — the Slack→profile map (§3.1).
  Migration; no new table.
- **Digest dedupe** — before emitting, guard on an existing `pm_digest` for today:
  either query (`kind='pm_digest'` AND `created_at >= start_of_today_utc` AND
  `payload->>'digest_key' = 'pm_digest:<YYYY-MM-DD>:portfolio'`) → skip if present, or add
  a nullable unique `notifications.dedupe_key` and rely on the constraint. v1 = the
  **query-guard** (no migration); the `dedupe_key` column is the hardening option if dupes
  still appear. This fixes the in-memory `last_run_date` reset-on-deploy hole.
- Optional (v1.1+) `pm_snooze` (client_id, task_id, kind, until) so a lead can mute a
  known-parked flag — deferred until asked for.

**Config (`config.py`) — build-ready (types/defaults/env):**
```
pm_agent_enabled: bool = False                 # PM_AGENT_ENABLED — master gate
pm_agent_model: str = "claude-haiku-4-5-20251001"   # PM_AGENT_MODEL
pm_agent_max_tokens: int = 1200                # PM_AGENT_MAX_TOKENS
pm_digest_weekday_only: bool = True            # workdays only
pm_digest_max_items: int = 8                   # cap the daily digest
pm_daily_brief_push: bool = False              # per-VA morning push (v1 pull-only)
pm_month_pace_grace: float = 0.15
pm_month_pace_min_tasks: int = 4
pm_stale_thresholds: dict = {                  # by status KEY; category fallback below
    "blocked": 3, "in_review": 5, "sent_to_client": 5, "in_progress": 10,
}
pm_stale_category_fallback: dict = {"blocked": 3, "in_progress": 10}
```
The digest runs on the **existing scheduler tick at `gsc_ingest_hour_utc`** — no new hour
setting (v1.0's `pm_daily_sweep_hour_utc = <ingest hour>` placeholder is resolved to
"reuse `gsc_ingest_hour_utc`"). Timezone: UTC, matching every other suite sweep; a
team-timezone digest hour is a later refinement, not v1.

**Notifications:** `kind="pm_digest"`, existing pipe. Per-user routing (a VA's own nudges
to *them*) needs the per-user inbox the notifications service still lacks (agency-level
today) — a **shared follow-up with the strategist**; v1 tags the shared channel with the
assignee's name.

**No hardcoded status keys** anywhere — all status logic via `status.category` /
`is_initial` / `is_done` + the override map above.

---

## 7. Cost model
Deterministic layer: free (DB reads on the shared scheduler). Daily digest: one Haiku-tier
call/workday agency-wide (Phase 2+; Phase 0B digest is template-only, zero LLM), only when
actionable. Conversational: one cheap call/question. Keeping PM work off Sonnet is the cost
win.

---

## 8. Phasing (identity/permissions before actions)

**Phase 0A — deterministic reads.** `pm_signals.py`: status-age (with reopen/created
resets), overdue, unassigned, missing-due-date, unacted-on producer tasks, month-pace
heuristic (+ suppressions), workload reuse. Unit-tested. No notifications yet.
*Acceptance:* on real board data the pure builders return the right items incl. the reopen
and first-3-days edges; green tests.

**Phase 0B — durable informational digest.** One agency-level, client-grouped,
capped-at-8, template-only (no LLM) digest per workday via `notifications.emit`, **durably
deduped**. Deep links, no reply-*yes*. *Acceptance:* validated on production data; runs
once/day even across a mid-day deploy (no dupes); posts nothing when all-clear.

**Phase 1 — identity & permissions.** `profiles.slack_user_id` + linking; `ActionContext`
(web now, Slack after mapping); the role→action matrix; actor audited on writes.
*Acceptance:* an unauthorized/unmapped request is refused *before* any confirm, with a
clear reason; every simulated write records the actor.

**Phase 2 — PM action registry.** The restricted allowlist actions, target-resolved +
permission-checked + confirm-gated; configurable-status semantics; `unblock` restores
previous status or asks. *Acceptance:* "move X to Ivy" from an authorized lead reassigns X
after a reply-*yes* naming X + Ivy; the same from a VA is refused.

**Phase 3 — PM persona/router.** `pm_agent.py`: PM system prompt, Haiku model, PM-only
context + tool allowlist, the pre-prompt router incl. PM portfolio, explicit
`run_strategy_review` handoff, and the LLM-phrased digest ranking. *Acceptance:* "what's
stuck on Acme?" answers from the digest in a PM voice; strategy-shaped asks still route to
SerMaStr.

**Phase 4 — personal brief.** Web `/tasks/mine`-backed brief first; Slack brief only after
Phase 1's Slack mapping; push stays default-off. *Acceptance:* a linked person gets *their*
real prioritized list; an unmapped Slack user is told to link.

---

## 9. Non-goals (v1)
Time tracking; Gantt/dependencies; **auto-executing without confirmation or without
authorization** (every write is authorized *and* reply-*yes* gated); owning strategy/
escalations (hand off to SerMaStr); a second notification channel or per-user inbox
(shared follow-up; v1 tags the channel); Block Kit interactive buttons (Option C, later);
cross-client capacity planning from the workbook.

---

## 10. Open decisions (defaults chosen; flag to change)
1. **Name** — "PMaStr" vs plain "PM" vs SerMaStr "PM mode". Rec: distinct name/voice.
2. **One channel or two** — v1 shares the SerMaStr channel + `/assistant`, routed by shape;
   split to a dedicated PM channel if the voices blur.
3. **Digest frequency (resolved)** — v1.0 was internally inconsistent; **v1 = one
   agency-level deterministic digest per workday, grouped by client, capped at 8, no
   per-client/per-VA push.**
4. **Model tier** — Haiku-tier; bump only if ranking quality disappoints.
5. **Slack linking UX** — a self-serve `/pmastr link <email>` vs an admin Team-page field.
   Rec: admin field first (fewer moving parts), self-serve later.
6. **`unblock` default** — restore previous status vs always ask. Rec: restore when the
   activity history is unambiguous, else ask.
7. **Snooze table** — ship now or on first "stop nagging me"? Default: wait (v1.1+).

---

## 11. What already exists to build on
- **Task manager** (merged): `task_service` (`get_statuses` incl. `category`/`is_initial`/
  `is_done`, `bucket_by_due`, `close_task_by_source`, `task_activity.actor_id`),
  `task_monthly`, `task_workload` (`build_team_workload`/`select_due_tasks`),
  `task_producers`, `task_collab`.
- **Identity bridge** (merged 2026-07-11): `asana_team_members.profile_id` +
  `/tasks/mine` `my_gid` — the *profile→member* half; §3.1 adds the *Slack→profile* half.
- **SerMaStr rails**: `services/slack_assistant/` (already modular:
  `helpers/prompts/context/actions/llm`), `_CONTEXT_PROVIDERS`, `_ACTIONS`, `_pending`,
  `interpret()`, streaming; `notifications.emit`; the `gsc_scheduler` inline-sweep pattern.
- **Precedents**: `response_episodes` (deterministic clock + daily sync), the Asana-task
  actions (stage-then-confirm target resolution), `strategy_digest` (provider registry +
  "cite the digest, never compute").

---

## 12. Review response — each point → resolution
| # | Review point | Resolution |
|---|---|---|
| 1 | No authorization model | §3 `ActionContext` + role→action matrix; permission-checked at stage; actor audited on `task_activity`. Identity/permissions now precede actions in phasing (§8). |
| 2 | Slack identity bridge doesn't exist | §3.1 `profiles.slack_user_id` + linking; web works now, Slack brief gated on the mapping; corrected the v1.0 over-claim. |
| 3 | Digest can't offer reply-yes | §4.3 Option A — informational digest + explicit commands; `_pending` one-per-thread limitation acknowledged. |
| 4 | Persona = real refactor | §4.1 `persona` dimension on `interpret()` (own prompt/model/tools), pre-prompt router incl. PM portfolio, **restricted tool allowlist**. |
| 5 | Hardcoded status keys | §2b/§4.2/§6 — logic via `status.category`/`is_initial`/`is_done` + a per-key override map; `unblock` restores previous status or asks. |
| 6 | Reopen breaks staleness | §2b — clock resets on `created`/`status_changed`/`reopened`, completed excluded; recommend `reopen_task` also emit `status_changed` (signal doesn't depend on it). |
| 7 | Digest not durably idempotent | §6 — query-guard on `kind=pm_digest`+today+`digest_key` (no migration); optional `dedupe_key` column as hardening. |
| 8 | "Untouched" ≠ unopened | §2b renamed **unacted-on producer task**; defined as no assign/change/comment (viewing writes no activity). |
| 9 | Month pace is a heuristic | §2b labeled a heuristic; suppress first 3 business days, min-task floor, business days, due-date-weighted once dates exist. |
| 10 | Capacity ≠ correct assignee | §2b/§4.2 — capacity yields a **candidate list** (active + eligibility filtered); the human picks. |
| 11 | Digest frequency inconsistent | §10.3 resolved — one agency-level, client-grouped, capped-8, no push. |
| 12 | Config not build-ready | §6 — exact types/defaults/env names; reuse `gsc_ingest_hour_utc`; UTC. |
