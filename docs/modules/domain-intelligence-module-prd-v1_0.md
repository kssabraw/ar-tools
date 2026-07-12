# Domain Intelligence — Module PRD / Build Plan (v1.0)

**Authored:** 2026-07-11 · **Status:** **Phases 0–4 built** — foundations + Domain Overview/Ranked Keywords + Keyword Gap + Backlink Gap + Discover + Phase 4 signals (weekly scheduled keyword-gap refresh on the shared scheduler, a "new competitor keyword gaps" notification on newly-opened gaps, and top gaps surfaced as deep-linked Action Plan items). Phase 5 (strategist / SerMaStr context) ahead · Competitive-intelligence module (the "SEMrush clone")

> Read alongside **`docs/suite-architecture-and-roadmap-v1_0.md`** (suite decision log), **`CLAUDE.md`** (stack, conventions, RLS/service-role rule), and the two competitive-intel-adjacent module docs already in the suite: **`docs/modules/organic-rank-tracker-prd-v1_0.md`** and **`docs/modules/seo-strategist-agent-plan-v1_0.md`**. Where this doc and older framing disagree on *how it's built in this repo*, this doc wins.

---

## 1. Product summary

A **per-client** competitive-intelligence workspace — the suite's answer to SEMrush's "Domain Overview → Organic Research → Keyword Gap → Backlink Gap" loop. From a client's workspace the team enters **any domain** (a named competitor, a prospect, or the client's own site) and gets, as a dated snapshot:

1. **Domain Overview** — estimated organic traffic, ranked-keyword count, authority (DR/RD), and traffic value.
2. **Ranked Keywords** — the full list of keywords the domain ranks for, with position, volume, CPC, KD, and estimated value; filterable/exportable.
3. **Keyword Gap** — keywords one or more competitors rank for that the **client does not** (or ranks far worse for) — the single most actionable output for content strategy.
4. **Backlink Gap** — referring domains linking to competitors but **not** to the client — feeds the Recipe Engine / Link-Building SOP.
5. **Competitor discovery** — domains that share the most SERP real estate with the client, surfaced as suggested additions to the existing competitor registry.

Not customer-facing. Internal agency use only. No billing.

### The core reframe (why this is ~70% built already)

The suite already **captures** almost all of this data — it's just wired into other modules and never surfaced as a "point at a domain and analyze" view. This module is **mostly surfacing + unifying**, plus ~5 DataForSEO **Labs** endpoints the suite doesn't call yet. See §3.

---

## 2. Suite-conformance (the locked-decision inheritance)

Same rules every module inherits — called out so nothing here reopens a settled decision:

| Concern | This module does |
|---|---|
| Surface | **Per-client workspace module** — a "Domain Intelligence" card + `pages/DomainIntel.tsx`, scoped to the client and its competitors. (A standalone global research entry point is a deliberate v2 follow-up, not v1.) |
| Auth / tenancy | RLS on, **no client-facing policies**; all access via the service-role key; authorization is API-layer `client_id` filtering. Single-tenant internal. |
| Scheduling | **Suite shared scheduler** (`services/gsc_scheduler.py`) enqueuing into `async_jobs`. No new infra. |
| Job execution | `async_jobs` + the existing asyncio worker (`services/job_worker.py`). New job types registered in the CHECK constraint. |
| Rank / SERP data | **DataForSEO** (org decision, suite decision log). This module adds the **Labs** family; it introduces no new vendor. |
| Notifications | Suite notifications service (`services/notifications.py`) for the async signals (new-competitor-content already exists; this adds gap-opened / authority-overtaken signals — Phase 4). |
| Cost control | Reuse the **paid-call budget + cache** pattern from `backlink_explorer.py` (daily cap via a `*_usage` table + an atomic reserve RPC + a TTL cache). Labs calls cost money per request — see §8. |
| Refactoring | Per the owner refactoring policy: **do not** refactor the 6 existing ad-hoc DataForSEO wrappers. Add **one** new consolidated Labs client (§4) and stop there. |

---

## 3. What already exists (reuse, do not rebuild)

| SEMrush capability | Already in the suite | Verdict |
|---|---|---|
| Backlink Site Explorer | `services/backlinks_api.py` (full DataForSEO Backlinks family: `summary`, `referring_domains`, `anchors`, `domain_pages`, `bulk_ranks`, `history`) + `services/backlink_explorer.py` (24h TTL cache, daily paid-call budget via `reserve_backlink_calls` RPC, tracked targets, new/lost-domain alerts) | **~done** — reuse wholesale |
| "Keywords a domain ranks for" | `DataForSEOClient.ranked_keywords` (`fanout/dataforseo/client.py:264`) already calls Labs `ranked_keywords/live` — but buried as Topic-Fanout candidate-mining, never a view | **lift the call, add table + UI** |
| Keyword volume / CPC / KD / value | `services/keyword_market.py` (cross-client `keyword_market` cache, seasonality) + `DataForSEOClient.keyword_overview` (`client.py:289`) | reuse |
| Competitor registry + cross-module profiles | `services/competitor_intel.py` — `client_competitors` table, `build_profiles`, weekly content-watch. The hub this module hangs off | reuse + extend |
| SERP landscape (DR/RD/AIO/intent) | `services/serp_snapshot.py` — mature per-keyword capture | reuse for context |
| Domain authority comparison | `services/authority_report.py`, `services/backlink_intel.py` (`backlink_profiles` table) | reuse |
| Content gap (depth/heading) | `services/content_intel.py` (`website_analyses`) | reuse for a per-gap-keyword drill-down |

**Net:** the backlink half is essentially complete; the keyword half has the DataForSEO plumbing (`ranked_keywords` + `keyword_overview`) but no domain-level surface, no gap analysis, and no persistence tables.

---

## 4. The genuine gaps to build (all DataForSEO **Labs** endpoints not called anywhere today)

1. **Domain Overview** — `dataforseo_labs/google/domain_rank_overview/live` + `bulk_traffic_estimation/live` (traffic / keyword-count / authority for any domain).
2. **Keyword Gap** — `dataforseo_labs/google/domain_intersection/live` (the marquee feature — keywords in competitor SERPs but absent/weak for the client). This is the one net-new engine.
3. **Ranked Keywords as a view** — surface the existing `ranked_keywords` call with paging beyond the current top-20 candidate use, its own table, and export.
4. **Referring-domain gap** — `backlinks/domain_intersection/live` (link intersection). Explicitly deferred today (`backlink_intel.py:5`).
5. **Competitor discovery by SERP overlap** — `dataforseo_labs/google/competitors_domain/live` (today discovery is maps / organic-top-10 / AI-visibility heuristics only in `competitor_intel.py`).

### The one consolidation: `services/dataforseo_labs.py`

A single new client for the Labs competitive endpoints above. **Lift** the working code from `fanout/dataforseo/client.py` (`ranked_keywords` `:264`, `keyword_overview` `:289`, `_post`, `_coerce_int/float`) rather than re-deriving parsers. Mirror the existing `_auth_header` Basic-auth pattern (`backlinks_api.py:56`) and read `settings.dataforseo_login/password`. This is **additive** — it does not touch the six existing wrappers.

---

## 5. Data model (new migrations in `writer/supabase/migrations/`)

Design principle: a **snapshot** row per (client, target domain, run) with child result rows, so every view is a cheap re-read and re-runs are cost-visible. Mirror the `serp_snapshots` / `backlink_snapshots` shape.

- **`domain_intel_snapshots`** — one row per analysis run: `id`, `client_id` (FK), `target_domain`, `role` (`competitor` | `client` | `prospect`), `location_code`, `language_code`, `captured_at`, rollup columns (`organic_traffic_est`, `ranked_keyword_count`, `dr`, `rd`, `traffic_value_est`), `status`, `cost_usd`.
- **`domain_ranked_keywords`** — child of a snapshot: `keyword`, `position`, `url`, `volume`, `cpc_usd`, `keyword_difficulty`, `search_intent`, `est_value`. (The Ranked Keywords view + the raw material for gap computation.)
- **`domain_keyword_gaps`** — computed gap rows for a (client, competitor-set) run: `keyword`, `competitor_position`, `competitor_domain`, `client_position` (nullable = client absent), `volume`, `cpc_usd`, `keyword_difficulty`, `gap_type` (`missing` | `weak` | `untapped`), `opportunity_score`.
- **`domain_link_gaps`** — referring domains linking to ≥1 competitor but not the client: `referring_domain`, `linking_to` (array of competitor domains), `referring_domain_rank`, `backlink_count`, `first_seen`.
- **`domain_intel_usage`** — daily paid-call meter (same shape as `backlink_usage`: `day`, `calls`), fronted by a `reserve_domain_intel_calls` atomic RPC (copy `reserve_backlink_calls`).

Registry extension: add a `serp_overlap_pct` / `last_intel_at` column set to `client_competitors` (Phase 3) so discovery + last-run surface on the existing Competitive Intel page.

All tables RLS-on, service-role access only, `client_id`-scoped.

---

## 6. Services & jobs

- `services/dataforseo_labs.py` — the consolidated Labs client (§4).
- `services/domain_intel.py` — orchestration: pure builders (`build_overview`, `compute_keyword_gap`, `compute_link_gap`, `score_opportunity`) + impure fetch-and-store (`run_domain_intel`), reusing `keyword_market` for value math and `backlinks_api` for the link half. **Pure gap/scoring helpers unit-tested** (`tests/test_domain_intel.py`) — the suite pattern.
- Async job types (register in the `async_jobs` job_type CHECK): `domain_overview`, `keyword_gap`, `link_gap`. Each per-target so a single unit stays under the stale-job reaper's 30-min window (the Local SEO bulk-job lesson).
- Scheduler hooks (`gsc_scheduler.py`): weekly re-snapshot of registered competitors (`enqueue_due_domain_intel`, interval-gated, gated on DataForSEO creds), mirroring `enqueue_due_competitor_intel`.

---

## 7. API & frontend

- `routers/domain_intel.py`:
  - `POST /clients/{id}/domain-intel/overview` (enqueue) + `GET .../overview/{domain}` (latest snapshot) + history.
  - `POST /clients/{id}/domain-intel/keyword-gap` (competitor-set in body) + `GET` latest.
  - `POST /clients/{id}/domain-intel/link-gap` + `GET` latest.
  - `GET /clients/{id}/domain-intel/discover` (competitor suggestions via `competitors_domain`).
  - Job-status poll endpoint (batch, matching the Local SEO `jobs/status` convention).
- `pages/DomainIntel.tsx` (route `clients/:id/domain-intel`, workspace "Domain Intelligence" card next to "Competitive Intel"): a domain input + tabs **Overview / Ranked Keywords / Keyword Gap / Backlink Gap / Discover**. Dependency-free tables with per-table CSV export (suite convention). Live-poll while a job is in flight.
- **Strategist / SerMaStr integration** (Phase 5): a `domain_intel` provider in `services/strategy_digest.py` and a `_ctx_domain_intel` provider in `services/slack_assistant/context.py`, so keyword/link gaps become raw material for strategist proposals and Slack Q&A. Deep-links from the Action Plan (a gap keyword → "create page", a link gap → Recipe Engine).

---

## 8. Cost model (the one thing that can go wrong)

DataForSEO Labs + Backlinks calls are **paid per request** and this module invites ad-hoc "analyze any domain" clicks — the exact usage pattern that runs up spend. Controls (all reuse existing machinery):

- **Daily budget cap** — `domain_intel_usage` + `reserve_domain_intel_calls` RPC, config `domain_intel_daily_call_budget` (copy `backlink_daily_call_budget`). Over budget → a clean `budget_exceeded` error, not a silent failure.
- **TTL cache** — a fresh snapshot within `domain_intel_cache_hours` (default 24h) is re-served, not re-fetched (copy `backlink_explorer`'s cache check).
- **Scheduled vs on-demand** — the weekly registry re-snapshot is bounded to registered competitors; arbitrary-domain lookups are on-demand only and counted the same.
- Every snapshot persists `cost_usd` from `task["cost"]` so spend is auditable per client.

Config additions (`config.py`): `domain_intel_enabled`, `domain_intel_daily_call_budget`, `domain_intel_cache_hours`, `domain_intel_interval_days`, `domain_intel_ranked_keyword_cap`, `domain_intel_gap_min_volume`, `domain_intel_model` (if any narrative is added — v1 is deterministic, no LLM).

---

## 9. Phasing

- **Phase 0 — Foundations.** `dataforseo_labs.py` client (lift `ranked_keywords`/`keyword_overview`), the five tables + usage meter + reserve RPC, config, budget/cache wiring. No UI.
- **Phase 1 — Domain Overview + Ranked Keywords.** `domain_overview` job, overview rollups, ranked-keywords table, the workspace card + first two tabs + CSV export. The SEMrush landing screen.
- **Phase 2 — Keyword Gap.** `keyword_gap` job over the client's registered competitors (or an ad-hoc set), `domain_intersection`, opportunity scoring, the Keyword Gap tab. The marquee deliverable.
- **Phase 3 — Backlink Gap + Discovery.** `link_gap` via `backlinks/domain_intersection` (reuse `backlinks_api`), `competitors_domain` discovery feeding suggested registry additions.
- **Phase 4 — Signals.** Notifications on gap-opened / authority-overtaken; Action-Plan deep-links.
- **Phase 5 — Agent integration.** Strategist digest + SerMaStr context providers; gaps become proposal raw material.

Phases 1 and 2 are the product; 0 is their prerequisite; 3–5 are compounding.

---

## 10. Open questions (decide before/while building)

1. **Location scope of a domain analysis.** Reuse the client's `rank_tracking_location_code` (from the rank tracker) as the default, or let the user pick per-run? (Recommend: default to it, allow override.)
2. **Keyword-gap competitor set.** Auto-use the top N registered `client_competitors`, or require an explicit domain list per run? (Recommend: default to registry, allow ad-hoc.)
3. **"Weak" gap threshold.** What client position counts as a gap worth surfacing (e.g. client absent, or client > position 20 while a competitor is ≤10)? Encode as `domain_intel_gap_*` config.
4. **Daily budget default.** What `domain_intel_daily_call_budget` is safe given current DataForSEO spend? (Needs the owner's number.)
5. **Standalone (non-client) research entry point** — confirmed **v2**, not v1. Flag if that changes.

---

## 11. Explicitly out of scope for v1

- Paid/PLA advertising research, Google Ads competitor spend (SEMrush "Advertising Research").
- A global, non-client-scoped research tool (v2 — see §10.5).
- Historical traffic trend charts per competitor beyond what snapshots naturally accumulate.
- Refactoring the six existing DataForSEO wrappers into the new client (owner refactoring policy — additive only).
- Any new vendor or infra (no new queue, no new scraper, no new LLM provider).
