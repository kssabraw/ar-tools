# LeadOff — Market Intelligence Module (PRD v1.0)

**Status:** v1 (read-only board + market briefs) shipped on branch `leadoff-module`.
**Authoritative for this module.** Agent usage rules: `docs/sops/LeadOff_Market_Intelligence_SOP.md`.
Scanner methodology + data provenance: `GBP Demographics Script\CLAUDE.md` on the
owner's machine (the scanner pipeline is external to this repo; its outputs are
served from Supabase).

## 1. What it is

LeadOff answers the question every other module assumes is already answered:
**"which market (city × service category) should we enter?"** It is the suite's
pre-client, top-of-funnel tool — a sabermetric market scanner covering
**34,352 measured US markets** (1,491 cities ≥30k pop × 100 home-service GBP
categories, incl. NYC boroughs) plus 955 nameable-neighborhood combos, each
graded A+…F for lead-gen buildability.

Per market it knows: regressed search demand (xdemand — outlier-corrected),
lead economics (per-category lead values × capture assumptions), rankability
(field review-strength + exact-category-lever openness), WPA-style effort stats
(`rev_win` = reviews to beat the #3 incumbent; `roi` = $/mo per review of
effort), luck/fragility flags (BABIP-style demand-vs-expectation), and — when
the Pass-2 caches hold it — competitor referring domains, review velocity, and
12-month demand trend.

## 2. Data (Supabase, schema `market_scanner`)

All tables live in the suite's own Supabase project, schema `market_scanner`
(populated by the external scanner; grants to `service_role` applied):

| Table | Rows | Serves |
|---|---|---|
| `leadoff_board` | 34,352 | the precomputed board (grades, economics, forensics) |
| `serp_top5` | ~170k | top-5 competitors per market (brief) |
| `domain_backlinks` / `business_reviews` / `demand_trend` | caches | Pass-2 enrichment (90-day freshness) |
| `lead_values`, `exp_val_percentiles`, `categories`, `cities`, `field_quality`, `aio_presence`, `nameable_*`, `neighborhood_opportunities`, `market_opportunity_master` | — | assumptions, references, raw scan |

**Activation requirement:** `market_scanner` must be listed in Supabase
PostgREST **Exposed schemas** (dashboard → API settings) — see HANDOFF.md.

## 3. Backend (built, v1)

- `services/leadoff_db.py` — `market_scanner`-scoped Supabase client
  (fanout-pattern `ClientOptions(schema=...)`).
- `services/leadoff.py` — pure, unit-tested logic (percentile→grade with the
  small-market / brutal-field vetoes; assumption recompute from
  capture/lead-tier; cache-enrichment assembly) + data access.
- `routers/leadoff.py` —
  - `GET /leadoff/board` — filters (city/state/category/min_demand), sorts
    (build|roi|expected|value|leads|demand|v3), assumption knobs
    (`capture` 0.01–0.5, `lead_tier` low|mid|high), `limit` ≤500. Non-default
    assumptions recompute economics server-side; grades under them are
    approximate (fixed percentile reference) and flagged
    `assumptions.approximate`.
  - `GET /leadoff/market-brief?city_id=&category_id=` — board row + top-5
    competitors + best-effort cached enrichment.
  - `POST /leadoff/create-client` (built post-v1 — §5 item 2) — the handoff:
    creates a client through the normal clients path (staff-gated; website
    optional — LeadOff is research-first, `ClientCreateRequest.website_url`
    relaxed to allow empty with every consumer truthiness-guarded), with
    `business_location` from the market's city, the top-5 seeded into
    `client_competitors` (`sources: ["leadoff"]`, best-effort per row), and
    the effort targets (reviews to beat #3, RD link budget ×10, momentum at
    scan) recorded as a `custom` campaign goal
    (`services/leadoff.handoff_competitors`/`handoff_goal`, unit-tested).
- Config: `leadoff_prefetch_rows` (pre-rank fetch bound for non-default
  assumption re-sorts).
- Tests: `tests/test_leadoff.py` (15 pure-logic tests).

## 4. Frontend (built, v1)

`pages/LeadOff.tsx`, suite-level route `/leadoff`, sidebar entry
(`Radar` icon, between Clients and Backlinks). Board table (grade chips,
HOT?/COLD? luck badges, low-confidence markers), filter/assumption bar
(capture slider, lead-tier, sorts incl. **ROI — win cheapest**), CSV export,
and a drill-in brief panel (economics · field forensics with the top-5
competitor list · scouting report, with RD displayed **×10 as true RD** per
`_ORCHESTRATOR.md` §2, and a **Create client from this market** card — name
required, website optional — that runs the §5-item-2 handoff and routes to
the new client workspace).

## 5. Build order (items 1–4 now built)

1. **Paid actions — ✅ built**: `POST /leadoff/tryout` (score any off-list
   city, ~$0.20) and `POST /leadoff/scout` (RD + review velocity + trend,
   ~$0.10–1/market, cache-cheapened) — ported faithfully from the scanner's
   `check_city.py` / `enrich_shortlist.py` (reference copies at
   `docs/reference/leadoff-scanner/`, the methodology authority).
   `services/leadoff_actions.py` (pure stats/economics/cache-contract
   builders unit-tested in `tests/test_leadoff_actions.py`) + async jobs
   `leadoff_tryout` / `leadoff_scout`. Tryout: keyword task with both forms →
   vol≥20 gate → Maps SERP at **13z** → rankability (category aliases) →
   grade vs `exp_val_percentiles`; results persist to `leadoff_tryouts`
   (public schema; migration `20260712120000`). Scout: fills the shared
   `market_scanner` caches with the EXACT PowerShell contracts (`biz_key`,
   `trend_key`, raw-RD, `pulled_at` 90-day freshness) so the two tools stay
   interoperable; the brief picks enrichment up on its next read. **Budget
   guard:** per-user daily ledger `leadoff_spend` + `leadoff_daily_budget_usd`
   (default $5); every enqueue records its estimate; scout exposes a free
   `GET /leadoff/scout/estimate` preflight; DataForSEO 40203 (money limit)
   aborts without recording; 40102 records a valid zero (scanner lesson #2).
2. **Create Client from market** — ✅ **built** (see §3/§4): a "Create client
   from this market" button on the brief creates the client card pre-loaded
   with the market's location, competitor set, and effort targets.
3. **Neighborhood board tab — ✅ built**: `GET /leadoff/neighborhoods` over
   `neighborhood_opportunities` (955 nameable combos) + a Neighborhoods tab
   (filters metro/state/service, sorts demand/value/leads/v3; UI notes that
   supply ≈ parent metro — pick on demand, per scanner lesson #5).
4. **SerMaStr routing — ✅ built**: `sop_library._RELEVANCE["leadoff"]` →
   the LeadOff SOP; the strategy digest emits the `leadoff` domain for
   clients carrying a "LeadOff targets — …" goal (the handoff's marker, and
   deliberately NOT an active-signal for the weekly gate), and the assistant's
   `sop_domains` gains leadoff/market-selection keyword hints.
5. Data refresh cadence: quarterly re-scan / AIO probe / category-rename sweep
   run from the external scanner; `leadoff_board.as_of` carries the vintage.

## 6. Known caveats (inherited from the scanner, documented in its CLAUDE.md)

- Estimates are planning numbers: volumes are Google-bucketed (`conf` flag),
  capture is an assumption, grades under non-default assumptions approximate.
- `growth_yoy` is seasonal-confounded (12-month window) — read with
  `peak_months`. **Fixed (2026-07-12) via the additive `growth_yoy_ss`**
  (same-month YoY from a 24-month pull; scout writes it, brief/UI prefer it);
  `growth_yoy` itself keeps legacy semantics as a coordinated cache contract
  with the PowerShell tools. Pre-fix cache rows carry `growth_yoy_ss = null`
  until re-scouted.
- Exact-category holder counts are only meaningful for verified-current GBP
  labels (Handyman rename / "Plumbing" not selectable already corrected).
- HOT? luck flags need a trend pull to adjudicate; the SOP mandates a live
  Maps eyeball before committing to any market.
