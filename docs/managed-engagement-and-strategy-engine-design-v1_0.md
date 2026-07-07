# The Strategist — Onboarding, Audit, Strategy, Continuous Monitoring & Autonomous Execution (Design v1.1)

> **Status:** Design proposal. **Nothing in this document is built yet.** This is the architecture + phased roadmap for the orchestration layer that turns the AR Tools suite from a toolbox into **"the Strategist"** — a system that creates strategy, **monitors campaigns continuously**, **suggests tweaks and fixes**, executes the automatable work itself, and **assigns the rest to Asana boards**. It sits alongside `docs/suite-architecture-and-roadmap-v1_0.md` (the product/architecture authority for "how many tools is this") and inherits all of that doc's locked decisions and the constraints in `CLAUDE.md`.

> **Scope decisions captured from the user (2026‑06‑28):**
> - **Autonomy target:** *maximally autonomous* — execute the automatable work end‑to‑end with humans approving only at a few checkpoints.
> - **Deliverable:** this design doc; **build nothing yet.**
> - **First‑party data:** connect Search Console, GA4, and the Business Profile Performance API during onboarding (Stage 0b, §6.7).
>
> **Scope decisions captured from the user (2026‑06‑29) — the Strategist framing:**
> - **Role:** this is **the Strategist** — it (1) creates strategy, (2) monitors campaigns, (3) suggests tweaks and fixes, (4) assigns tasks to Asana boards. It runs a **continuous loop**, not a one‑shot setup.
> - **Auto‑vs‑assign split:** **auto the automatable, assign the craft.** The Strategist auto‑executes technical/repeatable work (tracking setup, internal‑link drafts, page generation drafts, on‑page fixes); human‑craft work (content review/publish, outreach, manual fixes) becomes Asana tasks. This is how the `execution_mode` of each action is set.
> - **Asana: promoted from deferred to CORE.** Asana is the **human work surface**, with **role‑based auto‑assignment** (a role→assignee map: writer / SEO‑tech / link‑builder / VA / account‑manager) and **two‑way status sync**. The in‑app plan stays authoritative; Asana mirrors + assigns + reports status back.
> - **Monitoring model:** measure every engagement against a **fixed, universal goal set** — agency standards baked into the system, applied to **every tracked keyword** automatically (not custom per‑campaign KPIs entered at intake): **organic** = rank in the **top 3**; **maps** = **avg top‑3 within a 3‑mile radius** AND **avg top‑5 within a 5‑mile radius**; **LLM** = **appears in every tracked engine** for each keyword (§4.6). **Trend/anomaly detection runs on top** to catch movement *between* passes (e.g. slipping #2→#4). *(This supersedes the earlier "trend/anomaly only, no fixed targets" note — the targets are standard constants, so there's still no per‑campaign goal contract to author.)*

> **Revision history:** v1.0 (2026‑06‑28) — onboarding→audit→strategy→autonomous‑execution spine + first‑party data sources. **v1.1 (2026‑06‑29) — the Continuous Strategist: monitoring & signal bus, continuous‑optimization engine, the Strategist control loop, and Asana‑as‑core with role‑based assignment (§4.5, §6.8–6.10).** Filename retained at `-v1_0` for PR continuity.

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
| First‑party data (Search Console) | `services/gsc_service.py` (agency service‑account connect/verify), `services/gsc_ingest.py`, GSC Research — **GA4 + GBP Performance are NEW siblings (§6.7)** |
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
  id, engagement_id (FK), kind (enum: site_technical | serp_competition |
     maps_competition | performance_baseline),
  status (pending|running|complete|failed), result (jsonb), score (numeric), created_at
  -- one row per audit kind per audit cycle; reruns append
  -- performance_baseline reads the connected GSC/GA4/GBP-Performance ingests (Stage 0b)

strategy_plans
  id, engagement_id (FK), version (int), status (draft|proposed|approved|superseded),
  summary (jsonb: scores, headline findings), approved_by, approved_at, created_at
  -- immutable once approved; amendments create a new version

strategy_actions
  id, plan_id (FK), module (enum: organic | maps | ai_visibility | cross),  -- powers per-module filter views
  category (enum: silo | page | onpage | internal_link | citation |
     backlink | llm_tactic | technical_fix | tracking_setup | schedule | gbp | reviews),
  title, rationale, target (jsonb: keyword/url/location/etc),
  priority (int), effort (enum), est_value (numeric),
  execution_mode (enum: auto | assigned),         -- auto → executor; assigned → Asana task (§4.5)
  assignee_role (enum: writer|seo_tech|link_builder|va|account_manager|null),
  source (enum: initial_plan | strategist_signal), -- created by the audit-time engine or the monitor
  status (proposed|approved|queued|in_progress|assigned|done|blocked|skipped),
  job_id (FK async_jobs, when auto), asana_task_id (text, when assigned),
  result (jsonb), deep_link (text)
  -- the unit the executor OR Asana consumes; mirrors the reopt_planner action shape, generalized

execution_events
  id, action_id (FK), engagement_id, type (started|completed|failed|paused|checkpoint|
     budget_halt|assigned|asana_status),
  detail (jsonb), created_at
  -- the audit trail for autonomous AND assigned work; powers the activity feed + report

strategist_signals                                 -- §6.8 the monitoring/anomaly bus
  id, engagement_id (FK), module (enum: organic|maps|ai_visibility|ga4|gbp_performance|content),
  kind (enum: goal_gap|regression|win|anomaly|plateau|new_competitor|cannibalization|coverage_loss|...),
  metric, direction, magnitude (numeric), goal_target (numeric), goal_state (met|close|gap|null),
  baseline_ref (jsonb), detected_at, algo_update_id (FK algo_updates, nullable — §6.11),
  status (open|actioned|dismissed|resolved), action_id (FK strategy_actions, when actioned)
  -- goal_gap = distance from the fixed goal set (§4.6); others = trend/anomaly vs baseline
  -- algo_update_id set when a regression cluster correlates to a Google update (§6.11)
  -- generalizes the existing rank_alerts; feeds the continuous-optimization engine

role_assignees                                     -- routing map for Asana auto-assignment
  id, client_id (FK, nullable → agency default when null),
  role (enum: writer|seo_tech|link_builder|va|account_manager),
  asana_user_gid (text), email (text)
  -- assigned actions route category → role → this assignee

engagement_asana                                   -- per-engagement Asana board mapping
  engagement_id (FK, PK), workspace_gid, project_gid (the board),
  section_gids (jsonb: category → section/column), custom_field_gids (jsonb), synced_at
```

`strategy_actions` is deliberately a **superset of the existing `reopt_plans` action shape** so the generalized engine (Section 6.1) can absorb the rank‑tracker's existing logic without a parallel model. The `execution_mode` is now binary — **`auto`** (the executor runs it, §7) or **`assigned`** (becomes a role‑routed Asana task, §4.5/§6.10) — encoding the "auto the automatable, assign the craft" decision.

---

## 4. The lifecycle stages in detail

### Stage 0 — Onboarding (mostly exists; add a wizard + approval gates)

**Goal:** GBP and/or website in → approved brand voice + ICP out → **first‑party data sources connected**.

- Wrap existing pieces in a guided, multi‑step **Onboarding wizard** (today it's one flat `ClientForm`): Business → Voice → ICP → Reference pages → **Connect data** → Targets.
- **Reuse:** GBP picker/resolve, auto website scrape, page‑structure scrape, the brand‑voice and ICP scan/accept services — all already there.
- **New behavior:** make brand voice and ICP **approval gates**. The wizard requires an explicit "Approve voice" / "Approve ICP" before the engagement can leave `onboarding`. (Data already supports this — `brand_voice.recommended_accepted`, `detected_icp.source`; we add the gate, not the storage.)
- **New step — connect first‑party data (Stage 0b below):** the wizard's "Connect data" step links the client's **Search Console**, **Google Analytics (GA4)**, and **Business Profile Performance** so every downstream audit, the strategy engine, and reporting are grounded in the client's *own* numbers, not just third‑party SERP/Maps estimates.
- **Output:** `engagements.status = intake`.

### Stage 0b — Connect first‑party data sources (GSC existing; GA4 + GBP Performance NEW — Section 6.7)

**Goal:** authoritative first‑party performance data wired in during onboarding, on the suite's existing **agency service‑account** model wherever the API allows (locked decision: service account, no interactive OAuth).

These three sources are *authoritative ground truth* about how the client is actually performing — they outrank third‑party estimates (DataForSEO/SERP snapshots) when both are present. They feed the **performance baseline** the audits and strategy engine read (Stage 2), and they enrich the consolidated report (Stage 7).

| Source | Status | What it adds | Connection model | Stored on |
|---|---|---|---|---|
| **Search Console** | ✅ Exists (`services/gsc_service.py`, `gsc_ingest.py`, GSC Research) | Query×page impressions/clicks/position, indexation (URL Inspection), opportunity analysis | Agency **service account** (`client_email` added as a property user); app‑level key in `settings.google_service_account_key` | `clients.gsc_property` + `gsc_*` tables |
| **Google Analytics (GA4)** | ❌ NEW | Sessions, channel mix, landing‑page traffic, **engagement + conversions/key events** (which pages actually convert) — the demand/value layer the suite has no first‑party read of today | GA4 **Data API** supports a **service account** added as a *Viewer* on the property → reuse the same agency‑SA pattern as GSC (no new auth infra) | new `clients.ga4_property_id` + `ga4_*` ingest tables |
| **Business Profile Performance** | ❌ NEW | Real GBP **performance** metrics — profile impressions (Maps vs Search), calls, direction requests, website clicks, bookings, search‑keyword breakdown — vs. the current Outscraper/DataForSEO *profile + reviews* scrape, which has none of this | Google's **Business Profile Performance API** is OAuth‑centric (a Google account with **manager** access to the location); service‑account access is **not** generally supported — **decision needed** (Section 12 Q8). Falls back to the existing scrape if not connected | new `clients.gbp_performance_location_id` + `gbp_performance_*` ingest tables |

**Connection UX (wizard "Connect data" step):** per source — show connection status, the agency service‑account email to grant (GSC/GA4), a verify‑access check (reuse the `gsc_service.verify_access` shape), and for GBP Performance the OAuth‑connect affordance *if* we land on OAuth. Every source is **optional and best‑effort** — onboarding completes without them; an unconnected source just narrows the baseline and is flagged in the plan (degraded note), exactly like the existing GSC "not configured" state.

**Ingest:** each connected source gets a periodic pull on the **shared `gsc_scheduler`** (GSC ingest already runs there; GA4 + GBP Performance add `ga4_ingest` / `gbp_performance_ingest` jobs alongside it — no new infra), materializing a rolling window the audits read.

### Stage 1 — Intake (the Unified Keyword Portal, extended)

**Goal:** capture *what* to rank for and *where*.

- Builds directly on the **Unified Keyword Portal** already planned (one textarea → fan out to `tracked_keywords` / `maps_keywords` / `brand_tracked_keywords`, idempotent, with per‑target scan kickoff).
- **Extend** it with: topic/service framing (not just bare keywords), per‑target geography (reuse `target_cities` + `services/target_cities.py` multi‑city discovery), and a "this is for engagement X" link so intake feeds the audits.
- **Also capture the team routing map** (`role_assignees`) — the Asana assignee per role (writer / SEO‑tech / link‑builder / VA / account‑manager), so `assigned` actions can auto‑route from day one. Defaults to the agency‑level map when a client doesn't override.
- **No goal/target entry** — per the trend/anomaly decision, intake captures *what* and *where*, not numeric KPI targets. The baseline (audit 2d) is the reference the monitor compares against.
- **Output:** target set + routing persisted; `engagements.status = auditing`.

### Stage 2 — Audits (parallel; one `audit_runs` row each)

**Four** audits fan out concurrently via `async_jobs` (the three competitive/technical audits plus the first‑party **performance baseline**). Each is best‑effort and isolated — a failing audit degrades the plan, never blocks it (same resilience pattern as the Slack context providers and Local SEO planner). The competitive audits read the **performance baseline** (2d) so they can weight findings by the client's actual traffic/conversions, not just SERP position.

**2a. Site / technical audit — NEW (Section 6.2).** Crawl the client site (sitemap‑seeded via existing `services/site_page_index.py`), pull on‑page + technical signals. Sources: **DataForSEO OnPage API** and/or **Google PageSpeed/Lighthouse** (new external calls — see Section 9). Produces: indexability issues, meta/title gaps, heading/schema gaps, broken links, Core Web Vitals, thin/duplicate content, internal‑link graph snapshot. Cross‑references **GSC indexation** + **GA4 landing‑page traffic** to flag "high‑traffic page with technical problems" first.

**2b. Organic SERP competition audit — SYNTHESIS of existing + first‑party.** For each target keyword, compose existing `serp_snapshot` (top‑10 + DR/UR/referring domains + intent + topical focus), `rankability` (client‑relative difficulty + quick‑win signal), and `serp_trends` — now grounded by **GSC** (the client's real impressions/clicks/position for that query) and **GA4** (does the ranking page actually convert). New work = **rolling it up** into "where can we win, how hard, against whom, with what content shape — and what it's worth," with first‑party clicks/conversions replacing estimated value where available.

**2c. Maps competition audit — SYNTHESIS of existing + first‑party.** Where the client targets local, compose the geo‑grid scan + `maps_analytics` rollups + weak‑zone geocoding into "coverage gaps and the competitors owning them," now anchored by **GBP Performance** (real impressions/calls/direction‑requests/website‑clicks and the search‑keyword breakdown) so weak grid zones are prioritized by lost *local conversions*, not just rank. Reuses `local_dominator` + `maps_report` building blocks.

**2d. Performance baseline — NEW (reads Stage 0b sources, no competitive scraping).** A first‑party snapshot assembled from the connected GSC + GA4 + GBP Performance ingests: traffic + channel mix + conversions (GA4), query/page impressions‑clicks‑position (GSC), and local actions (GBP Performance). This is both the **engagement's starting line** (so progress is measurable in the client's own numbers) and the **weighting layer** the other three audits and the strategy engine consume. Degrades gracefully per unconnected source.

**Output:** up to four `audit_runs` rows; `engagements.status = strategizing`.

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

The **Executor** drains `strategy_actions` where `execution_mode = auto` (the "automatable" half of the split), respecting guardrails (Section 8). It dispatches each action to the tool that does it — content generation (Blog Writer / Local SEO generator), internal‑link injection (WordPress), tracking/schedule setup, on‑page fixes — as `async_jobs`, writing `execution_events` for the audit trail. **Publishing defaults to drafts**; going live is a checkpoint. Actions marked **`assigned`** are NOT touched by the executor — they go to Asana (§6.10) for the assigned role. → `steady_state` (the §4.5 loop) when the auto‑queue drains; assigned tasks live on in Asana with their status synced back.

### Stage 7 — Reporting + re‑planning

- **Consolidated client report (NEW — Section 6.6):** one Google Doc composing the existing rank/maps/brand report builders + the engagement's execution activity + plan progress. Delivered on the existing scheduler + notification channels.
- **Re‑planning loop:** existing rank‑drop alerting + reopt signals + scheduled re‑audits feed plan **amendments** that re‑enter `plan_review`. The engagement never "finishes."

### Stage 8 — Asana assignment (CORE — Section 6.10)

The human work surface. On provisioning, the engagement gets (or maps to) an **Asana board** (`engagement_asana`). Every `strategy_action` with `execution_mode = assigned` becomes an **Asana task**, **role‑routed** via `role_assignees` (category → role → assignee), placed in the board section for its category, with priority/effort as custom fields and a due date from the cadence. **Two‑way status:** a task moving to done in Asana flows back (`asana_status` event → action `done`), which the monitor then watches to confirm the fix actually moved the metric. Built as a notifications‑style **dispatcher** (`services/asana_sync.py` + `asana_sync` job), creds‑gated like Slack/email. The in‑app plan stays authoritative; Asana is the assignment + execution‑tracking layer. Requires an Asana token + workspace/board mapping (one‑time setup — Section 9).

---

## 4.5 The Continuous Strategist loop (steady‑state)

`steady_state` is not an end — it is the Strategist *running the campaign*. On a cadence (default weekly per engagement, on the shared `gsc_scheduler`), the Strategist executes a closed loop:

```
 monitor ─▶ detect ─▶ diagnose ─▶ amend plan ─▶ split ─▶ act / assign ─▶ report
 (§6.8)    signals   (§6.9)      strategy_actions   auto│assigned       digest
    ▲                                                                      │
    └───────────────── confirm effect on next monitor pass ◀──────────────┘
```

1. **Monitor (§6.8).** The cross‑module monitor pulls fresh data (rank, geo‑grid, AI‑visibility, GA4, GBP‑Performance, content) and compares **current vs. baseline** — **trend/anomaly only, no fixed targets**. It writes typed `strategist_signals` (regression / win / anomaly / plateau / new‑competitor / cannibalization / coverage‑loss). This **generalizes the existing `rank_alerts`** into one bus.
2. **Diagnose + tweak (§6.9).** The continuous‑optimization engine turns each open signal into a *specific, diagnosed* `strategy_action` (e.g. "organic clicks for X fell 40% and position slipped 3→7 → reoptimize page Y"), **deduped against already‑open actions**, prioritized by magnitude × value.
3. **Split — auto the automatable, assign the craft.** Each new action's `execution_mode` is set: technical/repeatable → **`auto`** (executor, §7); human‑craft → **`assigned`** (role‑routed Asana task, §6.10).
4. **Act / assign.** Auto actions run under the guardrails (§8); assigned actions appear on the right person's Asana board.
5. **Report (Strategist digest).** A periodic narrative — "what I saw, what I changed, what I assigned, what I'm watching" — over the existing notification channels (Slack live, email deferred, in‑app) + the consolidated report (§6.6). This is the "communicates all this" requirement.
6. **Confirm.** The next monitor pass checks whether actioned signals actually resolved (the lightweight effectiveness check; full attribution‑learning is a v2 follow‑up).

Material changes (a big new opportunity or a severe regression cluster) re‑enter **`plan_review`** for human approval; routine tweaks flow straight through under the engagement's autonomy level. The loop only stops when the engagement is paused or closed.

---

## 4.6 The goal model — standard success definitions

The Strategist measures every engagement against a **fixed, universal goal set** — agency standards (tunable constants in `config.py`, **not** authored per client). Goals are evaluated **per tracked keyword**, per module:

| Module | Goal (per tracked keyword) | Source / computation |
|---|---|---|
| **Organic** | Rank in the **top 3** | latest position ≤ 3 from `rank_keyword_metrics` (GSC / DataForSEO via `rank_status`) |
| **Maps** | **Avg top‑3 within 3 mi** **and** **avg top‑5 within 5 mi** | mean cell rank over the geo‑grid cells inside each radius ring (`maps_analytics` rollups); target mean ≤ 3 (3‑mi ring) and ≤ 5 (5‑mi ring) |
| **LLM** | **Appears in every engine that returned an answer** (all 6) | `brand_mention_history`: `mentioned = true` for each engine in the latest scan batch — but an engine that **didn't trigger** for the query (notably **Google AI Overview**, which often isn't shown) is **excluded from the bar**, not counted as a miss |

Each keyword rolls up to a per‑module **attainment state** (`met` / `close` / `gap`), and the engagement gets an overall **attainment %** = share of keyword×module goals met. The monitor (§6.8) recomputes attainment every pass and emits a `goal_gap` signal for any keyword×module not at target; the optimizer (§6.9) prioritizes the **largest gaps to goal** (weighted by `est_value`), so the plan is always driving toward these three bars. Trend/anomaly signals run alongside to catch *movement* even within a band (a slip from #2→#4 is still a regression worth acting on before it crosses the goal line).

**Computation rules (resolved 2026‑06‑29):**
- **Maps radius coverage — ✅ settled:** engagement geo‑grids are **already 5‑mile**, so both metrics come from one scan — the 5‑mile average over all in‑grid cells, and the 3‑mile average over the **inner subset** of cells within 3 mi of center. No config change needed.
- **"Avg top‑N" definition + absent‑cell penalty — ✅ settled at 21:** the mean *position* across in‑ring grid cells must be ≤ N ("avg top‑3" = average rank ≤ 3). A cell where the business **doesn't appear** in the local pack scores **21** in the average (consistent with how `maps_analytics` treats absent cells), so coverage gaps pull the average down meaningfully.
- **"Each LLM" — ✅ all six, minus non‑triggering engines:** the bar is **all six engines** (chatgpt, claude, gemini, perplexity, google_ai_overview, google_ai_mode). But an engine that **didn't produce an answer** for the query — chiefly **Google AI Overview**, which frequently doesn't trigger — is **dropped from the denominator** for that keyword on that pass; "met" = mentioned in every engine that *did* answer. **Required change (confirmed):** today, when no AIO is shown, `brand_scan._extract_dataforseo_ai` (`brand_scan.py:147‑154`) synthesizes a "does not appear" answer that the classifier records as **`mentioned = false`** — i.e. a *miss*. The goal model needs a distinct per‑engine **`triggered`/`not_shown`** flag so the no‑AIO case is **excluded** from the LLM bar instead of scored against it. Small, localized addition to the scan result + `brand_mention_history`.
- **Scope:** targets are **global constants** (tunable in `config.py`); a per‑client override stays deferred unless you ask for it.

---

## 4.7 SerMaStr — the organic strategy input contract

**Naming:** **SerMaStr** ("Search Engine Strategist") is the strategy **brain** (the §6.1 Strategy Engine + §6.9 optimizer). The existing Slack assistant **"SerMastr"** (`services/slack_assistant.py`) becomes its **voice** — i.e. SerMaStr reasons; SerMastr-the-bot reports/answers. *(Same portmanteau, near‑identical spelling — confirm we want them unified under one brand vs. distinct names; open question.)*

Strategy = **method × evidence.** The **method** is the team's **SEO SOPs** (a `seo_sops` store, ingested later — loaded into SerMaStr's reasoning/system prompt as the house playbook for *how* to strategize). This section defines the **evidence** — what SerMaStr reads to *create or tweak an organic strategy* — and the few new inputs it needs. Decisions captured 2026‑06‑29:

| Input | What SerMaStr uses | Source | Status / decision |
|---|---|---|---|
| **Ranking picture** | per‑keyword status/position/trend, alerts, striking distance, pages, the **Action Plan** (already‑synthesized reopt recommendations) | the rank tracker via the existing `organic_rank` context provider | ✅ Exists — richest of the three trackers (see the §4 rank‑module inventory) |
| **Value weighting** | `est_monthly_value` = search_volume × position‑CTR curve × CPC | `keyword_market` | ✅ **Decided: CPC/volume proxy only** — no manual per‑service value capture, and **GA4 is not required** for organic prioritization (GA4 still feeds the baseline/monitoring, just not the weighting) |
| **Demand map (generative)** | the **full** topic/keyword universe — discover what to target + which silos to build, not just tracked keywords | wire in **keyword research / Fanout** + striking distance + GSC Research | 🟡 **Decided: generative** — Strategy Engine pulls the demand universe and recommends targets; new wiring (Fanout exists, not yet a strategy input) |
| **Competitive benchmark** | top‑10 incumbents, per‑page RD/UR/backlinks, per‑domain DR, specialist‑vs‑generalist | **SERP snapshots** | ✅ **Decided: SERP‑derived only** — no named‑competitor capture |
| **Site & content state** | existing pages ↔ target keyword, silo/architecture, **internal‑link graph**, content age/quality | `site_page_index` + `page_structures` + GSC query×page (have); link graph + content audit (planned §6.2/§6.5) | 🟡 Partial — deepens as the audit modules land |
| **Authority / off‑site** | client backlink profile, link gap, local citations | SERP snapshots (competitor + client ranking page) today; planned backlink/citation modules (§6.3/§6.4) | 🟡 Partial / planned |
| **Technical / index baseline** | crawl, indexation, CWV, schema | URL Inspection (have) + planned site audit (§6.2) | 🟡 Partial / planned |
| **Capacity & constraints** | content/month, publishing cadence, link/tool budget, **off‑limits tactics**, risk tolerance, dev resources | **NEW per‑client capture** | ❌ **Decided: capture per client** → store on `engagements.config` (or `clients`); SerMaStr plans **within** these limits and respects house rules |
| **History & memory** | past actions + whether they worked; algo‑update timeline | `execution_events` + the monitor (forward‑looking); algo timeline optional | 🟡 Forward‑looking; historical import deferred |

**Net‑new to build for the organic input contract:** (1) a **per‑client capacity/constraints** capture (small form + `engagements.config` fields); (2) the **`seo_sops` store** + its load into SerMaStr's reasoning (when you provide the SOPs); (3) **wiring keyword‑research/Fanout** in as the generative demand‑map source. Everything else SerMaStr already has or gets from planned modules — confirming that the organic side is mostly *consume, don't rebuild*.

---

## 4.8 Maps — SerMaStr input contract + the Maps gap decisions

Maps hands SerMaStr a **strategist‑ready *local* picture** — rank at every grid cell, ring (distance) + octant (direction) analytics, a performance horizon, **geocoded weak zones (real city names, priority‑ranked) + octant pins (exact lat/lng to place pages)**, a competitor leaderboard + per‑weak‑sector rivals + **review‑gap diagnostics**, and **competitor‑momentum + per‑keyword coverage trends over ≤52 scans**. It is the **local analog** of the organic tracker: different ranking signals (proximity / reviews / category / GBP completeness, *not* links/content depth), so SerMaStr drives it from the **local branch of the SOPs**, and it is **thinner on synthesis** than organic (no winnability band, no alerting, no action plan). The line‑by‑line gap decisions (2026‑06‑29):

- **Value/demand weighting — ❌ won't build.** No reliable local search‑volume/CPC at suburb granularity. Maps prioritization uses the **opportunity score × proximity** already computed in `maps_geocode.extract_weak_cells` (`severity × proximity × beatability × core_adjacency`), not `est_value`.
- **Alerting — ✅ build, mirroring the organic `rank_alerts` system** (spec below).
- *Winnability band* — pending (ingredients are latent in `beatability`/proximity/severity; could surface as a 0–100 local band like `rankability`).
- *Signal‑bus / action‑plan wiring* — pending (today Maps feeds neither alerts nor the reopt planner).
- *3mi/5mi goal rollup* — pending (the inner‑subset average flagged in §4.6).
- *Cross‑channel competitor unification* — pending.

### 4.8.1 Maps alerting spec — mirror of `rank_alerts`

Built as a faithful port of the organic alerting pattern (`services/rank_alerts.py` + the `rank_materialize` reconcile + `notifications.emit`), adapted from *position* to *spatial coverage*:

- **New `maps_alerts` table** — same shape as `rank_alerts`: `client_id`, `keyword`, `alert_type`, `from_value`, `to_value`, `delta`, `message`, `details` (jsonb), `status` (`unread`|`read`|`dismissed`), `triggered_on`, `resolved_at`, `read_at`, `dismissed_at`. (Values are coverage %/avg‑rank/beats‑% rather than SERP position.)
- **Producer** — hook the scan‑complete path (`local_dominator.poll_pending_maps_scans` → after `_store_results`) into a new `reconcile_maps_alerts(client_id)`, exactly as `rank_materialize` reconciles `rank_alerts`. It compares the **latest completed scan vs. the prior scan** (scans are already weekly aggregates, so no extra smoothing needed) using the existing `build_maps_trends` + `competitor‑trends` series.
- **Episode model — identical:** at most one open alert per `(client_id, keyword, alert_type)`; opened when the condition first holds, **auto‑resolved** when it clears on a later scan.
- **Delivery — reuse `notifications.emit`** (in‑app + Slack live; email deferred) with `critical` vs `warning` severity, the same path organic uses. This makes Maps a **second notifications producer** and a ready **producer for the SerMaStr signal bus (§6.8)** — `reconcile_maps_alerts` is the seam the cross‑module monitor later absorbs into `strategist_signals` (`coverage_loss`, `new_competitor`, `goal_gap`).
- **Alert types + thresholds (✅ set confirmed 2026‑06‑29; config‑tunable `maps_alert_*`):**
  | Alert type | Trigger (scan‑over‑scan) | Severity |
  |---|---|---|
  | `coverage_drop` | top‑3 coverage % fell ≥ N points vs prior scan | warning |
  | `pack_exit` | top‑3 coverage was ≥ X%, now < Y% (lost the pack across the grid) | critical |
  | `avg_rank_drop` | average grid rank worsened ≥ M positions | warning |
  | `competitor_surge` | a competitor's beats‑% rose ≥ P points, or a new rival overtook on > Q% of pins | warning |
  | `zone_loss` | a previously‑ranked geocoded weak‑area / octant went **fully unranked** vs the prior scan (was ≥ 1 ranked pin, now 0) | warning → **critical** if the lost area is in the inner rings (proximity‑weighted) |

  (`coverage_drop`/`pack_exit`/`avg_rank_drop` mirror organic's `weekly_drop`/`page_one_exit`/`thirty_day_drop`; `competitor_surge` and `zone_loss` are the local‑specific additions with no organic equivalent. **`zone_loss` re‑added 2026‑06‑29:** it catches a *localized* area you held going dark even when grid‑wide `coverage_drop`/`pack_exit` don't fire — computed scan‑over‑scan from the geocoded `weak_areas`/octants (§4.8.3 geometry), severity **proximity‑weighted** (critical when the lost area sits in the inner rings, since nearby coverage matters most). It emits a `coverage_loss` `strategist_signal` and feeds a **restore** action — `maps_reoptimize_page` if the client has a page for that area, else `maps_competitor_threat` when a rival took it (§4.8.4).)

**Build timing — ✅ decided: spec now, build with the signal bus.** Maps alerting stays design‑only for now; it's implemented in **Phase 5** alongside the cross‑module monitor (§6.8) so the alert producer and the `strategist_signals` bus are built **once**, not twice. `reconcile_maps_alerts` is authored as the Maps detector inside `strategist_monitor`, emitting both `maps_alerts` rows (the in‑app/Slack feed, via `notifications.emit`) and the corresponding `strategist_signals`.

### 4.8.2 Local winnability ("maps rankability") — ✅ design settled

A transparent, **no‑LLM** 0–100 score + band per tracked Maps keyword, computed from the latest scan result (`rank_grid` + `competitors` + `report_analytics` + `report_weak_locations`) + client GBP (rating/reviews/category). Mirrors organic `rankability` in structure + bands, but built from **local** ranking signals (relevance / distance / prominence), **not** links. Much of the math is **latent** — `maps_geocode.extract_weak_cells` already yields per‑cell `severity`, `proximity`, `beatability`, `core_adjacency`; this engine reuses them and adds competitor‑prominence + relevance + crowding.

**Five blended sub‑scores** (each 0–100; weights sum to 1.0; renormalized if a factor is unavailable):

| Factor (weight) | Measures | Source | Organic analog |
|---|---|---|---|
| **Competitor beatability — prominence gap (0.30)** | how weak the dominant incumbents' review prominence is vs the client | `competitors` leaderboard rating/reviews + existing `beatability` review‑gap | competition weakness (was backlinks) |
| **Proximity advantage — distance (0.20)** | weakness near the business (winnable) vs only at the far ring (distance‑bound → needs a new/SAB location) | per‑cell `proximity` + ring distribution of weakness | *local‑specific (no organic analog)* |
| **Current standing + momentum (0.20)** | how close already — top‑10 coverage + avg rank + "edge of pack" cells (rank 4–10) | `rank_grid`, `report_analytics` | client capability + momentum |
| **Relevance gap — category/name (0.15)** | does the client's GBP category/name fit the keyword better than incumbents (off‑category/generalist rivals = opening)? | competitor `primary_category` + name‑keyword‑hit vs client category | topical opening / targeting gap |
| **Pack crowding (0.15)** | top‑3 locked by the same few strong rivals everywhere (hard) vs fragmented/volatile (easier) | competitor concentration + coverage variance | SERP crowding |

**Bands** (same as organic): 70–100 Easy · 50–69 Moderate · 30–49 Hard · 0–29 Very hard.

**Winnability ≠ opportunity (important):** the existing **opportunity** score (`severity × proximity × beatability`) answers *"where to attack and how much is left to gain"*; **winnability** answers *"how likely can we take the pack here."* They share beatability + proximity, but winnability *rewards* current standing where opportunity *rewards* current weakness — a distinct composite, not a rename.

**Output** (mirror `RankabilityResponse`): per keyword `{keyword_id, keyword, has_data, score, band, factors:[{text, direction}], top3_coverage, avg_rank, priority}`. `has_data=false` until a completed scan exists (like organic needs a SERP snapshot).

**Quick‑wins priority — ✅ decided: `winnability × gap‑to‑goal × proximity`.** No $ value (per the value decision); instead the sort rewards keywords that are **winnable AND far from the goal bars AND close to home** — `gap‑to‑goal` = distance from the 3mi‑top‑3 / 5mi‑top‑5 targets (§4.6), `proximity` weights nearby gains. Quick wins = Easy/Moderate band + score ≥ 50, sorted by this priority. Ties the local winnability layer **directly to the goal model**.

**Engine:** `services/maps_rankability.py` (pure; no LLM, no new external calls — all from stored scan data + GBP). API `GET /clients/{id}/maps/rankability`, mirroring the organic endpoint. Feeds the optimizer's **local Quick Wins** (§6.9) the same way organic `rankability` feeds the reopt planner. **Build timing:** spec now; implemented alongside the Maps signal/optimizer wiring (Phase 5).

### 4.8.3 The 3mi / 5mi goal rollup — ✅ design settled

The exact computation behind the Maps half of the goal model (§4.6): **avg top‑3 within 3 mi** and **avg top‑5 within 5 mi**, per tracked keyword, from the stored `rank_grid`.

**Pure helper** `maps_analytics.compute_goal_metrics(rank_grid, absent_penalty=21)` (no I/O; lives beside the existing `build_geogrid_analytics`):
- Grid geometry from the array itself: `grid_size = len(rank_grid)`, `center = (grid_size − 1) / 2`; each cell's distance from center in miles is `hypot(row − center, col − center)` (1‑mile pin spacing).
- **In‑circle test** distinguishes the two kinds of empty cell: a cell counts only if `distance ≤ radius_miles` (drops the corner cells masked out of the inscribed circle); **within that disc, an unranked cell is scored `21`** (the §4.6 absent‑cell penalty), a ranked cell uses its value.
- `avg_rank_3mi` = mean scored rank over cells with `distance ≤ 3.0`; `avg_rank_5mi` = mean over cells with `distance ≤ 5.0` (which, for a 5‑mile engagement grid, is every in‑circle cell).
- Returns `{avg_rank_3mi, avg_rank_5mi, cells_3mi, cells_5mi, goal_3mi_met (≤3), goal_5mi_met (≤5), goal_state}` where **`goal_state` requires BOTH** sub‑goals (§4.6 is an AND): `met` (both pass) · `close` (within `maps_goal_close_band`, default +2, of either target) · `gap` (beyond). 

**Why it's new, not the existing average:** the stored `maps_scan_results.average_rank` and `analytics.overall.avg_rank` are means over **ranked pins only** (absent cells excluded) — fine for "how good are we where we show up," but they'd **understate the goal gap**, since not appearing in an area is exactly the failure the goal penalizes. The goal rollup therefore includes absent in‑disc cells at `21`. (Boundary is inclusive, `≤`; pins sit at integer offsets so e.g. a `(2,2)` pin at 2.83 mi counts toward 3 mi, a `(3,1)` pin at 3.16 mi does not.)

**Surfacing:** persisted into the existing `report_analytics` JSONB as a `goal_metrics` block (computed when the report runs), exposed on the Maps API, fed to the monitor's `compute_goal_state(keyword, 'maps')` (§6.8) for `goal_gap` signals, consumed by the winnability **gap‑to‑goal** sort (§4.8.2), and shown in the **goal‑attainment scorecard** (§6.6). **Degrades** if a client's grid is < 5 mi (the 5‑mi metric is unavailable — engagement grids default to 5 mi, so this is the exception, flagged not fatal). **Build timing:** spec now; lands with the goal‑model/monitor work (Phase 2/5).

### 4.8.4 Maps signal → action wiring (the local action vocabulary) — ✅ design settled

Closes the Maps loop: the detectors (§4.8.1 alerts), winnability (§4.8.2), goal rollup (§4.8.3), and geocoded weak zones become `strategy_actions` in the optimizer (§6.9) / strategy engine (§6.1). Mirrors the organic reopt vocabulary, but with **local levers** (GBP / reviews / location pages / proximity), not links/content‑depth. **Every action serves closing the 3mi‑top‑3 / 5mi‑top‑5 goal gap**; create/reoptimize actions sort by the winnability priority (winnability × gap‑to‑goal × proximity, §4.8.2).

| Action kind | Trigger signal | Recommendation | Routes to | `execution_mode` · role |
|---|---|---|---|---|
| `maps_pack_exit` | `pack_exit` alert (coverage collapse) | **diagnose & restore first** — check GBP suspension/edits, NAP consistency, a category change, *then* content | Maps report + GBP | **assigned** · account_manager · **critical** |
| `maps_competitor_threat` | `competitor_surge` alert / new dominant rival | diagnose what the rival changed (reviews, new page, category) and counter | Maps report / snapshot | **assigned** · account_manager · warning |
| `maps_reoptimize_page` | winnability quick‑win where a page already exists, **or** `coverage_drop`/`avg_rank_drop` alert on a keyword with a page | reoptimize the existing local page | Local SEO **reoptimize‑by‑URL** | **auto** score → **assigned** edit · writer |
| `maps_coverage_gap` | high‑priority geocoded `weak_area` / octant pin, winnable, **no existing page** | create a location/area page for `{city}` (uses the octant‑pin coords + weak‑area names) | Local SEO content (**city silo / bulk‑create**) | **auto** draft → **assigned** review · writer |
| `maps_review_gap` | weak‑sector rivals with a large `review_gap` / low prominence factor | run a review‑generation + response campaign to close the prominence gap | assigned task (+ GBP data) | **assigned** · account_manager/va |
| `maps_gbp_optimization` | low relevance factor (category/name mismatch) or competitor name‑keyword advantage | tune GBP categories / services / description / posts / photos | assigned task (deep‑link GBP) | **assigned** · account_manager |
| `maps_proximity_gap` | weakness concentrated at the **far ring only** (distance‑bound; low proximity factor) | **advisory** — consider an SAB/satellite location; *don't* spend page effort that can't rank by distance | assigned advisory | **assigned** · account_manager · low |

**Tiering (sort, like organic):** `maps_pack_exit` (critical) > alert‑driven `maps_competitor_threat` / `maps_reoptimize_page` (warning) > goal‑gap `maps_coverage_gap` + winnability quick‑wins > supporting `maps_review_gap` / `maps_gbp_optimization` > `maps_proximity_gap` (advisory).

**Dedup:** a keyword already surfaced as an alert is excluded from the winnability quick‑win list for the same keyword (urgency wins — same rule as organic); `maps_coverage_gap` is deduped against existing `local_seo_pages` + already‑open actions (never recommend a page that exists or is queued); and **cross‑module** against organic page work on the same URL/topic so SerMaStr doesn't double‑assign.

**Routing note:** `maps_reoptimize_page` and `maps_coverage_gap` route into **existing tools** (the Local SEO content module's reoptimize / city‑silo bulk‑create — which already run as background jobs), so their "auto" half is real today; `maps_review_gap` / `maps_gbp_optimization` / `maps_competitor_threat` / `maps_proximity_gap` are **assigned‑only** (no in‑app tool, and real reviews can't be auto‑generated) — they become role‑routed Asana tasks carrying the diagnostic data. Publishing any generated page stays a checkpoint (§8).

**Data‑model touch:** extend `strategy_actions.category` with **`gbp`** and **`reviews`** (local‑page create/reoptimize reuse `page`); the `maps_*` kinds live in the action's `kind`/`rationale`, mirroring how the organic reopt kinds do. **Build timing:** spec now; built with the Maps optimizer wiring (Phase 5).

### 4.8.5 Cross‑channel competitor unification — ✅ design settled

**Problem:** today the same rival is **three disconnected identities** — a **domain** in organic (`serp_snapshot_domains`: DR/RD/backlinks), a **GBP `place_id`** in Maps (`competitors`: rating/reviews/category/beats‑%/avg grid rank), and a **brand name** in AI‑visibility (`brand_tracked_competitors`). SerMaStr would treat one company as three separate threats and miss "this same competitor beats you *everywhere*."

**Solution — a unified `client_competitors` entity** per client, keyed on the **registrable domain** (eTLD+1):

```
client_competitors
  id, client_id (FK), canonical_name,
  domain (eTLD+1 — the canonical join key), gbp_place_id (nullable),
  present_organic (bool), present_maps (bool), present_ai (bool),
  metrics (jsonb: organic {dr, rd, keywords_outranking}; maps {rating, reviews,
     primary_category, beats_pct, avg_grid_rank, top3_pins}; ai {mention_rate, engines}),
  source_refs (jsonb: back-links to the channel rows), updated_at
```

**Resolution** — `services/competitor_graph.py` (pure helpers):
- **Domain normalization** to the registrable domain (eTLD+1) is the primary key. Maps `competitor.website` → domain ↔ organic `serp_snapshot_domains.domain`.
- **Maps ↔ Organic auto‑merge** on matching domain — deterministic, no fuzz.
- **Multi‑location collapse:** several GBP `place_id`s sharing one domain fold into **one** competitor (a multi‑branch brand).
- **Aggregator/directory exclusion:** drop Yelp / YellowPages / Facebook / Angi / etc. via a maintained list — they rank organically but are **citation surfaces, not business rivals** (this also keeps them out of the local‑citation module, §6.4).
- **Maps competitor with no website** → stays **Maps‑only** (keyed by `place_id`); common for hyper‑local rivals.

**AI‑visibility leg — ✅ resolved in §4.9.4:** `brand_tracked_competitors` already carries `competitor_website` + `google_place_id` (stored today, just unused in scan logic), so the AI competitor joins **deterministically** on domain/place_id (name fallback) — no fuzzy matching needed. `present_ai` flips true when a unified competitor appears in `competitor_results`. See §4.9.4.

**Consumers:** a build job on the monitor cadence upserts `client_competitors`; consumed by the **strategy engine/optimizer** (a unified "beats you across channels" view → *coordinated* actions, e.g. one competitor‑teardown brief instead of three disconnected ones), the **consolidated report** (one competitor table), and a Slack **`competitors`** context provider.

**Minor open items:** (1) registrable‑domain parsing needs public‑suffix handling — a small lib (`tldextract`) vs. an embedded PSL heuristic, decided at build; (2) the source/maintenance of the aggregator‑exclusion list. **Build timing:** spec now; Phase 5 (with the monitor); AI leg attaches during the LLM tracker pass.

### 4.8.6 Maps synthesized action plan — ✅ decided: feed the unified plan only

§4.8.4 defined the Maps action *vocabulary*; the synthesized *plan* (organic's ranked, deduped, recommend‑only Action Plan artifact) is **not** rebuilt per‑module for Maps. **Decision (2026‑06‑29): Maps actions feed the one unified `strategy_plan`** (§6.1/§6.9) directly — no `maps_reopt_plans` store.

- The optimizer (§6.9) emits the §4.8.4 Maps actions as `strategy_actions` tagged **`module = maps`**; a **"Maps" filter** on the unified Action Plan view (the generalized `ActionPlan.tsx`) gives a Maps‑only slice when wanted, without a second plan store.
- The unified plan **ranks Maps actions alongside organic** (and later LLM) by severity/priority, and applies the **cross‑module dedup** from §4.8.4 (one company/page isn't actioned twice across channels) — the whole point of one plan.
- **Consistency:** this is the same convergence the design already states for organic — the Strategy Engine (§6.1) generalizes the existing `reopt_planner`; rather than build a second per‑module silo for Maps and then merge it, Maps lands **straight in the unified model**.
- **Build timing / interim:** the unified `strategy_plan` is established in **Phase 2** (recommend‑only); Maps actions join when the Maps optimizer wiring lands (**Phase 5**). Until then, organic keeps its existing `reopt_plans` Action Plan; there is **no interim Maps‑only plan** (deliberate — avoids throwaway).
- **Data‑model:** `strategy_actions` gains a **`module`** tag (`organic | maps | ai_visibility | cross`) for the filter views (added to §3.1).

This is the last item on the Maps gap list — **the Maps ↔ SerMaStr contract is now complete** (alerting §4.8.1 · winnability §4.8.2 · goal rollup §4.8.3 · action vocabulary §4.8.4 · competitor unification §4.8.5 · plan integration §4.8.6).

---

## 4.9 LLM / AI‑Visibility — SerMaStr input contract

AI‑Visibility hands SerMaStr, per **(keyword × engine × scan batch)**: presence (`mention_found` + `mention_type` direct/implied/none), **sentiment** (−1..1) + confidence, the **`citations`** the engine cited (its *trust set*), and **`competitor_results`** (the same answer re‑classified per tracked competitor) — plus per‑batch **trend** rollups (overall + per‑engine visibility %), the **mention matrix** (keyword × engine), and on‑demand **invisibility diagnoses**. It is the **thinnest tracker on synthesis** — measurement + diagnosis only (no goal‑tracking, alerting, winnability, value, or action generation today). SerMaStr drives it from the **LLM branch of the SOPs**. The goal (§4.6): **appears in every *triggered* engine** per keyword. Line‑by‑line decisions (2026‑06‑29):

- **Value/demand weighting — ❌ won't apply (visibility‑only).** Even though LLM keywords are real queries, prioritization is by **goal‑gap** (engines missing) + **citation‑authority gap**, not $.
- **Winnability band — ❌ won't build.** Visibility is treated as **binary**; prioritize invisible keywords by goal‑gap + how often the engine triggers + citation gap.
- **`triggered`/`not_shown` flag — ✅ build (prerequisite)** · **Alerting — ✅ build** (mirror organic/Maps) — §4.9.1.
- **Action vocabulary (LLM tactics)** — §4.9.2 · **Plan integration** — unified plan, `module=ai_visibility` — §4.9.3 · **Competitor unification (AI leg) — ✅ resolved** — §4.9.4.

### 4.9.1 The `triggered` flag + AI‑visibility alerting — ✅ design settled

**`triggered`/`not_shown` flag (the goal prerequisite):** add a boolean **`triggered`** (a.k.a. `answer_shown`) to `brand_mention_history`, set **deterministically at scan completion** — `true` for the four chat engines (they always answer); for `google_ai_overview`/`google_ai_mode`, **`false` when no AI block was present** (today that path synthesizes a "No Google…" `raw_response` in `_extract_dataforseo_ai` `brand_scan.py:147‑154` and mislabels it `mention_found=false`). Set the flag at extraction time instead of inferring from the synthetic text; the goal/visibility math then **excludes not‑triggered engines from the denominator** (the §4.6 LLM rule) — a non‑triggering AIO is *not* a miss.

**Alerting** — new **`brand_alerts`** table mirroring `rank_alerts`/`maps_alerts` (same columns + episode model), produced by **`reconcile_brand_alerts(client_id)`** on the scan‑complete path (latest batch vs. prior), delivered via **`notifications.emit`**. Triggers (`brand_alert_*`, config‑tunable):

| Alert type | Trigger (batch‑over‑batch) | Severity |
|---|---|---|
| `went_invisible` | a keyword that was visible in ≥ 1 engine is now **invisible across all triggered engines** | critical |
| `visibility_drop` | overall visibility % fell ≥ N points | warning |
| `engine_loss` | lost an engine you previously appeared in (for a keyword) | warning |
| `competitor_overtake` | a tracked competitor now appears for a keyword where you don't (or newly across ≥ M keywords) | warning |

Build timing: spec now; built **Phase 5** inside `strategist_monitor` (emits `brand_alerts` + `strategist_signals`: `goal_gap`/`regression`/`new_competitor`).

### 4.9.2 LLM action vocabulary (tactics) — ✅ design settled

From the invisibility diagnosis + the **citation gap** (what the engine trusts) + competitor presence → `strategy_actions` (`module=ai_visibility`, `category=llm_tactic`; content reuses `page`/`silo`). Mirrors Maps §4.8.4.

| Action kind | Trigger | Recommendation | Routes to | mode · role |
|---|---|---|---|---|
| `llm_content_gap` | invisible for a keyword that **triggers** + has intent | create/optimize content that directly answers the query in the form assistants quote | Blog Writer / Local SEO | **auto** draft → **assigned** review · writer |
| `llm_citation_gap` | invisible while rivals are cited; the engine trusts specific domains | earn presence on the **cited domains** (digital PR / get‑listed / guest) | assigned task (+ cited‑domain list) | **assigned** · link_builder/AM |
| `llm_schema` | invisible + thin structured data / no FAQ | add schema / FAQ / entity markup so assistants can extract you | **assigned** (or auto draft) · seo_tech |
| `llm_listings` | a **local** AI answer (AIO/AI‑mode) is invisible; GBP/citation weakness | strengthen GBP + local citations | **assigned** · AM — **deduped vs Maps** `gbp`/`reviews` |
| `llm_competitor_threat` | `competitor_overtake` | diagnose why the rival surfaces (citations/content/reviews) and counter | assigned · AM |

**Cross‑module synergy (important):** an `llm_content_gap` is often the **same content fix** that improves organic rank — so when the keyword/URL overlaps an organic action, SerMaStr **merges them into one `module=cross` action** serving both. `llm_listings` likewise **dedups against** Maps `maps_gbp_optimization`/`maps_review_gap`. Tiering: `went_invisible` (critical) > `competitor_overtake`/`visibility_drop` (warning) > content/citation gaps (by goal‑gap). Publishing stays a checkpoint (§8).

### 4.9.3 Plan integration — ✅ unified plan only

Same as Maps (§4.8.6): no per‑module store — LLM actions feed the **one unified `strategy_plan`** tagged `module=ai_visibility` (or `cross` when a content fix serves organic+LLM); an "AI Visibility" filter on the Action Plan view gives the slice. Cross‑module dedup ensures one content/listing fix isn't assigned three times.

### 4.9.4 Competitor unification — AI leg resolved (closes §4.8.5)

The §4.8.5 deferral is **resolved deterministically**: `brand_tracked_competitors` **already carries `competitor_website` + `google_place_id`** (stored, just unused in scan logic). The AI competitor joins `client_competitors` on **domain (`competitor_website` → eTLD+1) / `google_place_id`**, with **name fallback** to the unified entity's canonical name / GBP name; `present_ai` flips true when a unified competitor appears in `competitor_results`.
- **Build action:** start **capturing + using** `competitor_website`/`place_id` in the competitor‑add UI (the columns already exist); a manual‑link affordance covers name‑only residuals; optional domain backfill from citations.
- **New LLM‑authority signal:** the **`citations`** set (domains each engine trusts) is *distinct* from the tracked‑competitor list — when the client is invisible, SerMaStr mines the cited domains to (a) drive `llm_citation_gap` actions (earn presence there) and (b) surface frequently‑cited domains as **candidate competitors/authorities** to track.

**This completes the trio** — the SerMaStr **evidence base is now fully specified** across **organic (§4.7)**, **Maps (§4.8)**, and **LLM (§4.9)**: every tracker's contract, gaps, goal wiring, alerting, action vocabulary, and competitor unification are defined.

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

### 6.2 Site / Technical audit — `services/site_audit.py` (✅ approach settled 2026‑06‑29)
**Engine: DataForSEO OnPage + Google PageSpeed.** Seed the URL set from `site_page_index` sitemap discovery, then run a **DataForSEO OnPage** crawl task (POST → poll, like the other async jobs). That one API yields, per page: status codes, title/meta presence+length, H1, canonical, hreflang, **schema presence**, word count, **duplicate content**, broken links, redirect chains, and the **internal‑link graph** (which also feeds §6.5). Layer **free Google PageSpeed/Lighthouse** on the **top‑N pages by traffic** (from GA4/GSC) for **Core Web Vitals** — not every page, to bound cost/time. Reuse the rank tracker's existing **GSC URL Inspection** for indexation on key pages. **Output:** a deterministic, severity‑scored, **typed** issue list (indexability / crawlability / on‑page / performance / structure), each **weighted by GA4 traffic** so a high‑traffic page with a problem surfaces first → `technical_fix` / `onpage` actions (mostly **assigned** to seo_tech; some **auto**, e.g. a drafted title/meta). Async `site_audit` job → `audit_runs`. **Cadence:** full crawl at onboarding + monthly re‑audit; capped at `site_audit_max_pages`. **New external:** DataForSEO OnPage (per‑page paid, shared creds) + PageSpeed (free key) — §9.

### 6.3 Backlink‑gap — `services/backlink_gap.py` (✅ approach settled: enable Backlinks API, capped)
**Data: DataForSEO Backlinks API** for the client domain **and each unified competitor** — the §4.8.5 domain‑keyed `client_competitors` entity *is* the competitor set — **capped at the top‑N competitors** (`backlink_max_competitors`) to bound cost. **Compute (pure):** referring domains linking to ≥ N competitors **but not the client**, ranked by **DR + topical relevance** (links to multiple niche rivals). Also pull the client's **full backlink profile** → the authority baseline that sharpens organic `rankability`'s "competition weakness" (which today only sees ranking‑page RD/UR/DR from SERP snapshots). **Output:** a ranked **prospect list** → `backlink` actions, **assigned** to link_builder (outreach / digital PR is human craft — never auto‑executed); overlaps `llm_citation_gap` (a cited domain you lack a link from = double opportunity). Async `backlink_audit` job → `audit_runs`. **Cadence:** onboarding + monthly/quarterly. **New external:** DataForSEO Backlinks (per‑query paid, shared creds) — §9.

### 6.4 Local‑citation audit — `services/citation_audit.py` (✅ approach settled: static checklist now, API later)
**NAP truth** = the client's GBP (name/address/phone). **Approach: a curated target‑directory checklist** (the directories that matter for local + AI‑answer visibility — GBP, Apple, Bing Places, Yelp, Facebook, BBB, the data aggregators, + industry/country‑specific), with presence + NAP‑consistency checked via the **existing DataForSEO SERP / `site:` queries** (cheap; creds we already have). The audit = **target list − where found** → it **directly answers "which directories you're missing + which have inconsistent NAP."** **Reuse:** the directory set ≈ the §4.8.5 aggregator‑exclusion list (one list, two uses). **Output:** per‑directory `{listed?, nap_consistent?, url}` → `citation` actions, **assigned** to VA/AM; **dedups vs** `llm_listings` (§4.9.2) + Maps `gbp`/`reviews` actions (citations are a shared local + AI‑answer factor). Async `citation_audit` job → `audit_runs`. **Later enhancement (deferred):** the **DataForSEO Business Listings API** for richer auto‑discovery of unknown existing listings + their NAP attributes. **Cadence:** onboarding + periodic. **Cost:** a few cheap SERP lookups per client/run — **no new endpoint** to start.

### 6.5 Internal‑linking analyzer + injector — `services/internal_linking.py`
Analyzer builds the site's internal‑link graph from the crawl, finds orphan pages + missing topical links (silo‑aware) → `internal_link` actions. **Injector (autonomous):** for WordPress clients, applies approved link edits via the **existing** `wordpress_publish.py` REST/app‑password path, **as drafts/revisions**, never silently to live. Non‑WordPress → recommend‑only deep links.

### 6.6 Consolidated client report — `services/engagement_report.py`
Composes the existing `rank_report`/`brand_report`/`maps_report` builders + the **first‑party performance baseline + deltas** (GSC/GA4/GBP‑Performance, §6.7) + the **goal‑attainment scorecard** (§4.6 — % of keywords at top‑3 organic, the 3mi/5mi maps averages, all‑engine LLM coverage) + plan progress + `execution_events` into one Google Doc via the shared `google_docs.py`. The baseline makes the report a **measurable before/after** in the client's own numbers, and the scorecard shows progress toward the three standard goals. Async `engagement_report` job; scheduled via `gsc_scheduler`.

### 6.7 First‑party data connectors (GSC existing; GA4 + GBP Performance NEW)
The onboarding data layer (Stage 0b) + the periodic ingests + the performance baseline (audit 2d).

- **Search Console — exists.** `services/gsc_service.py` (agency service‑account connect/verify), `services/gsc_ingest.py` (query×page ingest on `gsc_scheduler`), GSC Research. No new build beyond surfacing connect/status in the wizard.
- **GA4 — NEW: `services/ga4_service.py` + `services/ga4_ingest.py`.** Connect/verify a GA4 property via the **GA4 Data API (`google-analytics-data`)** using the **same agency service‑account** added as a property *Viewer* (reuse `settings.google_service_account_key`; widen `SCOPES` with `analytics.readonly`). Periodic pull of sessions / channel mix / landing‑page traffic / engagement + **key events (conversions)** into `ga4_*` tables. Pure‑helper + lazy‑import pattern mirrors `gsc_service`. New: `clients.ga4_property_id`, `clients.ga4_access_status`. Async `ga4_ingest` job on `gsc_scheduler`.
- **GBP Performance — NEW: `services/gbp_performance_service.py` + `services/gbp_performance_ingest.py`.** Pull daily metrics from the **Business Profile Performance API** (`businessprofileperformance.googleapis.com`) — `BUSINESS_IMPRESSIONS_{DESKTOP,MOBILE}_{MAPS,SEARCH}`, `CALL_CLICKS`, `BUSINESS_DIRECTION_REQUESTS`, `WEBSITE_CLICKS`, `BUSINESS_BOOKINGS`, plus the search‑keywords report — keyed off the client's GBP location id (`clients.gbp_place_id` → resolve to the `locations/{id}` resource). **Auth wrinkle (Q8):** this API is OAuth‑centric (requires a Google account with *manager* access to the location); service‑account access isn't generally available, so this connector likely needs an **OAuth token store** (the one place the suite would deviate from the locked "service account, no OAuth" decision — flagged for decision, not assumed). New: `clients.gbp_performance_location_id`, `clients.gbp_performance_access_status`, `gbp_performance_*` tables. Async `gbp_performance_ingest` job on `gsc_scheduler`. **Best‑effort:** absent the connection, the suite keeps using the existing Outscraper/DataForSEO profile+reviews scrape (which has no performance metrics).

All three are read‑only, creds/connection‑gated, and degrade to "not configured" exactly like the current GSC path.

### 6.8 Cross‑module monitor + signal bus — `services/strategist_monitor.py`
The "monitors campaigns" pillar. A scheduled job (`strategist_monitor`, on `gsc_scheduler`, default weekly per engagement) that reads every module via the existing `slack_assistant` context‑provider registry + the first‑party ingests, and on each pass does **two** things: (1) computes **goal attainment** for every tracked keyword against the fixed goal set (§4.6) and emits a `goal_gap` signal for anything off‑target; (2) runs **trend/anomaly detection** vs. the prior pass / baseline and emits `regression`/`win`/`anomaly`/`plateau` signals. A pure `compute_goal_state(keyword, module)` helper per module (`organic` top‑3, `maps` 3mi/5mi ring averages with absent‑cell rank = 21, `llm` mentioned‑in‑every‑*triggered*‑engine) plus per‑module trend detectors, each isolated so one failing module never blocks the pass. **Generalizes `rank_materialize`'s existing rank‑drop alerting** into a cross‑module bus; `notifications.emit` delivers severe signals. No new external APIs (reuses the connected sources + the geo‑grid/brand scans).

### 6.9 Continuous‑optimization engine — `services/strategist_optimizer.py`
The "suggests tweaks and fixes" pillar — the steady‑state twin of the Strategy Engine (§6.1), sharing its `build_actions` core. Input: open `strategist_signals`. Output: diagnosed `strategy_actions` (`source = strategist_signal`), **deduped against currently‑open actions** (so a persistent regression doesn't spawn duplicates each pass) and prioritized by signal magnitude × `est_value`. Sets each action's `execution_mode` (`auto` vs `assigned`) per the split rule. Claude‑Sonnet for the diagnosis narrative; deterministic signal grounding (every tweak cites the signal that triggered it).

### 6.10 Asana sync — `services/asana_sync.py`
The "assigns tasks to Asana boards" pillar. A creds‑gated dispatcher (`asana_sync` job) that: (a) ensures the engagement's board exists/maps (`engagement_asana`); (b) for each `assigned` action, creates/updates an Asana task — **role‑routed** through `role_assignees` (category → role → `asana_user_gid`), in the category's section, with priority/effort custom fields + cadence‑derived due date; (c) **pulls status back** (webhook if available, else poll) so an Asana completion closes the action and feeds the monitor. Mirrors the `notifications.py` channel pattern (best‑effort, only fires when the Asana token is set). New external dependency — Section 9.

### 6.11 Algo‑update timeline — market context for the monitor (✅ design settled 2026‑06‑29)
Lets the monitor (§6.8) + optimizer (§6.9) tell **market‑wide movement from client‑specific regressions** — "a one‑day drop across many keywords = a Google update, not your content." Without it, the optimizer would emit N per‑page reoptimize actions for what is really one algo event; with it, the recommendation flips to "align with the update's theme and **hold** individual reopts until the rollout completes."

**Data — an agency‑wide `algo_updates` reference table** (not per‑client):
```
algo_updates
  id, name, update_type (core|spam|helpful_content|reviews|product_reviews|local|other),
  surface (organic|local|ai|multi), started_on (date), ended_on (date, null while rolling out),
  confirmed (bool), source_url, notes, created_at
```
Seeded via migration with recent confirmed updates; refreshed **best‑effort** by a slow (weekly) `algo_update_sync` job that pulls **Google's Search Status Dashboard** (the authoritative free source for confirmed ranking/core/spam updates) and upserts. If no source is reachable it still works from the seed + manual entries (updates are infrequent — a handful/year — so manual upkeep is trivial). **Cost: free.**

**Correlation heuristic** — `services/algo_updates.py` (pure): a regression signal is tagged **`algo_correlated`** only when (a) its detected date falls in an `algo_updates` window for the matching `surface`, **and** (b) the same window saw a **cluster** — ≥ `algo_cluster_min_pct` (default 30%) of the client's tracked keywords (or ≥ `algo_cluster_min_count`) regress together. A lone keyword dropping during an update window is **not** auto‑attributed (could be coincidental) — the cluster is the market‑wide tell. During an **active rollout** (`ended_on` null) the monitor flags "rollout in progress — hold."

**Downstream effects:**
- `strategist_signals` gains a nullable **`algo_update_id`** FK (added to §3.1); correlated regressions carry it.
- The optimizer **collapses an algo‑correlated cluster into one `algo_response` action** (`module = organic`/`cross`): *"Google [name] ([type]) rolled out [dates]; this looks market‑wide — align with its theme (core/helpful‑content → E‑E‑A‑T + depth, prune thin pages; reviews → first‑hand review content; spam → audit spam signals) and **hold individual reoptimizations until the rollout completes**"* — and **suppresses the per‑keyword `rank_drop`/reoptimize actions** for that cluster (no wasted 20‑page reopt).
- The **Strategist digest** notes active rollouts ("[Update] rolling out; X% of keywords moved — likely algo‑driven").

Primarily **organic**, but the `surface` field lets a `local`/`ai` update apply to the Maps/LLM monitors too. **Build timing:** spec now; built with the monitor (Phase 5).

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
| DataForSEO **OnPage API** | Site/technical audit (§6.2) | Per‑crawl cost; creds already on PLATFORM (DataForSEO shared) | ✅ **Enable** (decided 2026‑06‑29) — capped at `site_audit_max_pages` |
| Google **PageSpeed/Lighthouse API** | Core Web Vitals (§6.2) | Free tier / API key | ✅ **Enable** — top‑N traffic pages only |
| DataForSEO **Backlinks API** | Backlink‑gap (§6.3) | Per‑query cost; shared creds | ✅ **Enable** — capped at top‑N competitors (`backlink_max_competitors`) |
| DataForSEO **SERP** (citation presence checks) | Local citations (§6.4) | A few cheap SERP lookups/client/run; **shared creds, no new endpoint** | ✅ **Static checklist now** (decided) |
| DataForSEO **Business Listings** | Local citations — richer NAP discovery | Per‑query cost | **Deferred** — enhancement after the static checklist |
| **GA4 Data API** (`google-analytics-data`) | Performance baseline (2d), value‑weighted audits, report | **Free** API; reuse agency service account added as property *Viewer* + `analytics.readonly` scope. Per‑client dashboard step = grant the SA email (like GSC) | **Provisioning incoming** (user has access) |
| **Business Profile Performance API** | Local performance baseline, Maps audit weighting, report | **Free** API, but **OAuth‑centric** (manager access to the location) — likely needs an OAuth token store; service account may not suffice (Q8) | **Provisioning incoming — auth model TBD** |
| **Asana** API (token or OAuth) + workspace/board mapping + role→user map | Asana assignment (CORE, §6.10) — the human work surface | Free API; needs a Personal Access Token (or OAuth app), the workspace gid, a board per engagement, and the `role_assignees` map. Webhooks for two‑way status (else poll) | **In scope — provisioning needed** (token + role map) |

Everything else (LLM, WordPress, GSC, Outscraper, geocoding) is already provisioned. The three first‑party data sources (GSC/GA4/GBP‑Performance) are **read‑only and free** — their cost is setup/auth, not per‑call.

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

**Phase 1 — Engagement spine + onboarding wizard + intake + first‑party connectors.** `engagements` table + state machine, the onboarding wizard with brand‑voice/ICP **approval gates** and the **Connect data** step, the GA4 + GBP‑Performance connectors/ingests (§6.7) alongside existing GSC, and the extended intake. Mostly orchestration over existing data; the connectors are free read‑only APIs (GA4 reuses the agency SA; GBP‑Performance auth per Q8). Delivers the "guided onboard" + a first‑party baseline immediately.

**Phase 2 — Strategy Engine v1 (recommend‑only) + plan review + performance baseline.** Generalize `reopt_planner` to cross‑module using the existing context providers + the *synthesis* audits (2b/2c) + the **performance baseline (2d)** from Phase 1's connectors (no new external APIs). `strategy_plans`/`strategy_actions`, the generalized plan view, gate #2. This is the brain; valuable even before autonomy, and now value‑weighted by real traffic/conversions.

**Phase 3 — New audit modules.** Site/technical (6.2), backlink‑gap (6.3), local citations (6.4). Each gated on its external‑API approval (Section 9); each feeds richer actions into the engine.

**Phase 4 — Autonomous Executor + internal‑linking injector + consolidated report.** Turn on execution of `auto` actions under the Section 8 safety model, starting at `assisted` and graduating to `autonomous`. WordPress internal‑link injection. One consolidated report.

**Phase 5 — The Continuous Strategist loop + Asana assignment.** The steady‑state engine: cross‑module monitor + signal bus (§6.8), continuous‑optimization engine (§6.9), the §4.5 control loop on the scheduler, the Strategist digest, **and Asana‑as‑core** (§6.10) — board mapping, role‑based auto‑assignment, two‑way status. This is the phase that makes it "the Strategist" rather than a one‑shot planner. Requires the Asana token + role map (Section 9). *(Monitor + optimizer can land slightly ahead of Asana if the token isn't ready — assigned actions simply wait in‑app until the board is connected.)*

---

## 12. Open questions / decisions still needed

1. **Default autonomy level** for new engagements — recommend starting at `assisted` (auto‑setup + drafts, human publishes), opt‑up to `autonomous`. Confirm.
2. **External API budget** — OK to enable DataForSEO OnPage + Backlinks (+ PageSpeed)? Or start citations as a $0 static‑directory checklist?
3. **Per‑engagement spend ceiling** default (the budget cap value).
4. **Checkpoint defaults** — which pause points are on by default (e.g., always pause before first live publish?).
5. **WordPress live vs draft default** for autonomous internal‑link edits — recommend draft/revision always.
6. **Asana provisioning** — confirm: a Personal Access Token vs. an OAuth app; the workspace gid; **one board per engagement** vs. one shared board with per‑client sections; and the **`role_assignees` map** (which Asana user is writer / SEO‑tech / link‑builder / VA / account‑manager — agency default + per‑client overrides). Two‑way status via Asana **webhooks** (preferred) or polling?
7. **One engagement per client** assumption — confirm we never need concurrent engagements per client.
8. **Monitor cadence + signal severity thresholds** — default weekly per engagement; what magnitude of trend change counts as a `regression`/`win` worth a signal (to avoid noise), and which severities auto‑flow vs. re‑enter `plan_review`.
9. **Strategist digest cadence/channel** — weekly Slack digest by default? (Email is still deferred per the notifications service status.)
9b. **History / external context (§6.11):** the **algo‑update timeline is now designed** (§6.11 — correlate regression clusters to confirmed Google updates). Still open: **historical action→outcome import** (the effectiveness loop is forward‑looking only), plus the exact `algo_cluster_min_pct`/`_count` thresholds.
10. **Goal model specifics (§4.6) — ✅ RESOLVED 2026‑06‑29:** maps grids are already 5‑mile (3‑mi metric = inner subset); absent‑cell penalty = **21**; LLM bar = **all six engines, excluding any that didn't trigger** (esp. Google AI Overview). *Remaining small build item:* ensure `brand_scan` records a per‑engine `triggered`/`answered` flag so a non‑triggering engine is dropped from the bar rather than scored as a miss. Targets stay global constants (per‑client override deferred).
11. **SerMaStr naming** — unify the strategy brain (**SerMaStr**) and the existing Slack assistant (**SerMastr**) under one brand (brain + voice), or keep distinct names? (§4.7)
12. **SEO SOP store (§4.7)** — format + ingest of the SOPs you'll provide (structured checklist vs. prose playbook), and how they load into SerMaStr (system‑prompt vs. retrieval). Pending your SOPs.
13. **Capacity/constraints fields (§4.7)** — confirm the exact per‑client fields to capture: content pieces/month, publishing cadence, link/tool budget, off‑limits tactics, risk tolerance, dev resources available.
14. **GBP Performance API auth** — the Business Profile Performance API is OAuth‑centric (manager access to the location), so it likely needs an **OAuth token store**, deviating from the locked "service account, no interactive OAuth" decision *for this one source*. Confirm: stand up a minimal OAuth connect flow for GBP Performance, or stay on the existing Outscraper/DataForSEO scrape (no first‑party performance metrics)? (GA4 stays on the agency service account — no deviation.)

---

*End of design v1.1. Nothing herein is implemented. Next step on approval: pick the first phase to detail into a build plan (recommended: Phase 1, the engagement spine + onboarding wizard + first‑party connectors).*
