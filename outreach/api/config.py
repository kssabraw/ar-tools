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
