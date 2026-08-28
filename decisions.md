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
