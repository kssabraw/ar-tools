# Director of Operations — Cross-Agent Orchestration Layer — Module Plan v1.0

**Date:** 2026-08-28
**Status:** Proposed (spec for review — nothing built yet)
**Depends on:** the native task manager (`in-app-task-manager-prd-v1_0.md`), SerMaStr
(`services/slack_assistant/`, `seo-strategist-agent-plan-v1_0.md`), PACE
(`project-manager-agent-plan-v1_0.md`), QA (`qa-agent-plan-v1_0.md`), the autonomy
executor (`autonomous-seo-agent-plan-v1_0.md`), the shared scheduler
(`services/gsc_scheduler.py`), the notifications service (`services/notifications.py`).

> **Naming note.** "Director of Operations" is the **owner-facing surface you see and
> query the whole operation through** — not a fifth autonomous persona with its own
> login, auth surface, or write actions. It is the conversational face of a
> deterministic **cross-agent read model + reconciliation layer**. Its conversational
> surface is **SerMaStr** (your existing owner seat), the same way the strategist and
> the Q&A bot share one identity. The word "orchestrator" is used for the read/reconcile
> *layer*; "Director of Operations" is used for the *lens onto it*. Neither term implies
> scheduling or priority authority — see §5, which withholds it deliberately.

> **Framing decision (owner, 2026-08-28 — folds into `decisions.md`).** The trigger for
> this work was "we have SerMaStr + PACE + QA + the task board — a lot of moving parts;
> we need an orchestrator making sure they work in concert," refined to "a Director of
> Operations would give me more insight into how work is flowing." The analysis behind
> this plan (three grounded discovery passes over the live code) concluded: **build the
> eyes, defer the hands.** Insight is a property of the *read model + a surface you can
> interrogate* — it is fully delivered by a read-only Director and is not improved by
> giving it authority. Past a point, authority *degrades* insight: the more the Director
> acts, the more your view becomes "what the Director decided" rather than "what is
> actually happening," and it becomes one more layer to audit. So: **read-first,
> conversational, owner-facing; arbitration authority deferred behind observed
> triggers** (§8).

---

## 1. Purpose & position

The suite now runs four things that touch the same clients and the same task board:

- **SerMaStr** — the strategist. *Proposes, never executes* (`services/strategist.py`).
- **PACE** — delivery coordination. *Executes, authorized + actor-bound-confirm-gated*
  (`services/pace_agent.py`).
- **QA** — the deterministic quality judge (`services/qa_service.py`).
- **The autonomy executor** — SerMaStr's closed loop, *shipped dark*
  (`services/autonomy_executor.py`).

…all writing the **native task board** (`services/task_service.py`), with deterministic
**producers** (`services/task_producers.py`) creating and closing tasks from suite
signals.

**The gap this plan fills is not "they collide."** It is that **the coordination between
them is implicit and unobserved, and the only reconciler of last resort is the owner.**
Three concrete absences, confirmed against the code:

1. **No global cross-agent priority decider.** The scheduler (`services/gsc_scheduler.py`)
   is a flat sequence of ~40 independent `_safe(enqueue_due_*)` hooks; none consults any
   other. Once enqueued, ordering is FIFO on `scheduled_at` (`services/job_worker.py`,
   `_claim_next_job`), plus three lanes (main / interactive / fanout, `main.py:160-182`).
   Priority is emergent from lane + future-dating, never a central decision.
2. **No intake-time capacity arbitration.** Capacity (per-member `weekly_hours` + skills)
   is checked *per-task at placement only* — every producer calls `pm_assign.place_task`
   independently (`services/asana_push.py:411`, `services/task_producers.py:69`), and
   `place_task` refuses to reason about other pending demand (`services/pm_assign.py:303`,
   "Never overwrite an existing assignment").
3. **No cross-agent health/pipeline monitor.** `services/orchestrator.py` is a
   *content-run driver*, unrelated. `pm_signals` / `pace_episodes` watch the **task
   board**, not the seams *between* agents (strategist-approved-but-unplaced, QA-idle,
   autonomy-proposed-but-unactioned, degraded content shipped).

The Director of Operations is the standing answer to "how is work flowing, where is it
pooling, why did this client go quiet, who is the bottleneck this week" — a question no
existing surface can answer end-to-end today.

---

## 2. What the evidence supports (and what it doesn't)

Grounded in `CLAUDE.md`, `HANDOFF.md`, and history, the cross-agent **incident** record
is deliberately stated honestly, because it sets the ceiling on how much *authority* this
layer should hold:

- **Two** unambiguous cross-agent runtime failures that shipped / would-ship bad output:
  1. **Autonomy × Local SEO generator (WheelHouse IT, 2026-08-28).** The executor fed the
     client's street address as the generator's `location` (must be a DataForSEO city);
     both drafts failed `location_not_recognized` (`HANDOFF.md:296-303`, fix #830/#832).
  2. **Content run × brand-guide setup race (First Class Roofing, ~2026-07-31).** A run
     executed 11 minutes before the guide was saved, silently degraded to `1.9-degraded`,
     shipped with zero voice context (`CLAUDE.md`, `content_no_brand_context`).
- **One live coordination *gap* (not a crash): QA is armed-but-idle.** No task reaches
  In QA because imported checklists are `is_work_item=False`, so auto-advance Rule B never
  fires — an enabled agent doing zero work (`CLAUDE.md`, live-state caveat 2026-08-28).
- Three cross-*system* baseline/config cascades (one-off Maps scans polluting alert
  baselines; grid-resize false alerts; LeadOff scanner stripping DB grants).

**The load-bearing observation.** The collision an orchestrator is imagined to prevent —
*strategist proposed + autonomy executed + a producer created a task, all on one target* —
**has never happened.** It is defended in code one guard at a time (producer skip-lists,
`services/task_producers.py:164`; `trigger="manual"` to dodge a double-notify, caught in
CI; per-trigger escalation dedup, caught in review) but the defenses are **runtime-untested,
because autonomy is a narrow safe-slice, QA is idle, and the producers are new.** The
scarcity of incidents is not evidence of good coordination — it is evidence the agents
**have not yet run concurrently at scale against the same clients**, and every guard that
exists was found *one adversarial review at a time*, a pattern that does not scale as more
agents go live.

**Conclusion.** Build the **read/observe/reconcile** layer now (it pays for the insight and
catches the one live gap). Withhold **arbitration authority** until the collision surface is
actually exercised (§8). Two real incidents, neither an arbitration failure, cannot buy a
standing authority that would sit above three *tested* precedence engines.

---

## 3. The read model (the heart of this plan)

A deterministic, best-effort join that assembles, per client and per portfolio, the
**live state of every agent and every seam between them**. It reads only; it never writes
agent state. Each provider is isolated (a failing module degrades to a gap, never breaks
the read) — the same contract the SerMaStr context registry already uses.

| Provider | Source (read-only) | What it surfaces |
|---|---|---|
| `strategy` | `strategy_reviews`, strategist proposals | open reviews; proposals `proposed`/`approved`/`dismissed`; approved-but-unactioned |
| `delivery` | `tasks`, `task_sections`, `pm_signals` | board state per client; stale / overdue / unassigned / unacted-producer |
| `assignment` | `pm_assign` load, `asana_team_members`, `placement_deferred` activity | per-member load vs. `weekly_hours`; `team_at_capacity` holds; deferred placements |
| `qa` | `qa_reviews`, `qa_trigger_status` queue | verdict mix (30d); **is anything reaching In QA** (the idle detector); open rework |
| `autonomy` | `autonomy_runs` ledger, `autonomy_spend` | auto-executed vs. proposed vs. escalated; proposals never actioned; budget headroom |
| `producers` | `task_producers` source rows | open producer tasks; auto-close lag |
| `interventions` | `interventions` | tactics enrolled; verdicts (worked / partial / no_effect / pending) |
| `flow` | derived join of the above | **the seam predicates in §4** — the states no single agent owns |

The read model is the deliverable that produces the *insight*. Everything else in this
plan is either how you query it (§6) or what it's allowed to *do* with what it sees (§5).

---

## 4. Seam predicates (the stall detectors)

The states that live *between* agents and that nothing currently observes. Each is a pure
predicate over the §3 read model, tunable by threshold:

- **`strategist_approved_unplaced`** — a proposal `approved` but its task has no assignee /
  sits in `placement_deferred` past *N* days. (Approval hands to `pm_assign.place_task` at
  `asana_push.py:409`, which *holds* on capacity — the hold is invisible today.)
- **`qa_idle`** — zero tasks entered `qa_trigger_status` in *N* days while completed work
  exists. (This catches the live 2026-08-28 gap directly.)
- **`autonomy_proposed_unactioned`** — an autonomy candidate landed in `autonomy_runs` as a
  proposal and neither executed nor was picked up within *N* days.
- **`content_shipped_degraded`** — a run completed at a `-degraded` / `-no-context` schema
  version, or a page shipped with an unresolved voice `critical`. (The FCR class.)
- **`task_stuck_in_status`** — any task past its expected dwell time for its status
  (extends `pace_episodes`, which already clocks stale / overdue / unassigned / unacted).
- **`duplicate_target`** — two producers stamped the same `source_ref` (the dedup key —
  see §9), i.e. two paths acting on one target.

Each predicate resolves to a flag with the joined evidence, not a verdict. What the
Director may *do* with a flag is §5.

---

## 5. Decision rights (deliberately narrow, deliberately reversible)

**Acts without the owner (read + reversible only):**
- Emit health/flow telemetry and a **daily reconciliation line** in the existing PACE /
  owner digest (`notifications.emit`, atomically deduped via `notifications.dedupe_key`).
- **Answer questions** about the whole operation through SerMaStr (§6).
- **Open a board task / notification** when a §4 seam stalls (never resolve one silently).
- **Merge / suppress a duplicate task** when two producers stamped the same `source_ref`
  (deterministic, reversible, logged).
- **Pre-flight-veto a single autonomy auto-execute** when it detects an in-flight
  conflicting action on the same target — **fail-*open* to "propose," never to silence.**

**Must escalate — never decides:**
- Any **priority reordering**; any **reassignment of a human's work**; anything that
  **overrides a within-engine precedence** — `reopt_planner` tiers
  (`services/reopt_planner.py:46`), `autonomy_policy.classify`
  (`services/autonomy_policy.py:121`), a `pm_assign` capacity hold
  (`services/pm_assign.py:104`). These become **proposals to the owner or to PACE**, routed
  through PACE's existing actor-bound confirm machinery.

**Deferred behind a trigger (§8) — the one place real authority might eventually live:**
- **Intake-time capacity arbitration** — deciding, across *all* demand sources at once,
  which of the week's contending work actually gets placed given finite VA hours. Not built
  until a real capacity collision is *observed*, because today none has occurred.

**Hard boundary.** The Director never touches the three tested precedence engines. It
observes their outputs and escalates when they conflict; it does not arbitrate them. The
moment anyone extends it to reorder priority, it becomes the "Director-with-authority"
option the incident record explicitly could not justify — see §10.

---

## 6. Conversational surface

The Director is queried through SerMaStr (owner-facing seat), as a read persona over the
§3 model. Target interactions:

- "Walk me through where the WheelHouse work is stuck." → the client's seam flags +
  evidence, enumerated (mirrors PACE's enumerate-don't-count rule).
- "Why did nothing ship for this client this week?" → joins `delivery` + `qa` + `autonomy`
  + `content_shipped_degraded`.
- "Who's the bottleneck this week?" → `assignment` load vs. capacity across all sources.
- "Show me every place two agents are acting on the same target." → `duplicate_target`.

It answers; it offers to *open a task* or *raise a proposal to PACE* for anything
actionable; it never silently acts on delivery. Read tools only, plus the narrow reversible
write set in §5.

---

## 7. Phasing

**Prerequisite — E (contracts + validation, folds into the seams it protects).** Not
optional. Make `source_ref` a **stamped precondition** on every producer path (the
Recipe-Engine monthly push is the known gap — it assigns by name-match and does not stamp /
place, `asana_push.py:340`). Add the two seam validations the real incidents already needed
(autonomy→generator city-resolution is done in #832; run→brand-guide precondition is the
`content_no_brand_context` warning). Without a uniform `source_ref`, the Director's
`duplicate_target` detection silently under-reports (§9).

**Phase 1 — D (grow the existing watcher).** Add the §4 predicates to
`pace_episodes` / `pm_signals` and the read-model join. This catches `qa_idle` (the one
live gap) this week, at near-zero cost, and delivers the first cut of the insight surface
through SerMaStr. No new persona, no schema churn.

**Phase 2 — B (graduate to a distinct owner-facing read model + reconciler).** When §8's
trigger fires, promote the read model to its own subsystem (its own provider registry,
its own daily reconciliation digest, the reversible write set in §5), still surfaced
through SerMaStr — because at that point the seams span non-board state (autonomy ledger,
degraded content) that PACE's board-scoped watcher shouldn't own.

**Deferred — the capacity arbiter.** Only on §8's capacity trigger, and even then as a
*proposer* first (it recommends the intake ordering; the owner/PACE approve) before any
autonomous placement authority is considered.

---

## 8. Trigger conditions (what unlocks the next phase)

**D → B (graduate the read layer to its own subsystem):** the first time *any* of —
- autonomy auto-execution runs content against **>5 clients in a week**, or
- the read model records **`qa_idle` clearing** (tasks actually flowing into QA, so the
  quality seam is now load-bearing), or
- the owner personally reconciles **the same cross-agent conflict twice**.

**Unlock the capacity arbiter (build the deferred hands):** `pm_assign` records
**`team_at_capacity` holds from ≥2 different demand sources in the same week** — i.e. real
intake contention, not a single overloaded member. Until then, per-task placement +
advisory `pace_slips` / `pace_rebalance` are sufficient and the arbiter is overhead.

These are thresholds/events, not "if we grow." If none fires, Phase 1 (D) is the whole
build and that is a correct outcome.

---

## 9. Most failure-prone part (call it out loud)

**The dedup / collision detection keys on `source_ref` being stamped uniformly by every
producer — and today it isn't.** The confirmed gap is the Recipe-Engine monthly push
(`asana_push.py:340`, name-match, no `place_task`). If a producer skips the key, the
Director silently misses that collision — reintroducing the exact "found one review at a
time" failure it exists to end, just relocated.

**Mitigations, both mandatory:**
1. `source_ref` as an enforced precondition (Phase-E prerequisite).
2. **Fail-loud on unknown**, mirroring `job_worker`'s dispatch discipline
   (`job_worker.py`, the `else` that *fails* an unroutable job type rather than ignoring
   it). A new producer / status / job type that the read model doesn't recognize must
   surface as an explicit "unwatched seam" flag, never be silently skipped — otherwise the
   Director rots as the suite evolves.

---

## 10. What this explicitly does NOT do (anti-scope)

- **No scheduling authority.** It does not decide what the `gsc_scheduler` enqueues or in
  what order the `job_worker` claims. Lane + `scheduled_at` remain the mechanism.
- **No priority authority.** It does not reorder `reopt_planner` tiers, `autonomy_policy`
  outcomes, or `pm_assign` rankings. It escalates conflicts between them; it does not
  resolve them.
- **No new autonomous persona.** It is a read model + reversible reconciler behind the
  SerMaStr seat, not a fifth login/auth surface.
- **No capacity reallocation of a human's work** without owner/PACE approval (until §8).
- **It is not a smaller SerMaStr or PACE.** SerMaStr reasons about *SEO strategy* per
  client; PACE coordinates *delivery* on the board; the Director observes *the whole system
  of agents* and explains/reconciles the flow between them. Distinct altitude, distinct
  scope.

---

## 11. Open questions (for the owner)

1. **Seam thresholds.** Default *N* days for each §4 predicate (suggest: `qa_idle` 7d,
   `strategist_approved_unplaced` 3d, `autonomy_proposed_unactioned` 7d,
   `content_shipped_degraded` immediate). Confirm at build.
2. **Digest cadence & channel.** Daily reconciliation line into the existing owner/PACE
   digest, or its own weekly "operations flow" summary? (Leaning: ride the existing daily
   digest; a separate weekly narrative only if the daily line proves noisy.)
3. **Duplicate-task auto-merge.** Ship the reversible merge in Phase 1, or start with
   *flag-only* (open a task naming both) and add the merge once `source_ref` uniformity is
   proven live? (Leaning: flag-only first — the merge is only as safe as the key.)
4. **Pre-flight autonomy veto.** In scope for Phase 1, or hold until autonomy content-gen is
   live more broadly? (Leaning: hold — autonomy is a narrow safe-slice today; the veto
   guards a collision that hasn't occurred.)

---

## 12. Summary

Build the **eyes** — a deterministic cross-agent read model plus a conversational Director
of Operations surface through SerMaStr — because the insight into how work flows is real,
independent value, and it catches the one live coordination gap (QA idle) today. Withhold
the **hands** — scheduling, priority, and capacity arbitration — because the incident
record (two failures, neither an arbitration failure) cannot justify authority over three
tested precedence engines, and because an observer that doesn't act is one you can trust as
a mirror. Grow it inside PACE's existing watcher first (Phase 1 / D), on a hard `source_ref`
foundation (E), and graduate it to its own subsystem only when the collision surface is
actually exercised (§8).
