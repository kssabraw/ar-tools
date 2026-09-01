# Plan → PACE handoff — spec v1.0

**Status:** built (2026-09-01). **Authority:** this doc + `services/plan_handoff.py`.

## Problem

A coworker asked SerMaStr (suite web chat) to "take the plan it created for a
client and give those tasks to PACE to assign out." SerMaStr couldn't — and was
right not to fake it: there was **no seam** to do it.

Root cause (as-was):

- SerMaStr and PACE have hard two-way tool isolation (`_ACTIONS` vs
  `PACE_ACTIONS`); neither can invoke the other. SerMaStr's prompt tells it to
  point pure-delivery/assignment asks at the PACE chat.
- The "plan it created" is a **strategy review** (proposals) or **Action Plan
  steps** (`reopt_plans` / `assistant_plan_actions`) — a **recommend-only** surface
  with no bridge into the `tasks` board.
- Tasks reached the board only via SerMaStr's `push_task_plan` (the *Recipe Engine*
  monthly plan — a different plan) or PACE's own `generate_client_month`
  (template-driven). Neither ingests a SerMaStr-authored plan.
- The Action Plan → tasks path DID exist as an **automatic producer**
  (`task_producers.sync_action_plan_tasks`, capped at 10, only auto-placing when
  `pace_autoplace_producers` is on) — but there was **no on-demand trigger**.

## Design

One shared engine, exposed from **both** personas (owner decision 2026-09-01):

```
services/plan_handoff.py        # the engine + async job
services/strategist_proposals.py # extracted proposal-decision core + bulk approve
```

**Source = both** (owner decision): a handoff acts on the Action Plan AND the open
strategist proposals.

- **Action Plan half** (`handoff_action_plan`): read the latest `reopt_plans`
  items, skip the drop-driven kinds the alert producers own
  (`ACTION_PLAN_SKIP_KINDS`), cap at `plan_handoff_max_actions` (25), create a
  native task per action **reusing the producer's `(source='action_plan',
  action_source_ref)`** so it composes with `sync_action_plan_tasks` (no
  duplicates — an already-produced task is reused and simply placed), then
  `pm_assign.place_task` each (skilled + eligible + least-loaded, or held at
  capacity). The task name/description come from shared helpers
  (`task_producers.action_task_name` / `action_task_description`) so a handoff task
  is byte-identical to the auto-producer's.
- **Proposals half** (`strategist_proposals.handoff_open_proposals`): approve every
  still-open proposal of the client's latest review through `apply_decision` — the
  **same** core the per-proposal Approve button uses (push + auto-place the task,
  register the intervention, record the action-log decision, post the
  SerMaStr→PACE coordination-bus handoff). A `requires='senior'` proposal a
  non-admin can't approve is **skipped** (reported), never failing the batch.

`apply_decision` was **extracted** from `routers/strategist.py::set_proposal_status`
(which now delegates to it) so "approve a proposal" is defined once — no drift on a
side-effect-heavy path.

**Trigger side = both, shared engine** (owner decision):

- SerMaStr action **`assign_plan_to_pace`** (`scope`: action_plan | proposals |
  both) — confirm-gated (`paid`), staged so the confirm names the counts. This is
  the one time assignment is SerMaStr's to trigger; its prompt now calls it
  instead of punting to the PACE chat. Not actor-bound (SerMaStr's action layer
  isn't), so senior proposals are left for an admin.
- PACE action **`assign_client_plan`** — PM-gated (`require_pace_pm`, like monthly
  generation), actor-bound; threads the confirmer's role so an admin's handoff can
  also clear senior proposals.

Both enqueue the shared **`plan_handoff` async job** (mirrors `asana_push` — "push a
plan to the board"), so the chat confirm returns immediately and tasks land
shortly. Native-board only (placement is native-board); pre-cutover it returns a
clear "not enabled" result rather than writing to Asana.

## Guardrails preserved

- No precedence engine touched (`reopt_planner` tiers, `autonomy_policy`,
  `pm_assign` holds). Placement is the existing deterministic `place_task`.
- Idempotent: reuses `(source, source_ref)` for Action Plan items and the
  per-proposal approve path for proposals — re-running is safe.
- Best-effort per item — one failure never aborts the batch.
- Freeze: `plan_handoff` is PM board work (not content output), so — like
  `asana_push`/`task_month_generate` — it is **not** freeze-gated.

## Config

- `plan_handoff_max_actions` (25) — cap on Action Plan items per handoff.
- Reuses `native_tasks_enabled` (gate), `pace_enabled` (PACE surface), the PACE
  role model, and the existing placement engine.

## Migration

- `20260901180000_plan_handoff_job.sql` — adds the `plan_handoff` async_jobs type
  (CHECK rebuilt from the live constraint + the new type). Applied live.

## Tests

- `tests/test_plan_handoff.py` — eligibility/summary/confirm, the Action Plan
  create+place half (created/existing/placed/held tallies, source_ref parity,
  batch resilience), scope routing + native gate, enqueue dedupe.
- `tests/test_strategist_proposals.py` — `apply_decision` (invalid/senior/approve/
  not-found) and `handoff_open_proposals` (senior skip + tallies).
