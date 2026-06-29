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
  id, plan_id (FK), category (enum: silo | page | onpage | internal_link | citation |
     backlink | llm_tactic | technical_fix | tracking_setup | schedule),
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
  baseline_ref (jsonb), detected_at,
  status (open|actioned|dismissed|resolved), action_id (FK strategy_actions, when actioned)
  -- goal_gap = distance from the fixed goal set (§4.6); others = trend/anomaly vs baseline
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
10. **Goal model specifics (§4.6) — ✅ RESOLVED 2026‑06‑29:** maps grids are already 5‑mile (3‑mi metric = inner subset); absent‑cell penalty = **21**; LLM bar = **all six engines, excluding any that didn't trigger** (esp. Google AI Overview). *Remaining small build item:* ensure `brand_scan` records a per‑engine `triggered`/`answered` flag so a non‑triggering engine is dropped from the bar rather than scored as a miss. Targets stay global constants (per‑client override deferred).
11. **GBP Performance API auth** — the Business Profile Performance API is OAuth‑centric (manager access to the location), so it likely needs an **OAuth token store**, deviating from the locked "service account, no interactive OAuth" decision *for this one source*. Confirm: stand up a minimal OAuth connect flow for GBP Performance, or stay on the existing Outscraper/DataForSEO scrape (no first‑party performance metrics)? (GA4 stays on the agency service account — no deviation.)

---

*End of design v1.1. Nothing herein is implemented. Next step on approval: pick the first phase to detail into a build plan (recommended: Phase 1, the engagement spine + onboarding wizard + first‑party connectors).*
