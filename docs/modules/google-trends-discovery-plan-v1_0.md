# Google Trends Discovery — module plan v1.0

**Status:** Shared core + Phases 1, **1.1, 2, 3, and 4** all **BUILT** (Phase 1 2026-09-15; Phase 1.1 + 2 + 3 + 4 continued 2026-09-15, PR #1109), live-shape-fixed (#1118), and **ENABLED in production 2026-09-15** (`GOOGLE_TRENDS_ENABLED=true` on PLATFORM; code default stays False so a fresh env ships dark). **Live DataForSEO shape VERIFIED** on the deployed code (real end-to-end runs, since the sandbox is egress-blocked): rising-queries + interest-over-time both confirmed. One bug found + fixed while enabling — rising queries are single-term, so each seed must be its own explore (see §2); category + portfolio (which chunked 5 seeds/call) were silently returning 0 and need a live re-smoke-test after the fix deploys.
**Author:** drafted 2026-09-14; built + corrected 2026-09-15; Phases 1.1–4 continued 2026-09-15.

> **Continue build note (Phases 1.1–4, PR #1109).** Migration `20260916120000_google_trends_phases234.sql` (**applied live**): `google_trends_runs.mode` (keyword|category|portfolio|local_seasonal) + `client_id` made nullable (portfolio) + `google_trends_keywords.relevance_score`/`audience_fit`/`source_client_name`. **Phase 1.1** — a "Write this post" CTA on a qualified rising-query row (`pages/GoogleTrends.tsx`, cloning KeywordResearch's `topicSeedKeyword`/`composeWriterNotes` → `POST /runs`). **Phase 2** — a SEEDLESS category scan (`run_google_trends_category_scan`): seeds derived from the client's site topics/ICP (`keyword_research_topics.research_topics`) → the SAME relevance (`keyword_research_relevance.score_relevance`) + audience (`keyword_research_audience.filter_by_audience`) gates → survivors routed to Topic Research via the existing `POST /clients/{id}/topic-research` (a frontend "Send to Topic Research" button, so the expensive strategist run is an explicit click). **Phase 3** — a weekly portfolio sweep (`run_portfolio_trends_sweep`) over the union of clients' tracked keywords (no client scope, no relevance/audience gate) → a deterministic `trends_digest` notification that falls through to the SerMaStr strategy channel (`slack_default_channel` — in NEITHER the PACE nor DIRECTOR routing set); wired weekly on the shared `gsc_scheduler` (`enqueue_due_portfolio_trends_sweep`, self-gated) + an on-demand admin `POST /google-trends/portfolio-sweep`. **Phase 4** (re-scoped, LAST) — `parse_interest_over_time` + `seasonality_profile_from_series` (pure, the exact `{"index":{1..12}, "peak_months"}` shape `trend_watch.demand_outlook` consumes) + `run_local_seasonal_scan` (metro-gated, one explore per keyword over a 24-month window; result rides the job row, no new table). Pure helpers unit-tested (`tests/test_google_trends.py`, now 25). Config: `google_trends_category_seed_cap`, `google_trends_portfolio_weekday`/`_max_clients`/`_seeds_per_client`/`_digest_size`, `google_trends_seasonal_months`.

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
  - **`item_types` IS required for the rising-query scan, ONE keyword per call** (both corrected live 2026-09-15; the earlier "rejected with 40501 / never send item_types" note was **wrong** — fixed in #1118). The DEFAULT explore response carries only `google_trends_graph` (interest_over_time) and NO queries list, so a rising-query scan MUST send `item_types: ["google_trends_queries_list"]`. And Google Trends related/rising queries only exist for a **single search term**, so each seed is its own explore call — a multi-keyword explore is a comparison view that returns zero rising queries (`_QUERIES_EXPLORE_KEYWORDS=1`). The seasonal (graph) scan omits `item_types` and already explores one keyword per call.

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
- [x] **BEFORE FLAG ON:** live-verify the shapes on the deployed code (§2, §8.2). Done 2026-09-15 via real end-to-end runs on PLATFORM (worker path, since the sandbox has no egress): the `google_trends_queries_list` shape (keyword scan → 13/25 rising, all qualified) AND the `google_trends_graph` interest_over_time shape (seasonal → full 12-month `demand_outlook`). Flag flipped: `GOOGLE_TRENDS_ENABLED=true` on PLATFORM.
- [x] **Enablement fix — ONE keyword per rising-query explore.** Found while smoke-testing: Google Trends rising/related queries are a single-term concept, so a multi-keyword explore returns 0 (category + portfolio were chunking 5 seeds/call → always 0). Fixed to one explore per seed (`_QUERIES_EXPLORE_KEYWORDS=1`; estimate + config updated); each seed now costs one billed explore call (keep the portfolio caps × budget in mind). Category + portfolio need a live re-smoke-test after the fix deploys.
- [x] **Follow-up:** the category scan derives good on-topic anchor seeds but they can be too long-tail for Trends to carry rising related queries (returns 0 even with the single-keyword fix). **Done** — `google_trends.head_term_seeds` reduces each DERIVED category-scan seed to its head term (first 1-3 significant tokens via `keyword_research.tokenize`, deduped + capped) before exploring; the rich relevance anchors keep the full derived set. Applied to derived seeds only — Phase-1 user seeds stay verbatim. Pure + unit-tested.
- [x] Follow-up: "Write this post" CTA from a qualified row (Phase 1.1)
- [x] Follow-up: relevance/audience gate for the seedless category scan (Phase 2 — anchored on the client's site topics/ICP via `keyword_research_topics`)
- [x] Phase 2 route to Topic Research (frontend "Send to Topic Research" → the existing `POST /clients/{id}/topic-research`)
- [x] Phase 3 portfolio weekly digest on `gsc_scheduler` + notifications (`trends_digest` → strategy channel)
- [x] Phase 4 `trend_watch` seasonal core (`interest_over_time` parser + seasonality-profile builder → `demand_outlook`, metro-geo only; result rides the job row)
- [x] Phase 4 follow-up: persist the Trends seasonality where `trend_watch.build_demand_outlook` reads it, so it surfaces on the Forecast card automatically. **Done** — new `google_trends_seasonality` table (client × keyword × location, migration `20260916130000`, **applied live**); `run_local_seasonal_scan` upserts each per-keyword profile into it (best-effort, thin profiles skipped so an existing one is preserved); `trend_watch.build_demand_outlook` reads it and PREFERS the stored Trends profile over `keyword_market.monthly_searches` per keyword (Trends = the seasonality SHAPE, Ads volume = the WEIGHT), merged via the pure unit-tested `trend_watch.merge_seasonality_profiles` so the `demand_outlook()` output shape is unchanged and the Forecast card renders identically. Never overwrites `keyword_market.monthly_searches`.
- [x] **"Trending / social" lane — Phase A (classify + surface)** (issue #1129, PR #1132, merged). A rising query with NO Ads volume (`qualified=false`) is often an EMERGING term too new to have measured volume yet — the trend-jacking signal for SOCIAL / short-form content, not SEO. The scan already KEEPS those rows; `services/google_trends_social.py` tags them (unqualified rows only, best-effort): **Axis 1** social-shaped-from-the-text (a deterministic social/SEO-marker wordlist, then ONE batched Haiku call resolves the `ambiguous` ones — mirrors `keyword_research_audience`) → `social_lean` + `suggested_format`; **Axis 2** velocity (`rising_value` over `google_trends_social_velocity_floor`, `is_breakout` always passes); `social_score = velocity × lean weight` is the lane's sort key (NOT `trend_score`, ~0 for a no-volume row). Stored on `google_trends_keywords` (migration `20260916140000`, **applied live**: `social_lean`/`suggested_format`/`social_score`); `get_run` exposes the floor; frontend `pages/GoogleTrends.tsx` has a "Content (SEO) / Trending / social" toggle sorting by `social_score` with a suggested-format badge (CSV carries the columns). Config `google_trends_social_classify_enabled`/`_llm`/`_model`/`_max_tokens`/`_velocity_floor`. Pure helpers unit-tested (`tests/test_google_trends_social.py`, 13). **Live-verified in prod 2026-09-15**: an `ozempic` scan tagged `"ozempic weight loss coworker discussions"` (rising +6550%, no demand) → `social` / `short-form video` / score 2.83, while medical/dosage/comparison terms stayed `seo` (score 0); a `semaglutide` scan produced zero false-positive social rows (good precision) and exercised the Haiku ambiguous→seo path.
- [x] **"Trending / social" lane — Phase B (the social action)** (issue #1129, PR #1133, merged). Each Trending/social row has a **"Draft social post"** button that fans the trend out into reviewable, platform-native social drafts via the EXISTING Social module — frontend-only, mirroring how "Write this post" reuses `POST /runs`: the modal fetches the client's connected accounts (→ platforms), pre-fills the topic (query) + an angle composed from the query + velocity + `suggested_format`, and calls `POST /clients/{id}/social/fan-out` (`source_type='topic'`), then links to the Social page to review + publish (nothing auto-posts; publishing stays human-in-the-loop + freeze-gated there). No backend change, no migration, no new paid-call surface. Graceful states: social disabled (503) / no accounts (prompt + link) / frozen (409). **Deferred (optional, not blockers):** the PostPeer engagement **calibration loop** (measure engagement → tune the velocity/lean thresholds) + an optional **social-listening source** for direct trend measurement — both need real usage data first.

---

_Authoritative for this module once approved. Supersedes nothing. Reuses: Keyword Research, Topic Research, the Strategist, "Write this post", `trend_watch`, `keyword_market`, `dataforseo_labs`, `gsc_scheduler`, the notifications service._
