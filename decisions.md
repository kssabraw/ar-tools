# decisions.md

A running log of open/pending product decisions to discuss, and settled ones with
their reasoning. Append new entries; don't edit or delete old ones.

Status legend: **OPEN** (needs an owner decision) · **DECIDED** · **DEFERRED**.

---

## QA Agent — auto-fix machine-generated fails (PR 3 of the QA improvement work)

**Status: OPEN** — scope parked for later discussion (owner, 2026-08-28). PRs 1 & 2 of the
QA improvement work shipped (auto-resolve suite deliverables; gate the paid visual check +
fold the nlp score — see PR #870). PR 3 is **not built** pending this decision.

**Context — what PR 3 would do.** Today a QA `fail` creates `Rework: <check>` subtasks for a
human (the self-closing rework loop). For deliverables the suite can regenerate, a fail could
instead enqueue the existing reoptimize job (deficiencies built from QA's failed checks) and
re-QA the result — no human in the loop. It would ride the autonomy rails that already exist:
`autonomy_policy.classify` (freeze/tier/budget/rate-cap in one pure call), `autonomy_budget.reserve`
(atomic spend gate), and the reoptimize jobs (`blog_reoptimize`, `local_seo_reoptimize_url`,
`ecommerce_reoptimize_url`).

**The blocking discovery — the "publish gap".** QA rubrics split by what they read:

- **Blog** (`blog_article`) reads the *generated artifact* — the run's `sources_cited` markdown.
  `blog_reoptimize` regenerates that artifact, so re-QA reads the new version and **the loop
  fully closes with no publish step.** Genuinely autonomous.
- **local_seo / ecommerce / website_page** read the **live URL**. Reoptimize updates the *stored
  draft*, but **republishing to the live site is human (Tier 3 auto-publish, deliberately held by
  the owner).** So auto-fix → re-QA on the live URL would re-read the *old* page and loop to the
  retry cap — the rewrite happens but never reaches what QA checks.

**The scope options (the OPEN decision):**
1. **Blog only (v1).** Only blog fails auto-fix; the loop fully closes without any publish. Page
   rubrics stay Rework-only until Tier-3 auto-publish is decided. Cleanest, no publish risk.
2. **Blog + hybrid pages.** Blog fully closes; for Local SEO/ecommerce/website a fail also
   auto-reoptimizes the draft, then creates ONE human "Republish the improved page" Rework task
   (machine rewrites, human clicks publish).
3. **All four incl. auto-republish.** Requires enabling Tier-3 client-site auto-publish, which the
   owner has explicitly held. Not recommended for v1.

**Decided sub-points (locked, to fold in whenever PR 3 is built):**
- **Retry cap = 2** autonomous reoptimize→re-QA cycles per task (counted from `qa_reviews`
  history), then fall back to human `Rework:` subtasks. (owner, 2026-08-28)
- **Gating (proposed default, confirm at build):** double flag `qa_enabled` AND a new
  `qa_autofix_enabled` (default False, ships dark); each fix classified through
  `autonomy_policy.classify` so it only auto-runs for a client opted into autonomy **tier ≥ 2**,
  with budget reserved via the governor and freeze-awareness for free; refusal / not-opted-in /
  frozen → human Rework subtasks.
- **Human deliverables stay Rework-only.** Guest posts / niche edits / citations / press releases /
  map embeds live on third-party sites the suite can't regenerate — never auto-fixed.

**What must be decided to unblock:** the scope option (1/2/3), and — if 3 — whether Tier-3
client-site auto-publish is unheld.

---

## Cross-agent orchestration — "Director of Operations" scope

**Status: DECIDED (framing) + DEFERRED (the arbiter)** — owner, 2026-08-28. Full spec:
`docs/modules/director-of-operations-plan-v1_0.md`.

**Context.** With SerMaStr (proposes) + PACE (executes) + QA (judges) + the autonomy
executor (dark) + producers all writing one task board, the owner asked for an orchestrator
"making sure they work in concert," refined to wanting a **Director of Operations** for
**insight into how work is flowing.** Three grounded discovery passes over the live code
found: no global cross-agent priority decider, no intake-time capacity arbitration
(placement is per-task only — `pm_assign.place_task`), and no cross-agent health monitor
(`orchestrator.py` is a content-run driver; `pm_signals`/`pace_episodes` watch the board,
not the seams *between* agents). The cross-agent **incident** record is thin: two real
runtime failures (WheelHouse autonomy×LocalSEO `location`; First Class Roofing content×brand-
guide race) — **neither an arbitration failure** — plus one live *gap* (QA armed-but-idle,
`is_work_item=False` checklists → auto-advance never fires). The imagined
strategist+autonomy+producer triple-collision **has never occurred** (agents haven't run
concurrently at scale); its guards are runtime-untested.

**Decided (locked):**
- **Build the eyes, defer the hands.** The Director is a **read-only cross-agent read model +
  reconciler**, surfaced conversationally through **SerMaStr** — *not* a fifth autonomous
  persona and *not* a scheduling/priority authority. Insight comes from the read model + a
  queryable surface; authority does not improve it and past a point degrades it (your view
  becomes "what the Director decided," not "what happened").
- **It never touches the three tested precedence engines** (`reopt_planner` tiers,
  `autonomy_policy.classify`, `pm_assign` holds). It observes their outputs and *escalates*
  conflicts as proposals to the owner/PACE; it does not arbitrate them.
- **Reversible-only autonomy:** emit a daily reconciliation digest line, answer questions,
  open a task/notification on a stalled seam, merge a duplicate task on a shared `source_ref`,
  and pre-flight-veto a single autonomy auto-exec (fail-*open* to "propose").
- **`source_ref` uniformity is a hard prerequisite** (the Recipe-Engine monthly push is the
  known gap — name-match, no stamp/place). Unknown seams must **fail loud** (mirroring
  `job_worker`'s unroutable-type discipline), never be silently skipped.
- **Phasing:** grow the seam predicates inside `pace_episodes`/`pm_signals` first (Phase 1 /
  catches QA-idle now); graduate to a distinct subsystem only on an observed trigger.

**Deferred (needs a trigger, not a date):**
- **Intake-time capacity arbitration** — the one place real authority might live. Unlocked
  only when `pm_assign` records `team_at_capacity` holds from ≥2 demand sources in one week
  (real intake contention). Until then, per-task placement + advisory slips/rebalance suffice.
- **D→B graduation** trigger: autonomy content runs against >5 clients/week, OR `qa_idle`
  clears (QA seam becomes load-bearing), OR the owner reconciles the same conflict twice.

**What must be decided to unblock the build:** the four §11 open questions (seam
thresholds; digest cadence/channel; duplicate auto-merge vs. flag-only; whether the autonomy
pre-flight veto is in Phase 1).

---

## Director of Operations — give it its OWN surface (DORA)

**Status: DECIDED** — owner, 2026-08-29. **Partially reverses** the 2026-08-28 entry above
(the "surfaced conversationally through SerMaStr — *not* a fifth persona" clause), on the
owner's own call while verifying the Phase 1 rollout. Built in PR #892.

**Context.** Once the Phase 1 read model was live, the owner's reaction to "ask SerMaStr about
cross-agent flow" was: *"I don't want to ask SerMaStr questions, this is supposed to be a
separate Director of Operations."* The as-shipped surfaces were a lens inside SerMaStr
(`_ctx_director` + portfolio block) plus autonomous outputs (`ops_seam`/`ops_digest`) that
landed in the **PACE** channel — nothing read as a distinct "Director." The owner wanted the
full PACE-parity treatment.

**Decided (locked):**
- **The Director gets its own conversational persona + surfaces**, named **DORA** (*Director of
  Operations, Reconciliation & Awareness* — owner-chosen from a shortlist). This reverses only
  the *surface/persona* clause of 2026-08-28.
- **The "build the eyes, defer the hands" framing is UNCHANGED.** DORA is still **read-only,
  answer-only** — no tools, no actions, no confirm machinery (contrast `pace_agent.py`). It
  never touches the three tested precedence engines, never reassigns/reschedules/resolves. The
  reversal is about *where you talk to it*, not what it can do.
- **Additive, not a rewrite.** The SerMaStr `_ctx_director`/portfolio lens stays; DORA is
  layered on top of the same `services/director/` read model. No new cross-agent logic.
- **Full own-app treatment** (owner asked for both, explicitly): (1) a dedicated `/director`
  web chat page (its own persona, indigo, reads the read model directly — SerMaStr not
  involved); (2) its own **#dora Slack app** — a distinct DORA bot identity on the seam-flag +
  weekly-ops-digest posts (`ops_seam`/`ops_digest` route to `director_slack_channel` under
  `director_slack_bot_token`), AND inbound chat in #dora (`/slack/director/events`, fail-closed
  on `director_slack_signing_secret`, **Socket Mode OFF** per the PACE gotcha). Safe fallback
  to the PACE channel/bot until #dora is provisioned.
- **Provisioning is owner-side** (nothing blocks the web page, which lights up on deploy since
  `DIRECTOR_ENABLED` is already true): create #dora + a DORA Slack app, invite it, set
  `DIRECTOR_SLACK_CHANNEL`/`_BOT_TOKEN`/`_SIGNING_SECRET` on PLATFORM.

**Not reversed / still deferred:** everything in the 2026-08-28 "Deferred" block (intake-time
capacity arbitration, duplicate auto-merge, the D→B graduation to a distinct read-model
subsystem). DORA is a surface over the existing read model, not the graduation trigger.

---

## DORA / Director of Operations — what's left to be a "live agent" (roadmap summary)

**Status: REFERENCE** (owner asked, 2026-08-29, to capture the scoping answer). Grounds in
`docs/modules/director-of-operations-plan-v1_0.md` §5/§7/§8/§10 — no new decision, a map of
what is/isn't left. **The load-bearing point:** "live agent" splits in two, and the read-only
one is essentially done. Plan §8, verbatim: *"If none [of the triggers] fires, Phase 1 (D) is
the whole build and that is a correct outcome."*

**A. Read-only DORA (what exists) is already a live agent — only activation remains, not new
modules.** It runs the daily reconcile, the weekly ops digest, opens/auto-closes board tasks on
stalls, and answers portfolio questions. Remaining to fully light it up:
1. DORA-code deploy goes active (in flight — Railway backlog draining).
2. Slack inbound smoke test (owner posts in #dora → DORA replies).
3. Confirm the first daily reconcile fires (~08:00 UTC) → the `qa_idle` `ops_seam`.
4. Calibrate the §4 seam thresholds from real data (§11 Q1; defaults shipped — `qa_idle` 7d,
   `strategist_approved_unplaced` 3d, `autonomy_proposed_unactioned` 7d,
   `content_shipped_degraded` immediate).

**B. An *acting* agent ("hands") is deliberately deferred and trigger-gated — NOT a build
queue.** Hard boundary (§5/§10): DORA never arbitrates priority, reassigns humans, or overrides
the three tested precedence engines (`reopt_planner` tiers, `autonomy_policy.classify`,
`pm_assign` holds) — it escalates conflicts as **proposals routed through PACE's actor-bound
confirm machinery**. The "hands" already live in PACE (executes) + autonomy (generates); DORA's
role is to *see and route*. Each remaining piece unlocks only on an observed event (§8):
- **Phase 2 (B)** — promote to its own read-model subsystem (a `director_seam_flags` table).
  Unlocks when: autonomy runs content on **>5 clients/wk**, OR `qa_idle` clears (QA becomes
  load-bearing), OR the owner reconciles the same cross-agent conflict **twice**.
- **Duplicate auto-merge** — today flag-only (opens a task naming both). Unlocks when
  `source_ref` uniformity is proven live (§11 Q3 held it flag-only on purpose).
- **Autonomy pre-flight veto** — built but ships **dark** (`director_autonomy_veto_enabled`
  off). Unlocks when autonomy content-gen runs broadly enough to risk a real collision.
- **Capacity arbiter** — the one place real authority might eventually live. Unlocks when
  `pm_assign` records `team_at_capacity` holds from **≥2 demand sources in one week**; even
  then it starts as a *proposer*, not an autonomous placer.

**Recommendation (owner-agreed direction 2026-08-29):** don't build any acting-agent scope
now. Finish A's four activation steps, run read-only for ~2 weeks, and let §8's triggers decide
what (if anything) to build next. The one thing worth watching regardless is **uniform
`source_ref` stamping across all producers** (§9's failure-prone seam) — E1 (fail-loud on
unknown `source`) + E2 (Recipe-Engine monthly push now routes through `pm_assign.place_task`)
in #885 closed the known gap, but it's what would quietly degrade DORA's collision detection as
the suite grows.

---

## SerMaStr — autonomous recovery plans for chronically-behind goals

**Status: DECIDED** (owner, 2026-09-02, grilling session). PRD:
`docs/modules/sermastr-autonomous-recovery-plans-prd-v1_0.md` (full 20-ruling log in §11).

**Context.** Every scheduled strategist review from 2026-07-14 to 2026-09-01 emitted 0 proposals
while the assessment called First Class Roofing's local-pack goal a critical emergency; the
owner had to extract a recovery plan by chat. Measured root cause: the emit tool call is
truncated at `strategist_max_tokens`=4096 (findings are written before proposals), and the run
loop never checks `stop_reason` — portfolio-wide, not FCR-specific.

**Decided.**
- Ship the truncation fix as its own PR first (16k cap, proposals before findings in the emit
  schema, a `stop_reason` retry, a `truncated` flag rather than a silent `complete`).
- Then a dedicated `goal_recovery` strategist run, fired by the #949 escalation sweep on its
  14-day cadence, one per client, capped at 5 per daily tick; the finished run sends the one
  `goal_chronic` message carrying root cause + a costed, tiered, approvable plan.
- **Propose-only. No auto hand-off to PACE.** A human approves each proposal; only then does
  the existing approve → PACE path run. No autonomy guardrail is loosened.
- Unfundable work: proposals may reallocate this month's plan at proposal level (the stored plan
  is never rewritten), and over-budget work is offered as cumulative +25/+50/+100% tiers over
  deployable, computed deterministically. Budget is set only on the client card; the review row
  snapshots what the plan was costed against.
- Prior recovery proposals are superseded (own ledger value); the strategist card lists open
  proposals across 60 days / 5 reviews so a plan stays approvable after the next weekly review.

**Deferred.** A "Generate recovery plan" button (after the FCR validation run); raising
drill-down caps for recovery runs (only with evidence); per-goal runs.

---

## DORA — guide sync (DORA's one write)

**Status: BUILT** (owner ask 2026-09-02: "every time a module gets changes that affect the user
or output, DORA gets notified and updates the module's tutorial page if needed").

**Decided.**
- "Tutorial page" = the in-app **Guides** portal row for the module (`guides` table, the page
  an admin already edits in-app). The illustrated field guides and `docs/*.md` stay
  hand-maintained; DORA's #dora note is the cue to refresh them after a big change.
- Detection is deterministic and lives in the repo: a GitHub Actions run on every push to
  `main` maps changed files → modules → guide slug through `services/guide_registry.py`, and
  only user-facing code counts (tests/docs/CI/migrations/scripts/lockfiles never do).
- DORA judges "affects the user or output" from the diff + commit messages, and rewrites the
  guide only when the change is something a user would notice; internal changes are silent.
- **Auto-apply by default** (`guide_sync_auto_apply=True`): the rewrite goes live immediately
  with the prior body kept for a one-click **Revert** on the guide page; the flag flips it to
  propose-only (Preview / Apply / Dismiss). A deterministic sanity band gates every rewrite.
- **This is the one exception to "build the eyes, defer the hands"** and it is deliberately
  documentation-only: no board task, plan, assignment, or precedence engine is touched, and
  every write is reversible from the page. It does not widen DORA's operational authority.
- Fail-closed activation: the endpoint refuses everything until `GUIDE_SYNC_SECRET` is set on
  PLATFORM and mirrored (with `PLATFORM_API_URL`) as GitHub repo secrets.

**Deferred.** Updating the static field guides / long-form docs (would need a repo write path
from the platform, or a CI-side LLM pass — not worth it until the in-app sync proves accurate);
a per-guide "freeze" toggle to exempt a hand-curated guide from DORA's rewrites.

---

## GBP Profile Editor module

**Status: APPROVED FOR BUILD** (owner, 2026-09-04). PRD: `docs/modules/gbp-profile-editor-prd-v1_0.md`
(now Approved). The no-auto-apply divergence from GBP Posts is ADR
`docs/adr/0004-gbp-profile-edits-never-auto-applied.md`. Twelve decisions from the 2026-09-04
grilling session, folded into the PRD:

**Decided.**
- **Justification = absorbing manual GBP dashboard work** (editing description/services/hours by
  hand today). The `gbp_audit` "closed loop" is a genuine but NARROW bonus, not the reason — a
  code audit found only `description_quality` (built in #1009) and hours-missing map to a v1
  lever; category and review map to out-of-scope surfaces, and a "service gap" finding never
  existed. PRD §1 rewritten to say so; do not sell a four-way loop the diagnosis side can't feed.
- **All three fields ship, sequenced description → services → hours.** Hours is manual-only (the
  AI never drafts it, GBP-suspension risk) behind an extra "confirm the values you typed" step.
- **No auto-apply, ever, in v1** (ADR 0004) — the deliberate divergence from Posts (which allows
  opt-in auto-publish). Every edit is drafted → reviewed → applied on an explicit click.
- **Apply re-reads and diffs** against the draft snapshot; if the live value drifted out-of-band
  since drafting, it aborts into a `live_changed` re-review state rather than clobbering an unseen
  dashboard edit.
- **Pending-review reconciler built now** — a new `gbp_profile_sync` async job, self-continuing
  per-edit (the `leadoff_geocode` pattern, since the 30-min reaper forbids a sleep-poll), bounded
  backoff +2m/+30m/+2h/+12h/+24h → give up; terminal `applied`/`rejected`/gives-up-stays-
  `pending_review` (+ manual refresh). Distinct from the Phase-3 periodic drift sweep.
- **Per-location, one at a time** via the existing `RegisterLocations` picker. No bulk / no
  cross-location apply.
- **Strategist loop = BOTH a SerMaStr action (`update_gbp_profile`, staged + reply-yes) AND an
  Action-Plan producer** — but honest: both only STAGE a draft into the review queue, never apply
  (consistent with no-auto-apply + the strategist's propose-never-execute contract). The
  automatic producer fires on `description_quality` + hours-missing only; services has no auto
  trigger until a service-gap check lands.
- **Free-form services**, operator picks the `categoryId` per service from the listing's
  categories (Apply blocked until every service has one); for AI-drafted services the AI SUGGESTS
  a category and the operator confirms/overrides.
- **Services draft grounds on `clients.gbp` categories + silo plans** (best-effort/degrading).
  Keyword-research + page-inventory mining deferred to Phase 2.5.
- **A client-side content-policy linter for the description** (ALL-CAPS, promotional phrasing,
  URLs/phone, etc.) that is ADVISORY warnings only — never a gate. Google's `rejected` verdict +
  the reconciler stay the source of truth.
- Reuses the live GBP connection layer wholesale (verified against the code 2026-09-04, PRD §12):
  `gbp_auth` / `gbp_locations_service._build("mybusinessbusinessinformation", creds)` (the
  v1-hardcoded `_build`, NOT the performance-service one) / `gbp_locations` registry. `locations.get`
  and `locations.patch` are the genuinely new write path.
- The `gbp_audit` description-quality follow-up (the loop's real trigger) is **BUILT** — PR #1009,
  `description_quality: {ok, length, issues[]}`, wired into `reopt_planner.build_gbp_action`,
  `strategy_digest._prov_gbp_audit`, and the `MapsGbpAuditResponse` model.

**Deferred.** Structured services + AI-assigned categories; a real `service_gap` check in
`gbp_audit` (needs this module's live `serviceItems` read — building it earlier = a throwaway
capture path); categories + attributes editing; scheduled periodic drift detection; a Client
Report "profile updates" line + strategy-digest `gbp_profile` provider; keyword-research/
page-inventory grounding for the services draft (Phase 2.5).

