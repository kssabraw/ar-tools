# Google Trends Discovery — module plan v1.0

**Status:** Shared core + Phase 1 (ecommerce) **BUILT 2026-09-15**, ships **dark** behind `google_trends_enabled` (code default False). Phases 2–4 remain. Corrected against the adversarial review (the `item_types`/sandbox-reachability/category-count fixes below are now decisions in the code, not open risks).
**Author:** drafted 2026-09-14; built + corrected 2026-09-15.

> **Build note (what shipped in the first PR).** Migration `20260915120000_google_trends.sql` (applied live: `google_trends_runs` / `google_trends_keywords` / `google_trends_usage` + the fail-closed `reserve_google_trends_calls` RPC + `async_jobs` CHECK += `google_trends_scan`). `services/google_trends.py` (wrapper + pure parsers/scoring + budget + scan job). `routers/google_trends.py` (`/clients/{id}/google-trends` scan/runs/estimate/jobs + `/google-trends/categories`). Config `google_trends_*`. `scripts/verify_google_trends.py` (the Railway smoke-test). Frontend `pages/GoogleTrends.tsx` + a "Google Trends Discovery" workspace card + route. Pure helpers unit-tested (`tests/test_google_trends.py`, 14). **Before flipping the flag on: run `scripts/verify_google_trends.py` from Railway PLATFORM** — the sandbox cannot reach `api.dataforseo.com`, so the live response shape is unconfirmed.
**One-liner:** a demand-discovery front door that pulls *rising* queries from Google Trends (via DataForSEO), qualifies them with the volume/CPC data we already buy, and routes the survivors into the research → strategy → draft flow the suite already runs.

> **Read this first.** This is an **input source**, not a new pipeline. Everything downstream of "here is a rising query" already exists (Keyword Research, Topic Research, the Strategist, "Write this post", the blog Writer, the seasonal-demand watcher). The whole build is *one shared core* + *four thin surfaces* that reuse those modules. If you find yourself building a second scorer, clusterer, or content generator, stop — you're rebuilding something that already ships.

---

## 0. Why this exists (and what it is NOT)

A viral post claimed Google Trends' category-browsing + "rising related queries" lets you find trending keywords before competitors who lean on backlink-lagging tools. The **real kernel**: Trends surfaces emerging demand days-to-weeks before it shows up in volume-based tools, and it is near-real-time.

**What it is NOT — the traps this plan deliberately avoids:**

1. **Not a keyword-volume source.** Trends gives *relative interest over time* and *rising/top related queries* — **not** absolute search volume, CPC, competition, or keyword difficulty. A rising query is a *lead*, never a target. Every rising query MUST pass through DataForSEO qualification (`dataforseo_labs.parse_keyword_overview` — the same call Keyword Research already uses) before it is actionable. Skipping that is how you write content for a spike with zero commercial intent.
2. **Not an LLM problem.** The tweet's "GPT-6 / ChatGPT plugin" framing is noise. This is a data-fetch + filter + route problem. The LLM only enters at the end (turning a qualified trend into a brief), which we already do.
3. **Not a scraper.** No `pytrends`, no scraping `google.com/trends`. We already pay DataForSEO, which exposes the Google Trends endpoints natively (`keywords_data/google_trends/*`). The tweet's "click CATEGORY" step is literally one request parameter (`category_code`).
4. **Not a replacement for anything.** It's an additional discovery signal alongside seed-driven Keyword Research and problem-first Topic Research. Those start from a seed the user supplies; this surfaces the seeds themselves.

**Honest fit caveat (owner-confirmed 2026-09-14: build for all four segments).** Google Trends category-trending is dominated by *national consumer/news* trends. Its value is highest for **ecommerce/DTC** (a rising ingredient/compound is timely + commercial) and **informational content sites**, real-but-narrow for **local seasonal** (storm/season spikes only — most local service demand is stable, not trend-driven), and broadest-but-least-targeted for a **portfolio-wide** scanner. The phasing below sequences by that ROI ordering.

---

## 1. The one-engine insight (why "all four" is cheap)

All four requested surfaces are the same three-step engine wearing different clothes:

```
  fetch rising Trends  →  qualify with DataForSEO  →  route into an existing module
```

They differ only in **scan scope** and **downstream route**:

| Surface | Scan scope | Routes into |
|---|---|---|
| Ecommerce / DTC | category + keyword-anchored (rising *related* to a seed) | Keyword Research → "Write this post" |
| Informational sites | category (rising *within* a category) | Topic Research → topic cards → blog run |
| Portfolio-wide | category sweep, no client scope | Notifications digest (DORA / SerMaStr surface) |
| Local seasonal | geo-scoped, keyword-anchored | `trend_watch.py` seasonal-demand enrichment |

So "all four" is **the shared core + progressively cheaper surfaces**, not four builds. Phase 1 pays for the core; Phases 2–4 are thin.

---

## 2. Data source: DataForSEO Google Trends (endpoint shape to lock)

**Family:** `keywords_data/google_trends/` — a *different* DataForSEO family from `dataforseo_labs` (Labs is domain/keyword intelligence; this is the Trends product). New wrapper `services/google_trends.py`; **do not** bolt it onto `dataforseo_labs.py`.

**Primary endpoint:** `POST /v3/keywords_data/google_trends/explore/live`
- Returns, for up to 5 keywords: `interest_over_time`, `trends_topics_list` / `related_queries` (with a **`rising`** bucket and a `top` bucket), and per-region breakdowns.
- Key params to expose:
  - `category_code` — the "hundreds of categories" the tweet references (DataForSEO ships the Google Trends category taxonomy; we vendor it as a static map, see §5).
  - `location_name` / `location_code` — geo scope (defaults to the client's rank-tracking location, mirroring the Keyword Research location default).
  - `date_from` / `date_to` or `time_range` — recency window (default: trailing 90 days, so "rising" means rising-recently).
  - `type` — `web` (default) | `news` | `youtube` | `froogle` (shopping) | `images`. (The `froogle` literal for shopping is documented-convention but unconfirmed live — verify with the Railway smoke-test.)
  - **Do NOT send `item_types`.** The documented `item_types` param is **rejected live** with task error `40501 Invalid Field: 'item_types'` (confirmed via GitHub `superdesigndev/treg#493` during the adversarial review). `google_trends_queries_list` is returned in the DEFAULT response, so the parser reads it from there. The wrapper never sends `item_types`.

> **⚠️ Verify against a LIVE call — from Railway, not the sandbox.** The build sandbox is **egress-blocked** from `api.dataforseo.com` (a 403 CONNECT tunnel, confirmed during the review), so the live response shape could NOT be confirmed at build time. `scripts/verify_google_trends.py` makes one real `explore/live` + one `categories` call and prints the shape; **run it from the Railway PLATFORM service** (which holds the creds and has egress) before flipping `google_trends_enabled` on. If the live shape differs from `parse_rising_queries`'s fixtures, update the parser + `tests/test_google_trends.py` together. Auth mirrors `dataforseo_labs._auth_header`; `_post` copies `dataforseo_labs._post` (retry + jittered backoff verbatim).

**Cost note:** Trends `explore/live` is billed per task. A single category sweep across many categories is where cost accumulates — hence the budget meter (§4) and the per-scan category cap.

---

## 3. The qualify gate (non-negotiable)

Between "rising query" and "actionable" sits one deterministic gate, reusing existing code:

1. **Enrich** — batch the rising queries through `dataforseo_labs.parse_keyword_overview` (volume / CPC / competition / KD), the exact call Keyword Research already makes, chunked at 1000 via the existing `chunk` helper. Reuse its cross-client market cache (`keyword_market.py`) so a term another client already priced is free.
2. **Drop the un-priceable** — a rising query DataForSEO returns zero volume for is a *spike without a market*; it's tagged `no_demand` and excluded from the actionable set (kept in the raw scan for inspection, never surfaced as a recommendation).
3. **Score** — `trend_score = rising_velocity × log(volume) × commercial_intent_weight`. Pure, unit-tested, in `google_trends.py`. `rising_velocity` comes from the Trends `rising` bucket's breakout/percentage value; `commercial_intent_weight` reuses the intent-weighting already in `keyword_research.opportunity_score` (do not invent a second intent model).
4. **Audience/relevance gate (client-scoped scans only)** — for a client scan, reuse the existing `keyword_research_relevance` semantic gate + `keyword_research_audience` job-seeker/off-audience filter so a category's national noise doesn't flood a client's list. Portfolio scans skip this (no client anchor).

**Output of a scan:** a persisted run of `{keyword, category, rising_velocity, volume, cpc, competition, kd, trend_score, intent, audience_fit, source_geo, type}` rows — the same shape Keyword Research rows carry, so the existing table renderer + CSV export + "Write this post" action all work unchanged.

---

## 4. Shared core (build once, Phase 1)

Mirrors the `keyword_research` module's proven shape one-for-one:

- **`services/google_trends.py`** — the DataForSEO wrapper (impure fetch + pure parsers) **and** the pure scoring/gate helpers (`trend_score`, `rank_rising_queries`, `build_trends_rows`). Pure helpers unit-tested (`tests/test_google_trends.py`), external calls mocked — never hit DataForSEO in tests.
- **Budget meter** — `google_trends_usage` table + `reserve_google_trends_calls(p_day, p_n, p_cap)` RPC, atomic, **fail-closed** (a refused reservation spends nothing — copy the `reserve_keyword_research_calls` RPC, not the fail-open `keyword_research` HTTP path). Config `google_trends_daily_call_budget` (start conservative — see §8 open item).
- **Async job** — `google_trends_scan` registered in `job_worker._dispatch` (the `elif job_type == ...` chain) + imported at the top, exactly like `run_keyword_research_job`. Runs on the interactive worker lane. Idempotent per run row.
- **Data model** — `google_trends_runs` (jsonb result set + scan params + filter summary, mirroring `keyword_research_runs`) + `google_trends_keywords` (per-row, `run_id` FK, the qualified rows). Migration `writer/supabase/migrations/<ts>_google_trends.sql` — apply live via the Supabase MCP, and add `google_trends_scan` to the `async_jobs` job_type CHECK (rebuild the CHECK from the *live* constraint, per the house gotcha — the live set is wider than any repo file).
- **API** — `routers/google_trends.py`: `POST /clients/{id}/google-trends/scan` (+ `POST /google-trends/scan` for portfolio/no-client), `GET .../runs`, `GET .../runs/{run_id}`, `GET .../categories` (the static taxonomy for the dropdown), `GET .../estimate` (free preflight cost estimate before a paid sweep). Budget-guarded; returns `needs_confirm` + cost when a sweep would spend.
- **Config** — `google_trends_*` block: `enabled` (default **False** — ships dark), `daily_call_budget`, `default_time_range` (90d), `max_categories_per_scan`, `rising_velocity_min`, `no_demand_drop` (bool), `scan_type` default (`web`).

---

## 5. Category taxonomy

Google Trends categories are a fixed `category_code` tree (root "All categories" = 0). DataForSEO exposes a **free** categories endpoint (`POST /v3/keywords_data/google_trends/categories`, confirmed real + $0 in the review), so rather than vendor a static JSON we **fetch it live and cache it per process** (`google_trends.fetch_categories`, best-effort — an empty list on failure, and the scan form falls back to a free-text category code). The exact node count is unknown (the "~1,400" figure in an earlier draft was unattributed and has been dropped); the smoke-test prints the real tree. The leaf codes ride through to the API as `category_code`.

---

## 6. The four surfaces (Phases 1–4, by ROI)

### Phase 1 — Ecommerce / DTC (proves the whole loop)
Highest, most commercial ROI (peptide clients feel it immediately). Category + keyword-anchored scan (rising queries *related to* a seed compound/product) → qualify gate → the existing Keyword Research table + **"Write this post"** action (already wired: card → blog run, `topicSeedKeyword`/`composeWriterNotes`). Frontend: a "Trending now" panel + scope picker on `pages/KeywordResearch.tsx` (reuse the seed box, the location picker, the budget-meter callout, the thin-result UX). **This phase pays for the shared core; everything after is thin.**

### Phase 2 — Informational content sites
Nearly free once Phase 1 exists. Same category scan, routed to **Topic Research** (`keyword_topic_research` / the Strategist) → topic cards grouped by pillar → the blog run we already wire. This is the tweet's exact "click category → pick trending topic → write" workflow, done right (qualified, deduped against existing content via `keyword_topic_coverage`, and strategist-prioritized rather than a raw list).

### Phase 3 — Portfolio-wide scanner
An agency-level "what's rising this week" scan (category sweep, no client scope) → a deterministic weekly digest through the **notifications service** (`kind="trends_digest"`, `client_id=None`), surfaced by DORA / SerMaStr. Reuses the core with no client anchor and skips the client relevance/audience gate. Rides the shared `gsc_scheduler` weekly block (self-gated on `google_trends_enabled`), like every other scheduled scan. **No new infra.**

### Phase 4 — Local seasonal (narrowest, last — re-scoped after the review)
Geo-scoped Trends feeding the seasonal-demand signal we **already** have in `trend_watch.py`. **Two corrections from the adversarial review, both to respect before building this:**
1. **It is NOT "the same engine" as Phases 1–3.** `trend_watch.demand_outlook` consumes a *calendar-month seasonality profile* (a monthly `index` dict from 12-month history), not the *rising queries* the §1 engine produces. To corroborate it you need Trends' **`interest_over_time`** series (a different slice of the explore response) run through a new seasonality-profile builder — a different downstream contract. So Phase 4 is a distinct, smaller build, not a thin reroute; treat it as Phase 5/"later," or cut it.
2. **Local geo is where the data is thinnest.** The §3 qualify gate needs DataForSEO Ads volume, which the suite's own **LeadOff ZIP-demand probe** (`docs/modules/leadoff-gbp-placement-plan-v1_0.md`, dropped 2026-08-26) measured returns `null` at ZIP granularity, and Trends itself is sparse below metro. Scope Phase 4 to **metro-level geo only** (where volume resolves), or gate it on the same feasibility that probe failed. Most local demand is stable anyway — the least load-bearing of the four.

---

## 7. What this reuses (the "don't rebuild it" map)

| Need | Existing thing to reuse | Do NOT build |
|---|---|---|
| Volume/CPC/KD qualification | `dataforseo_labs.parse_keyword_overview` + `keyword_market.py` cache | a second market fetcher |
| Intent weighting | `keyword_research.opportunity_score` intent weights | a second intent model |
| Semantic relevance gate | `keyword_research_relevance` | a second embedding gate |
| Audience filter | `keyword_research_audience` | a second audience judge |
| Clustering / table / CSV | Keyword Research row shape + renderer | a new results view |
| Trend → draft | "Write this post" (card → blog run) | a new content path |
| Topic strategy | `keyword_topic_research` / Strategist | a new topic planner |
| Seasonal enrichment | `trend_watch.demand_outlook` | a new seasonality model |
| Scheduling | `gsc_scheduler` weekly block | new infra |
| Delivery | `notifications.emit` | a new channel |
| Budget metering | `reserve_keyword_research_calls` RPC pattern | anything Redis/queue |

---

## 8. Open items / decisions to lock before build

1. **DataForSEO daily budget ceiling** — `google_trends_daily_call_budget` needs the owner's real DataForSEO monthly ceiling (same open item Domain Intelligence carries). Start conservative (e.g. 100/day) until a real spend rate is measured. **[owner input needed]**
2. **Live endpoint verification** — one real `explore/live` call, response saved to `scratchpad/`, parser written against it, before any parse code. **[build-time task]**
3. **"Rising" threshold** — DataForSEO's rising bucket includes "Breakout" (>5000%) and numeric % rows. Decide the `rising_velocity_min` floor from a real category sample, not a guess. **[build-time, calibrate on live data]**
4. **Portfolio digest cadence + audience** — weekly by default; which channel (DORA #dora vs SerMaStr strategy channel) and whether it's owner-only. **[owner input, Phase 3]**
5. **Trends `type` per segment** — ecommerce likely wants `froogle`/`web`; informational wants `web`/`news`; local wants `web`. Default per surface, overridable. **[design detail, low-risk]**

---

## 9. Non-goals (v1)

- No scraping / `pytrends`. DataForSEO only.
- No Trends-only content — the qualify gate (§3) is mandatory; a rising query never reaches a writer without DataForSEO pricing.
- No new scorer/clusterer/content generator — reuse the map in §7.
- No real-time/streaming ("trending right now this minute") — a daily/weekly scan cadence is the product; sub-day polling adds cost for noise.
- No auto-generation from a trend without a human in the loop (a scan surfaces candidates; a person clicks "Write this post" or the autonomy executor proposes — it does not auto-publish).

---

## 10. Rough build order (checklist)

- [x] `services/google_trends.py` wrapper + pure parsers + pure scoring (`tests/test_google_trends.py`, 14 passing)
- [x] Migration: `google_trends_runs` + `google_trends_keywords` + `google_trends_usage` + `reserve_google_trends_calls` RPC + `async_jobs` CHECK += `google_trends_scan` (**applied live**)
- [x] `google_trends_scan` async job + `job_worker` dispatch + fail-closed budget meter
- [x] `routers/google_trends.py` (scan / runs / estimate / jobs + free `/google-trends/categories`)
- [x] Qualify gate wired to `dataforseo_labs.fetch_keyword_overview` (volume/CPC — the non-negotiable gate; §3)
- [x] **Phase 1** frontend `pages/GoogleTrends.tsx` + workspace card + route (ecommerce, keyword-anchored) — dedicated page rather than a KeywordResearch panel (lower regression risk on that large file; the "Write this post" reuse is the next follow-up)
- [x] `google_trends_enabled` flag + `google_trends_*` config block (ships dark, code default False)
- [x] `scripts/verify_google_trends.py` (the Railway live smoke-test, §2)
- [ ] **BEFORE FLAG ON:** run `scripts/verify_google_trends.py` from Railway PLATFORM → confirm the `google_trends_queries_list` shape; reconcile parser/fixtures if it differs (§2, §8.2)
- [ ] Follow-up: "Write this post" CTA from a qualified row (Phase 1.1)
- [ ] Follow-up: relevance/audience gate for a future seedless category scan (Phase 2 needs an anchor source — a seed-anchored Phase 1 scan doesn't)
- [ ] Phase 2 route to Topic Research
- [ ] Phase 3 portfolio weekly digest on `gsc_scheduler` + notifications
- [ ] Phase 4 `trend_watch` seasonal enrichment (re-scoped — see Phase 4 above: `interest_over_time`, metro-geo only)

---

_Authoritative for this module once approved. Supersedes nothing. Reuses: Keyword Research, Topic Research, the Strategist, "Write this post", `trend_watch`, `keyword_market`, `dataforseo_labs`, `gsc_scheduler`, the notifications service._
