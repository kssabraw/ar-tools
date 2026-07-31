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
