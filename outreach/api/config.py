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
