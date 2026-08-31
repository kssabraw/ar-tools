# PACE Proactive Interventions — plan v1.0

**Status:** proposed (build in progress on `claude/pace-duplicate-detection-awujxk`).
**Owner rulings captured (2026-08-29):** curated detector set · Slack replies **and** a web
approvals panel · "approve with conditions" = **free-text constraint PACE re-plans against** ·
cadence = **daily batch + immediate for severe**.

## 1. What this adds

PACE already *reacts* per-task: the daily **Chase Plan** (`pace_proposals.py`) proposes
individual nudges/reassignments as reply-*yes* items, and **episodes** (`pace_episodes.py`)
chase and escalate stuck work. What it does **not** do is step back, notice a *systemic*
delivery problem, and put a **considered decision** in front of the PM.

Two real incidents motivated this:

- a teammate sitting at **293% of weekly capacity** (a rebalance the Chase Plan only ever
  offers as scattered one-off moves), and
- a Chase Plan with **450+ items silently held back** because ambiguous **duplicate task
  names** made the automation unable to resolve which task an action targeted — a data
  problem nothing detects or fixes.

This module is the **managerial layer**: PACE proactively scans for a curated set of
systemic problems, and for each opens a durable **intervention proposal** — a *problem* + a
concrete *fix plan* — that the PM dispositions four ways:

| Disposition | Effect |
|---|---|
| **Approve** | PACE executes the fix plan (bulk), records the result. |
| **Deny** | PACE does nothing; the problem is suppressed for a cooldown window. |
| **Defer** | Snoozed to a chosen date; re-surfaces then. |
| **Approve with conditions** | Free-text constraint ("only reassign to Ivy", "cap at 3 moves", "skip client X"); PACE re-plans the fix to honor it, then executes. |

**Division of labor (deliberate, to avoid two systems fighting over the same tasks):**
the **Chase Plan** owns the routine per-task cadence; **Interventions** fire only at an
**aggregate / severe threshold** (a cluster or a systemic data problem worth one considered
decision). Execution re-stages every action through the existing `PACE_ACTIONS` stage/run
contract, so a target that moved since detection is re-validated (never blindly written).

## 2. Curated detector set (v1)

Each detector produces a proposal `{kind, scope_client_id, signature, severity, title,
problem, evidence, actions[]}`; every `action` is a `PACE_ACTIONS` entry so it executes
through the tested stage→run path.

| kind | fires when | fix plan (actions) | signature |
|---|---|---|---|
| `member_overload` | a member's open-hours ≥ `overload_pct` of cap (default 150%; **critical** ≥ 200%) | `reassign_task` moves from `pm_assign.build_rebalance` (not-yet-started work only) | `member_overload:<member_id>` |
| `duplicate_names` | a client has ≥2 open top-level tasks sharing a normalized name (**critical** when the client's colliding total ≥ 10) | `rename_task` **disambiguation** of all but the primary in each colliding group (append assignee / month / counter). **Merge is never auto-executed** — flagged, and requestable via conditions. | `duplicate_names:<client_id>` |
| `untriaged_backlog` | a client has ≥ `untriaged_min` (8) unassigned open tasks | `assign_task` auto-placement (capacity-aware) per unassigned task | `untriaged_backlog:<client_id>` |
| `overdue_cluster` | a client has ≥ `overdue_min` (5) overdue open tasks | `nudge_assignee` per assigned overdue task; unassigned overdue flagged | `overdue_cluster:<client_id>` |
| `slip_forecast` | a client has ≥ `slip_min` (3) tasks forecast to slip (`pace_slips.forecast_slips`) | the cheaper-first fix per slip (reassign → due-move → flag) | `slip_forecast:<client_id>` |

`member_overload` + `duplicate_names` are the two flagship detectors (the incident cases);
the other three reuse existing pure logic (`pm_signals`, `pace_slips`) and only add the
aggregate threshold + bundling. Every action list is capped at `max_actions` (25) with an
"+N more" overflow that re-proposes next scan.

## 3. Lifecycle & idempotency (`pace_interventions` table)

One **open** intervention per `signature`. Statuses:
`proposed → {approved→executing→executed|failed | denied | deferred | resolved | superseded}`.

- **Open/suppressing set** = `{proposed, deferred, executing}` (one per signature).
- **Resolve:** an open row whose signature is absent from a fresh scan → `resolved` (problem
  cleared). Recurrence later opens a fresh `proposed`.
- **Deny cooldown:** a `denied` signature is not re-proposed for `deny_cooldown_days` (14);
  after that, if still a problem, it re-raises (a deny is time-bounded, not forever-silent).
- **Re-execute cooldown:** after execution, the signature waits `reexecute_cooldown_days` (3)
  before re-proposing (lets the fix take effect / metrics recompute).
- **Plan drift:** if a still-open problem's fix plan changes materially (fingerprint of the
  action list), the old row is `superseded` and a fresh `proposed` opens.
- **Deferred snooze:** a `deferred` row with `deferred_until > today` is skipped; once the
  date arrives the scan flips it back to `proposed` and re-surfaces it.

Pure decision helpers (`decide_scan_action`, cooldown checks, `plan_fingerprint`) are
unit-tested; the DB reads/writes are thin and batched (mirrors `response_episodes`).

## 4. Surfaces

- **Web approvals panel** (primary, richest): a card list on the `/pace` page — each
  intervention shows the problem, the concrete action list, severity, and
  **Approve / Deny / Defer (date) / Approve-with-conditions (textarea)** controls, plus the
  execution result once run. Backed by `GET /pace/interventions`, `GET /pace/interventions/{id}`,
  `POST /pace/interventions/{id}/disposition`.
- **Slack (#pace):** the daily scan posts a digest of newly-proposed + critical interventions
  (indexed) under the PACE bot. The PM replies naturally — `approve 2`, `deny 2`,
  `defer 2 to 2026-09-05` / `defer 2 in 3 days`, `approve 2 but only reassign to Ivy` — parsed
  by a pure `parse_intervention_reply` (ISO or simple-relative dates; free text after
  but/if/only → conditions). `approve` (and approve-with-conditions) first **previews the exact
  plan** and requires a `yes` to run; `deny`/`defer` execute immediately. Each intervention has
  a **durable short-code** (its uuid prefix, e.g. `a1b2c3`) shown in the digest and the web
  card — `approve a1b2c3` always targets that exact intervention even across scans, index
  shifts, or a deploy (it resolves by a DB read over the open set, not the in-memory index). A
  positional index still works for the latest digest. Anything it can't parse points the PM at
  the web panel.
- **Per-client note:** each client-scoped intervention (and its execution result) also lands on
  that client's workspace Alerts feed, and — when the client has its own Slack channel
  (`clients.slack_channel_id`) — posts there; otherwise it's in-app only (the master `#pace`
  rollup already carries the Slack copy). `member_overload` is cross-client and gets no
  per-client note. The dedupe key carries the date, so a resurfaced intervention re-notes.

## 5. Cadence

- **Daily full scan** on the shared scheduler (in the existing PACE initiative block),
  gated `pace_enabled ∧ pace_initiative_enabled ∧ pace_interventions_enabled`.
- **Weekly report (Fridays):** a rollup to the PACE channel + in-app on
  `pace_intervention_report_weekday` (default Friday) at the scheduler hour — open
  interventions awaiting a decision (with their short-codes) + this week's decisions and
  outcomes (approved/executed, denied, deferred, auto-resolved). Suppressed on a totally-quiet
  week; once-per-ISO-week via the notification dedupe key. Gated on
  `pace_intervention_report_enabled` (default on) + the feature being enabled.
- **Immediate for severe:** a **severe-only** pass (`member_overload` + `duplicate_names`,
  critical only) runs on the scheduler tick, throttled to at most once per
  `pace_intervention_severe_min_interval_minutes` (default 15) so it doesn't re-scan the whole
  board every 5-minute tick; the one-open-per-signature invariant + the notification
  `dedupe_key` make it idempotent, so a 293% spike or a large new duplicate cluster surfaces
  quickly instead of waiting for the daily batch. Set the interval to 0 for per-tick immediacy.

## 6. Safety / execution model

- **Ships dark:** new `pace_interventions_enabled` (default **False**), on top of the existing
  two PACE flags. Nothing scans, posts, or executes until all three are on.
- **Disposition is staff-gated** (`pace_intervention_decider_min_role`, default `admin`) and
  bound to the acting user; execution **additionally** re-authorizes each action through the
  `PACE_ACTIONS` matrix (defense in depth), skipping any the actor can't run.
- **Execution re-stages** every action (re-resolves the target, re-checks permission) before
  running — a task renamed/reassigned/closed since detection is handled, never clobbered.
- **Reversible fixes only:** `duplicate_names` renames (append a suffix — reversible) and
  never merges/deletes; overload/slip only move **not-yet-started** work; `assign`/`nudge`/
  `triage` are all existing reversible PACE actions.
- **Approve-with-conditions** interprets the free text into a *structured directive*
  (`{only_assignee, drop_indexes, max_actions, exclude_clients, assignee_overrides}`) via one
  best-effort `pace_model` call, applies it **deterministically** (pure `apply_conditions`),
  then re-stages + executes the survivors. A parse failure asks the PM to approve as-is or use
  the web panel — it never free-form-executes an unparsed instruction.

## 7. New pieces

- `services/pace_interventions.py` — detector registry, lifecycle, dispositions, scan runner.
- `pace_actions.py` — a new reversible `rename_task` action (+ `pace_auth` matrix entry).
- Migration `20260829150000_pace_interventions.sql` — the table + a partial-unique open index.
- `routers/pace.py` — the three intervention endpoints.
- `services/pace_agent.py` — the Slack disposition parse/route hook.
- `config.py` — the `pace_intervention_*` block.
- `notifications.py` — `pace_intervention` / `pace_intervention_result` kinds → PACE channel.
- `gsc_scheduler.py` — daily full scan + per-tick severe pass.
- Frontend — `components/pace/InterventionsPanel.tsx` on the `/pace` page + types/api.
- Tests — `tests/test_pace_interventions.py` (pure lifecycle, detectors, conditions, parsing).

## 8. Deliberately out of v1

Auto-merge of exact-duplicate tasks (destructive — condition-gated or manual only); Slack
interactive buttons (text replies + web panel cover it); per-detector custom re-planning
beyond the structured-directive conditions; learning thresholds from outcomes.
