# Maps Geo-Grid Strategy & Action Plan — Module PRD (v1.0)

**Authored:** 2026-06-29 · **Status:** **Phases 1–3 built** — Action Plan hybrid + cadence; Tier A (Share of Local Voice + brand-search); Tier B (B1 competitor GBP, B2 GBP audit, B3 reviews, B4 backlinks, B5 content). Only Tier C / GBP engagement (#8) remains, deferred. · **Extends Module #5 (Maps / local-pack geo-grid ranker)**

> Read alongside **`docs/suite-architecture-and-roadmap-v1_0.md`** (suite decision log), **`docs/modules/organic-rank-tracker-prd-v1_0.md`** (the Action Plan / reoptimization-planner pattern this extends), and **`CLAUDE.md`** (stack, conventions, RLS/service-role rule). Where this doc and CLAUDE.md disagree on "how it's built in this repo," CLAUDE.md wins; this doc is authoritative for *what this extension should do*.

---

## 1. Why this exists (the gap)

The suite has two ranking trackers. They are **asymmetric on guidance**:

| Capability | Organic Rank Tracker (#4) | Maps Geo-Grid Tracker (#5) — *today* |
|---|---|---|
| Automatic drop alerting → notifications (in-app / Slack) | ✅ `rank_alerts` + `notifications.emit` | ✅ `maps_alerts` + `notifications.emit` (kind `maps_drop`, 5 alert types, episode-deduped) |
| **Reoptimization guidance** (a ranked, deep-linked "what to do" list) | ✅ Action Plan (`reopt_planner.py` → `ActionPlan.tsx`) | ❌ **none** — the Local Rank Analysis report is observational-only by design ("never prescribe fixes") |

So a Maps drop alert tells the team *that* local-pack visibility slipped and *where* (octant/area), but never *what to do about it*. There is no Maps equivalent of the organic Action Plan.

**This module closes that gap and then makes the guidance materially smarter** by collecting and analyzing strategic data the geo-grid tracker does not yet capture.

Two parts:

- **Part 1 — Maps Action Plan (hybrid).** Bring the geo-grid tracker to parity with the organic tracker's guidance half, reusing the existing Action Plan surface and cadence machinery.
- **Part 2 — Strategic data layers.** Add the data needed to make better strategic decisions (competitor intelligence, reviews, backlinks, share of local voice, brand search, on-site content, GBP audit), each feeding new actions into the Action Plan.

---

## 2. Locked decisions (this effort)

Settled with the user on 2026-06-29:

1. **Hybrid architecture, not standalone.** The Maps guidance is *not* a separate planner/view. A **separate pure planning function** (`build_maps_actions`) — because the local-pack levers genuinely differ from organic page-reoptimization — feeds the **shared** `reopt_plans` store + the **shared** `ActionPlan.tsx` view + the **shared** cadence (weekly digest + on-drop rebuild). Rationale: the "methods differ" concern lives entirely in the recommendation-building logic, which we keep separate; everything downstream (action dict shape, store, view, scheduler, notifications) is already generic, so unifying there avoids two-places-to-look and duplicated infra. The one thing we can't cheaply un-share later is the single ranked list — accepted, since Maps guidance is a to-do list like organic's.
2. **Full-parity cadence.** Mirror the organic tracker exactly: on-demand rebuild anytime, a **weekly digest** notification, and a **silent on-drop rebuild** that rides the existing `maps_drop` alert.
3. **GBP engagement (data layer #8) is deferred.** It requires Google OAuth 2.0 (`business.manage`) per listing owner — incompatible with the suite's non-interactive service-account model — plus GCP dashboard provisioning. Out of scope for v1; revisit as its own project. See §7.
4. **Recommend-only.** Like the organic Action Plan, every action deep-links a human into an existing tool; nothing is auto-executed.
5. **No new infrastructure.** Reuse `async_jobs`, the `gsc_scheduler` loop, and the notifications service. (Consistent with CLAUDE.md's "don't add a queueing system / scheduler beyond what exists.")

---

## 3. Part 1 — Maps Action Plan (hybrid)

### 3.1 What the user gets

The existing per-client **Action Plan** view (`clients/:id/action-plan`) now also contains local-pack actions, clearly labelled by source (organic vs maps), interleaved by priority. A Maps drop alert now routes the team to a concrete fix instead of a dead-end notification.

### 3.2 Action sources (Maps)

All reads are data the geo-grid tracker **already produces**:

| Signal (existing) | New action `kind` | Recommendation (deep-links to) |
|---|---|---|
| Open `maps_alerts` of type `grid_rank_drop` / `coverage_drop` / `lost_pack` / `area_decline` | `maps_decline` | "Local-pack visibility is slipping {sector}. Diagnose in the geo-grid, then strengthen local signals (GBP posts, reviews in the weak area, location-page content)." → `clients/{id}/maps` |
| `maps_alerts` of type `competitor_surge` | `maps_competitor` | "{competitor} is newly outranking you on N pins. Review their GBP profile + check your category/review parity." → `clients/{id}/maps` |
| `maps_scan_results.report_weak_locations.weak_areas` (geocoded weak towns/cities) | `maps_weak_area` | "Weak coverage near {city} ({n} pins). Create/strengthen a location page targeting it." → `clients/{id}/local-seo` (place pre-filled where feasible) |

### 3.3 Implementation seam (confirmed by code research)

The action dict shape is already generic: `{kind, keyword, diagnosis, recommendation, cta_label, cta_path, severity, sort}`. The store (`reopt_plans.items`) is plain JSONB; `ActionPlan.tsx` renders actions generically.

- **New pure builder** `build_maps_actions(client_id, maps_alerts, weak_areas) -> list[dict]` in `services/reopt_planner.py` (or a sibling `services/maps_action_planner.py` imported by it). Emits the existing shape with the new kinds above and a new `source: "maps"` field. The organic `build_actions` is **untouched** (no regression risk) and gains `source: "organic"` on its rows.
- **`build_plan`** gains two reads after the GSC read (~`reopt_planner.py:230`): open `maps_alerts` (`resolved_at IS NULL`) and the latest scan's `report_weak_locations.weak_areas`. Then `actions = build_actions(...) + build_maps_actions(...)`, existing sort/store unchanged.
- **Sort tier.** Add a Maps tier between cannibalization and quick-wins (e.g. `_SORT_MAPS = 2.5 * _TIER`) so an urgent organic drop still outranks a routine Maps decline but Maps declines sit above hidden wins. `lost_pack` gets a critical bump like deindex does. Final-list cap (`TOTAL_MAX`) stays; revisit if Maps + organic regularly overflow it.
- **Dedup.** Skip a Maps keyword already surfaced as an organic drop for the same keyword (the organic drop supersedes), mirroring the existing `dropped_keywords` suppression.
- **Frontend.** One new `kindMeta` case per new kind in `ActionPlan.tsx` (+ a `MapPin` icon) and a small per-row source chip / optional grouping. No other UI change.

### 3.4 Cadence (full parity)

- **On-demand:** existing `POST .../action-plan/refresh` already rebuilds synchronously — now includes Maps actions for free.
- **Weekly digest:** existing `gsc_scheduler.enqueue_due_reopt_plans` already enqueues a `reopt_plan` job per client; `build_plan` now folds Maps in. The digest notification (`trigger == "scheduled"`) covers both.
- **On-drop rebuild (silent):** add one call in `maps_analyzer.analyze_scan`, right after it emits the `maps_drop` notification, to `enqueue_reopt_plan(client_id, trigger="maps_drop")`. Treated like the organic `trigger="drop"` — silent (no second notification; the `maps_drop` alert already fired).

### 3.5 Tests

- Pure-unit tests for `build_maps_actions` (each alert type → expected action; weak-area → action; empty → no actions).
- `build_plan` ordering test: organic drop > maps decline > quick win > hidden win; `lost_pack` critical bump.
- Dedup test: keyword present as both organic drop and maps decline yields one action.

**Effort: ~1–1.5 days incl. tests.**

---

## 4. Part 2 — Strategic data layers

Each layer adds a data source and an analysis, and (where it implies action) one or more new Action Plan action kinds. Grouped by real effort. Competitor-set size is **capped by config** (default: top-N from the existing maps `competitors` leaderboard) to bound API spend.

### Tier A — reuse existing data, mostly new analysis (cheap, high ROI)

**A1. Share of Local Voice (SoLV). — BUILT.** *Data already exists* — each `maps_scan_results` row carries the client's Top-3 coverage (`top3_pins`/`total_pins`) and a stored `competitors` leaderboard (each with its own `top3_pins`). **Derived on read** (no `maps_solv_metrics` table — follows the existing `build_maps_trends`/`build_competitor_trends` pattern; deviation from §5): pure `services/maps_solv.py` (`overall_coverage`/`build_solv`/`detect_solv_drop`), endpoint `GET /clients/{id}/maps/solv`, rendered as a "Share of Local Voice" panel in the Maps History tab (client coverage sparkline + competitor presence table). **Action** (`maps_solv_drop`, sits near the top of the Maps tier, just under `lost_pack`): "Top-3 local-pack share fell from {x}% to {y}% — {competitor} gained ground." Fed into the Action Plan via `reopt_planner._fetch_maps_signals` (compares the two most recent scans; `SOLV_DROP_MIN_PCT`=10pts). No new API calls.

**A2. Brand-search analysis (GSC). — BUILT.** `gsc_query_daily` already holds every query. Pure `services/brand_search.py` derives brand terms (client name + GBP business name; generic/trade words stripped — manual `brand_terms` override is a follow-up), classifies branded vs non-branded, and buckets a weekly branded-share series (`build_brand_search`); `load_brand_series` resolves the verified property + pages `gsc_query_daily`. Endpoint `GET /clients/{id}/rank/brand-search`; rendered as a GSC-gated "Brand search" tab in Rankings (branded-share KPIs + per-week stacked bars). **Action** (`brand_search_decline`, organic, hidden-win tier): "Branded searches fell {x}% over the last N weeks vs the prior N." Fed into the Action Plan via `reopt_planner._fetch_brand_decline` (`detect_brand_decline`; recent 4 weeks vs prior 4, `BRAND_DECLINE_MIN_PCT`=25% relative). No new table.

### Tier B — existing APIs + creds, new tables + fetch/analysis (medium)

**B1. Competitor GBP intelligence. — BUILT (on-demand; monthly auto-refresh deferred).** `gbp_service.get_business_details()` already fetches arbitrary businesses. `services/competitor_gbp.py` selects the top local-pack competitors from the latest scan's stored `competitors` leaderboards (`select_competitors`, capped by `competitor_gbp_max`=8), fetches each GBP, and inserts a time-series capture into `competitor_gbp_profiles` (migration `20260629160000`) via the async `competitor_gbp` job (best-effort per competitor). Endpoints `GET /clients/{id}/maps/competitor-intel` + `POST .../competitor-intel/refresh`; rendered as a "Competitor intelligence" panel in the Maps History tab (category/rating/reviews/top-3-pins/hours, refresh button). Foundation for B2. *Follow-up: monthly auto-refresh via the scheduler.*

**B2. GBP profile audit / gaps. — BUILT.** Pure `services/gbp_audit.py::audit` scores `clients.gbp` completeness (primary/secondary categories, description, website, phone, photo, hours) and computes competitor-relative gaps vs the B1 profiles — categories on ≥ half the competitors the client lacks (`(n+1)//2` threshold), and a review deficit vs the competitor median. Endpoint `GET /clients/{id}/maps/gbp-audit`; rendered as a "GBP profile audit" panel in the Maps History tab (score + per-check chips + category/review gaps). **Action** (`gbp_gap`, mid Maps tier): one consolidated "strengthen your GBP" item, fed via `reopt_planner._fetch_gbp_audit`. No new fetch (reuses B1 captures + stored client GBP).

**B3. Review analytics. — BUILT (deterministic; LLM sentiment/themes deferred).** `services/review_analytics.py` pulls a fuller review set (all ratings, newest-first via DataForSEO — not gbp_service's 4★-only marketing pull) for the client + top competitors into a new `reviews` table (migration `20260629180000`, content-hash dedup) via the async `review_intel` job, and computes deterministic analytics on read — volume, velocity (reviews/month), rating distribution, recent negatives — client vs competitor medians (`analyze_reviews`/`compare`/`detect_review_gap`). Endpoints `GET /clients/{id}/maps/review-intel` + `POST .../refresh`; "Review analytics" panel in the Maps History tab (you-vs-competitors table + velocity warning). **Action** (`review_gap`, Maps tier): velocity behind the competitor median or recent negatives → "run a review-generation push." *LLM sentiment/theme extraction is a deliberate follow-up (the `reviews.sentiment` column is reserved).*

**B4. Backlinks. — BUILT (summary metrics; per-referring-domain gap deferred).** `services/backlink_intel.py` reuses the SERP snapshot's DataForSEO Backlinks-summary call (`serp_snapshot.fetch_domain_summary`) to profile the client domain (from `clients.website`) + top competitor domains (from B1 websites) into a new `backlink_profiles` time-series (migration `20260629190000`) via the async `backlink_intel` job. Deterministic compare on read — Domain Rating, referring domains, backlinks — client vs competitor medians (`compare`/`detect_backlink_gap`). Endpoints `GET /clients/{id}/maps/backlink-intel` + `POST .../refresh`; "Backlink authority" panel in the Maps History tab. **Action** (`backlink_gap`, organic, hidden tier): DR or referring-domains behind the competitor median → "run link-building." *The specific referring-domains-competitors-have-that-you-don't list needs the heavier per-domain endpoint — a follow-up.*

**B5. Website content analysis. — BUILT (depth + heading coverage; semantic/entity comparison deferred).** `services/content_intel.py` fetches the top organic URLs for a keyword (DataForSEO SERP), scrapes the client's ranking page + top competitor pages (ScrapeOwl via `website_scraper`), and compares **content depth** (word count vs competitor median) + **topic coverage** (H2/H3 headings on ≥ half the competitor pages the client lacks) — pure `extract_outline`/`compare_content`/`detect_content_gap`. Stored per keyword in `website_analyses` (migration `20260629200000`) via the async `content_intel` job. Endpoints `GET /clients/{id}/maps/content-intel` + `POST .../refresh?keyword=` (defaults to the client's first active Maps keyword); "Content vs competitors" panel in the Maps History tab. **Action** (`content_gap`, Maps tier): "your page is ~N words thinner; missing topics: …" → expand via Local SEO. *Deep semantic/entity comparison (TextRazor via nlp-api) is a follow-up.*

### Tier C — deferred (see §7)

**C1. GBP engagement** (profile views, calls, direction requests, website clicks). **Deferred.**

---

## 5. Data model (new tables)

All in the suite's public schema, FK → `clients`, RLS on (service-role access only, per the suite rule). Migrations in `writer/supabase/migrations/`.

- `maps_solv_metrics` (A1) — client_id, keyword, scan_id, as_of, client_coverage_pct, competitor_shares (JSONB), created_at.
- (A2 reuses `gsc_query_daily`; brand classification can be a computed view or a `brand` flag column + a small `brand_terms` config on the client.)
- `competitor_gbp_profiles` (B1) — client_id, competitor_place_id, captured_at, profile (JSONB), name, primary_category, rating, review_count, …
- `reviews` (B3) — client_id, subject_place_id (client or competitor), review_date, rating, text, reviewer, source, sentiment, themes (JSONB).
- `backlink_profiles` (B4) — client_id, subject_domain (client or competitor), captured_at, domain_rating, referring_domains, backlinks, new_domains/lost_domains (JSONB).
- `website_analyses` (B5) — client_id, subject_url, keyword, captured_at, title, meta, word_count, headings (JSONB), topics (JSONB), is_competitor.

(Final column lists firm up per phase; this is the shape.)

---

## 6. Sequencing

1. **Phase 1** — Part 1 (Action Plan hybrid + cadence). Ships parity; gives the framework every new action hangs on.
2. **Phase 2** — Tier A (A1 SoLV, A2 brand search). Cheap, strategic, no new API spend.
3. **Phase 3** — Tier B cluster (B1 → B2 → B3/B4/B5), each building on the last.
4. **Phase 4 (conditional)** — Tier C / GBP engagement, only if OAuth is greenlit later.

---

## 7. Deferred: GBP engagement (#8) — why and what it needs

GBP engagement metrics are **not collectable with current infrastructure**:

- Google's **GBP Performance API** requires **OAuth 2.0 with the `business.manage` scope**, granted per listing owner. The suite authenticates Google with a **non-interactive service-account key** (used for GSC); the Performance API rejects service accounts.
- Enabling it would require: new `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`, the GBP Performance API enabled on the GCP project, an OAuth consent screen, and a **per-client refresh-token** storage + refresh flow — plus a new `gbp_engagement_metrics` table and daily ingest.

That is a dashboard-level + new-auth-paradigm change. Per CLAUDE.md ("You should NOT need dashboard-level setup. If you think you do, stop and ask"), it is **out of scope for v1** and parked here. A lighter fallback (DataForSEO/Outscraper GBP-insights data, if any exists) can be investigated before committing to OAuth.

---

## 8. Credentials status

All Tier A + Tier B layers use **already-provisioned** creds: `DATAFORSEO_LOGIN/PASSWORD`, `OUTSCRAPER_API_KEY`, `SCRAPEOWL_API_KEY`, `TEXTRAZOR_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_KEY` (GSC), `GOOGLE_MAPS_API_KEY`. **Only the deferred Tier C needs new creds** (`GOOGLE_CLIENT_ID/SECRET` + GBP Performance API).

---

## 9. Out of scope for v1

- GBP engagement metrics (§7).
- Any auto-execution of recommendations (recommend-only, per §2).
- A standalone Maps-only Action Plan view (rejected in favor of the unified view, §2).
- Customer-facing exposure of any of this data (internal agency use only, per CLAUDE.md).
