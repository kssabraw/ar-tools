# Director of Operations — Phase 1 (D) + Prerequisite E — Build Spec v1.0

**Date:** 2026-08-28
**Status:** Spec for build (concrete). Implements Phase 1 (D) + Prerequisite E of
`director-of-operations-plan-v1_0.md` (the design authority — read it first).
**Folds in:** the owner's four §11 decisions (2026-08-28) + three corrections to the
plan discovered while grounding this spec against the live code (§2).

> This is the **build** spec: exact modules, seams, tables, function shapes, config
> keys, and tests. The plan v1.0 is the **why**; this is the **how**. Where this spec
> and the plan disagree on a fact, this spec's grounding wins (§2) and the plan should be
> footnoted, not silently overridden.

---

## 0. Owner decisions folded in (§11 of the plan)

| # | Question | Decision | Deviates from plan's leaning? |
|---|---|---|---|
| 1 | Seam thresholds | **Suggested defaults**: `qa_idle` 7d · `strategist_approved_unplaced` 3d · `autonomy_proposed_unactioned` 7d · `content_shipped_degraded` immediate. All config-tunable. | No |
| 2 | Digest cadence/channel | **Separate weekly "operations flow" summary** (its own weekday hook + narrative), not a line on the daily PACE digest. | **Yes** — plan leaned "ride the daily digest." |
| 3 | Duplicate-target handling | **Flag-only** (open a task naming both; no auto-merge) until `source_ref`/target uniformity is proven live. | No |
| 4 | Autonomy pre-flight veto | **Build it in Phase 1** (fail-open pre-flight downgrade to `propose`). | **Yes** — plan leaned "hold." |

**Consequence of the two deviations — Phase 1 is broader than plan-§7's minimal D.** As
scoped by the owner, Phase 1 = D (predicates + read model + SerMaStr surface) **plus** E
(prerequisite) **plus** a weekly narrative digest (decision 2, which the plan filed under
Phase 2/B) **plus** the autonomy veto (decision 4, a §5 reversible write the plan deferred).
Flag-only duplicate detection (decision 3) keeps that one narrow. This is a deliberate,
owner-chosen widening; the spec is structured so each added piece ships behind its own flag
and can be turned off independently.

---

## 1. Scope of this build

**In scope (Phase 1, this spec):**

- **E1** — fail-loud on unknown producer `source` values (the read model refuses to
  silently skip an unrecognized seam; mirrors `job_worker`'s unroutable-type discipline).
- **E2** — close the Recipe-Engine **placement** gap (route `_push_task_plan_native`
  through `pm_assign.place_task`, so monthly-plan tasks produce observable capacity holds).
- **D** — the deterministic cross-agent **read model** (§4), the **seam predicates** (§5),
  and the **SerMaStr read surface** (§7).
- A **daily reversible reconciliation** pass (open a board task / agency notification on a
  newly-stalled seam; flag a duplicate target) — never resolves, never merges (§6.1, §9).
- A **weekly operations-flow narrative digest** (decision 2, §6.2).
- The **autonomy pre-flight veto**, fail-open (decision 4, §8).

**Explicitly NOT in scope (deferred per plan §5/§7/§8):** duplicate **auto-merge**
(decision 3 → flag-only); intake-time **capacity arbitration**; any **priority /
scheduling / precedence** authority; a distinct fifth persona/login; a new read-model
**subsystem** (Phase 2/B graduation) — this build grows inside PACE's watcher.

**No migration.** Everything Phase 1 needs is computed on read or written through existing
tables (`notifications`, `tasks` via the existing producer contract, `scheduler_state`
markers). A dedicated `director_seam_flags` table is a Phase 2 concern (§11).

---

## 2. Corrections to plan v1.0 (grounded against live code)

Three load-bearing premises in the plan are imprecise. The build follows the corrected
facts; the plan should be footnoted to match.

### 2.1 The Recipe-Engine gap is **placement, not `source_ref`** (revises §7, §9)

The plan (§7, §9) names `asana_push.py:340` as a producer that "does not stamp
`source_ref`," making it the reason `duplicate_target` under-reports. **It does stamp
`source_ref`.** `_push_task_plan_native` (`asana_push.py:338-351`) writes
`source="task_plan"`, `source_ref=f"{plan_row_id}:{key}"`. What it does **not** do is call
`pm_assign.place_task` — it assigns by name-match (`match_member_gid`) and therefore never
records a `placement_deferred` / `team_at_capacity` hold. So the real gap is **placement
observability**, and it is fixed by E2 (§3.2), not by a `source_ref` change.

**Corollary:** `source_ref` is *already uniform across every producer path* — the five
`task_producers` hooks, `task_monthly`, `task_import`, and both `asana_push` native paths
all stamp a stable key. The genuinely unstamped `create_task` calls are the
**manual/interactive** ones (`routers/tasks.py:640`, `slack_assistant/actions.py:310`,
`task_collab.py` duplication, and the `source="manual"` default) — and those are
*correctly* unstamped (a hand-created task must not dedup against another). So the "make
`source_ref` a universal precondition" framing in plan §7 is dropped; E's real content is
E1 (fail-loud on unknown `source`) + E2 (placement).

### 2.2 `duplicate_target` must key on the **target**, not on `source_ref` equality (revises §4, §9)

Plan §4/§9 define `duplicate_target` as "two producers stamped the same `source_ref`." Two
*live* tasks with the same `(source, source_ref)` are **already prevented** by the partial
unique index `uq_tasks_source_ref` (`20260711130000_native_task_manager.sql:146-147`) and
by `create_task`'s app-level dedup (`task_service.py:407-411`). The cross-agent duplicate
that actually escapes is **two different sources acting on the same target** (e.g. an
`action_plan` task and a `strategy_proposal` task both targeting one keyword) — their
`source_ref`s differ, so neither guard fires. Detection therefore keys on the **target**:
`tasks.target->>'keyword'` / `->>'page_url'` (the jsonb added in
`20260828240000_interventions.sql:41-42`), cross-referenced with open `interventions.target`
and in-flight `async_jobs` payload keywords. See §9.

### 2.3 `qa_idle` reads `task_activity`, and QA-idle is agency-level (refines §4)

The durable record of a task *entering* In QA is a `task_activity` row
(`kind="status_changed"`, `detail->>'to' = settings.qa_trigger_status`), not a column.
`qa_idle` = zero such rows in N days while completed work exists (a `qa_reviews.created_at`
count in the window is an equivalent proxy). Because the live gap is "**nothing at all**
reaches In QA," `qa_idle` is a **portfolio** predicate → an agency notification
(`client_id=None`), not a per-client board task.

---

## 3. Prerequisite E (build first — the read model's foundation)

### 3.1 E1 — fail-loud on unknown seams

The read model enumerates the seams it understands; anything it doesn't recognize must
surface as an explicit **`unwatched_seam`** flag, never be silently dropped. Mirror
`job_worker.py:994-1004` (unknown job type → `logger.warning` + settle **failed** with an
explicit `unknown_*: <value>` error + early return, never the silent-skip path).

- Add `KNOWN_PRODUCER_SOURCES = {"manual", "monthly", "asana_import", "rank_drop",
  "maps_alert", "action_plan", "content_run", "scan_health", "task_plan",
  "strategy_proposal", "director_seam"}` (the last is the Director's own producer, §6.1) as
  a module constant in the read model.
- The `producers` provider (§4) groups open producer tasks by `source`. Any `source` value
  not in `KNOWN_PRODUCER_SOURCES` is emitted as an `unwatched_seam` flag carrying the
  offending value + a count, and logged `director.unwatched_source`. It is **not** skipped.
- Same discipline for a `qa_reviews` verdict, an `autonomy_runs` `decisions[].outcome`, or a
  `task_episodes.kind` the read model doesn't recognize: unknown → flagged, never dropped.

*Rationale (plan §9):* the Director rots the moment a new producer/status/job type is added
without teaching the read model about it. Fail-loud makes that omission visible on the first
tick instead of silently under-reporting collisions.

### 3.2 E2 — Recipe-Engine placement gap

`_push_task_plan_native` (`asana_push.py:338-351`) assigns monthly-plan tasks by name-match
and never routes through PACE, so a monthly task assigned into an over-capacity member
produces **no** `placement_deferred` hold — invisible to `strategist_approved_unplaced` and
to the `assignment` provider. Fix: after the `create_task(...source="task_plan"...)` insert,
call `pm_assign.place_task(row["id"], actor_id=...)` **best-effort in a try/except** (mirror
`push_proposal` at `asana_push.py:408-411`), so a capacity hold is recorded as a
`task_activity` `placement_deferred` row like every other placed path.

- **Preserve the name-match as a fallback, not a duplicate.** `place_task` gap-fills only
  when `assignee_id` is empty (`pm_assign.py:304-305`, "never overwrite an existing
  assignment"). So: if the name-match resolved a `gid`, the task is already assigned and
  `place_task` returns `already_assigned` (no hold, no overwrite) — harmless. If the
  name-match found **no** gid (unassigned), `place_task` now runs the skilled/least-loaded
  placement and records a hold if the team is at capacity. Net effect: monthly tasks gain
  the same hold-observability as proposal tasks, and nothing that already worked changes.
- Gated on `settings.pace_autoplace_producers` (the existing producer-placement flag) so
  this stays consistent with the other producers and off by default.

---

## 4. The read model

New package `services/director/` (grows inside PACE's watcher; not a new subsystem).

```
services/director/
  __init__.py         # re-exporting facade (mirrors slack_assistant package split)
  read_model.py       # build_read_model(client_id|None, today) -> dict  (portfolio or per-client)
  providers.py        # the isolated, best-effort providers below
  seams.py            # pure seam predicates (§5)
  reconcile.py        # run_daily(today): reversible actions (§6.1)
  digest.py           # run_weekly(today): narrative (§6.2)
  veto.py             # preflight_conflict(rec, client_id) for the autonomy seam (§8)
```

**Provider contract (identical to `slack_assistant/context.py`):** each provider is
`prov_<name>(supabase, client_id: Optional[str], today: date) -> Optional[dict]`, does
bounded reads, returns a compact dict or `None` on empty. `build_read_model` wraps every
provider in its own `try/except` (log `director.provider_failed`, continue) so a failing
module degrades to a gap, never breaks the read. The heavy lift for the delivery/assignment
providers is **one call** to the shared portfolio read `pm_signals.build_board_digest(None,
today)` (the same read `pace_episodes` and `pace_digest` already use), not fresh queries.

| Provider | Source (read-only) | Emits |
|---|---|---|
| `strategy` | `strategy_reviews.proposals[]` (recent reviews) | open reviews; per-status proposal counts; **approved-but-`asana_task`-empty** list (§5 `strategist_approved_unplaced`) |
| `delivery` | `pm_signals.build_board_digest(None, today)` | per-client `stale`/`overdue`/`unassigned`/`unacted_producer` (reuse verbatim) |
| `assignment` | board digest `workload` + `task_activity` `placement_deferred` rows | per-member load vs `weekly_hours`; open `team_at_capacity`/`no_eligible_member` holds |
| `qa` | `task_activity` (`status_changed`→`in_qa`), `qa_reviews` (30d) | did-anything-enter-QA (the idle detector, §5); verdict mix; open rework |
| `autonomy` | `autonomy_runs.decisions[]` (latest N/client), `autonomy_spend` | executed/proposed/escalated buckets; proposals-never-actioned; `remaining` headroom |
| `producers` | `tasks` open where `source` in a producer set | open producer tasks by `source`; **`unwatched_seam`** on any unknown `source` (E1) |
| `interventions` | `interventions` | tactics enrolled; verdicts (worked/partial/no_effect/pending) |
| `flow` | derived join of the above | the seam flags of §5 |

`build_read_model(None, today)` = portfolio; `build_read_model(client_id, today)` =
one-client (for "walk me through where WheelHouse is stuck").

---

## 5. Seam predicates (`services/director/seams.py`, pure + unit-tested)

Each is a pure function over the §4 read model, tunable by a config threshold, returning a
flag `{seam, client_id|None, evidence, since, threshold_days}` — evidence, never a verdict.

| Predicate | Data source | Threshold (config) | Flag scope |
|---|---|---|---|
| `strategist_approved_unplaced` | `strategy` provider: proposal `status=="approved"` **and** `not proposal.get("asana_task")` (the exact guard at `routers/strategist.py:140`), aged by review/decided time | `director_seam_approved_unplaced_days` = **3** | per-client → board task |
| `qa_idle` | `qa` provider: zero `task_activity` `status_changed`→`in_qa` (or zero `qa_reviews`) in N days **while** completed work exists in the window | `director_seam_qa_idle_days` = **7** | portfolio → agency notification |
| `autonomy_proposed_unactioned` | `autonomy` provider: `autonomy_runs.decisions[]` with `outcome="propose"`, `executed=false`, and no task/intervention on that target since, aged N days | `director_seam_autonomy_unactioned_days` = **7** | per-client → board task |
| `content_shipped_degraded` | scan `runs`/writer for a `-degraded`/`-no-context` schema version or a shipped unresolved voice `critical` | **immediate** (no dwell) | per-client → board task |
| `task_stuck_in_status` | extends `pace_episodes`/`pm_signals` staleness — reuse `pm_signals.is_stale` + `pace_stale_thresholds`; the Director only *reads* it into the flow view | (existing `pace_stale_thresholds`) | per-client (already surfaced by PACE) |
| `duplicate_target` | two live tasks with **different `source`** but the same `tasks.target->>'keyword'`/`->>'page_url'` for one client (§2.2, §9) | n/a (presence) | per-client → flag-only task |

Thresholds live in `config.py` so recalibration needs no code change (the four defaults are
decision 1).

---

## 6. Reconciliation cadence

### 6.1 Daily reversible pass — `reconcile.run_daily(today)`

Runs on the shared scheduler in the existing PACE block (§gsc wiring below), gated on
`settings.director_enabled` (else `{"reconciled": False, "reason": "disabled"}`). For each
newly-tripped seam it takes the **one reversible action the plan permits (§5)** — and never
resolves or merges:

- **Per-client board seam** (`strategist_approved_unplaced`, `autonomy_proposed_unactioned`,
  `content_shipped_degraded`) → open a board task through the standard producer contract:
  `task_service.create_task(..., source="director_seam",
  source_ref=f"{seam}:{client_id}:{ident}")`. This makes the Director itself a **producer**
  (hence its inclusion in `KNOWN_PRODUCER_SOURCES`, E1), so the task **auto-closes** via
  `close_task_by_source` when the seam clears — same open/close discipline as
  `task_producers`. Idempotent by construction (the partial unique index).
- **`duplicate_target`** → open one `source="director_seam"` task **naming both** offending
  tasks (flag-only, decision 3). No merge, no suppression. `source_ref =
  f"dup:{client_id}:{target_key}"`.
- **`qa_idle`** (portfolio) → `notifications.emit(client_id=None, kind="ops_seam",
  title="QA idle — nothing has entered In QA in {N} days",
  dedupe_key=f"ops_seam:qa_idle:{iso_week}")`. Notification, not a board task (no client).

Every action is reversible (a task that can be trashed; a deduped notification) and logged.
The daily pass **never** touches priority, scheduling, or a precedence engine.

### 6.2 Weekly operations-flow digest — `digest.run_weekly(today)` (decision 2)

Its own weekly hook (not a line on the daily PACE digest). Deterministic assembly of the
portfolio read model into a narrative + the week's seam flags, emitted once per ISO week:

```python
notifications.emit(
    client_id=None, kind="ops_digest",
    title=f"Operations flow · week of {monday.isoformat()}",
    summary=body,                       # narrative (see below)
    severity="info",
    payload={"link": "/tasks", "slack_channel": settings.pace_slack_channel or None},
    dedupe_key=f"ops_digest:{iso_year}-W{iso_week:02d}",   # stable across a redeploy re-run
)
```

- **Channel:** route to the **PACE channel** (add `"ops_digest"` to
  `notifications.PACE_CHANNEL_KINDS`, `notifications.py:145-154`) so operations chatter stays
  out of the strategy channel — consistent with the daily PACE digest. `client_id=None` →
  master PACE channel via `resolve_slack_channel`.
- **Body (deterministic, no LLM for v1):** a compact flow summary — per-seam counts with the
  named clients (enumerate, don't count — PACE's rule); the week's `qa_idle` state;
  autonomy executed-vs-proposed totals + headroom; the top capacity holds; any
  `unwatched_seam` (E1). An LLM narrative pass is a deferred polish, not Phase 1 — the
  deterministic body is the deliverable and never fabricates.
- **Noise valve (the §11.2 hedge, made real):** the digest suppresses (returns silently,
  no emit) when the week has **zero seam flags and zero autonomy activity** — an all-clear
  week produces no message, exactly as `pace_digest` goes silent on `all_clear`
  (`pace_digest.py`). This is the guard against the weekly-narrative-is-noisy risk the plan
  flagged when it leaned toward the daily line.

### Scheduler wiring (`services/gsc_scheduler.py`)

Two additions in the existing PACE block (~lines 744-766, all `_safe(...)`):

```python
# after pace_chase_plan (762) — daily reversible reconciliation
_safe("director_reconcile", run_director_reconcile, now.date())

# weekly operations-flow digest — mirror the reopt weekly block (802-806)
if now.weekday() == settings.director_digest_weekday and should_run(now, last_ops_digest_date, hour):
    if _safe("ops_digest", run_ops_digest, now.date()):
        last_ops_digest_date = now.date()
        save_marker("ops_digest_weekly", last_ops_digest_date.isoformat())
```

- Load `last_ops_digest_date = parse_marker_date(state.get("ops_digest_weekly"))` beside the
  other markers (~line 646); mirror `reopt_weekday` exactly (weekday gate + `should_run`
  hour/not-today + marker advance **only on `_safe` success**, so a transient failure retries
  next tick, not next week).
- Daily reconcile runs **after** `pace_episode_sync` (761) and `pace_chase_plan` (762) so it
  reads post-sync episode state.

---

## 7. SerMaStr read surface

A single best-effort context provider so the Director answers through the existing owner seat
(plan §6). No new persona.

- Add `_ctx_director(supabase, client_id, today)` to `slack_assistant/context.py`, returning
  a compact projection of `build_read_model(client_id, today)` (seam flags + the cross-agent
  state) or `None` when empty. Register `("director", _ctx_director)` in `_CONTEXT_PROVIDERS`
  (`context.py:1831-1865`) — the only wiring change; it reaches the prompt automatically via
  `format_context` (no prompt edit needed for the JSON to appear).
- **Portfolio path:** extend `build_portfolio_context` (`context.py:60-107`) with a
  `director` block from `build_read_model(None, today)` so agency-wide questions ("who's the
  bottleneck this week", "show me every place two agents act on the same target") are answered
  without a client named.
- One prompt line in the SerMaStr system prompt: the Director block is **read-only insight**;
  it may *offer* to open a task or raise a proposal to PACE, but SerMaStr never silently acts
  on delivery from it (plan §6). The actual task-opening is the daily reconcile pass (§6.1) or
  an explicit PACE action — not a side effect of an answer.

---

## 8. Autonomy pre-flight veto (decision 4) — `services/director/veto.py`

Fail-open downgrade of a single autonomy auto-execute when an in-flight conflicting action
targets the same keyword for the same client.

**Seam (exact):** `autonomy_executor.run_autonomy_for_client`, inside the act loop
(`autonomy_executor.py:345-362`), as the **first** check once a rec is confirmed
`auto` + in `AUTO_EXECUTE` (i.e. after the `:346` gate `continue`, **before** the `:349`
budget reserve):

```python
if settings.director_autonomy_veto_enabled and director_veto.preflight_conflict(rec, client_id):
    rec["outcome"] = "propose"
    rec["policy_reason"] = "director veto: in-flight conflicting action on same target"
    continue
```

Placing it before `reserve` means a vetoed candidate never touches budget; the summary
already recomputes `proposed` from `rec["outcome"]` (`:372`), so no other change is needed.

**`preflight_conflict(rec, client_id) -> bool` — fail-OPEN:**

- Exempt candidates with no target: `rebuild_action_plan` (no `keyword`) → return `False`
  (nothing to conflict on).
- For content candidates, `kw = rec.get("keyword")`; join on `client_id` + `kw` across:
  - **`async_jobs`** — `status in ('pending','running')`, `entity_id = client_id`,
    `payload->>'keyword' = kw` (an in-flight `local_seo_generate`/`autonomy_run` on the same
    keyword — the single most direct signal).
  - **`tasks`** — `client_id`, `completed=false`, `deleted_at is null`,
    `target->>'keyword' = kw` (a live producer task already on this target).
  - **`interventions`** — `verdict is null`, `client_id`, `target->>'keyword' = kw`
    (work already landed and being measured — don't pile on).
- **Any exception → return `False`** (no veto). The predicate swallows its own errors: the
  whole autonomy loop is best-effort ("a per-step failure degrades to observation, never
  raises," `autonomy_executor.py:298`), and the plan mandates fail-*open* to `propose`,
  **never** to silence. A DB hiccup must not silently block an autonomous action.

**Gated on `settings.director_autonomy_veto_enabled` (default False)** so it ships dark even
though it's in Phase 1 scope. **Scope caveat (plan §2/§8):** this guards a collision that
*has not yet occurred* (autonomy is a narrow safe-slice, the triple-collision has never
happened). Building it now is the owner's call (decision 4); shipping it dark keeps the
not-yet-exercised guard from adding runtime risk before autonomy widens.

---

## 9. Duplicate-target detection (flag-only, decision 3)

Per §2.2, this keys on the **target**, not `source_ref`:

- For each client, collect live tasks (`completed=false`, `deleted_at is null`) with a
  non-empty `target->>'keyword'` or `target->>'page_url'`, plus open `interventions.target`
  and in-flight `async_jobs` payload keywords.
- A `duplicate_target` flag fires when **two or more live items with different `source`**
  share a normalized target key for one client.
- Action (§6.1): open **one** `source="director_seam"` task naming both offenders. **No
  auto-merge, no suppression** — decision 3 holds the merge until target/`source_ref`
  uniformity is proven live, because "the merge is only as safe as the key" (plan §9).
- Same-`source` same-`source_ref` collisions are **not** duplicate_target — they're already
  DB-prevented (the partial unique index), so surfacing them would be noise.

---

## 10. Config keys to add (`config.py`)

```python
# Director of Operations (cross-agent read model) — Phase 1
director_enabled: bool = False                        # master gate (read model + daily reconcile)
director_digest_weekday: int = 0                      # weekly ops digest weekday (0=Mon); mirrors reopt_plan_weekday shape
director_autonomy_veto_enabled: bool = False          # decision 4 — ships dark
director_seam_approved_unplaced_days: int = 3         # decision 1
director_seam_qa_idle_days: int = 7                   # decision 1
director_seam_autonomy_unactioned_days: int = 7       # decision 1
# content_shipped_degraded is immediate (no dwell) — no key
director_autonomy_ledger_lookback_runs: int = 8       # per-client autonomy_runs to read
```

All default off/conservative — the module ships dark, consistent with the suite convention.

---

## 11. Data model

**No migration in Phase 1.** The read model is computed on read; the daily reconcile writes
through the existing producer contract (`tasks`, `source="director_seam"`); the weekly digest
uses `notifications` + a `scheduler_state` marker (`ops_digest_weekly`); the veto writes
nothing. A dedicated `director_seam_flags` table (durable flag history, resolve/ack, a UI) is
a **Phase 2/B** concern, unlocked by §8 of the plan — not built until the read layer
graduates to its own subsystem.

---

## 12. Testing (pure-first, mirrors the suite convention)

- `tests/test_director_seams.py` — each §5 predicate: fires at threshold, silent below,
  correct evidence shape; `qa_idle` portfolio-vs-per-client; `duplicate_target` fires on
  different-source same-target and stays silent on same-`source_ref` (which is DB-prevented).
- `tests/test_director_read_model.py` — provider isolation (a failing provider degrades to a
  gap, never breaks the read); **E1 fail-loud**: an unknown `source` surfaces as
  `unwatched_seam`, is **not** silently skipped, and logs `director.unwatched_source`.
- `tests/test_director_veto.py` — `preflight_conflict` returns `True` on an in-flight
  `async_jobs`/`tasks`/`interventions` match; **fail-open**: any raised exception → `False`
  (no veto); `rebuild_action_plan` (no keyword) → `False`; and a wiring test asserting the
  downgrade sets `outcome="propose"` before `reserve` (mirror the budget-refusal test).
- `tests/test_director_digest.py` — dedupe_key stability across a re-run; the all-clear
  suppression (zero flags + zero autonomy → no emit); enumerate-don't-count body.
- E2: a `_push_task_plan_native` test asserting `place_task` is called and an unassigned
  monthly task at capacity records a `placement_deferred` activity, while an already-named
  task is left untouched (`already_assigned`, no overwrite).

Mock every external/DB read (`unittest.mock`), consistent with the existing suite — and use
a fake Supabase that **honours column projection** (the `.select(...)` bug lesson from
`website_generate`: a fake more generous than the DB hides real defects).

---

## 13. Files

**New:** `services/director/{__init__,read_model,providers,seams,reconcile,digest,veto}.py`;
the five test modules above.

**Edited:** `config.py` (§10); `services/gsc_scheduler.py` (two `_safe` additions +
marker); `slack_assistant/context.py` (`_ctx_director` + registry + portfolio block);
`services/notifications.py` (add `"ops_digest"`/`"ops_seam"` kinds to `PACE_CHANNEL_KINDS`);
`services/autonomy_executor.py` (the veto hook, §8); `services/asana_push.py` (E2 —
`place_task` in `_push_task_plan_native`).

**Untouched (hard boundary, plan §5/§10):** `reopt_planner.py` tiers,
`autonomy_policy.classify` (stays pure — veto lives in the impure executor), `pm_assign`
placement ranking. The Director reads their outputs and escalates conflicts; it never
arbitrates them.

---

## 14. What Phase 1 deliberately still does NOT do

- No scheduling or priority authority (plan §10). Lane + `scheduled_at` remain the mechanism.
- No duplicate auto-merge (decision 3 → flag-only).
- No intake-time capacity arbitration (deferred behind the plan §8 trigger:
  `team_at_capacity` holds from ≥2 demand sources in one week).
- No new persona/login; no `director_seam_flags` table; no LLM digest narrative (deterministic
  body only for v1).
- The autonomy veto ships **dark** (`director_autonomy_veto_enabled=False`) — the guard exists
  but does not fire until the owner enables it, because the collision it guards is not yet
  observed (plan §2/§8).

---

## 15. Open confirmations (small)

1. **Weekly digest weekday.** Default Monday (`director_digest_weekday=0`). The daily PACE
   digest already runs weekdays; a Monday ops-flow summary reads the prior week. Confirm or
   pick a day.
2. **E2 rollout.** Routing monthly-plan tasks through `place_task` is gated on the existing
   `pace_autoplace_producers` flag (off today). Confirm E2 should respect that flag (so it
   activates when producer auto-placement does) rather than always-on.
3. **`ops_digest` channel.** Spec routes it to the PACE channel (via `PACE_CHANNEL_KINDS`).
   Confirm that's the right home vs. the default/strategy channel.
