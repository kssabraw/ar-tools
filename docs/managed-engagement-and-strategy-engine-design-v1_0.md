# Managed Client Engagement — Onboarding, Audit, Strategy & Autonomous Execution (Design v1.0)

> **Status:** Design proposal. **Nothing in this document is built yet.** This is the architecture + phased roadmap for the orchestration layer that turns the AR Tools suite from a toolbox into a managed, semi‑autonomous SEO engagement. It is meant to sit alongside `docs/suite-architecture-and-roadmap-v1_0.md` (the product/architecture authority for "how many tools is this") and inherits all of that doc's locked decisions and the constraints in `CLAUDE.md`.

> **Scope decisions captured from the user (2026‑06‑28):**
> - **Autonomy target:** *maximally autonomous* — the system should execute most of an approved plan end‑to‑end (write pages, set internal links, publish drafts, provision tracking) with humans approving only at a few checkpoints.
> - **Deliverable:** this design doc; **build nothing yet.**
> - **Asana:** **deferred.** Designed for, but not built in the first phases; the plan stays internally authoritative until we add it.

---

## 1. Purpose

Today the suite is a set of excellent but **independently operated** modules. An operator manually: creates a client, fetches GBP, scrapes the site, edits brand voice/ICP, adds keywords to three different trackers, runs scans, reads three separate reports, and decides what to do next. Each module is strong; the **connective tissue is missing**.

This design adds that connective tissue: a single **Engagement** lifecycle per client that

1. **Onboards** the client (GBP/website → brand voice + ICP, with explicit approval gates),
2. takes the **targets** (keywords / topics / services + the geographies to win them in),
3. **audits** the client's site, the organic SERP competition, and the Maps competition,
4. **synthesizes a strategy** (content silos, on‑page, internal linking, citations, backlinks, LLM‑visibility tactics, technical fixes) into one approvable plan,
5. on approval, **provisions** rank tracking, geo‑grids, LLM tracking, and content schedules,
6. **autonomously executes** the plan against guardrails and human checkpoints,
7. **reports** progress in one consolidated client report and over the existing notification channels,
8. (later) **mirrors** the plan and status into Asana.

The design's guiding principle: **~60% of this is orchestration over machinery that already works.** The genuinely new build is five modules + a strategy engine + an autonomous executor. We reuse everything else.

---

## 2. What already exists (do not rebuild)

This layer is an orchestrator. It calls existing services rather than reimplementing them.

| Need | Existing service(s) it will call |
|---|---|
| GBP fetch / resolve | `services/gbp_service.py` (search/details/resolve, service‑area capture) |
| Website analysis | `services/website_scraper.py` + `website_scrape` job → `clients.website_analysis` |
| Brand voice | `clients.brand_voice` (JSONB) + BrandVoice scan/accept UI |
| ICP + differentiators | `clients.detected_icp`, `clients.differentiators` + Icp scan/accept UI |
| Reference page structures | `services/page_structure_scraper.py` → `clients.page_structures` |
| Keyword intake (3 trackers) | `tracked_keywords`, `maps_keywords`, `brand_tracked_keywords` (+ the planned **Unified Keyword Portal**) |
| Target geographies | `clients.target_cities`, `services/target_cities.py`, Local SEO multi‑city discovery |
| Organic SERP intelligence | `services/serp_snapshot.py`, `services/serp_trends.py`, `services/rankability.py` |
| Maps competition | `services/local_dominator.py`, `services/maps_grid.py`, `services/maps_report.py`, `services/maps_analytics.py` |
| Content silos | Local SEO **Plan Silo** (`services/local_seo_silo.py`), content silos (`silo_dedup`/`silo_promotion`), Fanout clustering |
| Content generation | Blog Writer pipeline, Local SEO page generator (`services/local_seo_service.py`) |
| Content scheduling | Fanout content scheduler (`fanout/writer/scheduler.py`) |
| Publishing | Google Docs (`services/google_docs.py`) **and WordPress REST + app passwords** (`services/wordpress_publish.py`) |
| Per‑module reports | `services/rank_report.py`, `services/brand_report.py`, `services/maps_report.py` |
| Recommendation precedent | `services/reopt_planner.py` (organic‑rank‑only Action Plan) — we **generalize** this |
| Notifications | `services/notifications.py` (in‑app + Slack live + email deferred) |
| Cross‑module context | `services/slack_assistant.py` `_CONTEXT_PROVIDERS` registry (reusable as the strategy engine's read layer) |
| Job queue / scheduler | `async_jobs` + `services/job_worker.py` + `services/gsc_scheduler.py` (in‑process asyncio loop) |

**Net‑new modules** (Sections 6–7): technical/site audit, backlink‑gap, local‑citation audit, internal‑linking analyzer+injector, the **Strategy Engine**, the **Autonomous Executor**, and the **Consolidated Report**. Asana is designed but deferred.

---

## 3. Core concept: the Engagement object + lifecycle

A new first‑class object, **`engagements`**, represents "we are actively running SEO for this client." One active engagement per client (history retained). It is a **state machine** the UI walks through and the executor drives.

```
 onboarding ─▶ intake ─▶ auditing ─▶ strategizing ─▶ plan_review ─▶ provisioning ─▶ executing ─▶ steady_state
     │            │          │             │              │ (human gate)     │            │ (autonomous)  │
   approve      targets    3 audits    synthesis      APPROVE PLAN      auto‑setup    runs the plan   reports + re‑plan
   voice/ICP                (parallel)                                                                  on a cadence
```

- **Stages are resumable and idempotent** — each transition enqueues `async_jobs` work; re‑entering a stage re‑uses completed artifacts (same pattern as the rest of the suite).
- **Two human gates only** (consistent with "maximally autonomous"): (1) **onboarding approval** of brand voice + ICP, (2) **plan approval**. Everything after the second gate runs autonomously under guardrails, with per‑checkpoint pauses configurable (Section 8).
- **`steady_state`** is not an end — it's a loop: the engagement keeps tracking, detects drops/opportunities (existing alerting + reopt signals), and proposes plan amendments that re‑enter `plan_review`.

### 3.1 New data model (sketch)

All tables `client_id`‑anchored, RLS‑guarded, service‑role accessed, migrations in `writer/supabase/migrations/`. No new infra — these are just tables consumed by `async_jobs` workers.

```
engagements
  id, client_id (FK), status (enum above), autonomy_level (enum, §8),
  current_plan_id (FK strategy_plans), created_by, created_at, updated_at,
  config (jsonb: budgets, checkpoint toggles, publish_mode draft|live)

audit_runs
  id, engagement_id (FK), kind (enum: site_technical | serp_competition | maps_competition),
  status (pending|running|complete|failed), result (jsonb), score (numeric), created_at
  -- one row per audit kind per audit cycle; reruns append

strategy_plans
  id, engagement_id (FK), version (int), status (draft|proposed|approved|superseded),
  summary (jsonb: scores, headline findings), approved_by, approved_at, created_at
  -- immutable once approved; amendments create a new version

strategy_actions
  id, plan_id (FK), category (enum: silo | page | onpage | internal_link | citation |
     backlink | llm_tactic | technical_fix | tracking_setup | schedule),
  title, rationale, target (jsonb: keyword/url/location/etc),
  priority (int), effort (enum), est_value (numeric),
  execution_mode (enum: auto | assisted | manual),
  status (proposed|approved|queued|in_progress|done|blocked|skipped),
  job_id (FK async_jobs, when executing), result (jsonb), deep_link (text)
  -- the unit the executor consumes; mirrors the reopt_planner action shape, generalized

execution_events
  id, action_id (FK), engagement_id, type (started|completed|failed|paused|checkpoint|budget_halt),
  detail (jsonb), created_at
  -- the audit trail for autonomous work; powers the activity feed + report
```

`strategy_actions` is deliberately a **superset of the existing `reopt_plans` action shape** so the generalized engine (Section 6.1) can absorb the rank‑tracker's existing logic without a parallel model.

---

## 4. The lifecycle stages in detail

### Stage 0 — Onboarding (mostly exists; add a wizard + approval gates)

**Goal:** GBP and/or website in → approved brand voice + ICP out.

- Wrap existing pieces in a guided, multi‑step **Onboarding wizard** (today it's one flat `ClientForm`): Business → Voice → ICP → Reference pages → Targets.
- **Reuse:** GBP picker/resolve, auto website scrape, page‑structure scrape, the brand‑voice and ICP scan/accept services — all already there.
- **New behavior:** make brand voice and ICP **approval gates**. The wizard requires an explicit "Approve voice" / "Approve ICP" before the engagement can leave `onboarding`. (Data already supports this — `brand_voice.recommended_accepted`, `detected_icp.source`; we add the gate, not the storage.)
- **Output:** `engagements.status = intake`.

### Stage 1 — Intake (the Unified Keyword Portal, extended)

**Goal:** capture *what* to rank for and *where*.

- Builds directly on the **Unified Keyword Portal** already planned (one textarea → fan out to `tracked_keywords` / `maps_keywords` / `brand_tracked_keywords`, idempotent, with per‑target scan kickoff).
- **Extend** it with: topic/service framing (not just bare keywords), per‑target geography (reuse `target_cities` + `services/target_cities.py` multi‑city discovery), and a "this is for engagement X" link so intake feeds the audits.
- **Output:** target set persisted; `engagements.status = auditing`.

### Stage 2 — Audits (parallel; one `audit_runs` row each)

Three audits fan out concurrently via `async_jobs`. Each is best‑effort and isolated — a failing audit degrades the plan, never blocks it (same resilience pattern as the Slack context providers and Local SEO planner).

**2a. Site / technical audit — NEW (Section 6.2).** Crawl the client site (sitemap‑seeded via existing `services/site_page_index.py`), pull on‑page + technical signals. Sources: **DataForSEO OnPage API** and/or **Google PageSpeed/Lighthouse** (new external calls — see Section 9). Produces: indexability issues, meta/title gaps, heading/schema gaps, broken links, Core Web Vitals, thin/duplicate content, internal‑link graph snapshot.

**2b. Organic SERP competition audit — SYNTHESIS of existing.** For each target keyword, compose existing `serp_snapshot` (top‑10 + DR/UR/referring domains + intent + topical focus), `rankability` (client‑relative difficulty + quick‑win signal), and `serp_trends`. New work = **rolling it up** into "where can we win, how hard, against whom, with what content shape."

**2c. Maps competition audit — SYNTHESIS of existing.** Where the client targets local, compose the geo‑grid scan + `maps_analytics` rollups + weak‑zone geocoding into "coverage gaps and the competitors owning them." Reuses `local_dominator` + `maps_report` building blocks.

**Output:** three `audit_runs` rows; `engagements.status = strategizing`.

### Stage 3 — Strategy Engine (NEW — Section 6.1)

**Goal:** audits + ICP + brand voice + targets → one ranked, structured `strategy_plan` of `strategy_actions`.

The engine is a **generalization of `reopt_planner.py`** from "organic‑rank signals only" to cross‑module. It reads via the existing `slack_assistant` context‑provider registry (already assembles organic/maps/AI‑visibility/content/keyword/setup context) plus the new `audit_runs`, and emits actions across categories:

- **Content silos** — from SERP audit + Local SEO Plan Silo + Fanout clustering → which silos/pages to build, in what order.
- **On‑page** — per existing/target URL fixes (titles, headings, schema, entity coverage) from the site audit + SIE‑style entity signals.
- **Internal linking** — link opportunities from the crawl's internal‑link graph (Section 6.5).
- **Local citations** — NAP/directory gaps (Section 6.4).
- **Backlinks** — link‑gap targets vs. competitors' referring domains (Section 6.3).
- **LLM tactics** — derived from AI‑Visibility invisibility diagnoses (which engines/keywords the brand is missing from, and the content/citation moves that tend to fix it).
- **Technical fixes** — from the site audit.
- **Tracking + schedules** — the provisioning actions (auto by default).

Each action carries `priority`, `est_value`, `effort`, an `execution_mode` (auto/assisted/manual), and a `deep_link`. Synthesis uses Claude (Sonnet, consistent with the suite's model decisions) for the *narrative/prioritization*, but **the signals are deterministic** — the engine grounds every action in a concrete audit datum, never free‑floating advice.

**Output:** `strategy_plans` (status `proposed`); `engagements.status = plan_review`.

### Stage 4 — Plan review (human gate #2)

A plan view (generalize `pages/ActionPlan.tsx`) where the operator can re‑order, edit, accept, or reject individual `strategy_actions` and set each one's `execution_mode`. **Approving the plan is the consent boundary for autonomy.** On approval: plan → `approved`, actions → `approved`/`queued`, `engagements.status = provisioning`.

### Stage 5 — Provisioning (orchestration over existing enqueue paths)

Auto‑executes the low‑risk setup actions: add/confirm tracked keywords across the three trackers, ensure geo‑grid config exists (flag if the Maps center point is missing — same blocker handling as the Unified Keyword Portal plan), create content schedules in Fanout, set report cadences. Almost entirely existing `enqueue_*` calls sequenced by the executor. → `executing`.

### Stage 6 — Autonomous Execution (NEW — Section 7)

The **Executor** drains `strategy_actions` where `execution_mode = auto`, respecting guardrails (Section 8). It dispatches each action to the tool that does it — content generation (Blog Writer / Local SEO generator), internal‑link injection (WordPress), citation worklists, etc. — as `async_jobs`, writing `execution_events` for the audit trail. **Publishing defaults to drafts**; going live is a checkpoint. → `steady_state` when the action queue drains.

### Stage 7 — Reporting + re‑planning

- **Consolidated client report (NEW — Section 6.6):** one Google Doc composing the existing rank/maps/brand report builders + the engagement's execution activity + plan progress. Delivered on the existing scheduler + notification channels.
- **Re‑planning loop:** existing rank‑drop alerting + reopt signals + scheduled re‑audits feed plan **amendments** that re‑enter `plan_review`. The engagement never "finishes."

### Stage 8 — Asana (DESIGNED, DEFERRED)

When enabled: push `strategy_actions` as Asana tasks (one project per engagement, sections by category), mirror `status` outbound. Built as a notifications‑style **dispatcher** (`services/asana_sync.py` + an `asana_sync` job) so it's additive and creds‑gated like Slack/email. **Not in the first phases.** Requires an Asana token + workspace/project mapping (dashboard setup — ask the user). Decision still open: mirror vs. system‑of‑record (user leaned "defer," so we keep the in‑app plan authoritative for now).

---

## 5. How autonomy rides existing infrastructure

No new queue, no Redis/Celery (per locked decisions). The Executor is **just another `async_jobs` consumer**:

- A new job type `engagement_step` advances the state machine; category‑specific jobs (`engagement_execute_action`) run individual actions and reuse the existing generators' jobs underneath.
- The **shared `gsc_scheduler` asyncio loop** gains an `enqueue_due_engagements` due‑check (re‑audit cadence, report cadence, re‑plan) exactly like `enqueue_due_reopt_plans` / `enqueue_due_gsc_research` today.
- Bulk content work uses the **existing staggered `scheduled_at` background‑priority pattern** (from Local SEO bulk‑create) so autonomous generation never monopolizes the single worker.

---

## 6. New non‑autonomy modules (sketches)

### 6.1 Strategy Engine — `services/strategy_engine.py`
Generalizes `reopt_planner.build_actions`/`summarize_plan`. Pure functions `build_plan(context, audits) -> strategy_plan` + `summarize_plan`, plus a `strategy_plan` job. Reads via the `slack_assistant` provider registry + `audit_runs`. Claude‑Sonnet for prioritization/narrative; deterministic signal grounding. API `routers/strategy.py` (`GET/POST .../engagement/plan`, `POST .../plan/approve`).

### 6.2 Site / Technical audit — `services/site_audit.py`
Crawl seeded by `site_page_index` sitemap discovery; pull on‑page + technical signals from **DataForSEO OnPage** and/or **PageSpeed**. Async `site_audit` job → `audit_runs`. Emits a deterministic issue list (typed, severity‑scored) the engine turns into `technical_fix`/`onpage` actions. **New external API (Section 9).**

### 6.3 Backlink‑gap — `services/backlink_gap.py`
We already capture competitors' referring domains + DR/UR in `serp_snapshots`. New: a **link‑gap** computation (domains linking to ≥N competitors but not the client) via **DataForSEO Backlinks API**, ranked by DR + relevance → `backlink` actions (prospect lists; outreach stays manual/assisted). **New external API.**

### 6.4 Local‑citation audit — `services/citation_audit.py`
Check NAP presence/consistency across a directory set (DataForSEO Business Listings or a fixed checklist) → `citation` actions (missing/ inconsistent listings). **New external API (or a static directory list to start, zero‑cost).**

### 6.5 Internal‑linking analyzer + injector — `services/internal_linking.py`
Analyzer builds the site's internal‑link graph from the crawl, finds orphan pages + missing topical links (silo‑aware) → `internal_link` actions. **Injector (autonomous):** for WordPress clients, applies approved link edits via the **existing** `wordpress_publish.py` REST/app‑password path, **as drafts/revisions**, never silently to live. Non‑WordPress → recommend‑only deep links.

### 6.6 Consolidated client report — `services/engagement_report.py`
Composes the existing `rank_report`/`brand_report`/`maps_report` builders + plan progress + `execution_events` into one Google Doc via the shared `google_docs.py`. Async `engagement_report` job; scheduled via `gsc_scheduler`.

---

## 7. The Autonomous Executor — `services/engagement_executor.py`

The heart of "maximally autonomous." A worker that, for an engagement in `executing`, repeatedly:

1. Pulls the next `approved`/`queued` `strategy_action` with `execution_mode = auto`, ordered by priority.
2. **Pre‑flight guardrails** (Section 8): budget remaining? checkpoint required? publish mode? — if blocked, write a `checkpoint`/`budget_halt` event, pause, notify.
3. Dispatches to the category handler (content gen, internal‑link injection, tracking setup, schedule create…), each reusing an existing service/job.
4. Records `execution_events`; on success marks the action `done` and links the produced artifact (draft URL, page id, job id).
5. On failure: retry policy (transient vs terminal, mirroring `brand_scan`/`job_worker` conventions), then mark `blocked` + notify.
6. When the auto‑queue drains → `steady_state`; `assisted`/`manual` actions remain as human to‑dos with deep links.

The executor is **resumable** (state in the DB, not memory) and **idempotent** (actions carry their produced‑artifact ids; re‑running a `done` action is a no‑op).

---

## 8. Autonomy & safety model (because the target is "maximally autonomous")

Autonomy is powerful and expensive; the design makes it **bounded, observable, and reversible.**

- **`autonomy_level` per engagement:** `recommend` (no execution) · `assisted` (auto‑setup + drafts, human publishes) · `autonomous` (executes most, checkpoints only). Default new engagements to `assisted`; the user can opt an engagement up to `autonomous`.
- **Hard consent boundary:** nothing auto‑executes before **plan approval** (gate #2).
- **Publish‑as‑draft by default:** content and internal‑link edits land as **WordPress drafts / Google Docs**, never live, unless `publish_mode = live` is explicitly set. Going live is always a checkpoint.
- **Checkpoints:** configurable pause points (`config.checkpoint_toggles`) — e.g., "pause before first publish," "pause after N pages," "pause before any backlink outreach." The executor stops, emits a `checkpoint` event, and notifies.
- **Budget caps:** per‑engagement spend ceiling for paid API calls (DataForSEO/LLM). The executor checks remaining budget before each paid action and halts with a `budget_halt` event when exhausted — same shape as the Workflow budget pattern. Prevents an autonomous loop from running up cost.
- **Kill switch:** a `POST .../engagement/pause` that flips the engagement out of `executing` and drops queued auto‑jobs (reuse the Maps `cancel_client_scans` pattern).
- **Full audit trail:** every autonomous action writes `execution_events`; the workspace shows a live activity feed and the consolidated report includes "what the system did."
- **Idempotency + dedup** everywhere (the suite's standing convention) so retries/resumes never double‑create.

---

## 9. External dependencies & provisioning (requires user approval)

Per `CLAUDE.md`, new external dependencies and dashboard setup must be confirmed. None of these are new *infrastructure* (no Redis/Celery/queue) — they're additive **API calls** behind best‑effort, creds‑gated paths — but they cost money and need keys:

| New dependency | For | Cost / setup | Status |
|---|---|---|---|
| DataForSEO **OnPage API** | Site/technical audit | Per‑crawl cost; creds already on PLATFORM (DataForSEO shared) | **Ask** (enable endpoint) |
| Google **PageSpeed/Lighthouse API** | Core Web Vitals | Free tier / API key | **Ask** |
| DataForSEO **Backlinks API** | Backlink‑gap | Per‑query cost; shared creds | **Ask** |
| DataForSEO **Business Listings** (or static directory list) | Local citations | Per‑query cost — or $0 with a fixed checklist to start | **Ask / default to static** |
| **Asana** API token + project mapping | Asana sync (deferred) | OAuth/token + dashboard mapping | **Deferred — ask when we get there** |

Everything else (LLM, WordPress, GSC, Outscraper, geocoding) is already provisioned.

---

## 10. Compliance with locked decisions

This design intentionally stays inside the suite's guardrails:

- **No new queue / no Redis/Celery** — the executor and all new work are `async_jobs` consumers; scheduling reuses `gsc_scheduler`.
- **No new infra services** — all new code lives in `platform-api` (services/routers/models), same three‑service topology.
- **Anthropic for generation, DataForSEO for SERP, Google Docs/WordPress for publish** — unchanged.
- **Recommend‑precedent reused** — the Strategy Engine generalizes `reopt_planner`; the plan view generalizes `ActionPlan.tsx`.
- **Best‑effort, creds‑gated, idempotent, degraded‑note** patterns reused throughout.
- **No reversal of any decision‑log item** in `suite-architecture-and-roadmap-v1_0.md`.

---

## 11. Phased roadmap (recommended build order)

Large surface area — built in slices, each shippable and useful on its own.

**Phase 0 — Unified Keyword Portal** (already planned separately). The intake primitive; ships independently.

**Phase 1 — Engagement spine + onboarding wizard + intake.** `engagements` table + state machine, the onboarding wizard with brand‑voice/ICP **approval gates**, and the extended intake. Pure orchestration over existing data; no new external APIs. Delivers the "guided onboard" immediately.

**Phase 2 — Strategy Engine v1 (recommend‑only) + plan review.** Generalize `reopt_planner` to cross‑module using the existing context providers + the *synthesis* audits (2b/2c, no new APIs yet). `strategy_plans`/`strategy_actions`, the generalized plan view, gate #2. This is the brain; valuable even before autonomy.

**Phase 3 — New audit modules.** Site/technical (6.2), backlink‑gap (6.3), local citations (6.4). Each gated on its external‑API approval (Section 9); each feeds richer actions into the engine.

**Phase 4 — Autonomous Executor + internal‑linking injector + consolidated report.** Turn on execution under the Section 8 safety model, starting at `assisted` and graduating to `autonomous`. WordPress internal‑link injection. One consolidated report.

**Phase 5 — Asana sync.** The deferred dispatcher, when the plan format is settled and the account is provisioned.

---

## 12. Open questions / decisions still needed

1. **Default autonomy level** for new engagements — recommend starting at `assisted` (auto‑setup + drafts, human publishes), opt‑up to `autonomous`. Confirm.
2. **External API budget** — OK to enable DataForSEO OnPage + Backlinks (+ PageSpeed)? Or start citations as a $0 static‑directory checklist?
3. **Per‑engagement spend ceiling** default (the budget cap value).
4. **Checkpoint defaults** — which pause points are on by default (e.g., always pause before first live publish?).
5. **WordPress live vs draft default** for autonomous internal‑link edits — recommend draft/revision always.
6. **Asana model** when we build it — one‑way mirror vs. system‑of‑record (user leaned defer; revisit at Phase 5).
7. **One engagement per client** assumption — confirm we never need concurrent engagements per client.

---

*End of design v1.0. Nothing herein is implemented. Next step on approval: pick the first phase to detail into a build plan (recommended: Phase 1, the engagement spine + onboarding wizard).*
