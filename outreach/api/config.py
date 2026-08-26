"""Configuration for the outreach pipeline.

Every tunable loads from environment/config. Nothing in this pipeline may hardcode a threshold,
a coefficient or a price — see CLAUDE.md invariants. Phase 1 has no coefficients, but the same
rule applies to filter thresholds and provider rates.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Franchise / chain name patterns. Case-insensitive substring match against the listing name.
#
# UNVALIDATED: this seed list has not been checked against a real market pull. It exists so the
# rule is exercisable; it is not an authoritative chain registry. A match only ever sets
# franchise_status = 'flagged' — never excludes — so a false positive costs a human glance, and a
# false negative costs nothing in Phase 1 because nobody is contacted. Extend via
# OUTREACH_FRANCHISE_PATTERNS rather than editing this list.
DEFAULT_FRANCHISE_PATTERNS: tuple[str, ...] = (
    "roto-rooter",
    "mr. rooter",
    "mr rooter",
    "benjamin franklin plumbing",
    "ars/rescue rooter",
    "rescue rooter",
    "the plumbing joint",
    "zoom drain",
    "plumbingpro",
    "one hour heating",
    "aire serv",
    "servicemaster",
    "servpro",
    "roterooter",
    "bio-one",
    "drain doctor",
    "rescue plumbing",
    "wind river",
    "michael & son",
    "horizon services",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OUTREACH_",
        env_file=".env",
        extra="ignore",
    )

    # --- Supabase (separate project from AR Tools — see DECISIONS.md) ---------------------
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # --- Outscraper ----------------------------------------------------------------------
    outscraper_api_key: str = ""

    # Host fallback order mirrors the official SDK's transport. All three serve the same API;
    # the client tries them in order on connection/TLS failure only, never on a 4xx.
    outscraper_base_urls: list[str] = Field(
        default_factory=lambda: [
            "https://api.app.outscraper.com",
            "https://api.app.outscraper.cloud",
            "https://api.outscraper.net",
        ]
    )

    # Which maps-search endpoint to use. Two are live:
    #   /maps/search-v3      GET  — DEFAULT; proven against THIS account by platform-api's
    #                               gbp_service, which has called it with this key for months.
    #   /google-maps-search  POST — what the vendor's current SDK (v6.0.4) uses. Newer, but
    #                               unproven against this account.
    # Defaulting to the one with production evidence. Flip after the first pull if the other
    # behaves better at market scale.
    outscraper_search_endpoint: str = "/maps/search-v3"

    # Google returns no more than ~400 organisations for a single query area regardless of what
    # we ask for. Tiling by submarket centroid is what gets past that, not a larger limit.
    outscraper_places_per_query_limit: int = 400

    # Tiles run concurrently. Sequential 14-tile runs took ~5 minutes of wall time and the
    # first real run was terminated at ~4; shortening the window is half the mitigation, the
    # other half being per-tile persistence. Modest by default — this is a courtesy limit on
    # a paid third-party API, not a throughput contest.
    outscraper_tile_concurrency: int = 4

    outscraper_language: str = "en"
    outscraper_region: str = "US"

    # Async submissions are polled at GET /requests/{id}. Outscraper retains a completed
    # response for 2 HOURS ONLY, so the poller persists raw the moment it lands.
    outscraper_poll_interval_seconds: float = 5.0
    outscraper_poll_timeout_seconds: float = 3600.0
    outscraper_request_timeout_seconds: float = 60.0

    # Optional: write each untouched archive body here before anything reads it, as a hedge
    # against a crash inside the 2-hour retention window. Unset means no landing, which is fine
    # for a smoke test and unwise for a real market run. Moves to R2 in Phase 2 (ISSUES I-024).
    raw_landing_dir: str | None = None

    # Where the `render-heatmap` command writes rendered SVGs, keyed by content_hash. Local-disk
    # for now; R2 + signed prospect URLs are a later Phase 3 slice (reporting §5). Defaults to a
    # working dir so a render never fails for want of a configured path.
    artifact_dir: str = "artifacts"

    # --- DataForSEO ----------------------------------------------------------------------
    # The independent second opinion for I-041, and the sole provider for Phase 2 scanning.
    # Set on Railway as REFERENCE variables (${{PLATFORM.DATAFORSEO_LOGIN}}) rather than copies,
    # so the secrets never leave the platform and a rotation propagates automatically.
    dataforseo_login: str = ""
    dataforseo_password: str = ""

    # Business Data reviews/live is billed per task. Used for the pre-flight projection on
    # verify-reviews; like the Outscraper rate this is a CONFIGURED number, not one the API
    # reports back, so the abort gate is exactly as honest as it is (same caveat as I-022).
    dataforseo_cost_per_request_cents: int = 1

    # my_business_info/live is a LIVE endpoint: DataForSEO queries Google while the request is
    # open. The observed round trip is ~19s typical, and 4 of the first 20 lookups blew straight
    # through the 60s Outscraper timeout — which reported as an EMPTY error string, since httpx's
    # timeout exceptions carry no message. Its own budget, well clear of the tail, because a
    # timeout here does not just lose the answer: DataForSEO has already run the query, so it is
    # a lookup paid for and thrown away.
    dataforseo_request_timeout_seconds: float = 180.0

    # --- AI engine (I-004 granularity spike, PRD §16a.2) ---------------------------------
    # Same reference-variable pattern as the DataForSEO credentials above:
    # OUTREACH_OPENAI_API_KEY = ${{PLATFORM.OPENAI_API_KEY}}, so the secret stays on the
    # platform service and a rotation propagates without a second place to update.
    openai_api_key: str = ""

    # The spike asks a consumer-shaped question ("who is the best plumber in X"), so the model
    # should be one a consumer would actually reach. Overridable because the answer to the
    # granularity question may differ by model, and re-running against a second one is the
    # cheapest way to find out.
    ai_granularity_model: str = "gpt-5.4"

    # --- AI-visibility scan (report increment 3) -----------------------------------------
    # The report's LLM signal: does an AI assistant name this business for its keyword in its
    # region. Two engines (owner ruling 2026-08-08): ChatGPT (OpenAI, reuses OUTREACH_OPENAI_API_KEY)
    # and Google AI Overview (DataForSEO). The ChatGPT model is a consumer-reachable one, like the
    # granularity spike. OpenAI does not return a per-call cost, so the ledger stores this configured
    # estimate (the DataForSEO/AIO side rides dataforseo_cost_per_request_cents) — reconciled against
    # the dashboard like every other rate here.
    ai_visibility_chatgpt_model: str = "gpt-5.4"
    ai_visibility_openai_cost_cents: int = 2

    # --- Cost guardrails -----------------------------------------------------------------
    # Abort the paid stage if the pre-flight projection exceeds this (brief §4).
    max_market_run_cost_cents: int = 5000

    # UNVERIFIED against a live account. The Outscraper API does not appear to return a
    # per-request cost, so cost_ledger stores units x this rate and is reconciled manually
    # against the dashboard once per cycle (ISSUES I-022). Set from the real plan before any
    # production run — the abort gate is only as honest as this number.
    outscraper_cost_per_1000_places_cents: int = 200

    # --- Filter thresholds (brief §3) ----------------------------------------------------
    filter_exclude_closed: bool = True
    filter_require_phone: bool = True
    filter_check_suppression: bool = True

    filter_min_review_count: int = 10
    filter_min_review_count_enabled: bool = True

    # DEFERRED IN PHASE 1 — see DECISIONS.md "Review recency deferred to Phase 5".
    # Review timestamps are not in the Outscraper base pull; they need a separately billed
    # /maps/reviews-v3 call. Phase 1 contacts nobody, so a blunt filter costs nothing here, and
    # by Phase 5 there are multiple listing pulls to compute relative review VELOCITY from —
    # which is the better rule anyway (a commercial plumber can be busy and profitable with
    # near-zero consumer review flow). The rule stays in config, disabled, and still writes an
    # honest filter_result row.
    filter_review_recency_enabled: bool = False
    filter_review_recency_months: int = 9

    franchise_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_FRANCHISE_PATTERNS)
    )

    # --- Category relevance (three-bucket gate) ------------------------------------------
    # A Google Maps category search returns adjacent trades too — a "plumbing contractor" pull for
    # Inglewood surfaced apartment buildings, tool stores, HVAC firms and supply houses, ~half the
    # contactable set. This gate drops a listing whose PRIMARY Google category is off the vertical's
    # allow-list, keeps it when the primary matches, and flags it for REVIEW (never auto-drops) when
    # only a SECONDARY category matches. Fail-open: a listing with no category, or a vertical absent
    # from the map below, is NOT_EVALUATED and kept.
    #
    # Enabled by default, but a no-op for any vertical not in `filter_category_relevance` — so it
    # touches only the verticals whose allow-list has been curated here. Keyed on the INGEST
    # category (the typed business type). Add a vertical by adding a key.
    filter_category_relevance_enabled: bool = True
    filter_category_relevance: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "plumber": ["Plumber", "Fontanero", "Drainage service"],
            "plumbing contractor": ["Plumber", "Fontanero", "Drainage service"],
            "plumbing": ["Plumber", "Fontanero", "Drainage service"],
        }
    )

    # --- Distance gate -------------------------------------------------------------------
    # `coordinates` biases the Outscraper search centre but does not bound it (there is no radius
    # parameter), so a category search can return a business outside the target city. This drops a
    # listing further than `filter_max_distance_miles` from its assigned submarket centroid — which,
    # for the typed-city onboard flow, IS the city centre (platform-api geocodes the city to that
    # submarket). Fail-open: a listing with no coordinates is kept.
    #
    # 7 miles (owner ruling 2026-08-10). Tight enough to keep results in the city while still
    # covering a business on the far side of it — the live Inglewood pull sat entirely within 6.7
    # miles of centre. A market whose submarkets are spaced further apart than this may need a
    # looser cap; it is per-config for that reason.
    filter_max_distance_enabled: bool = True
    filter_max_distance_miles: float = 7.0

    # --- Cadence -------------------------------------------------------------------------
    scan_interval_days: int = 15

    # --- Maps geogrid scanning (PRD §B1) --------------------------------------------------
    # Zoom is what makes a task a GEOGRID rather than 81 copies of a city-wide query: it sets how
    # tightly the provider simulates standing at that coordinate. 13 matches the suite's proven
    # geo-grid and the LeadOff scanner's reference implementation; changing it changes what every
    # historical snapshot measured, so treat it like geometry rather than like a tuning knob.
    scan_zoom: int = 13

    # Results requested per point. The pipeline needs the FULL local pack at every point (~20) —
    # that is the capability the whole provider choice rests on, because it is what lets one grid
    # score every business in a submarket instead of one target.
    scan_depth: int = 20
    scan_device: str = "desktop"
    dataforseo_default_language_code: str = "en"

    # PRD §9a.3. Below this ratio of points collected to points expected, a snapshot is marked
    # incomplete and excluded from scoring rather than quietly scored on partial evidence.
    scan_completeness_threshold: float = 0.98

    # The ready list holds a task ~3 days; results stay retrievable by id for 30. Past this age a
    # task has aged off the list and is collected directly (PRD §B1.3) — a normal recovery.
    scan_collect_fallback_days: int = 3
    scan_collect_fallback_limit: int = 500

    # PRD §B1.4. Past this age, something is wrong with the COLLECTOR'S SCHEDULE, not with the
    # task — which is a distinction invisible from any single run, so it is alerted rather than
    # retried silently.
    scan_collect_alert_days: int = 5

    # --- Coverage rollup (storage spec §4, PRD §9a.1) --------------------------------------
    # Consecutive null scans before a grid point leaves the coverage DENOMINATOR. PRD §9a.1 says
    # three. It lives here rather than in the SQL because it changes what `coverage_pct` MEANS,
    # and a threshold that only exists inside a function body is one nobody can find when a
    # coastal submarket's numbers look wrong (the same complaint as ISSUES I-071).
    #
    # Raising it is safe; LOWERING it is not retroactive and not free. `live_points` is stored
    # contemporaneously, so snapshots already rolled up keep the denominator they were computed
    # with — which is the point (§4: without the contemporaneous value, historical coverage
    # becomes uninterpretable) and also means a mask that fired too eagerly cannot be undone for
    # claims already made from it.
    land_mask_null_scans: int = 3

    # How many snapshots one `rollup` invocation will process. A bound rather than a cap on
    # ambition: the rollup rides the collector's frequent tick, so a backlog drains over ticks
    # instead of turning one tick into an unbounded job that the platform may kill halfway.
    rollup_batch_limit: int = 50

    # --- Delta heatmaps (reporting spec §4.3, PRD §9a.2) -----------------------------------
    # A before/after delta MUST NOT be rendered across a gap wider than this — a gap means missed
    # cycles, and a two-snapshot comparison spanning them attributes to one interval what really
    # happened over several (PRD §9a.2). Default 45 per PRD §9a.2. The guard is enforced from the
    # two snapshots' `scanned_at`, which exist today; the provider-boundary and drift-suppression
    # halves of the same guard are wired in `heatmap.assert_delta_renderable` and land fully when a
    # second provider and `prospect_delta` exist (ISSUES I-091).
    max_delta_span_days: int = 45

    # --- Site tech-signal scan (paid-placement Slice B1, PRD §B3) --------------------------
    # `scan-tech` fetches each prospect's OWN site and detects ad/marketing tech (Meta pixel, AW-
    # conversion tag, GTM container, CallRail/Podium/Birdeye). FREE (own HTTP GET, "not a paid
    # service" — §B3), so `scan-tech` is deliberately NOT in PAID_COMMANDS.
    tech_fetch_timeout_seconds: float = 12.0
    tech_scan_concurrency: int = 8
    # Only this many bytes of a page are kept and regex-scanned. Ad tags live in the head and in
    # script tags near it, so 2 MB is generous; without a cap one CMS page dumping a 50 MB inlined
    # payload would be held in memory and scanned by every pattern, times the concurrency.
    tech_max_page_bytes: int = 2_000_000
    # Follow the GTM container to recover pixels injected client-side (ISSUES I-003 / §16a.1). OFF
    # until the §16a.1 spike measures whether inline scanning misses GTM-injected pixels — the seam
    # is built either way, this only decides whether it runs by default.
    tech_follow_gtm: bool = False

    # `tick` auto-runs the tech scan so every scored prospect carries the Slice-B1 money signal
    # without a manual `scan-tech` per market (which needs a definition file the any-city onboard
    # path has none of). FREE — an own HTTP GET, same posture as `collect` — idempotent (a prospect
    # already carrying a CURRENT signal is skipped, never re-fetched), and bounded per heartbeat so
    # one large market cannot monopolize a tick. 0 disables the drain entirely. Kept modest because
    # the drain runs synchronously inside the tick: worst-case iteration time is roughly
    # per_tick / tech_scan_concurrency × tech_fetch_timeout_seconds (≈75s at 50/8/12), and while it
    # runs the tick-loop's next iteration — which drains newly-placed enrich/scan orders — cannot
    # start, so this caps how long an order can wait behind a tech batch.
    tech_scan_per_tick: int = 50
    # The tech backlog does two portfolio-sized reads (candidate prospects + their signals), so on
    # the always-on `tick-loop` (every `tick_loop_interval_seconds`, ~8s) running it every heartbeat
    # would be constant read load for a drain that is empty most of the time. Throttle it to at most
    # once per this many seconds: a fresh cron process (long-lived state absent) always runs it, and
    # the daemon runs it occasionally so order-draining stays near-instant between tech batches. 0
    # disables the throttle (run every tick).
    tech_scan_min_interval_seconds: int = 300
    # Re-fetch a prospect's site once its latest tech signal is older than this many days. Tech
    # stacks change on a scale of months (a business installs CallRail once), and re-fetching hits
    # third-party sites, so a light cadence keeps the vendor-failing pairing honest (tech present +
    # a fresh coverage delta) without re-hammering every site each 15-day cycle. 0 = fetch a
    # prospect's tech once and never auto-refresh.
    tech_refresh_days: int = 45

    # --- Site name-scrape (FREE owner/manager fallback) ------------------------------------
    # `scan-names` / the `name_scrape_request` order fetch a prospect's OWN site and pull the
    # owner/manager NAME when Outscraper enrichment couldn't. FREE (own HTTP GET, the `scan-tech`
    # posture — NOT in PAID_COMMANDS). Owners are rarely on the homepage, so a bounded same-host
    # crawl fetches the homepage + a few likely pages (about/team/contact/meet); this cap is the
    # whole-crawl bound so one prospect can never fan out.
    name_scrape_max_pages: int = 5
    name_scrape_max_names: int = 8
    name_scrape_fetch_timeout_seconds: float = 12.0
    name_scrape_max_page_bytes: int = 1_500_000
    # Concurrency ACROSS prospects (each prospect's own pages are fetched sequentially). Doubles as
    # nothing else — a chunk of this many is scraped, stored, then the next, so a crash mid-order
    # marks the finished prospects (idempotent skip on re-order).
    name_scrape_concurrency: int = 6
    name_scrape_chunk_size: int = 6
    # A name-scrape order is batchable + free (like enrichment, unlike the ≤1/tick geogrid scan), so
    # the tick drains several per heartbeat.
    name_scrape_orders_per_tick: int = 5
    # Defensive ceiling on one order's selection (the placement layer caps it too). A bigger
    # "select all" is split into several orders.
    name_scrape_max_places_per_order: int = 200
    # Max prospects FETCHED per tick, across all orders AND within a single order. Unlike enrichment
    # (one cheap provider call per place), a name-scrape does up to `name_scrape_max_pages` sequential
    # site fetches per prospect, so a 200-prospect order could otherwise block the tick loop for many
    # minutes. This budget caps the wall-time per heartbeat (the `tech_scan_per_tick` discipline): an
    # order larger than the remaining budget is scraped up to it and left PENDING to resume next tick
    # — the marker-based idempotent skip means a resume re-scrapes only the un-done prospects, so no
    # work is lost or repeated. <=0 means no cap (process whole orders up to name_scrape_orders_per_tick).
    name_scrape_per_tick: int = 60

    # --- Web-search owner/manager name (PAID third-rung fallback) --------------------------
    # When enrichment AND the free site-scrape both found no name, a paid web search looks the owner
    # up (OpenAI Responses API + web_search, reuses OUTREACH_OPENAI_API_KEY). BILLS one search per
    # prospect, so it is a signed/admin-gated/budget-guarded order (the enrichment model), NOT free.
    # The model + tool mirror the suite's brand scan (gpt-5.4 + the web_search tool).
    name_search_model: str = "gpt-5.4"
    name_search_web_search_tool: str = "web_search"
    # A web search + tool round-trip is slow — its own generous timeout, clear of the 60s chat base.
    name_search_request_timeout_seconds: float = 120.0
    # Concurrency across prospects (doubles as the drain's chunk size).
    name_search_chunk_size: int = 4
    name_search_orders_per_tick: int = 3
    name_search_max_places_per_order: int = 100
    # At most this many names kept per prospect (an owner is usually one person).
    name_search_max_names: int = 2
    # OpenAI returns no per-call cost, so — like every rate here — this is a CONFIGURED estimate
    # reconciled against the dashboard (I-022). A web-search Responses call is a few cents; keep in
    # sync with platform-api's outreach_name_search_cost_cents (that one drives the budget guard,
    # this one the drain's cost_ledger write).
    name_search_cost_cents: int = 3

    # --- Lead enrichment (contact names / phones / emails via Outscraper) ------------------
    # A SEPARATE, spend-gated, per-selection action — NOT the mass ingest, which hardcodes
    # `enrichment=""` with a hard invariant so a market pull can never silently bill per-place
    # enrichment (outscraper_client.submit_maps_search). This path builds its own request (like
    # pixel_probe.fetch_enriched_sample) and never touches that method. The order row
    # (`enrichment_request`) is its own spend confirmation; the `tick` command drains it.

    # The enricher set requested by default (the fallback; an order freezes its own set at placement).
    # Outscraper takes a LIST, called BY place_id. `domains_service` is the SCRAPER that pulls emails +
    # contact names + phones from the business's website (the repo's contact-pull convention); the
    # other two post-process it (email validation → email.emails_validator.status; phone carrier). The
    # first live run requested the validators WITHOUT the scraper and got name_for_emails but no emails
    # (I-109). The parser still never asserts a field it hasn't seen — `probe-enrich` confirms the shape.
    enrich_enrichments: list[str] = Field(
        default_factory=lambda: [
            "domains_service", "emails_validator_service", "phones_enricher_service"
        ]
    )

    # Outscraper enrichment is billed per record. The API returns no per-request cost, so like every
    # other rate here this is a CONFIGURED number reconciled against the dashboard (I-022) — set it
    # from the real plan before a production run. Keep in sync with platform-api's
    # outreach_enrich_cost_per_place_cents (that one drives the placement-time budget guard; this
    # one drives the drain's cost_ledger write).
    enrich_cost_per_place_cents: int = 5

    # place_ids per Outscraper enrichment request. Enrichment is BATCHABLE — one request covers many
    # place_ids — so chunks stay modest: a synchronous enriched pull for a chunk stays under the
    # timeout, and a failed chunk loses one chunk's worth, not the whole order (the pixel_probe
    # per-query-isolation lesson).
    enrich_chunk_size: int = 10

    # Enrichment is lightweight + batchable, so the tick is deliberately NOT held to the ≤1-order
    # cadence the heavy geogrid scan uses (that cadence exists so each scan's collection starts
    # before the next scan's spend — irrelevant when one cheap request covers a whole selection). It
    # drains up to this many orders per heartbeat.
    enrich_orders_per_tick: int = 5
    # A defensive ceiling on one order's selection, so a single order can never run unboundedly (the
    # placement layer caps it too — this is the drain's backstop). A bigger "select all" is split
    # into several orders.
    enrich_max_places_per_order: int = 200

    # A single enrichment HTTP request (the async submit, or one poll of the archive) can take
    # longer than the base search; its own per-request timeout, clear of the 60s base.
    enrich_request_timeout_seconds: float = 180.0

    # Enrichments run ASYNC on Outscraper: a synchronous (async=false) call returns the base Maps
    # record BEFORE the enrichers finish, i.e. with no emails/contacts/people at all (confirmed live
    # 2026-08-26 by two probe-enrich runs — I-109). So `enrich_client` submits async and polls the
    # archive to completion. This is the per-place poll ceiling: a stuck-Pending enrichment fails
    # THAT place after this long rather than hanging the whole tick for the mass-ingest 1h timeout.
    enrich_poll_timeout_seconds: float = 300.0

    # --- Report signal scans (organic / AI-visibility UI triggers, 2026-08-10) -----------
    # The per-prospect report's ORGANIC and AI sections are filled by two signed-order queues
    # (`organic_scan_request` / `ai_scan_request`), drained by `tick`. Each is a single cheap paid
    # call, so ≤1 per tick — matching the geogrid scan's cadence, NOT enrichment's batch drain —
    # keeps every capture a discrete, terminal, first-run-fault-bounded order. Raise if a queue ever
    # backs up faster than the 15-minute cron clears it.
    organic_orders_per_tick: int = 1
    ai_orders_per_tick: int = 1

    # --- Always-on worker (tick-loop daemon) ---------------------------------------------
    # The `tick-loop` command runs `tick` continuously so a UI-placed order (enrich / scan)
    # drains within seconds instead of waiting for the cron. This is the sleep between ticks.
    # Every iteration is one tick, whose spend is authorized per signed order (tick is not in
    # PAID_COMMANDS); an idle iteration spends nothing and `collect` is free, so a short interval
    # is cheap. Kept off the floor so the DB / free-endpoint polling stays modest.
    tick_loop_interval_seconds: float = 8.0

    # --- Scoring model — Phase 4 Stage 1 (scoring-spec.md) --------------------------------
    # EVERYTHING here is a CONFIG value. Zero hardcoded betas, ever (CLAUDE.md invariant). The
    # scalar knobs live here; the full coefficient REGISTRY (the elicited priors, ~40 bins) lives
    # in `services/scorecard_config.py`, loaded through this settings layer and overridable via
    # `scorecard_coefficients_json`. Every coefficient in this model is an ELICITED estimate — no
    # part has been tested against a single reply — so treat rank order as a strong prior, not a
    # prediction, until ~100 prospects have been contacted (CLAUDE.md → What is unvalidated).

    # scoring-spec §1. Score = TargetScore + Factor x ln(odds); Factor = PDO / ln(2). Every +PDO
    # points doubles the odds. TargetScore 500 = a market-average prospect. Factor is DERIVED from
    # pdo (scorecard_config.factor_of) — not a stored constant — so the two can never drift.
    score_pdo: float = 50.0
    score_target: float = 500.0

    # scoring-spec §5. The uniform shrinkage on every elicited beta at v1. A UNIFORM multiplier: it
    # cannot change rank order (CLAUDE.md trap — do not tune it to improve ranking). Store both the
    # prior and the effective contribution; this is the only knob between them.
    score_lambda_shrink: float = 0.5

    # scoring-spec §1 offsets, PINNED to the values the golden fixtures were hand-computed against
    # (tests/fixtures/golden-fixtures.json). They are DERIVED from the base rates below
    # (offset = target - factor x ln(base_odds)); a unit test asserts the derivation rounds to
    # these, so replacing a base rate per §9 without updating its offset fails loudly rather than
    # silently miscalibrating. Phone and email are 126 points apart and MUST NEVER be ranked in one
    # list (enforced at the read surface by carrying `channel` on every score row).
    score_offset_email: float = 705.0
    score_offset_phone: float = 579.3
    score_offset_close: float = 625.1

    # scoring-spec §1 base rates — sequence-level (a full 5-touch sequence), per-channel, and
    # ASSUMPTIONS (MUST be config, not constants — §1). The phone figure is the weaker guess and is
    # observable first. Overwrite with observed data after ~3 weeks of sends rather than tuning
    # coefficients around them (§9 open decision 1).
    score_base_rate_reply_email: float = 0.055
    score_base_rate_reply_phone: float = 0.25
    score_base_rate_close: float = 0.15

    # scoring-spec §5. v1 scores are ORDINAL ONLY — displayed probabilities clamped to this until a
    # score_run has a non-null calibration_alpha (Stage 2). Applied at the read surface
    # (v_prospect_ranked.display_prob) and by the engine's display_prob.
    score_display_prob_clamp_pct: float = 60.0

    # scoring-spec §4 — Model C value layer. INERT under flat pricing: R and T are constants and drop
    # out of ranking, so the operative ranking is p_reply x p_close. Do NOT spend effort tuning these
    # (CLAUDE.md trap) — they exist so E[revenue] is a meaningful dollar figure and reactivating the
    # value dimension is a config change (§4, revisit ~month 9).
    score_r_base: float = 2000.0
    score_t_base: float = 15.0

    # Stamped on every score_run so a stored score names the coefficient generation that produced it.
    # Bump when the registry or scaling changes (a re-score is always a NEW run — immutable history).
    score_model_version: str = "stage1-priors-v1"

    # Optional JSON object overriding any coefficient in the registry, keyed by bin name:
    # '{"geogrid_lt20_steep": 60, "aw_tag": 22}'. Empty = the elicited-prior defaults in
    # scorecard_config.py. This is the "coefficients load from config" seam — the registry is the
    # documented default, this is the override, and nothing in the scoring LOGIC hardcodes a beta.
    scorecard_coefficients_json: str = ""

    # scoring-spec §7a — the AI-inversion trigger's threshold. Below this variance of AI presence
    # across a market's qualified set, AI features stay low-weight pitch flags; crossing it is the
    # signal to re-elicit them as discriminators. Stage 1 only records the metric; it does not act.
    score_ai_variance_threshold: float = 0.10

    # Bin BOUNDARIES for the feature-extraction layer (scoring-spec §2 geogrid pain / trajectory).
    # These define which bin a measurement falls in — structural like the point values, and config
    # for the same reason (§7a: geogrid weight/boundaries may shift if local-pack results compress).
    # Coverage is a percentage 0-100. <low = severe pain; low-mid; mid-high = reference; >high = strong.
    score_geogrid_low_pct: float = 20.0
    score_geogrid_mid_pct: float = 50.0
    score_geogrid_high_pct: float = 80.0
    # Bottom-review-quartile bin requires >= this many reviews (scoring-spec §Trajectory, "bottom
    # quartile (>=10)") — a business with near-zero reviews is a different case than a lagging one.
    score_review_bottom_min: int = 10
    # GBP "strong" needs rating >= this AND photos/categories evidence. Stage 1 does not capture
    # photos/categories, so strong/weak stay dormant and GBP scores at the `adequate` reference
    # (ISSUES: a future GBP-detail enrichment lights them up). Threshold kept for when it does.
    score_gbp_strong_rating: float = 4.0

    # scoring-spec §6 Stage 2 — the standalone recalibration job. It fits a two-parameter logistic
    # (alpha + gamma x prior-log-odds) on real reply outcomes, correcting calibration WITHOUT
    # touching rank order. Below this many reply outcomes IN A CHANNEL it refuses and writes nothing
    # (§6 "~30-50 outcomes"). Zero outcomes exist today, which is the correct empty-safe state.
    score_recalibration_min_outcomes: int = 30


def missing_outscraper_vars(settings: "Settings") -> list[str]:
    """Which Outscraper credentials are absent, by env-var name.

    Mirrors `missing_supabase_vars` / `dataforseo_client.missing_dataforseo_vars` so a paid command
    can REFUSE before opening a credential rather than firing N requests with an empty API key and
    failing per-request. `OutscraperClient.__aenter__` does not validate the key (unlike the
    DataForSEO client), so the check has to live at the command boundary.
    """
    return [
        name
        for name, value in (("OUTREACH_OUTSCRAPER_API_KEY", settings.outscraper_api_key),)
        if not value
    ]


def missing_supabase_vars(settings: "Settings") -> list[str]:
    """Which Supabase credentials are absent, by env-var name.

    Pure, and deliberately not in db.py: that module imports the Supabase driver at module scope,
    so a test for this check would need the driver installed to assert on a message about the
    driver's configuration.

    Names only what is actually missing. "A and B must be set" when only B is absent sends people
    to check A first, which is set, and makes the error look wrong.
    """
    return [
        name
        for name, value in (
            ("OUTREACH_SUPABASE_URL", settings.supabase_url),
            ("OUTREACH_SUPABASE_SERVICE_ROLE_KEY", settings.supabase_service_role_key),
        )
        if not value
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
