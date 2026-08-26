# Autonomous SEO Agent — SerMaStr Closed-Loop Mode — Module Plan v1.0

**Status:** proposal / decision doc. Nothing here is built. This plan exists so
the owner can react to the *design and the boundary* before any code lands,
because autonomy reverses two standing owner rulings (publishing-is-human;
confirm-gated spend) and acts on client money and client rankings.

**Position in the suite:** this is not a new agent. It is a **posture change**
to the two agents that already exist — SerMaStr (proposes) and PACE (executes) —
plus the specific missing muscle that lets their existing propose→approve→execute
loop run *on a clock, with humans in the loop by exception instead of per action*.

Read alongside:
- `docs/modules/seo-strategist-agent-plan-v1_0.md` — SerMaStr (the decider).
- `docs/modules/project-manager-agent-plan-v1_0.md` — PACE (the executor);
  §5 already defines the strategist→PACE handoff this plan makes autonomous.
- `docs/sops/_ORCHESTRATOR.md` §3/§6 — the halt-and-ask boundaries that stay
  hard-coded here, unchanged.

---

## 1. Purpose & position

Today the suite can *observe* a client's whole search picture, *decide* what
should happen (the strategist emits SOP-grounded proposals), and *execute* it
(PACE places an **approved** proposal on the board as skilled/eligible/least-loaded
work). The one thing standing between that and "SerMaStr handles the SEO for a
client against their goals" is the **human approval in the middle of the loop**,
plus a handful of commission actions the executor can't yet call.

Autonomy = **close the loop on the scheduler, per client, driven by that client's
`campaign_goals`, replacing the per-action human confirm with policy + budget +
exception-escalation guardrails.** ~80% of the machinery already exists; this
plan is mostly *wiring*, one *executor*, a few *commission actions*, and — the
hard part — the *guardrail and boundary decisions*.

### The loop (per client, on the shared scheduler)

```
        ┌───────────────────────────────────────────────────────────┐
        │  1. READ GOAL     campaign_goals (status computed on read) │
        │  2. DIAGNOSE GAP  strategy_digest + drop_classifier +      │
        │                   forecasting + competitor_intel + gsc_*   │
        │  3. DECIDE        strategist proposals + recipe_engine      │
        │                   budget allocation to deficiencies        │
        │  4. EXECUTE       commission actions, within budget +      │  ← the new muscle
        │                   policy (content runs, reopt, GBP posts,  │
        │                   citations, link tasks via PACE)          │
        │  5. MEASURE       response_episodes verify clock (2wk/6wk) │
        │                   + forecasting + goal status recompute    │
        │  6. ADJUST        goal moved? stop. Regressed / no move?   │
        │                   next lever, or escalate to a human       │
        └───────────────────────────────────────────────────────────┘
                    ▲                                    │
                    └────────── weekly / event-driven ───┘
```

Steps 1, 2, 3, 5 exist today. Step 4's *authority* and some of its *actions*, and
step 6's *autonomous adjust*, are what this plan builds.

### Decision record — why this is a posture change, not a new brain

- **Rejected: a second "omniscient" agent.** SerMaStr already decides and PACE
  already executes; a third agent would duplicate both. Autonomy is SerMaStr
  *driving PACE on a loop*, reusing PACE's already-built authorization model
  (`pace_auth`: `ActionContext`, role→action matrix, actor-bound confirms).
- **Rejected: flip one `autonomous=true` switch.** The owner flipped
  `strategist_enabled` only after a clean live gate run. Autonomy over client
  spend and client-site content is higher-stakes; it must roll out **graduated**
  (Tier 1→3, §3) with the same gate-run discipline, per-client opt-in.
- **Kept: proposes-never-executes stays true of the *reasoning*.** The strategist
  still reasons and proposes into `strategy_reviews`. Autonomy changes *who
  approves the proposal* (a policy engine within a budget, for scoped action
  classes) — not whether a plan is reasoned and recorded first. Every autonomous
  act still traces to a recorded proposal with its SOP citation.

---

## 2. Architecture

### 2.1 The autonomy executor (`services/autonomy_executor.py`, new)

A scheduled per-client `autonomy_run` async job that walks the loop:

1. Loads the client's goals (`campaign_goals.evaluate_goal`) → the objective set.
   **No `behind`/`overdue` goal ⇒ no interventions** (a healthy client is left
   alone; the executor is not a make-work engine).
2. Runs / reuses the latest strategist review (`strategist.run` or the last
   `strategy_reviews` row if fresh) → the candidate interventions, each already
   SOP-cited and tool-mapped.
3. Loads the Recipe Engine allocation (`recipe_engine.build_plan`) → the client's
   deployable budget and which deficiencies it funds, in client-type order.
4. **Filters proposals through the autonomy policy** (§2.2): keep only those
   whose action class is in-tier AND within remaining budget AND not in
   halt-and-ask territory. Everything else is left as a normal human-approval
   proposal (the current behaviour) — autonomy *narrows* what's auto-approved,
   it never *widens* what's allowed.
5. **Commissions** the surviving interventions (§2.3) — enqueues the real jobs,
   or hands the task to PACE for placement (§2.4).
6. Opens/refreshes `response_episodes` so the verify clock measures each act.
7. Writes an **autonomy ledger row** (what it did, why, which proposal, cost) and
   contributes to the daily owner digest.

The executor holds **no new intelligence** — it orchestrates existing services.
All reasoning stays in the strategist; all placement stays in PACE.

### 2.2 The autonomy policy engine (`services/autonomy_policy.py`, new, pure)

Pure, unit-tested decision layer — the heart of the safety model. For each
candidate proposal it returns `auto_approve | propose_to_human | escalate`, from:

- **Action class** vs the client's **autonomy tier** (§3). E.g. Tier 1 auto-approves
  `rebuild_action_plan`, `create_task`, `gbp_post_owned`, `schedule_scan`,
  `internal_report`; it does *not* auto-approve `publish_to_client_site`.
- **Budget**: the action's estimated cost vs the client's remaining autonomous
  budget for the period (§2.5). Over budget ⇒ `propose_to_human`.
- **Halt-and-ask** (`_ORCHESTRATOR.md` §3, inherited verbatim from the strategist,
  §3 below): manual action, deindexing, GBP suspension/duplicate, margin < 50%,
  separate-entity/DBA, disavow, any decision no SOP owns ⇒ `escalate`, never act.
- **Freeze**: a frozen client ⇒ observation-only; the executor does not run
  step 4 at all (Freeze Protocol already pauses *decide + output*).
- **Rate limits**: link/citation velocity caps, max autonomous content pieces per
  client per week — the SOPs' own guidance encoded as ceilings.

Pure `classify(proposal, tier, budget_left, freeze, rate_state) -> decision` so the
whole boundary is testable without I/O, the #751 / `recipe_engine` pattern.

### 2.3 Commission actions (new — the executor's hands)

The strategist/SerMaStr action registry can trigger *analysis* and edit *campaign
state* but cannot *commission deliverables*. New actions, each also usable
interactively behind reply-*yes* (so they exist before autonomy trusts them):

| Action | Wraps | Tier |
|---|---|---|
| `start_content_run` | `POST /runs` (Blog/Service/Local) | 2 |
| `generate_local_seo_pages` | `local_seo_service` bulk generate | 2 |
| `reoptimize_page` | blog/service/local/ecommerce reopt jobs | 2 |
| `schedule_gbp_posts` | `gbp_posts_service` (owned profile) | 1 |
| `build_citations` | citation task creation | 1 |
| `publish_to_client_site` | existing publish paths + voice/publish gates | 3 |

Every content action already passes through the **voice + quality + publish
gates** built suite-wide; autonomy adds no new content path, it only removes the
human *trigger* for scoped tiers.

### 2.4 Handoff to PACE (reuse, don't rebuild)

PACE §5 already turns an **approved** proposal into an auto-placed board task
(skilled/eligible/least-loaded, or held+flagged at capacity). Autonomy's only
change: the executor supplies the *approval* (policy-derived) for in-tier work,
so PACE places it without waiting on a human. Work PACE can't place (capacity) is
**held + flagged** exactly as today — autonomy never forces past a full team.

### 2.5 Read parity (prerequisite — the executor can't manage the unseen)

Six modules have no SerMaStr context provider today; an autonomous agent must see
all the work it might commission. One `_ctx_*` each (the #751 pattern):
Website Builder, Ecommerce, GBP Posts, native Task board, per-client LeadOff, and
an **outcomes/episodes** provider (surfacing `response_episodes` — the "did it
work?" signal step 6 depends on).

### Triggers (event-driven + a slow clock — never a tight always-on loop)

- **Weekly** per client on the shared scheduler (day after the strategist's
  weekly pass, so it acts on a fresh review), goal-gated (skip healthy clients).
- **Event:** a newly-`behind` goal, an opened drop/maps alert, a 6-week episode
  escalation — each can enqueue an off-cycle `autonomy_run` (same pattern as the
  existing `trigger="drop"` Action-Plan rebuilds).
- **Never** a sub-hourly poll. Autonomy is deliberative and budgeted, not reactive
  spam.

---

## 3. The autonomy boundary — the central decision (Tiers)

Per-client opt-in, set on the client (`clients.autonomy_tier`, default `0` = off =
today's fully-human behaviour). Higher tiers include lower.

- **Tier 1 — owned & reversible (recommended v1 default when enabled).**
  Auto-acts only on cheap, reversible, agency-owned actions: rebuild plans, create
  & assign tasks, GBP posts to owned profiles, schedule scans/research within
  budget, internal reports. Anything client-site-facing or irreversible still
  proposes for human approval. **Lowest risk; still meaningfully autonomous** (it
  keeps the board full and the local signals fresh against goals with zero
  unreviewed public output).

- **Tier 2 — drafts + owned content.** Tier 1 plus autonomously *generating*
  content and reoptimizations into **drafts** and owned properties (Website
  Builder, Syndication). Publishing to the client's live site still human.

- **Tier 3 — full auto-publish.** Fully autonomous including publishing to client
  sites, behind the existing voice/quality/publish gates. Highest leverage,
  highest brand/Google risk. Per-client opt-in only, after a per-client trust
  period.

**Open decision (this doc's reason for existing):** which tier is v1's ceiling,
and whether Tier 3 ships at all in v1. **Recommendation: build Tiers 1–2, ship
enabled at Tier 1 for one pilot client after a gate run, hold Tier 3 behind a
separate later decision** once the audit trail shows the policy engine and budget
governor behaving. This mirrors how `strategist_enabled` was flipped only after a
clean live run.

---

## 4. Guardrails — what replaces each human confirm

Autonomy removes gates the owner chose; each needs a deliberate, mostly-already-built
replacement.

1. **Spend governor.** Per-client monthly autonomous budget = the Recipe Engine's
   already-computed **deployable $**, enforced as a hard ceiling in the pattern of
   `outreach`'s `spend_denial` (the safe path is what you get by omission; spend
   additionally requires headroom). Exhausted ⇒ the loop *proposes* instead of
   acting. A per-client `autonomy_spend` ledger, mirroring `leadoff_spend`.
2. **Publish policy.** The single highest-stakes gate. Tier 1–2 never auto-publish
   to a client site; Tier 3 does, behind the built voice + quality + publish
   gates (a critical voice violation is non-overridable there already). This is
   the reversal to make *consciously*, per client.
3. **Freeze kill-switch.** Freeze Protocol already halts all output on manual
   action / deindexing. Kept unchanged as the circuit breaker; a frozen client
   drops to observation-only.
4. **Policy boundary = the SOPs.** SOP-grounding (already mandatory in the
   strategist) becomes *enforced* here: no-SOP decisions escalate, link/citation
   velocity is rate-limited, senior/passthrough territory (`sanitize_review`'s §3
   `requires=senior`) escalates and is never auto-approved.
5. **Audit + daily "what I did and why".** Every autonomous act is a ledger row
   with its proposal + SOP citation + cost, reversible by default, and rolled into
   a once-daily owner digest (the PACE digest pattern + atomic `dedupe_key`).
6. **Escalate by exception, not per action.** Human-in-the-loop fires on:
   ambiguity, senior-territory, budget exhaustion, or a goal *regressing* after an
   intervention — reusing the existing episode + sitewide-decline escalation hooks.

---

## 5. Data model & config

**Schema (additive):**
- `clients.autonomy_tier smallint not null default 0` — per-client opt-in.
- `autonomy_runs(id, client_id, trigger, goal_snapshot jsonb, decisions jsonb,
  actions_taken jsonb, cost_usd, created_at)` — the ledger (RLS on, service-role).
- `autonomy_spend(day date, client_id, spent_usd)` + a `reserve_autonomy_spend`
  RPC — the per-client budget meter (mirrors `leadoff_spend`).
- Widen `async_jobs.job_type` with `autonomy_run`.
- Reuse `campaign_goals`, `strategy_reviews`, `monthly_task_plans`,
  `response_episodes`, `client_freezes` unchanged.

**Config (`config.py`) — build-ready:**
```
autonomy_enabled: bool = False              # AUTONOMY_ENABLED — master gate
autonomy_max_tier: int = 2                  # ceiling shipped in v1 (Tier 3 held)
autonomy_model: str = "claude-sonnet-4-6"   # the executor reuses strategist reasoning
autonomy_weekly_weekday: int = ...          # day after the strategist pass
autonomy_max_content_per_week: int = 3      # per-client rate ceiling
autonomy_link_velocity_cap: int = ...       # SOP-derived
autonomy_budget_source: str = "recipe"      # deployable $ from recipe_engine
```
Every layer best-effort + gated: `autonomy_enabled=false` ⇒ the whole loop is
dormant and behaviour is exactly today's.

---

## 6. Cost model

The executor itself is cheap (reuses the strategist's already-budgeted review;
one Sonnet reasoning pass reused, not re-run). The real spend is the **work it
commissions**, which is exactly the work a human would have approved anyway — so
autonomy doesn't add cost, it changes *who pulls the trigger*, hard-capped by the
per-client budget governor (§4.1). Net new API cost of the loop machinery: ~one
reused strategist digest + the policy pass (pure, $0) per client per week.

---

## 7. Phasing (guardrails before autonomy)

- **Phase 0 — read parity.** The six missing `_ctx_*` providers (§2.5). Makes
  SerMaStr a complete observer; useful on its own, zero autonomy risk.
- **Phase 1 — commission actions, interactive only.** The §2.3 actions behind
  reply-*yes*. SerMaStr becomes a *director of work* with a human still pulling
  each trigger. Proves the actions before autonomy trusts them.
- **Phase 2 — policy engine + budget governor.** Pure, unit-tested; no autonomy
  yet, just the decision layer + the `autonomy_spend` meter + the ledger.
- **Phase 3 — the executor at Tier 1.** Wire the loop; enable for **one pilot
  client** after a clean gate run (the `strategist_enabled` playbook). Owner reads
  the daily ledger digest; nothing public ships.
- **Phase 4 — Tier 2 (owned/draft content).** Widen the tier for the pilot once
  Tier 1 is trusted.
- **Tier 3 — separate later decision.** Only after the audit trail earns it.

---

## 8. Non-goals (v1)

- Auto-publishing to client sites in v1 (Tier 3 held for a separate decision).
- Autonomy over the human-passthrough classes (`_ORCHESTRATOR.md` §3) — ever.
- A tight reactive loop / sub-hourly polling.
- Replacing PACE's placement or the strategist's reasoning — both are reused.
- Cross-client autonomous budget reallocation (per-client budgets only in v1).

---

## 9. Open decisions (defaults chosen; flag to change)

1. **v1 tier ceiling** — Tiers 1–2 built, ship at Tier 1 for a pilot; Tier 3
   deferred. (This is the decision the doc was written to settle.)
2. **Budget source** — deployable $ from the Recipe Engine, or a separate,
   smaller explicit "autonomy budget" per client? (Default: Recipe deployable,
   capped.)
3. **Pilot client** — which client opts in first?
4. **Digest cadence/recipient** — daily to the owner only, or per-account-manager?
5. **Goal-less clients** — a client with no `campaign_goals` set: does the
   executor do nothing (recommended — no objective, no autonomous action), or fall
   back to the strategist's opportunity mining? (Default: nothing; goals are the
   mandate.)

---

## 10. What already exists to build on

- **Goals** (`campaign_goals`) — the objective function, status computed on read.
- **Diagnosis** (`strategy_digest`, `drop_classifier`, `forecasting`,
  `competitor_intel`, `gsc_research`, `rankability`) — the gap analysis.
- **Decision** (`strategist` proposals + `recipe_engine` budget allocation).
- **Execution + placement** (PACE §5 — approved proposal → auto-placed task).
- **Authorization** (`pace_auth`: ActionContext, role→action matrix, actor-bound
  confirms) — the model autonomy's policy engine extends.
- **Verify loop** (`response_episodes` — 2-week recheck, 6-week escalate).
- **Kill-switch** (Freeze Protocol).
- **Spend-governor pattern** (`leadoff_spend`, `outreach` `spend_denial`).
- **Scheduler + jobs** (`gsc_scheduler`, `async_jobs`).
- **Audit + digest** (`strategy_reviews`, activity feed, PACE digest + atomic
  `dedupe_key`).

The honest summary: autonomy is a **loop, an executor, a policy engine, a budget
governor, and a boundary decision** on top of components that already exist — not a
new intelligence. The risk is entirely in the guardrails and the tier boundary,
which is why they are the substance of this plan.
