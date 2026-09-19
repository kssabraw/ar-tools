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
capture path); ~~categories + attributes editing~~ (now IN scope — see the 2026-09-09 expansion
below); scheduled periodic drift detection; a Client Report "profile updates" line +
strategy-digest `gbp_profile` provider; keyword-research/page-inventory grounding for the services
draft (Phase 2.5).

### Field-scope expansion (owner, 2026-09-09) — PRD bumped to v1.1

The owner expanded the editable-field surface beyond the original three (description / services /
hours, all built + merged dark in PR #1011). Recorded in the PRD's **v1.1 amendments block**
(authoritative on scope) and ADR 0005.

- **In scope now — the full editable set EXCEPT the NAP identity triplet.** Tiered:
  - **Tier A (same `locations.patch` endpoint):** `websiteUri`, `labels`, `specialHours`,
    `moreHours`, `serviceArea`, `openInfo` → **Phase 3a**.
  - **Tier B (category-gated reads):** `categories` (needs a `categories.list`/`batchGet` picker;
    consumes the existing `gbp_audit` `category_gaps` finding — so the loop's automatic reach
    grows) and `attributes` (the **separate** `getAttributes`/`updateAttributes` endpoints +
    category-scoped `attributes.list`) → **Phase 3b**.
  - **Tier C (media):** photos / logo / cover via the **v4** `accounts.locations.media` API (NOT
    `locations.patch`; mirror the GBP-Posts v4/httpx + image-upload pattern; own storage, not the
    `gbp_profile_edits` row; verify the media access grant on PLATFORM) → **Phase 3c**.
- **OUT — the NAP identity triplet** (`title` / `storefrontAddress` / `phoneNumbers`), deliberately
  held: editing these via API triggers GBP re-verification / suspension on established listings —
  the highest-blast-radius field group. **ADR 0005.** If ever revisited, it's a separate hardened
  flow (unverified block + typed-value re-confirm + likely owner-only), never a fold-in. (Owner
  picked **media only** from the two higher-stakes groups offered; NAP declined.)
- **No auto-apply still governs every new field** (ADR 0004, scope-extended). Extra
  "confirm-the-values" gate now also covers `serviceArea`, `openInfo` (`CLOSED_*`), a
  **primary-category** change, and a logo/cover media replace. The AI **never drafts** hours, a
  business closure, or a primary-category downgrade; it may *suggest* additional categories,
  service-area places, and applicable attributes (human confirms). `serviceArea` prefills from the
  already-captured `clients.gbp.service_area_places` / `clients.target_cities`.
- **Data model:** `gbp_profile_edits.field` widens (add `website|labels|special_hours|more_hours|
  service_area|open_info|categories|attributes`). **A migration IS required** — the live column
  has `check (field in ('description','hours','services'))` (verified 2026-09-09), so 3a/3b must
  drop/rebuild that CHECK. `media` is a distinct op, not a `field` value. New `ErrorDetails` codes
  per PRD §8 + the v1.1 block.
- **Process:** spec-first (owner choice) — PRD/decisions/ADRs updated before code. Build order
  3a → 3b → 3c.
- **Build status (2026-09-09): Phases 3a + 3b COMPLETE, shipped dark.** 3a (six Tier-A fields,
  migration `20260909120000`); 3b `categories` (#1044, migration `20260909130000`) + 3b
  `attributes` (migration `20260909140000`). `attributes` is the one field that does NOT ride
  `locations.patch` — the SEPARATE `getAttributes`/`updateAttributes` endpoint pair with a
  per-attribute `updateMask` (comma-joined `attributes/{id}`) and category-scoped `attributes.list`
  availability; the service branches read/write for it (`_run_apply_attributes`/`_run_sync_attributes`)
  but REUSES the `gbp_profile_apply`/`gbp_profile_sync` job types (no new async_jobs type). An
  attributes edit targets the changed SUBSET (mask names only those; a cleared attribute stays in the
  mask with an empty value); the `read_current` attributes read is best-effort. **The v1 attributes
  `updateMask` shape is flagged to re-verify live at activation.** Only **3c (media)** remains.

### "Missing elements" issue — Menu link (built) + Chat (not buildable) (2026-09-14)

Ryan Maizis logged "GBP Missing Elements": *(1) add Menu/Service, (2) add Chat.* Findings +
owner decision (via AskUserQuestion):

- **Chat — NOT buildable; nothing shipped.** Google **permanently discontinued** GBP
  chat/messaging on **2024-07-31** (new chats stopped mid-July 2024). There is no profile element
  and no API to re-enable it — it's a dead Google feature, not a gap in our tool. (Google's only
  pointer for eligible accounts is SMS/WhatsApp contact tied to the phone number, which isn't an
  API-settable profile field.) Reported to the owner; no code.
- **Services already shipped.** The **Services** card (structured + free-form) has been live since
  the 2026-09-09 enablement and is in production use — so "Menu/Service" is not a services gap.
- **"Menu link" — BUILT (a first-class `menu` field).** Owner ruling: add a dedicated **Menu link**
  URL card rather than relying on the generic Attributes card. In GBP's data model the menu link
  is the **`attributes/url_menu`** URL attribute, so `menu` is an **attribute-backed field**: it
  presents as a single URL string but rides the SAME separate `getAttributes`/`updateAttributes`
  endpoint pair as `attributes` (NOT `locations.patch`), reusing the existing `gbp_profile_edits`
  row / apply job (re-read-and-diff, scoped to *only* url_menu so unrelated attributes drifting
  never abort a menu edit) / reconciler / freeze gate / history / revert. **No new job type**
  (reuses `gbp_profile_apply`/`gbp_profile_sync`). Manual-only (not AI-draftable — a menu URL is a
  fact the operator supplies, like hours). Migration `20260914120000_gbp_profile_menu.sql` widens
  the `field` CHECK to add `'menu'` (applied live). `url_menu` availability is category-scoped —
  where a listing's category doesn't support it, Apply returns a **`rejected`** verdict (surfaced),
  never a silent bad write. **Structured Food Menus (v4 `FoodMenus`) deliberately NOT built** — a
  separate v4 surface, restaurant-only, and the agency has 0 food/restaurant clients.
- Ships dark under the same flags as the rest of the module (`gbp_api_enabled` +
  `gbp_profile_enabled`) — currently ON in production.


---

## Task board — dedicated "For Revision" status + QA routes complete fails to it

**Status: DECIDED** (owner, 2026-09-05).

**Context.** Admin analytics work added overdue-task + revision tracking (PR #1030).
Revision counting keyed on a `revision_status_key` — but the board had only "In Review"
(historically "client rejected → redo"), and the owner wanted a first-class, unambiguous
lane for rework so the reports (and the team) can see every deliverable being redone.

**Decisions.**
- **Add a dedicated `for_revision` board status** ("For Revision", category `in_progress`,
  non-initial/non-done, at the end of the row with Blocked / In Review). Migration
  `20260905193000_for_revision_status.sql`. `config.revision_status_key = "for_revision"`;
  each entry bumps `tasks.revision_count` (migration `20260905190000`).
- **It is used for BOTH triggers:** a **complete QA failure** OR a **client-requested
  revision**. Both are "a finished deliverable that must be redone", so one tracked lane.
- **Auto-route complete QA fails to For Revision.** `qa_fail_status` default repointed
  `in_progress` → `for_revision`. The `Rework:` subtasks QA writes stay (they ARE the
  precise what/why to revise). `for_revision` added to `task_service._AUTO_ADVANCE_FROM`
  (Rule B only) so the self-closing rework loop still fires from the new lane — ticking the
  last `Rework:` item re-enters In QA. ("Complete fail" = verdict == `fail`; `needs_human`
  is inconclusive and never routes here.)
- **Repurpose "In Review" as an INTERNAL review lane** (a teammate/lead checks the work
  before it goes to the client). The client-rejected-rework meaning moves to For Revision.
- **Precise revision details + a due date are a DOCUMENTED CONVENTION, not app-enforced.**
  A For Revision task should carry what to revise and why (QA fills this in as `Rework:`
  items; a human writes it for a client revision) and a revision due date (the Overdue and
  revision reports read the task's due date). No new validation gate.
- **Docs updated:** the task-manager user guide + manual, the PACE & QA user guide, the
  in-app-task-manager PRD, the QA agent manual + plan, and `CLAUDE.md`.
- **Future Inbox Agent (deferred):** when built, a client "revisions requested" reply routes
  into For Revision (not In Review) with the feedback + a due date.

---

## QA Agent — graduated verdicts (pass / advisory / revisions / fail)

**Status: DECIDED (owner, 2026-09-08). Built same day.**

The QA verdict was effectively binary (`pass` / `fail`, plus `needs_human` fail-open
and `skipped`). Owner asked for graduating degrees. The axis is **severity (the
nature of the failure), not count** — count was rejected because it inverts priority
(three trivial misses would escalate while one catastrophic miss — a wrong client
name — would look minor).

**The five tiers (best → worst): pass · advisory · needs_human · revisions · fail.**

- **advisory** — clean on every blocking check; only a non-blocking recommendation
  tripped. **Ships exactly like `pass`** (owner ruling: "ship it, just labeled") —
  advances when `qa_pass_status` is set, recommendations logged + badged, never a hold.
  (This surfaces what used to fold silently into `pass`.)
- **revisions** — a fixable, non-critical blocking failure. The pre-ruling `fail`
  behaviour: bounce to For Revision + `Rework:` subtasks + the self-closing re-QA loop.
- **fail** — a **critical** blocking failure OR the count safety net. **Escalates to a
  human and SKIPS the self-re-QA auto-loop** (owner ruling: "fail escalates / skips
  auto-loop") — no `Rework:` subtasks, a critical-severity notification; a person
  decides rather than the bot churning on a broken deliverable.

**Critical check set (owner: "keep as is"):** `client_name`, `nap`, `link_back`,
`map_embed`, `keyword_in_url` — the deliverable is for the wrong client / carries an
inconsistent NAP / lacks its backlink / lacks its map embed / needs a slug change
(a near-republish). Static + code-defined in `qa_signals.CRITICAL_CHECK_KEYS`; the
LLM never sets severity (same discipline as `blocking`).

**Count safety net (owner: "add the count net"):** even with no critical check, ≥
`qa_fail_count_threshold` (default 4) blocking fails → `fail`. Severity is the primary
signal; the net only catches a mostly-broken deliverable (in practice only the
website-page rubric has enough blocking checks to reach it on standard checks alone).
`0` disables it.

**Build:** `qa_signals.build_verdict` (verdict logic + `critical`/`escalated_by_count`
on the result) · `qa_service._apply_outcome` (revisions vs fail routing; critical-
severity notification for fail) · config `qa_fail_count_threshold` (4) +
`qa_fail_escalation_status` ("" = the revisions lane) · migration
`20260908120000_qa_reviews_graduated_verdicts.sql` widens the `qa_reviews.verdict`
CHECK (applied live) · frontend `QaPanel` badges + `QaReview.verdict` union · SerMaStr
`_ctx_qa` + the `qa_agent` chat persona include `revisions` in "needs attention".
Additive + backward-compatible: existing rows still satisfy the constraint; no data
migration.

**~~OPEN~~ RESOLVED follow-up (owner, 2026-09-08):** `visual_render` (a high-confidence
broken render — raw unstyled HTML / dead stylesheet) was **added to the critical set** —
a broken render needs a human to find out WHY it broke, not a VA ticking a rework item, so
it escalates (`fail`) rather than self-looping (`revisions`). `CRITICAL_CHECK_KEYS` is now
`client_name`, `nap`, `link_back`, `map_embed`, `keyword_in_url`, `visual_render`. The
high-confidence gate is unchanged (the qa_visual judge only bounces on high confidence; low
confidence / capture failure stays fail-open `needs_human`), so only a *confirmed* broken
render escalates.


---

## QA Agent — critical `fail` excluded from revision_count

**Status: DECIDED (owner, 2026-09-08). Built 2026-09-09.**

Follow-up to the graduated-verdicts entry above (which flagged this as an open,
discretionary behavior note). A critical `fail` lands in the For Revision lane by
default, and `task_service.update_task` bumps `tasks.revision_count` on any
transition into the revision status — so a QA-internal critical escalation was
inflating the client-facing "keeps missing expectations" counter the same as a
routine `revisions` bounce. Owner: exclude critical fails.

**Build:** `update_task` gained `bump_revision_count: bool = True` (default =
prior behavior); `qa_service._apply_outcome`'s `fail` branch passes
`bump_revision_count=False` when moving the task to the escalation status. A
routine `revisions` bounce still bumps (it's a real redo). Behavior change is
scoped to the QA critical-fail path only; every other `update_task` caller is
unchanged. Tests: `test_task_manager.py` (bump fires by default into
for_revision; suppressed with the flag). No migration, no API change.

## Brand Guide Generator — no headless browser for visual extraction (reverses PRD D4)

**Status: DECIDED** (owner, 2026-09-15, via the Brand Guide PRD design grill; recorded in PRD
`docs/modules/brand-guide-generator-prd-v1_0.md` §2 D4 / §4.1 / §8).

**Context.** The Brand Guide module needs a client site's visual identity — palette, fonts, type
scale, logo candidates — plus a screenshot for the aesthetic/"vibe" read. The PRD's original D4
chose a **hosted headless browser (Browserless over CDP)** to collect *true computed styles*
(cascade-resolved, area-weighted via `getBoundingClientRect`), on the reasoning that Chromium
shouldn't bloat any suite image at ~1–3 guides/month.

**Decision.** **No headless browser anywhere.** Capture instead reuses paths the suite already
runs in production:
- **Exact declared hex** parsed from CSS scraped via the existing **ScrapeOwl** path
  (`scrapeowl_fetch(url, render_js=True)`), **ranked/area-weighted by screenshot-pixel dominance**
  (Pillow quantization over the **DataForSEO `page_screenshot`** — the same screenshot path
  `qa_visual` already uses).
- Fonts / type scale / logo candidates from the same scraped HTML.
- The vibe read = one Claude-vision call over that DataForSEO screenshot (the established
  `qa_visual` pattern).

**Why (the real trade-off).** Three facts, verified against the live code during the grill,
removed every reason to add a browser:
1. **Visual extraction is a best-effort *garnish* layer** (owner ruling), not the module's value —
   the moat is the existing voice/ICP/differentiator assets. True computed styles don't justify
   new infrastructure for a garnish.
2. **Pixel-dominance over the rendered screenshot is a *truer* "what dominates the page" signal**
   than area-weighted computed styles, and exact hex still comes from the CSS (so JPEG/anti-alias
   drift never touches the reported numbers).
3. **The census machinery was never a drop-in reuse regardless.** `website_theme_precompile.py`'s
   `census_styles`/`TokenCensus` are count-only and hard-wired to the Claude-Design *upload*
   format (regex over inline `style=`), with no per-item weight seam — so a new weight-aware
   census had to be written whether the style data came from a browser or from scraped CSS.

Bundling Chromium into platform-api (~400MB, ~3× the `python:3.11-slim` image) hits every deploy
of the busiest service; Browserless adds an external vendor holding an API key, client-URL egress
to a third party, and a new point of failure — all for ~1–3 guides/month. The suite's own code
repeatedly documents the deliberate "no Chromium — heavy, memory-hungry, deploy-risky on Railway"
posture (`qa_visual.py`), and production already fetches arbitrary client sites (ScrapeOwl, QA's
SSRF-guarded httpx, DataForSEO screenshots), so nothing here needs a browser.

**Considered and rejected.** (a) Bundle Playwright+Chromium in platform-api — real one-time-per-
deploy image cost, honest but unnecessary once extraction is garnish. (b) Browserless over CDP
(the original D4) — external vendor + key + client-URL egress + failure point for negligible
volume. (c) A fourth Railway service owning Chromium — new topology, disallowed without owner
sign-off. All rejected in favor of the no-browser assembly above.

**Consequences.** No `BRANDGUIDE_BROWSER_WS_URL`, no Browserless account, no Playwright dep, no
Chromium in any image, no topology change. The one thing given up — cascade-resolved area
weighting — is replaced by screenshot-pixel dominance.

**Adversarial-review caveat (2026-09-15, added after this ADR).** One half of the method is
NOT yet proven: "exact declared hex from scraped CSS." `scrapeowl_fetch` returns rendered DOM
markup, not inlined external stylesheets, so colors defined in linked CSS, `var(--x)` custom
properties, or utility classes (Tailwind) may not surface as inline `color:`/`background-color:`
declarations — the common case on templated SMB sites. There is also no live-scraped-site color
extractor in the suite today (the only census, `website_theme_precompile.py`, assumes all-inline
CSS from an uploaded `.dc.html`), and the "truer signal than area-weighted computed styles" claim
was never measured (the sandbox is egress-blocked). So screenshot-pixel dominance is the *primary*
signal and CSS hex is a best-effort refinement with a pixel-sampled fallback (PRD §4.2).

**Revisit trigger.** A **Phase-0 spike** (PRD §10) must run the real ScrapeOwl-CSS + DataForSEO-
screenshot + Pillow path against ≥3 live client sites on the worker and measure the palette vs a
manual eyedropper (PRD §11 acceptance #1, within a stated tolerance) **before Phase 1 builds on
D4.** If declared-hex-from-scraped-CSS doesn't recover real brand colors and the pixel-sampled
palette is unacceptably wrong, reopen this decision (the fallbacks then in play: parse linked
stylesheets / resolve `var()` ourselves, or reconsider a headless render after all).
---

## Fanout Luna writer — `reasoning_effort="none"` on tool calls (reasoning OFF for now)

**Status: DECIDED (owner, 2026-09-15). Built in the same change (PR #1130).**

gpt-5.6-luna began (2026-09-15) rejecting function tools combined with a
non-`"none"` `reasoning_effort` on `/v1/chat/completions` (`400 — Function tools
with reasoning_effort are not supported … set reasoning_effort to 'none'`). This
dead-lettered every Fanout content run on the OpenAI/Luna provider that hits a
forced tool-call step (observed live: Nova Life Peptides' retatrutide +
tirzepatide 16:00 UTC runs). An earlier Luna article the same day succeeded, so
this reads as a provider-side tightening, not a code change.

**Decision (owner):** keep Luna running **without** reasoning on the tool-call
steps for now — ship the one-line chat-completions fix
(`OpenAIWriterLLM.call_tool` sends `reasoning_effort="none"`). Do NOT do the
larger endpoint migration yet.

**Scope of what loses reasoning:** ONLY the four short structured tool-call
steps — `writer_intro`, `writer_faqs`, `writer_cta`, `writer_takeaways`. The
long-form prose (`complete_text`: body sections, conclusion, enrichment lede)
is untouched and keeps the model's default reasoning. The downstream Claude
voice/quality judges still grade the output. Quality impact judged marginal.

**To turn reasoning back on later (if needed):** migrate the Fanout writer's
tool calls from `/v1/chat/completions` to OpenAI's `/v1/responses` endpoint,
which supports function tools WITH a non-`none` reasoning_effort. That is a
larger change (different request/response surface + parsing in
`fanout/llm/openai_writer_client.py`) and was deliberately deferred. Only the
tool-call path needs it; `complete_text` is unaffected either way.

---

## Topic-Vector Information-Gain — reopt coaching pushes only SITE-INVARIANT facts (2026-09-16)

**Status: DECIDED** (built this session; the P1 reopt-coaching live-check follow-up).

**What was found.** Inspecting Nova Life Peptides' live `site_claim_index` (the P1
grounding corpus) plus the deployed 05:58 score run on its "buy retatrutide" PDP,
and reconstructing `topic_vector.render_gain_guidance` offline on that exact data,
the reopt COACHING block for a retatrutide reoptimize would push **6 bad facts of
8**: a garbage `price: 0.00 USD` (an empty-cart / chrome artifact the price regex
scraped from `/blog/`) and five cross-product `size` facts (25 / 4 / 5 / 6 / 75 mg
— semaglutide dosage-comparison numbers from a blog, not this product's 10mg/30mg
vials). Only `coa: present` and `storage_temp: -20 °C` were defensible.

**Root cause (deeper than the zero price).** The site-claim index is CLIENT-level
(the whole site — every product + blog), but the coaching PUSHES a fact onto ONE
page ("state this"). For a multi-product client (Nova sells dozens of peptides),
per-product (`size`), per-compound (`cas` / `molecular_weight` / `molecular_formula`)
and transactional (`price`) facts belong to some OTHER page; coaching them onto a
retatrutide PDP is a factual error, not fabrication-prevention. (The scored-gain
GROUNDING path is unaffected — it corroborates the page's OWN claim against the
index, which is safe for every fact type.)

**Decision / fix.**
1. **Extraction (source):** drop `$0` / `$0.00` price matches — an empty-cart /
   discount-widget artifact is never a real product price
   (`site_claim_index.extract_facts`). Keeps the corpus clean for every consumer
   (also stops a `0.00` claim false-grounding via `_site_fact_values`).
2. **Coaching (correctness):** `render_gain_guidance` pushes only SITE-INVARIANT
   fact types — the quality/handling facts a vendor asserts site-wide:
   `_COACHABLE_FACT_TYPES = {coa, purity, storage_temp}`. The identity / commerce
   facts (`price` / `size` / `cas` / `molecular_weight` / `molecular_formula`) are
   never coached because the client-level index can't guarantee they belong to the
   target page's product.

**Tradeoff (accepted).** For a genuinely SINGLE-product client the excluded facts
ARE that product's facts, so coaching loses some grounding for them — but the
scored-gain grounding still credits the page's own CAS/MW/size claim, so
single-product clients are not penalised; only the PUSH coaching is narrowed. The
subtopic-gap coaching (keyword-anchored, from the SERP) is the primary signal and
is unchanged.

**Not a new defect elsewhere.** The age-gate chrome ("I acknowledge that I am age
21 or older.") still scoring as `realized` gain in the 05:58 run is the #1169
`_CHROME_CLAIM_RE` fix not-yet-deployed (merge-queue lag), not a new issue.

**Live-reopt confirmation.** Not re-run for a fresh paid reoptimize: the coaching
block is ephemeral (prompt-only, never persisted), so a live reopt cannot reveal
it — the offline reconstruction on the deployed 05:58 measure + the real index is
the faithful check. Post-deploy, delete Nova's `site_claim_index` row (or wait the
30-day TTL) to force a clean re-crawl so the stale `price: 0.00` clears from the
grounding fast-path too.

---

## LeadOff — on-demand grading + scout-from-grade + sort-by-service (2026-09-18)

**Context.** LeadOff's precomputed board is ≥30k pop only (34,352 rows). The owner
wanted to (a) reach the smaller cities (15k–30k) that were never scanned and (b) be
able to "type a city + a service → get a grade." Rather than precompute a whole
below-30k tier (the tabled small-market/demand-gate debate — see HANDOFF), the answer
was an **on-demand grader** that grades the exact cell asked for.

**DECIDED + BUILT (this session):**
- **On-demand grader** (PR #1204, merged + live): board (free) → cache (free) → live
  single-cell grade (~$0.06, cached), reusing `tryout_rows` scoped to one service.
- **The live grade path does NOT apply the `vol≥20` demand gate** — grade the requested
  cell regardless, *surface* `thin_demand`. Rationale: the gate only ever bounded
  PRECOMPUTE cost; on demand the user asked for THIS cell.
- **Off-catalog services still grade live**, with the CPL falling back to the flagged
  default (`cpl_default`) — only the lead value needs the catalog; the keyword+SERP work
  for any term.
- **Staff-gated + per-user daily-budget guarded**, like Tryout.
- **Scout-from-grade** (PR #1212, green mergeable draft): a "Scout this market" button
  deepens a graded OFF-BOARD market by injecting the grade's stored top-5 into the same
  `leadoff_scout` job (no new job/spend types). **Gated to on-catalog grades** (scout keys
  on `category_id`).
- **Sort-by-service uses the existing Board** (filter by category + sort by Opportunity/
  Expected value) for scanned services on the ≥30k gated tier — no new build needed there.

**DECIDED — the 4 categories to add to the catalog/board** (runbook written, owner runs on
the scanner machine): Fire damage restoration service (75/138/200), Dumpster rental service
(20/45/70), Carpenter (25/50/75), Dryer vent cleaning service (20/40/60). Level A (catalog,
~$0) vs Level B (board precompute, ~$80–90).

**OPEN — needs an owner decision / go-ahead:**
1. **Merge PR #1212** (scout-from-grade). Green + mergeable; not merged (owner asked to
   build, not merge).
2. **`grade-all` bulk endpoint** — a cross-city "rank every city for a service" sweep that
   reaches the sub-30k + off-catalog cities the Board sort can't (~$195–240 for HVAC across
   all ~3,993 gradeable cities). Would batch the per-city grade + a ranked table + CSV.
   NOT built — the most natural next build. Also needs the per-user `leadoff_daily_budget_usd`
   ($5 default) raised for a sweep.
3. **Scout button on Tryout rows** (not just the single-service grade card). NOT built.
4. **Sub-10k geocode step** — to grade towns below the 10k `market_scanner.cities` floor.
   NOT built.

**DEFERRED — small-market board backfill / drop the demand gate to 10** (the tabled
exploration): 30–50k backfill ~$91, gate-10-everywhere ~$450–550. Largely made optional by
the on-demand grader; only matters if the owner wants that tier *browsable* on the board.

## LeadOff — Enigma card-transaction pilot (better pricing/profit data) — NOT RUN (2026-09-18)

**Status: OPEN / BLOCKED.** Owner asked (2026-09-18) to "run the coverage pilot on a trial
key." It **cannot run from a Claude Code session**: no `ENIGMA_API_KEY` in the env, no Enigma
HTTP client/host in platform-api (the only Enigma code is the *outreach* module's ordering/
budget side, not a reusable LeadOff client), no LeadOff pilot script, and no sandbox egress to
Enigma's API. Running it needs (a) an Enigma trial/eval key (a human signup step) and (b) a
machine with egress (owner's machine or a Railway shell). Plan + go/no-go thresholds:
`docs/modules/leadoff-enigma-pilot-plan-v1_0.md`. Working hypothesis: growth-signal is the
salvageable use; lead-value calibration is risky (home-service jobs are insurance/invoice-paid
→ card data undercounts → biases CPL down), and the better lead-value source may be the agency's
own won-client close data via the existing `leadoff_calibration` loop.

**AGREED PREP — BUILT 2026-09-18 (owner picked this over the sub-10k/won-client alternatives).**
`writer/platform-api/scripts/enigma_coverage_pilot.py` + `scripts/leadoff_enigma_ground_truth.csv`
now exist: a standalone (stdlib + `httpx`, no app import, **no new dependency**) harness that reads
`ENIGMA_API_KEY` + `ENIGMA_GRAPHQL_URL`, **refuses to run without a key**, calls Enigma once per
ground-truth business, and prints the §5 coverage/growth/lead-value scorecard + the §5.4 outcome
(deterministic verdicts, unit-tested 27 cases; §5.3 avg-ticket plausibility is an auto flag with an
authoritative `plausible_human` column). It reuses the **outreach module's live-verified** Enigma
GraphQL `search(searchInput)` shape (`outreach/api/services/enigma_graphql.py`) rather than guessing
endpoints — the single `cardTransactions` connection + the `enigmaId: null`-on-match gotcha — and
writes a raw-envelope JSONL so the real transaction-count slug is discoverable on the first run
(`--count-quantity`). `--dry-run` validates the CSV + prints the query with no key/egress. **Bucket A
is pre-filled** with the 5 real Little Rock water-damage competitors (from `competitor_locations`);
**bucket B (revenue anchors) + the positive control are `#`-placeholder rows the owner fills.** Plan
§6a documents the run command. **Still cannot RUN from a Claude Code session** (no trial key + no
egress) — the owner runs `python scripts/enigma_coverage_pilot.py` once they have a key and pastes
the scorecard into plan §8. The won-client-close-data calibration path remains the alternative
lead-value source if the pilot's §5.3 fails (expected).

## LeadOff — grade-all bulk sweep ("Rank cities") (2026-09-18)

**Context.** The single-cell grader answers "type a city + a service → grade";
the board answers "rank cities for a service" but only for scanned categories on
the ≥30k tier. Nothing ranked EVERY gradeable city (incl. sub-30k + off-catalog)
for one service — the #2 open item from the 2026-09-18 grader entry, and the one
flagged there as "the most natural next build."

**DECIDED + BUILT (this session, green draft PR):**
- **A board/cache-aware bulk sweep**, NOT a re-run of every cell: per candidate
  city, board-first (free) → recent cache (free) → live (~$0.06). So a service
  already precomputed on the board (HVAC = 723 free rows) only pays for the
  ungraded remainder. Distinct from city-finder (which always pays + caps at
  300); grade-all reaches all ~3,993 gradeable cities.
- **Each live grade is persisted to `leadoff_grades`** — the sweep is
  idempotent/resumable (a reaper requeue re-runs but finds graded cells cached =
  free) and those cells are free for future single grades too. Paired with a
  180-min stale-timeout override (cheap requeue, not a double-spend risk).
- **Spend model — nothing spends without staff auth + confirm + a ceiling:** a
  FREE estimate endpoint shows the board/cache-free split + the live cost; the
  caller sets a required `max_spend_usd`; the job grades only as many live cities
  as the RESERVED amount (`min(estimate, ceiling)`) covers (biggest markets
  first), the rest `budget_skipped` → run `partial`. The reserved amount is
  guarded + recorded, and the job's hard cap = the reservation, so a
  candidate-set change between enqueue and run can never overspend.
- **A DEDICATED daily budget** `leadoff_grade_all_daily_budget_usd` ($300),
  SEPARATE from the tight $5 single-grade `leadoff_daily_budget_usd` — so a
  deliberate sweep can be authorized without loosening single-grade safety.
  Rationale: a sweep is a different, infrequent, staff-only action; conflating
  its budget with single grades would either block sweeps or weaken the single
  guard.
- **Ranked by expected value** across all three sources; board rows carry the
  regressed `xdem` demand, live/cache the raw observed `vol` — both surfaced with
  `demand_basis` (the same board-vs-tryout apples-to-oranges the grader already
  accepts, made transparent per row rather than hidden).
- Migration `20260918200000` applied live (`leadoff_grade_all_runs` + the
  `grade_all` spend action + the `leadoff_grade_all` job type, both rebuilt from
  the verified live constraints). Frontend "Rank cities" tab (estimate → set
  ceiling → run → ranked table + CSV).

**Scout-from-grade (PR #1212) — MERGED** (`1ccd4df` on `main`); the prior entry's
OPEN item #1 is closed.

**Still OPEN (unchanged):** the 4-category board-add runbook (owner's scanner
machine), a scout button on Tryout rows, a sub-10k geocode step, and the Enigma
coverage pilot. The real DataForSEO sweep is worker-verified post-deploy (the
sandbox is egress-blocked from DataForSEO).

## LeadOff — grade the literal keyword, not the catalog category (2026-09-18)

**Context.** Owner searched "roofer in cypress, ca" and got nothing. Diagnosis
uncovered two things: (1) the Board search box is a filter over the precomputed
board and has no live fallback (Cypress had no roofing board row → empty); and
(2) the on-demand grader, when the typed term fuzzy-matched a catalog category
(`roofer`→`Roofing contractor` via the `roof` stem), pulled the volume + Maps
SERP on the CATEGORY, not the user's keyword — so it graded the wrong query.

**DECIDED + BUILT (this session, on PR #1217's branch).** Decouple the pulled
keyword from the lead-value lookup:
- **The live pull (volume + Maps SERP) always uses the LITERAL keyword** the user
  typed. "roofer" grades "roofer".
- **The nearest catalog category is used ONLY** for the CPL (lead value, flagged),
  the exact-category holder count, and the board/scout id — never as the pulled
  keyword. Rationale: the catalog match is free accuracy for lead value; there's
  no reason to throw it away, but it must not replace the keyword.
- **The grade cache keys on the literal keyword**, so "roofer" and "roofing
  contractor" (different SERPs) cache distinctly.
- **Board-first and cache-first are unchanged**: a board hit is still the free
  precomputed *category* grade (transparently labeled). Only the LIVE path — the
  case the owner hit — changed. Forcing a live literal grade for every mapped
  keyword would defeat the free board and cost money for no benefit.
- **Consequence (accepted):** on-catalog live grades now measure the literal
  keyword's SERP, so grade numbers shift vs before. Intended.

Applies to the single-cell grader AND the grade-all sweep. `resolve_service`
now returns `{keyword, category_name (catalog match or None), on_catalog}`;
`field_stats` gained an optional `holder_category` so the literal keyword's SERP
is graded while holders count against the catalog category.

**Related UX gap (NOT yet built, proposed):** the Board search box silently
returns nothing when it resolves a city+service with no board row, even though a
live grade is one tab over. Proposed fix: an inline "Grade it live (~$0.06)?"
handoff from the empty board-search state into the grade flow (offer a button,
never auto-spend). Awaiting owner go-ahead.

## LeadOff — Board-search "Grade it live?" handoff (2026-09-18)

**Status: DECIDED + BUILT** (the "Related UX gap" from the prior entry — owner
gave the go-ahead). When the Board smart-search resolves a city + service but the
precomputed board has no such row, the empty state now offers **"Grade it live
(~$0.06)"**, which hands off to the Grade tab (prefilled) and auto-runs the grade.

Decisions:
- **Offer, then auto-run on the click** — the "Grade it live (~$0.06)?" button IS
  the deliberate spend action (cost named on it), so landing on the Grade tab and
  requiring a second click would be redundant. Auto-runs once (guarded by a ref;
  the parent prefill is cleared on consume so a later manual visit can't re-fire).
  Grading stays staff- + budget-gated like any grade.
- **Grades the literal keyword**, consistent with the same-day keyword-decoupling
  fix: `leadoff_category_match` now extracts the literal `service` phrase (its own
  tool-schema field, independent of the mapped category), and the handoff seeds
  the Grade form with it (fallback to the mapped category only if the parser
  didn't isolate the service).
- **Board search stays a free filter** — no live call is made from the search box
  itself; the handoff is a one-click bridge to the paid Grade flow.

## LeadOff — Scout button on Tryout rows (2026-09-18)

**Status: DECIDED + BUILT** (the "scout button on Tryout rows" open item from the
2026-09-18 grader entries). Scout was on the single-service grade card only; a
tryout grades a whole city across the ~100 catalog categories but offered no way
to deepen any one of them.

Decisions:
- **Reuse scout-from-grade wholesale, no new job/spend/migration.** A tryout scout
  is a third off-board path on the existing `leadoff_scout` job (`tryout_id` +
  `category_id` in the payload), mirroring the grade path (`grade_id`). Pure
  helpers `tryout_scoutable` / `tryout_result_row` / `tryout_market_comps` /
  `tryout_scout_inputs` / `store_tryout_scout_result` parallel `leadoff_grade`'s
  scout helpers.
- **Stash the top-5 competitors on each tryout row at completion** (the only
  run-time change) — the tryout analogue of a grade row's `grade.competitors`.
  A tryout already pulls them (`top5_by_cat`); they were used for footprint + GBP
  pins but discarded from the row. Competitors + the resulting `scout` block ride
  in the existing `leadoff_tryouts.results` jsonb — no schema change.
- **Key scout on the tryout category NAME directly** (not a `lead_category`
  indirection). A tryout category IS a scanned catalog category, so its name keys
  the scanner's Pass-2 caches (`trend_key`/`biz_key`) as-is — unlike the grader,
  whose row stores the user's literal keyword and so needs `lead_category`.
- **One scout at a time per tryout, budget-guarded + staff-gated** like every
  paid LeadOff action; the fully-cache-fresh case stores inline ($0, no job),
  same as the grade card. Older tryouts (generated before the stash) show no
  Scout button — re-run the tryout to scout them.

Backend + frontend + tests (`TestTryoutScout`, 8 pure cases); the live paid scout
pulls are worker-verified post-deploy (sandbox egress-blocked from DataForSEO).

## LeadOff — valuation v1: exclusive CPL re-anchor + CPC modifier + monetization (2026-09-18)

**Context.** LeadOff's grade value is `leads × CPL × rankability`, but the CPL
was a flat, national, hand-authored `market_scanner.lead_values` estimate
anchored to *shared*-lead (low) economics, and the grader pulled per-market CPC
then **discarded it** — so a painting lead in Manhattan and Mobile graded
identically, and the board under-ranked the high-ticket emergency trades a
rank-and-rent operator most wants. Plan (the authority):
`docs/modules/leadoff-valuation-plan-v1_0.md`; owner chose "build full v1 in one
PR" (2026-09-18).

**DECIDED + BUILT (this session):**
- **Exclusive CPL re-anchor via the §4 ladder** (`services/leadoff_lead_values.py`,
  pure): rung 1 = Service Direct published exclusive ranges (mid = geomean of the
  published low/high — grounded, not a model), rung 2 = observed 2026 CPI-adjusted
  averages (+ remodeling's §3 CPL tier), rung 3 = cluster-sibling inheritance at
  the anchor's floor (only where sane), rung 4 = keep the flagged manual estimate.
  Every row records `source` + `confidence`. Delivered as
  `scripts/leadoff_lead_values.csv` (the scanner's `inputs/lead_values.csv` is the
  source of truth — reload-wiped) + `scripts/build_lead_values.py` (writes the
  CSV, prints the before→after, `--upsert` interim mirror, `--board-compare`).
  Measured re-rank: water damage ×7.7, remodeling ×6, roofing ×2.9,
  plumbing/HVAC/electrical ×2.3; a few over-priced low-ticket trades (handyman,
  carpet cleaning) settle DOWN to observed exclusive averages — the re-anchor
  corrects both directions, grounded > manual.
- **Deliberate divergence from the plan (recorded honestly):** the §4 rung-2
  *formula* (`job value × close rate × margin`) over-shoots the mid-ticket
  non-emergency trades (validated only for HVAC in the spec), so v1 anchors to
  **observed** network prices/averages where they exist and keeps `formula_cpl`
  as a cross-check / v2 lever. More categories stay on flagged manual than the
  plan's "~15" target (small finishing sub-trades have no reliable sub-job value
  without the raw 713-row HomeAdvisor CSV, an open item) — safer than an
  inheritance scale that would fabricate a number. Net: 25 high / 27 medium /
  55 low across 107 categories.
- **Per-market CPC local modifier** (`services/leadoff_cpc.py`, pure
  `cpc_modifier`): `CPL = anchor × clamp(market_cpc ÷ national_median_cpc(cat),
  0.7, 1.5)`, bounded + conservative + calibratable per the `leadoff_scoring`
  precedent. National median per category lives in the app-owned
  `public.leadoff_cpc_baseline` (migration `20260918210000`, applied live +
  populated from `market_opportunity_master.category_cpc` — $0, no paid call;
  refreshable via `scripts/build_cpc_baseline.py`). Wired into the shared
  `tryout_rows` seam (so tryout + on-demand grade + grade-all all get it) with the
  caller passing a per-key multiplier; **×1.0 (byte-identical) when the baseline
  is unpopulated or any CPC is thin** — a missing signal never penalizes a market.
  The precomputed board stays a national-anchor view (no live CPC); the live grade
  is the per-market view — the `demand_basis` board-vs-live distinction already
  surfaced. Flag `leadoff_cpc_modifier_enabled` (default True).
- **Monetization print** (`services/leadoff_monetization.py`, pure): the three
  grounded models (PPL-exclusive = `value_mo`; rank-and-rent = × `rent_discount`
  0.6; PPL-shared = leads × exclusive×`shared_price_ratio` 0.35 × `n_buyers` 4) on
  the grade card + market brief (NOT board columns, per plan §7). Honesty rule
  rendered in the UI copy — same lead flow, different billing, not independent
  streams; the speculative Enigma affordability ceiling is deliberately v2.
  Constants config + calibratable.

**Guardrails held (nothing auto-applies the big re-rank).** The CSV + the
mirror-upsert + the board re-export are **owner-run after reviewing the
before→after** (the plan's "never blind-swap"); shipping the code does not push
exclusive CPLs to the live table. The CPC modifier ships enabled but is **inert
until the owner runs `build_cpc_baseline.py`** — though this session populated the
baseline live, so on deploy the live grade paths gain bounded per-market CPC
variation on the CURRENT CPLs; the exclusive re-anchor lands when the owner runs
the mirror-upsert. No grade *weight* shipped unearned (the modifier is bounded +
flag-gated; monetization is display).

**Activation order (owner, documented in HANDOFF):** review the before→after
(`build_lead_values.py`) → run `--upsert` (interim) or reload the scanner from the
new CSV → re-run `export_leadoff_board.py` (board re-rank). The `build_cpc_baseline`
baseline is already populated (run it again after a scanner re-scan).

**Open (unchanged from the plan §10):** the raw 713-row HomeAdvisor CSV (sharpens
the ladder to sub-job level → more categories off flagged manual); `review_rate`
calibration + a Shovels.ai per-contractor-permit eval + the Enigma pilot result
(all v2 — revenue estimation + the affordability ceiling). The
`market_scanner.lead_values` DataForSEO/scanner side is the owner's machine.

## LeadOff — valuation v1.5: income folded into the local modifier (2026-09-18)

**Context.** Plan §8's v1.5 step — fold the "income / home-value ratio" into the
CPL `local_modifier` as a second bounded signal that COMPOSES with the v1 CPC
modifier (plan §3's confidence-weighted blend). Owner picked v1.5 next (v2 is
blocked on the un-run Enigma pilot) and confirmed the modifier should key off
**above/below the national median** with my conservative defaults, enabled.

**Scope call (recorded honestly).** The plan says "income / home-value ratio,"
but median **home value is NOT captured** anywhere: `census_demand.py` pulls
households/pop/income/year-built (no B25077) and is block-group data cached only
where a Placement Advisor scan ran — not board-wide. So v1.5 ships **income-only**
(the correctness win), from the already-live `public.city_household_income`
(the `leadoff_income` ACS-B19013 backfill — **3,731 board cities**, all non-null,
board median **$78,921** ≈ the US ACS median, keyed by `city_id`). A board-wide
home-value fetch (a new B25077 backfill) is a deferred follow-up if wanted.

**DECIDED + BUILT (this session):**
- **Income modifier** (`services/leadoff_income_modifier.py::income_modifier`,
  pure): `clamp(city_income ÷ national_median, 0.85, 1.2)` — bidirectional (an
  above-median metro → premium up to +20%, below → discount down to −15%),
  `None` (absent → ×1.0) on any missing/thin income. National median is a config
  scalar (`leadoff_income_national_median`=78921, calibratable).
- **The blend** (`combine`, pure): a **renormalizing weighted-deviation average**
  of whichever signals are present — a SINGLE present signal is returned
  UNCHANGED, so CPC-only (income absent/disabled) is **byte-identical to v1**; two
  present → `1 + Σ(w·(m−1))÷Σw` (weights CPC 0.7 / income 0.3), clamped to the
  widest of the two bounds ([0.7, 1.5] = CPC's). The blend always sits BETWEEN the
  two individual modifiers, so it is never MORE extreme than a single signal — the
  conservative property. A new `leadoff_cpc.cpc_modifier_opt` returns `None` when
  CPC is genuinely absent (vs the `1.0` `cpc_modifier` returns for both absent AND
  market==national), so an absent CPC hands full weight to income; `cpc_modifier`
  itself is untouched (byte-identical, its tests unchanged).
- **Wired into all 3 live grade paths** (tryout / grade / grade-all) via
  `local_modifier(cpc, category, city_income, cpc_baseline, params)` → the same
  `tryout_rows` `cpl_multipliers` seam the CPC modifier already fed. Income is a
  per-city scalar (batch-loaded once per sweep in grade-all). Each row records a
  `cpl_modifier_detail` = `{"cpc": …, "income": …}` (which signals fed it — plan
  §3 transparency; surfaced in the grade-card monetization hint).
- **Config + flag** (`leadoff_income_modifier_enabled` default True, bounds,
  weights, national median — all calibratable). No migration (reuses the live
  `public.city_household_income`). The board stays a national-anchor view (income,
  like CPC, applies only on the live grade paths).

**Guardrails held.** Ships enabled, and the income data IS populated, so on deploy
the live grade paths gain bounded per-market income variation (mirrors how the
CPC modifier activated) — but it's a NEW mechanic, so it's bounded + conservative
+ flag-gated per the `leadoff_scoring` precedent (no grade *weight* shipped
unearned). The exclusive CPL re-anchor + board re-export stay the owner's to run.

**Open (unchanged v2, plan §10):** median home value (a new B25077 backfill) if
the second demographic signal is wanted; the raw 713-row HomeAdvisor CSV; revenue
estimation + Enigma (gated on the pilot).

## LeadOff — valuation: HomeAdvisor job-value formula rung (2026-09-19)

**Context.** Plan §10's open item ("the raw 713-row HomeAdvisor CSV → more
categories off flagged manual") and §8's "sharpen the CPL ladder", owner-picked
next. The v1 §4 ladder left **45 of 107** `market_scanner.lead_values` categories
on `manual_estimate`/`low` (hand-guesses) because they had no observed Service
Direct resale price and no sane cluster-sibling anchor. The raw HomeAdvisor True
Cost Guide dataset (job value per sub-job) is the input that grounds the project
trades among them.

**Finding (recorded honestly).** There is **no separate `homeadvisor_true_cost_guide_full.csv`
in Drive** — the spec references it as a "source file alongside this doc" but it
lives on the owner's machine. The owner shared it this session as a Google Sheet
(`combined_job_value_and_lead_cost`, 713 rows). Downloaded via the Drive connector
and committed to the repo as
`writer/platform-api/scripts/homeadvisor_true_cost_guide_full.csv` (the durable
build input, next to the output CSV). Schema: `url, sub_job_title, industry,
job_value_avg, job_value_range_low/high, job_value_sample_n, job_value_template,
lead_cost_low/high, lead_cost_note`. The spec's §2 *vertical-weighted* job values
were already in v1's `JOB_VALUE` dict; the raw CSV's value is the **per-sub-job
granularity** the vertical average couldn't carry.

**DECIDED + BUILT (this session).** Two new ladder rungs in the pure
`services/leadoff_lead_values.py`, running only when `homeadvisor_rows` is passed
(so `homeadvisor_rows=None` is **byte-identical to v1** — no behaviour change; the
17-case `tests/test_leadoff_lead_values.py` pins it):
- **Rung 3.5 — observed HomeAdvisor lead range** (`homeadvisor_lead_range`,
  `medium`): a previously-manual category whose GENUINE trade carries a published
  Service Direct resale range in the CSV → `mid = geomean(low, high)`. Only two
  qualify: **Fence contractor** ($55–175 → $98) and **Solar energy contractor**
  ($100). The `industry` on a cross-mapped row (a chimney page filed under HVAC)
  is deliberately NOT trusted as that trade's price.
- **Rung 3.6 — HomeAdvisor job-value formula** (`job_value_formula`, `low`): a
  previously-manual *project* trade with a real job value but no observed price →
  `CPL = weighted_job_value × close_rate(0.42) × margin_share(0.22)`, **clamped to
  [20, 150]**. `weighted_job_value` (pure, sample-weighted over `n>0` rows, plain
  mean fallback) reuses the spec §4 "vertical-weighted, not a flagship sub-job"
  rule. A conservative, explicit `_CATEGORY_JOB_MATCH` maps 24 categories to
  url-slug patterns.
- **The cap is the load-bearing guardrail (and the key judgment call):** the raw
  formula over-shoots high-ticket trades (a $40k pool at ~9% ≈ $3,600, absurd for
  a resale CPL), because **CPL decouples from job value at the top** — roofing's
  $7,696 job resells at $85–550, not thousands. So the cap = the observed
  GC/remodel lead-range high (~$150, spec §1), the empirical local-project CPL
  ceiling. High-ticket remodeling-class trades (cabinet, deck, countertop,
  masonry, stucco, stair, pool, interior design, asphalt/paving) correctly cluster
  there; mid/low-ticket trades (drywall $91, awning $72, wallpaper $48, cleaning
  $20–23, inspection/consulting $29–56, chimney sweep $23) differentiate below it.
  All three knobs (`leadoff_formula_close_rate` / `_cpl_cap` / `_cpl_floor`) are
  config-calibratable — the owner tunes them from the printed before→after.

**Result.** **27 of 45** manual categories moved onto grounded data (18 remain
manual). Confidence tiers: 25 high / 29 medium / 53 low. Direction is honest and
two-way: 19 lifted (the high-ticket project trades, 1.5–3.1×), and a handful
grounded DOWN where the manual guess was high (Solar 170→100, building
inspector 60→29, cleaning trades → ~$20–23) — grounded > guess, consistent with
v1 lowering handyman/carpet.

**Deliberate exclusions (nothing fabricated).** Moving (spec §5 — zero lead-price
signal, CPC-proxy is v2), piano tuning, furniture repair, upholstery, ponds,
fountains, sprinklers, snow removal (no CSV match) → **stay flagged manual**.
**Tile contractor** is deliberately NOT mapped: the CSV's only tile pages are
grout/repair (a tile INSTALLER's job value is flooring-class, uncaptured), so a
formula off them would *under*-value it — better to keep the manual estimate.
**Chimney services** excludes the rare `chimney-rebuild` ($9k, n=0) so an outlier
can't pin a small-repair lead to the cap.

**Delivered as** `scripts/leadoff_lead_values.csv` regenerated (the owner's
`inputs/lead_values.csv` source of truth) via `build_lead_values.py` — now loads
the committed HomeAdvisor CSV, threads the formula knobs, and gained `--from-csv`
(offline regen from a prior CSV, no DB egress) + `--no-homeadvisor`. Deliberately
prose-only for the pure module (no I/O; the CSV is read in the script and passed
in). **The `formula_cpl` raw cross-check is preserved** (a NEW clamped
`job_value_formula_cpl` wraps it — the existing test's positional call is
unchanged).

**Guardrails held (unchanged from v1).** Nothing auto-applies. The regenerated
CSV + the `--upsert` mirror + the board re-export are **owner-run after reviewing
the before→after** (the plan's "never blind-swap"); shipping the code does not
push these CPLs live. Every rung-3.6 row is flagged `low` confidence.

**Open (v2, plan §10, unchanged):** median home value (B25077 backfill); revenue
estimation + Enigma top-down + affordability ceiling (gated on the un-run pilot).
