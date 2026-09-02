# SerMaStr Autonomous Recovery Plans — PRD v1.0

**Status:** BUILT (owner-approved 2026-09-02). **PR 1** (the emit-truncation fix) merged as [#956](https://github.com/kssabraw/ar-tools/pull/956); **PR 2** (chronic-goal recovery runs) built the same day — see §12 for the as-built notes. Migration `20260902130000_strategy_reviews_goal_recovery.sql` applied live.
**Owner rulings captured (2026-09-02, grilling session):** separate truncation PR first · a dedicated `goal_recovery` run **plus** a strengthened weekly prompt · proposals may reallocate the current monthly plan at proposal level, and over-budget work is offered as cumulative **+25% / +50% / +100%** tiers over deployable · **propose-only, no auto hand-off to PACE** (owner, 2026-09-02, from the implementation brief) · one run per client on the re-escalation cadence, capped at **5 runs per daily tick** · the finished run sends the one `goal_chronic` message · `goal_recovery_enabled` defaults **on**.
**Repo:** `kssabraw/ar-tools` · backend `writer/platform-api/`. Builds on PR #949 (chronic-goal escalation + maps brief + notification-wipe fix, merged 2026-09-01).

---

## 1. The problem

The owner had to open a SerMaStr chat and ask a chain of questions to get a recovery plan for First Class Roofing's Maps collapse (Aug 7: pack presence 90.7% → 12.4% on "roof restoration melbourne"; Metropolitan Roof Repairs +68 pins; Melbourne Roof Restorers and Roof Makeover Specialist building suburb pages). SerMaStr produced an excellent costed 45-day plan **reactively**. The autonomous weekly strategist had called the local-pack goal "a critical emergency" every week for two months and **prescribed nothing**: every scheduled review from 2026-07-14 to 2026-09-01 carried **0 proposals and 0 questions**.

The owner's requirement, verbatim: *"I need SerMaStr to reason autonomously and provide suggested solutions."* The human's job is to review and approve a solution, not to extract a diagnosis and hand-build the plan.

## 2. Root cause — measured, not hypothesised

The implementation brief hypothesised the strategist was taking the prompt's "an empty review is a valid review" exit, or treating its own stale proposals as "nothing new". **Neither is the mechanism.** The reviews were **truncated**.

- `config.strategist_max_tokens` is **4096**.
- The `emit_strategy_review` tool schema lists `assessment`, then `findings`, then `proposals`, then `questions`. The model writes them in that order.
- The run loop (`services/strategist.py::run_strategy_review`) never inspects `stop_reason`. A tool call cut off at the cap is persisted as `status='complete'` with whatever parsed.

Evidence from `strategy_reviews.token_usage`, all clients, 2026-08-18 → 2026-09-01:

| Reviews | Emit-round output tokens | Proposals | Questions |
|---|---|---|---|
| 35 zero-proposal reviews | **4096–4700** (cap + drill-down overhead) | 0 | 0 |
| 8 reviews with proposals | 3566–3936, or short findings | 4–5 | 0–5 |
| Week of Aug 31, all 13 reviews | all at cap | 0 | 0 |

Two reviews stored **zero findings** (the cut landed mid-array). The collapse is **portfolio-wide** and worsened as the digest grew (#945 competitor pages, GBP metrics, backlinks → longer findings). FCR was merely the case the owner noticed.

Secondary facts that shape the design:

- **#949's escalation sweep has never fired in production** as of 2026-09-02 (`goal_escalations` 0 rows, `goal_chronic` notifications 0). The "natural delivery vehicle" is untested.
- **FCR's notification feed looks wiped** — no `strategy_review`, `maps_drop` or `reopt_plan` row after 2026-07-07 despite weekly reviews and the Aug 7 collapse (consistent with the bulk-delete footgun #949 fixed). Whether Slack received the weekly reviews cannot be confirmed from the database.
- The Strategist Review card (`components/StrategistReview.tsx`) renders **only the latest completed review's** proposals. An open proposal from an earlier review is invisible once a newer review completes.
- Already in place and reused: per-proposal grounded costing (`ground_proposal_cost` from `costed_items`), `recipe_engine.budget_envelope` (deployable / discretionary), the chat `cost_plan` tool, the `escalation` trigger with `escalation_context`, per-trigger enqueue dedupe, `sermastr_audit` ledger, the approve → `asana_push.push_proposal` → `pm_assign.place_task` path.

## 3. Scope

### PR 1 — stop the truncation (ship first)

1. `strategist_max_tokens` **4096 → 16000** (Sonnet supports it; worst-case output cost ≈ $0.25/review).
2. Reorder the emit schema so **`proposals` and `questions` precede `findings`** (cheap insurance: if anything is ever cut, it is the least actionable part).
3. **`stop_reason` guard.** On `max_tokens`: one retry round — append the truncated assistant turn and a user message ("you were cut off; call `emit_strategy_review` again with proposals first, ≤5 findings of ≤2 sentences each") and force the emit. If still truncated: store as `complete` with `token_usage.truncated=true` and an appended question naming the truncation. `status` stays within the existing CHECK (`running|complete|failed`); the findings are kept.
4. Deploy checklist: confirm PLATFORM has **no `STRATEGIST_MAX_TOKENS` env override** (the Railway connector was unauthorised in the design session; the data shows the effective cap is 4096 either way).

### PR 2 — autonomous recovery plans

Everything in §4–§9.

## 4. Behaviour

### 4.1 Trigger and cadence

- New `strategy_reviews.trigger` value **`goal_recovery`** (migration widens the CHECK). Distinct from `escalation` (a case file for seniors) — a recovery run is a **plan to approve**, with its own title, notification, dedupe and filter.
- Fired by the daily `goal_escalation` sweep (`services/goal_escalation.py::_sweep_client`): when **any** of a client's goals is due to (re-)escalate (`should_escalate` — ≥ `goal_escalation_chronic_weeks`, then every `goal_escalation_reescalate_days`), enqueue **one recovery run for the client** covering **all** its chronic goals. Deduped so a client gets at most one recovery run per re-escalation window (`enqueue_strategy_review`'s per-trigger in-flight dedupe + `clients_reviewed_within("goal_recovery", reescalate_days - 1)`).
- **Cap: 5 recovery runs per daily tick**, oldest-behind first. A capped client is **not escalated that day at all** (no message, `last_escalated_at` untouched) and rolls to the next tick with its run. The first production tick will open rows for every chronic goal portfolio-wide (`initial_behind_since` seeds from the baseline date), so the cap bounds the day-one burst.
- **Portfolio-wide by construction.** Gates are the existing ones: the client has ≥1 active campaign goal (a no-goal client never escalates — that is the #931 nudge's job), the client is not opted out (`clients.strategist_enabled=false`), and a **frozen** client gets the alarm plus an observation-only review with zero proposals (`sanitize_review` unchanged).

### 4.2 Who sends the notification

The **finished run** emits the single `goal_chronic` message (alarm + plan). The sweep emits the bare #949-style alarm **only** when a run is impossible: flag off, strategist disabled, or enqueue failure. Never both — one message per escalation, at most a day late on the first tick.

### 4.3 What the run reads

The same full digest as the weekly run (`strategy_digest.build_strategy_digest`) plus a **RECOVERY block** in `build_run_prompt`:

- the chronic goal(s): label, status, weeks behind, worst value seen, current vs target (from `goal_escalations` + `campaign_goals.assess_goals`);
- the **prior recovery plan's proposals** with their statuses (so the run refreshes/re-costs rather than duplicates);
- the **budget envelope** (`recipe_engine.budget_envelope`: deployable, reporting, baseline stack, discretionary) and the **tier ceilings** (+25/+50/+100% over deployable);
- the current monthly task plan (already in the digest via `_prov_task_plan`).

Drill-down caps unchanged (`strategist_max_drilldowns`=4, paid 1). Raise only with evidence from a live run.

### 4.4 Emit schema

- Optional **`root_cause`** field (string), **required in recovery mode**: the prompt demands the specific driver — the competitor, the sector/quadrant, and what they built — sourced from the `competitors` (#945 page pushes) and `maps_geogrid` sections. Never "a competitor is surging".
- Proposals keep the existing advice-object shape; the prompt orders them by priority. Costing stays **grounded in code** (`costed_items` → `ground_proposal_cost`); the model never writes a dollar figure.

### 4.5 Budget: reallocation and tiers

- A proposal may **reallocate this month's task plan** (drop X, fund Y) — **proposal-level only**. Approval turns it into a task through the existing path; the stored `monthly_task_plans` row is **never rewritten** (propose-only; the plan regenerates monthly).
- **Tiers are cumulative over deployable** (retainer × margin), assigned **deterministically in code** after sanitize: walk proposals in the strategist's priority order, keep a running total, assign each the first tier whose ceiling covers it — `within_budget` (≤ deployable), `+25%`, `+50%`, `+100%`, `over` (beyond +100%). Discretionary is shown but is not the tier base (for a $1,000 retainer it is ≈ $55 — noise).
- Per-proposal `tier` + `cumulative_cost_usd` are stored inside the proposal object; the envelope, ceilings, fundable count and `root_cause` are stored on the review row (§5).
- The client card remains the **only** place budget is set (retainer, client type, SAB). The review row merely **remembers what the plan was costed against**, so an edited retainer never silently re-tiers an old plan.

### 4.6 Superseding

On **persistence** of a new recovery review (never at enqueue, so a failed run leaves the old plan standing), every still-`proposed` proposal on the client's **prior `goal_recovery` reviews** is marked **`superseded`**. Weekly and escalation reviews are never touched. `superseded` is invisible to the current UI (it filters on proposed/approved/dismissed) and the approve endpoint refuses it (`invalid_status`). In the `sermastr_action_log` ledger `superseded` is recorded as its **own decision value**, excluded from approve and dismiss rates so it cannot poison the learning signal.

### 4.7 The `goal_chronic` message (Slack + in-app)

```
🔴 STILL CRITICAL (week 10): First Class Roofing — 35% local-pack presence
"35% local-pack presence" has been behind for 10 weeks — now 6.2 vs target 35. 2 open alerts.
Root cause: <2 sentences naming competitor + sector + what they built>
Recovery plan (5 proposals, 2 within budget, +25% covers 4):
1. <title> — $X · within budget
2. <title> — $Y · within budget
3. <title> — $Z · +25% · requires senior
…
<link: clients/{id}/action-plan>
```

Reuses `notifications.emit(kind="goal_chronic", severity="critical")` and `format_slack`; payload gains `review_id`, `tiers`, `fundable_count`.

### 4.8 Prompt changes (all runs)

- The exit line "An empty review is a valid review… emit no proposals" becomes: **"Empty proposals are valid only when every behind goal already has an OPEN proposal addressing it; otherwise re-propose — refreshed and re-costed — and say which earlier proposals still stand."**
- New digest section **`open_proposals`** (provider in `strategy_digest._PROVIDERS`): the client's `status='proposed'` proposals from recent reviews with age, cost and trigger, so the strategist can see its own unactioned advice. This closes the brief's "stale proposals look like nothing new" hypothesis at the source.
- The weekly scheduled review **still runs** after a recovery run; the `open_proposals` section stops it duplicating the plan.

### 4.9 On-demand

`POST /clients/{id}/strategy-review` accepts a `trigger` body field (`goal_recovery` allowed; staff-only) for validation and deliberate use. No "Generate recovery plan" button in this PR — decide after the FCR validation run.

### 4.10 Frontend

- The Strategist Review card lists **open proposals across the last 60 days, up to 5 reviews**, newest first, grouped by review with its trigger label; the latest review's assessment and findings remain the headline. (Fixes the same invisibility for weekly reviews today.)
- **"Approve tier"** convenience: a client-side loop that fires the existing per-proposal endpoint for every proposal in tiers up to the chosen one. No backend change.
- Tier and cost pills on each proposal; the recovery review shows its root cause and budget line.

## 5. Data model

One migration (`writer/supabase/migrations/2026090xxxxxxx_strategy_reviews_goal_recovery.sql`, applied live + committed):

- `strategy_reviews.trigger` CHECK widened with `'goal_recovery'`.
- `strategy_reviews.budget jsonb` (nullable): `{envelope: {retainer_monthly, margin_used, deployable, reporting_cost, baseline_stack_cost, discretionary}, tiers: {within_budget, plus_25, plus_50, plus_100}, fundable_count, total_cost_usd, root_cause, goals: [{goal_id, label, weeks_behind, worst_value, current_value, target_value}]}`.
- `sermastr_action_log.decision` accepts `'superseded'` (if a CHECK exists; the column is text today — verify against the live constraint before writing the migration).

Proposal objects (JSONB, no constraint) gain `tier`, `cumulative_cost_usd`; `status` gains the value `superseded`.

## 6. Config

| Setting | Default | Purpose |
|---|---|---|
| `strategist_max_tokens` | **16000** (was 4096) | PR 1 |
| `goal_recovery_enabled` | **True** | PR 2 master gate; rides `strategist_enabled` + `goal_escalation_enabled` |
| `goal_recovery_max_runs_per_tick` | 5 | day-one burst cap |
| `goal_recovery_tiers` | `[0.25, 0.50, 1.00]` | cumulative ceilings over deployable |
| `strategist_open_proposals_days` | 60 | `open_proposals` digest window + card window |

## 7. Guardrails (unchanged, enforced)

- **Strategist proposes, never executes.** `sanitize_review` untouched: §3 passthrough → `requires:"senior"`, disavow dropped, frozen → zero proposals.
- **Propose-only — no auto hand-off to PACE.** PACE assignment happens only after a human approves a proposal, through the existing unchanged path (`routers/strategist.py` → `asana_push.push_proposal` → `pm_assign.place_task`).
- No change to `autonomy_policy.classify`, `AUTO_EXECUTE`, tiers, `autonomy_budget`, the freeze protocol, or `recipe_engine.allocate`.
- No new queue/infra; rides the shared scheduler and the `strategy_review` job type.
- Cost control: recovery runs fire only on the escalation cadence, one per client, capped per tick.

## 8. Acceptance criteria

Given a client with a campaign goal `behind`/`overdue` for ≥ the chronic threshold and no human interaction:

1. A `goal_recovery` review exists whose `proposals` are a concrete, multi-tactic, SOP-cited, prioritised recovery plan — not an empty/findings-only review.
2. Each proposal carries a grounded cost and a deterministic tier; `budget` on the review records the envelope and ceilings; a budget-adequacy item marked `requires:"senior"` appears when the fundable set is thin.
3. `root_cause` names the specific driver (competitor + sector + what they built).
4. Exactly one `goal_chronic` notification per escalation, sent by the finished run, carrying the root cause, the top proposals with cost and tier, the fundable line and the link — on both channels.
5. Every proposal is approvable through the existing endpoint; the autonomous run hands nothing to PACE.
6. Re-runs ride `goal_escalation_reescalate_days`; prior recovery proposals are superseded, not piled up; no daily-tick fan-out; ≤5 runs per tick.
7. PR 1: no review in the following week has `token_usage.truncated=true` without a retry having been attempted; the emit round's `output_tokens` sits well under the cap; proposals and questions reappear portfolio-wide.
8. Pure logic unit-tested (tier assignment, supersede selection, cap ordering, notification builder, stop-reason retry decision, `open_proposals` provider shape); every new read best-effort + provider-isolated.

## 9. Validation and deploy checklist

1. **PR 1 first.** After deploy: confirm no `STRATEGIST_MAX_TOKENS` override on PLATFORM; run one on-demand review on FCR; check `token_usage.output_tokens` < cap and `proposals > 0`. Watch the next weekly pass across all clients.
2. **PR 2.** After deploy: `POST /clients/a121d78b-…/strategy-review` with `trigger=goal_recovery` (≈ $1); read the review against §8; confirm one `goal_chronic` in Slack **and** the in-app feed. Then watch the first daily escalation tick (after `gsc_ingest_hour_utc` 08:00 UTC) for the day-one burst behaviour and the cap.
3. FCR's wiped notification feed: after PR 1, verify the weekly `strategy_review` notification actually lands in Slack (`channels_sent.slack="ok"`).

## 10. Out of scope / deferred

- Auto hand-off to PACE (owner ruling). Any auto-execution of the plan.
- A "Generate recovery plan" button (decide after the FCR validation run).
- Per-goal runs (a client with several chronic goals gets one plan, sectioned by goal).
- Rewriting the stored monthly plan on approval.
- Raising drill-down caps for recovery runs (only with evidence).

## 11. Decision log

| # | Decision | Ruling (2026-09-02) |
|---|---|---|
| 1 | Truncation fix as its own PR, first | Yes |
| 2 | Dedicated recovery run vs prompt-only | Dedicated `goal_recovery` run **plus** the prompt fix |
| 3 | Rewrite the empty-review exit; `open_proposals` digest section | Yes |
| 4 | Unfundable plans | Proposal-level reallocation of the current plan **or** cumulative +25/+50/+100% tiers over deployable, offered for approval |
| 5 | First-tick burst | Cap 5 runs/tick; capped clients roll forward unescalated |
| 6 | Trigger value | New `goal_recovery`, one-line migration |
| 7 | Who sends `goal_chronic` | The finished run; sweep only when a run is impossible |
| 8 | Message shape + `root_cause` emit field | Yes to both |
| 9 | Plan rewrite on approval; tier base | No rewrite; tiers over deployable, cumulative, deterministic |
| 10 | Supersede prior recovery proposals | Yes, at persistence; own ledger decision value |
| 11 | Card shows only the latest review | List open proposals across 60 days / 5 reviews |
| 12 | Run granularity | One per client per re-escalation window |
| 13 | Gating | `goal_recovery_enabled` default on |
| 14 | Tier approval | Client-side "Approve tier" over the existing endpoint |
| 15 | Capped-run day | No bare alarm; escalation deferred with the run |
| 16 | Recovery-run drill-downs | Same caps |
| 17 | Budget math storage | Snapshot on the review row (`budget jsonb`); client card stays the input |
| 18 | Weekly review after a recovery run | Runs anyway |
| 19 | On-demand trigger | API only in this PR |
| 20 | Still-truncated after retry | `complete` + flag + question |

## 12. As built (2026-09-02)

Everything in §3–§9 shipped as specified, with these implementation notes:

- **`services/goal_recovery.py`** is the module: pure `parse_tiers` / `tier_ceilings` / `assign_tiers` / `budget_snapshot` / `goals_context` / `order_for_cap` / `build_recovery_block` / `build_recovery_notification` / `mark_superseded`; impure `enqueue_recovery_run` (returns `enqueued | in_flight | disabled | failed` so the sweep can tell "a run is coming" from "a run is impossible"), `load_recovery_context`, `apply_budget`, `supersede_prior_recovery`, `stamp_escalations`, `after_persist`.
- **The sweep collects, then dispatches.** `goal_escalation._sweep_client` no longer emits — it returns the due `(row, goal)` pairs; `_dispatch_due` orders clients oldest-behind first, enqueues up to `goal_recovery_max_runs_per_tick` recovery runs, and only calls `_escalate_bare` (the #949 alarm) when the gate is closed, the client opted out, or the enqueue failed. A capped or in-flight client is neither alarmed nor stamped. Sweep stats gained `recovery_enqueued` / `recovery_deferred` / `recovery_in_flight`.
- **Stamping moved to the run.** The FINISHED run stamps `goal_escalations.last_escalated_at` + `escalation_count` (`stamp_escalations`), so a failed run is retried by the next tick; `clients_recovered_within` (COMPLETE recovery reviews inside the window) guards the one case where a completed run's stamp did not land.
- **`root_cause`** is an optional emit field, demanded by the recovery orientation; `sanitize_review` carries it only when the model set it, and it persists inside `strategy_reviews.budget.root_cause` (no separate column).
- **Tiers** ride each proposal as `tier` + `cumulative_cost_usd` (labels `within_budget`, `plus_25`, `plus_50`, `plus_100`, `over`, `unbudgeted`); the envelope comes from `recipe_engine.budget_envelope` over the digest's client card values (no extra DB read).
- **`superseded`** is a system decision: `strategist_proposals` refuses to decide on one (`proposal_superseded` → 409) and excludes it from `open_proposal_indices` (so the bulk plan→PACE handoff can never approve a stale plan); `sermastr_audit` counts it in its own bucket, outside the approve/dismiss rates.
- **`open_proposals`** digest provider (`strategy_digest._prov_open_proposals`, window `strategist_open_proposals_days`) feeds both the weekly review and the recovery block's "prior plan" list.
- **On demand:** `POST /clients/{id}/strategy-review` body `{"trigger": "goal_recovery"}` (409 `goal_recovery_disabled` when the flag is off, 422 `invalid_trigger` otherwise).
- **Frontend:** `StrategistReview.tsx` shows a "Recovery plan" box (goals + root cause + budget line + "Approve tier" buttons), tier pills per proposal, a "Still open from earlier reviews" section (60 days / the 5 fetched reviews) with the same approve/dismiss + tier controls, and a superseded count.
- **Validation (owner):** one on-demand `goal_recovery` run on First Class Roofing after deploy, then the first 08:00 UTC escalation tick.
