# Social P4 — Autonomy (Social Manager orchestrator + integration + QA) — Build Plan v1.0 (agreed scope)

> The **agreed** build plan for P4, the module's autonomy phase (ADR-0003). Records the
> owner rulings taken 2026-09-19 via AskUserQuestion and turns them into a concrete,
> phased build. Analytics read-back is **deferred** (owner ruling Q5 — the provider can't
> supply engagement metrics; see below). Discuss-first: this doc is the review artifact —
> nothing is built until the owner green-lights the phasing.
>
> Read alongside: `../social-media-module-prd-v1_0.md` §10/§12/§13 (the endgame),
> `../../adr/0003-social-autonomy-is-a-domain-executor.md` (the disposition ruling),
> `p3-manager-plan-v1_0.md` (the cadence/drip/policy this layers on), and the built
> `services/social/{schedules,policy,fanout,creator,budget}.py`.

## Owner decisions (locked 2026-09-19)

| # | Fork | Answer |
|---|---|---|
| **Q1** | P4 build scope | **Full P4** — the Social Manager orchestrator loop + graduated approval + agent integration (SerMaStr/PACE/DORA) + the opt-in QA rubric. **Analytics read-back DEFERRED** (Q5). |
| **Q2** | Autonomy ceiling | **Generate + auto-queue.** `autonomy_tier` gates the *generative* half (produce drafts; at a higher tier auto-*queue* them); P3's existing gates still govern the unattended *publish*. |
| **Q3** | Source selection | **Hybrid** — prefer the client's recent content (blog runs + saved Local SEO pages), fall back to the Social Policy topic bank when content is exhausted/stale. |
| **Q4** | Generation trigger | **Both** — a weekly baseline pass PLUS empty-queue top-ups when a platform's approval queue runs dry before its next cadence slot. |
| **Q5** | Analytics source | **Defer analytics entirely this build.** PostForMe exposes no analytics/insights endpoint (all 13 endpoints are posting/accounts/results/webhooks); the PRD's "analytics reads 1 credit/call" was a PostPeer assumption killed by the ADR-0006 swap. Analytics becomes its own later slice once a metric source (own-account Apify vs. status-only) is chosen. |

## What P4 is (and what it is NOT)

**Is:** a headless, per-client **Social Manager orchestrator** — a NEW loop that *calls* the
shared autonomy primitives (`autonomy_policy.classify`, the social `budget.reserve`
fail-closed meter, freeze, the DORA pre-flight veto) rather than extending the SEO
executor. Per ADR-0003 the SEO executor's `gather_candidates` is **remediation-reactive**
(nothing unless a goal is behind); social is **cadence-driven and generative**, so the
candidate loop is genuinely new code. It reads the Social Policy + per-platform cadence +
current approval-queue depth + competitor signals → plans a period → dispatches the
existing Creator (fan-out) to PRODUCE per-platform drafts → (at tier 2) auto-queues them →
writes a ledger + owner digest. Not a new conversational persona; it stays legible through
SerMaStr/PACE/DORA.

**Is NOT:** a new posting path, a new budget, or a new publish gate. Publishing continues
to run through P3's drip (`schedules.enqueue_due_social_schedules` → `publish_existing_draft`),
governed by the P3 gates. The orchestrator never itself calls the provider — it stops at
producing/queuing drafts. Auto-publish-without-`auto_fill` (a true tier-3 behavior) is
**out of scope** this build.

## The tier & gate model (the safety crux)

`social_policy.autonomy_tier` (already in the P0 schema, default 0) drives a ladder, reusing
`autonomy_policy.classify` verbatim (the ladder falls straight out of it):

| Tier | The orchestrator's behavior | What still requires a human |
|---|---|---|
| **0** | Off — the loop does nothing for this client. | Everything (today's behavior). |
| **1** | **Generate → `ready`.** Produces per-platform drafts into the Drafts tab; budget + freeze gated. | Approve → enqueue → publish (all human). |
| **2** | **Generate → auto-`queued`.** Additionally marks its own draft `queued` (its machine-approval). | Nothing *extra* to reach the queue — but the queued draft only PUBLISHES if the client separately set the schedule's `auto_fill=true` **and** `social_auto_publish_enabled` is on (P3). Else it sits in the queue for a human. |

Two independent **global** clamps keep the whole loop dark by default:

1. **`social_enabled`** (already on in prod) — the module gate.
2. **`social_autonomy_enabled`** (NEW config, **default False** — ships dark; **independent of
   the SEO `autonomy_enabled`** so enabling one never enables the other).

**The composite gate for an AI-produced, never-human-seen post to publish unattended** is
therefore **all four**: `social_autonomy_enabled` (global) **+** `social_policy.autonomy_tier ≥ 2`
(client opt-in to auto-queue) **+** schedule `auto_fill=true` (P3 per-platform opt-in) **+**
`social_auto_publish_enabled` (P3 global). Four independent opt-ins — this *is* the ADR's
"top-tier + explicit per-client opt-in only, never a default." A tier-2 client with `auto_fill`
**off** gets auto-queued drafts that a human still publishes — safe.

New `autonomy_policy.ACTION_TIERS` entries (keep the SEO scheme's grain — owned/reversible = 1,
owned content = 2):
- `generate_social_drafts` → **1**
- `queue_social_draft` → **2**
- `publish_social_post` → **3** (registered for completeness; **NOT executed this build** —
  the loop never publishes; publish stays P3's job. Reserved so a future tier-3
  auto-publish-without-`auto_fill` slots in cleanly.)

The loop's own minimal auto-execute allowlist (mirrors the SEO executor's `AUTO_EXECUTE`
clamp) = `{generate_social_drafts, queue_social_draft}`. Everything else a period-plan might
surface is **recorded as a proposal**, never run — widen only after a pilot reads the ledger.

`autonomy_policy.effective_tier(client_tier, cap)` is reused with a social cap of **2** this
build (tier 3 can't auto-run), independent of the SEO `autonomy_max_tier`.

## Budget (reuses the built social meter — no new infra)

Spend is gated by the **existing** social meter (`services/social/budget.py`): a per-client
**monthly USD** meter (`social_usage.spent_usd` vs `social_policy.monthly_ceiling_usd`, default
$100), fail-closed. Per generated draft the loop reserves the per-image cost
(`image.select_image_model` → ~$0.10 Nano Banana 2) via `budget.reserve` **before** the fan-out
image call — which the fan-out path *already* does per image, so the orchestrator just runs
inside that same metered path. `autonomy_policy.classify(budget_left=…)` is fed
`budget.remaining(ceiling, spent)` as the **advisory** pre-filter; `budget.reserve` remains the
atomic spend gate (a classify `auto` verdict is necessary, not sufficient — same invariant as
the SEO executor). A refused reservation downgrades the candidate to a proposal. **NOT the
Recipe-Engine/`autonomy_budget` meter** — social content production is metered separately (PRD §11).

## Source selection — hybrid (Q3)

The Creator needs a Source. The orchestrator picks one autonomously, per platform, per cycle
(pure `select_source`, unit-tested; the impure reads are a thin shell):

1. **Recent client content, freshest-first, not-recently-used** — completed blog `runs`
   (via `illustration._load_article`) + saved `local_seo_pages` (`content_html`/`page_title`).
   "Not-recently-used" = not the source of a social draft created in the last
   `social_autonomy_source_cooldown_days` (config, default 30), read from `social_drafts.source_ref`.
2. **Fallback → the Social Policy topic bank** (`allowed_topics`) — when the client has no
   eligible fresh content (new client, or all recent content already repurposed inside the
   cooldown), the loop drives angles straight from a rotated `allowed_topics` entry (a topic
   Source, no source article). `blocked_topics` filters both paths.

The chosen Source + Angle then go through the **existing** `creator.propose_angles` /
`fanout.enqueue_fanout` path unchanged — the orchestrator is a caller of the built Creator, not
a reimplementation. Competitor signals already ground `propose_angles` (P1), so "reads
Competitor Signals" (PRD §10) comes for free.

## Trigger — both (Q4)

1. **Weekly baseline pass** — `enqueue_due_social_autonomy_runs()` on the shared
   `gsc_scheduler` daily block, firing on `social_autonomy_weekly_weekday`, one
   `social_autonomy_run` job per opted-in (tier > 0) client not run within the last week
   (self-clocked off the ledger, mirroring `enqueue_due_autonomy_runs`). No-op while
   `social_autonomy_enabled` is False.
2. **Empty-queue top-up** — folded into the P3 sweep's existing `empty` branch
   (`schedules._fire_slot`): when a due `auto_fill` slot finds **no queued draft**, instead of
   only emitting the `social_slot_empty` nudge, enqueue a **targeted** `social_autonomy_run`
   (scoped to that one client+platform) so the loop fills the slot ahead of the next tick.
   Still gated on the client's tier + `social_autonomy_enabled`; if the loop can't fill it
   (tier 0 / disabled / budget), the nudge still fires. This turns "your slot is empty" from a
   reminder into an auto-fill for opted-in clients.

## Data model

- **Migration — `autonomy_runs.domain`** (`text not null default 'seo'`). One ledger for both
  domain executors; social runs write `domain='social'`. DORA's `prov_autonomy` already reads
  `autonomy_runs` — it becomes domain-aware (split the surfaced counts by domain) so social
  proposals appear in DORA for free without a second table. Chosen over a separate
  `social_autonomy_runs` table (keeps DORA/legibility unified; a nullable `goal_snapshot` holds
  the social period-plan snapshot instead of SEO goals).
- **Migration — `async_jobs` CHECK** widened (rebuilt from the **LIVE** constraint) to add
  `social_autonomy_run`.
- **No `social_policy` schema change** — the planning fields (`autonomy_tier`, `allowed_topics`,
  `blocked_topics`, `tone_prefs`, `competitor_focus`) already exist from P0; P4 only opens the
  write path to them.
- **No `social_drafts` change** — `status`/`angle_set_id`/`source_ref` already carry everything
  (a `queued` status already exists from P3; orchestrator-produced drafts are marked with a
  provenance flag in `platform_metadata`, e.g. `{"produced_by":"autonomy"}`, so the Drafts tab
  can badge them — free-text jsonb, no migration).
- **QA:** reuse the built `qa_reviews` table + `qa_review` machinery (see QA section) — no new
  table.

## The orchestrator loop — `services/social/manager.py` (NEW)

Structure mirrors `autonomy_executor.py` (pure core + thin impure shell), but the candidate
gathering is cadence/generative, not goal-reactive:

```
run_social_autonomy_for_client(client_id, *, trigger, platform=None, today=None):
  1. gate    — social_enabled AND social_autonomy_enabled AND effective_tier(policy.autonomy_tier, cap=2) > 0
  2. read    — policy (tier, topics, tone, competitor_focus), active auto_fill schedules,
               per-platform queue depth (count of `queued` drafts), recent draft sources
  3. plan    — plan_period (PURE): per platform with an active cadence, target queue depth =
               `social_autonomy_target_queue` (config, default 2). For each platform under
               target → a generate candidate {action:"generate_social_drafts", platform,
               cost_usd, requires:"none"}. (Empty-queue trigger scopes to one platform.)
  4. source  — select_source (hybrid, above) → Source + Angle for the batch
  5. decide  — classify each candidate (effective tier, social budget_left, freeze, weekly
               content cap) → auto | propose | escalate
  6. act     — for an AUTO generate candidate: reserve budget → dispatch the existing fan-out
               (produces the draft(s)); then, per produced draft, classify a
               {action:"queue_social_draft"} candidate — AUTO (tier 2) → mark the draft
               `queued`; else leave `ready`. DORA veto runs before the reserve (fail-open).
  7. record  — write the autonomy_runs ledger (domain='social') + emit `social_autonomy_run`
               notification (owner digest: produced N, queued M, proposed K).
```

Freeze is enforced **inside** the run (a client frozen between enqueue and execution produces
nothing) — `social_autonomy_run` is deliberately NOT added to `FREEZE_GATED_JOB_TYPES` (same
pattern as `social_fanout`, so a mid-flight freeze can't orphan drafts). Best-effort throughout:
any per-step failure degrades to observation, never raises into the scheduler.

The weekly content rate cap (`autonomy_policy.CONTENT_ACTIONS`/`content_cap`) applies to
`generate_social_drafts` via `social_autonomy_max_per_week` so a misconfigured cadence can't
mass-produce.

## QA rubric — the opt-in social gate (PRD §9)

- **`qa_signals.RUBRIC_SOCIAL`** + a `qa_service` social-draft review path
  (`review_social_draft(draft_id)`), checking exactly §9's list: **voice pass** (reuse the
  voice-card scorecard the Creator already runs), **has-CTA**, **platform constraints** (reuse
  the built `publish.validate_post` / Platform-Spec validator), **no banned claims** (reuse
  `content_compliance.scan_text` where the client is regulated + a banned-terms net), **image
  present** (per the platform spec). Deterministic verdict (the LLM only phrases findings),
  mirroring the existing QA agent's discipline.
- **Trigger:** opt-in per client via a new `social_policy.qa_gate` (boolean). When on, the
  orchestrator (and the manual approve path, `fanout.publish_existing_draft`/the draft-publish
  route) runs the social rubric **before** a draft is auto-`queued`/published; a **critical**
  fail blocks the auto-queue (leaves the draft `needs_revision`, emits `social_qa_failed`) and
  a human decides. Off (default) → today's behavior, no QA call. This is a draft-scoped review
  (social drafts aren't native tasks), so it does not ride the task-board `in_qa` flow.

## Agent integration (PRD §12)

- **SerMaStr** — a `social` context provider: `slack_assistant/context.py::_ctx_social`
  (per-client: scheduled/published posts, queue depth, latest competitor signals, autonomy tier
  + last run) + `strategy_digest.py::_prov_social` (so a strategy review can *propose* a social
  push — never publish). Each isolated + best-effort per the provider contract (empty → None).
- **PACE** — a `task_producers.on_social_*` producer: an "approve this week's social calendar"
  task (`source="social_calendar"`, one per client per week, idempotent) and, when the QA gate
  or a proposal needs a human, a "review N generated social drafts" task. Follows the
  `_create(source, source_ref)` pattern.
- **DORA** — `domain`-aware `prov_autonomy` (split SEO vs social) + a new social seam
  (`providers.prov_social` + a seam predicate): **approved-but-unqueued drafts** aging past a
  threshold, **idle connected accounts** (a connected account with no post in N days), and the
  loop's proposals. Read-only legibility (opens a `director_seam` task like the other seams);
  no new authority.
- **QA** — the rubric above; DORA/PACE surface a failed social QA the same way they surface
  other QA verdicts.

## Frontend

- **Settings tab (`SocialCompose.tsx`)** — extend the Policy editor with the P4 planning
  fields: an **Autonomy tier** selector (0/1/2 with plain-language labels for each rung), an
  **allowed/blocked topics** editor (the topic bank), **tone prefs**, **competitor focus**, and
  a **QA gate** toggle. Wired through the widened `policy.upsert_policy` write path.
- **Drafts tab** — orchestrator-produced drafts badged (`produced_by:autonomy`) with their
  Source + Angle, so a human reviewing the queue sees what the loop made and why.
- **An autonomy activity view** — a compact per-client read of recent `social_autonomy_run`
  ledger rows (produced/queued/proposed + cost), mirroring the SEO autonomy digest surface.
- `errorGuidance.ts` — codes for the new failure paths (`social_qa_failed`,
  `social_autonomy_not_enabled`, budget/tier refusals surfaced as friendly text).

## Config (all new, working defaults; nothing spends until flipped)

`social_autonomy_enabled` (False — the loop kill switch) · `social_autonomy_weekly_weekday`
(e.g. Wed) · `social_autonomy_target_queue` (2 — desired queued-draft depth per platform) ·
`social_autonomy_max_per_week` (content rate cap) · `social_autonomy_source_cooldown_days` (30)
· `social_autonomy_cap_tier` (2). No new env, no new vendor — copy/angles reuse
`ANTHROPIC_API_KEY`, images reuse `GEMINI_API_KEY`, spend rides the existing social meter.

## Build phases (each a fresh branch off latest `main` + a draft PR)

**A — Policy planning fields + tier plumbing (foundation). ✅ BUILT (PR #1240).** Opened the
`social_policy` write path to `autonomy_tier`/`allowed_topics`/`blocked_topics`/`tone_prefs`/
`competitor_focus` (`policy.py` `_EDITABLE` + validation) + the Settings-tab UI. Added the three
`ACTION_TIERS` entries + the `social_autonomy_enabled`/cap config. Migration `20260919120000`:
`autonomy_runs.domain` + the `social_autonomy_run` async-job type. (`qa_gate` deferred to Phase C
with the rubric that consumes it.) No loop. Pure + wiring tests.

**B — The orchestrator loop. ✅ BUILT (PR #1240).** `services/social/manager.py` (pure
`plan_batches` + `platform_deficits` + `select_source` + `filter_candidates` + `compose_angle`;
impure shell dispatching the built fan-out, auto-queue at tier 2, budget-advisory/freeze gates,
shared `autonomy_runs` ledger + digest). Both triggers: `enqueue_due_social_autonomy_runs` on the
scheduler weekly + the empty-queue top-up folded into the P3 sweep's `empty` branch (deduped via
`_in_flight_run`). `auto_queue`/`produced_by` threaded into the fan-out job (additive; default
off = manual behavior). `social_autonomy_run` job + `job_worker` dispatch. Ships dark behind
`social_autonomy_enabled`. Pure-core + gate/decision + fan-out-wiring unit tests.

> **Deviation (deliberate):** the **DORA pre-flight veto is NOT wired** in v1. It's
> keyword-collision-based (`director_veto.preflight_conflict` matches a candidate's *keyword*
> against in-flight jobs/tasks/interventions); a social generate candidate carries no keyword
> target, so the veto is a guaranteed no-op. Wiring it would be a guard that does nothing —
> deferred until social candidates gain a target. (The plan listed it as a reused primitive;
> the other primitives — `classify`, the fail-closed budget meter, freeze — are all wired.)

**C — QA rubric. ✅ BUILT (PR #1240).** `qa_signals.RUBRIC_SOCIAL` + `check_social_draft`
(voice / banned-claims / CTA / platform / image, folded by the shared `build_verdict`; the
voice + claims keys added to `CRITICAL_CHECK_KEYS`) + `services/social/qa.py` (the
deterministic orchestration reusing `voice_forbidden_hits` / `content_compliance.scan_text` /
`validate_post` / `has_cta`). Per-client opt-in via `social_policy.qa_gate` (migration
`20260919130000`, applied live). **Auto-queue gate**: `run_fanout_job` runs the rubric before
auto-queuing (tier 2) and holds any non-pass/advisory draft at `ready` (+ a `social_qa_failed`
digest). **Manual-publish gate**: `publish_existing_draft` blocks a CRITICAL fail (a
guide-forbidden voice term or a banned regulated claim) with a `force_qa` override; other
misses are advisory (owner ruling 2026-09-19). Settings `qa_gate` toggle + Drafts QA badge +
"Publish anyway" override + `errorGuidance`. 168 social+QA tests pass.

> **Deviations (both deliberate, surfaced to the owner):** (1) `qa_reviews.task_id` is
> `NOT NULL references tasks(id)` — a social draft isn't a task, so the plan's "reuse
> `qa_reviews`" was infeasible; the verdict is persisted on **`social_drafts.qa_verdict`**
> (a migration column) instead — cleaner + isolated. (2) The manual-publish gate blocks on a
> **CRITICAL fail only** (owner ruling): platform/char/image-required are already hard-blocked
> by `validate_post`; adding the voice + banned-claims block closes the real gap that social
> manual publish had no voice/claims guard, without blocking a human on a CTA nitpick.

**D — Agent integration + activity UI.** `_ctx_social`/`_prov_social`, the DORA `domain`-aware
autonomy split + `prov_social` seam, the PACE `on_social_calendar` producer, and the
frontend autonomy activity view + Drafts provenance badge.

(Analytics read-back is a **separate later slice**, gated on the Q5 metric-source decision.)

## Acceptance

- With `social_autonomy_enabled=false` (default) the module behaves **exactly** as today —
  the loop never runs, no scheduler work, no spend, byte-identical publish path.
- A tier-1 client with the loop on: a weekly/empty-queue trigger produces per-platform drafts
  to `ready`, budget-reserved, never auto-queued, never published; the owner digest names them.
- A tier-2 client with `auto_fill` **off**: same, but drafts land `queued` (a human publishes).
- A tier-2 client with `auto_fill` **on** + `social_auto_publish_enabled` **on**: the loop
  produces → auto-queues → P3's drip publishes on cadence — the full unattended path, behind all
  four opt-ins.
- The `qa_gate`-on path blocks an auto-queue on a critical rubric fail and routes it to a human.
- SerMaStr can *propose* a social push; DORA surfaces social autonomy runs + the social seam;
  PACE files the weekly calendar-approval task. None of them publish.

## Deferred (explicitly out of this build)

- **Analytics / performance read-back** (Q5) — no provider metric source; its own slice later.
- **Tier-3 auto-publish without `auto_fill`** — the loop stops at produce/queue; publish stays
  P3's gated job.
- **Own-account engagement scraping via Apify** — the candidate analytics source, decided later.
- **AI video** for Reels/Shorts (P5).

## Open items / risks

- **`autonomy_runs.domain` migration touches a shared table** — additive, defaulted, and DORA's
  reader is updated in the same phase; no other reader assumes single-domain.
- **QA on a draft, not a task** — the social rubric runs draft-scoped (drafts aren't native
  tasks). Confirm this doesn't need a `qa_reviews` shape tweak (it stores `entity_id`; a draft id
  fits) during Phase C.
- **Empty-queue top-up re-entrancy** — the top-up enqueue must dedupe against an in-flight
  `social_autonomy_run` for the same client+platform so a burst of due slots can't stack jobs.
- **The four-opt-in publish gate is easy to misread** — the Settings UI must state plainly that
  tier 2 alone does NOT publish; `auto_fill` + the global flag are still required.
