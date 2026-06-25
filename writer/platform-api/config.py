from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    pipeline_api_url: str = "http://ar-tools.railway.internal:8080"
    nlp_api_url: str = "http://nlp.railway.internal:8080"
    scrapeowl_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    max_concurrent_runs: int = 5
    job_worker_poll_interval_seconds: int = 10
    allowed_origins: List[str] = ["*"]
    log_level: str = "INFO"
    google_apps_script_url: str = ""
    outscraper_api_key: str = ""
    # Google Search Console — Organic Rank Tracker (Module #4).
    # The service-account key JSON (the entire downloaded key file, as a single
    # string) for the agency-owned identity that clients add as a user on their
    # Search Console property. Stored once at the app level; never per-client.
    google_service_account_key: str = ""
    # GSC daily ingest (M2). The scheduler enqueues one ingest job per active
    # property once a day, after `gsc_ingest_hour_utc`. Each run re-pulls the
    # last `gsc_repull_days` days to catch GSC's ~2–3 day late-arriving data
    # (a missed run is therefore self-healing on the next pull). The scheduler
    # loop wakes every `gsc_scheduler_poll_interval_seconds`.
    gsc_repull_days: int = 3
    gsc_ingest_hour_utc: int = 8
    gsc_scheduler_poll_interval_seconds: int = 300
    # One-time historical backfill window. GSC retains ~16 months; pull it all so
    # the Supabase store keeps it forever (the core value-add — PRD §10).
    gsc_backfill_days: int = 480
    # Weekly query×page ingest window (canonical-URL resolution + Pages view).
    gsc_page_window_days: int = 30
    # Striking-distance discovery: queries averaging in this position band (and
    # not already tracked) are page-2 opportunities.
    striking_distance_min: float = 8.0
    striking_distance_max: float = 20.0
    # URL Inspection (deindex confirmation) has a daily per-property quota, so
    # re-check a flagged keyword's canonical page at most this often.
    url_inspection_recheck_days: int = 3
    # M3 materialize: the trailing window (days) of the per-keyword-per-day axis.
    # Covers all rolling windows (max 90d) + margin; the full 16-month history
    # stays in gsc_query_daily.
    rank_materialize_days: int = 120
    # DataForSEO fallback rank (used when GSC is absent or the site doesn't rank
    # for a keyword). Refreshed WEEKLY on this weekday (0=Mon..6=Sun) to bound
    # cost. A keyword counts as GSC-covered if it had a GSC position within the
    # last `rank_gsc_coverage_days` days; otherwise it falls back to DataForSEO.
    dataforseo_rank_weekday: int = 0
    rank_gsc_coverage_days: int = 14
    dataforseo_serp_depth: int = 100  # find rank within the top 100, else "not ranking"
    dataforseo_default_location_code: int = 2840  # United States
    dataforseo_default_language_code: str = "en"
    # Keyword market data (CPC / volume / competition): Google Ads numbers
    # refresh monthly, so re-fetch only when a keyword's cached row is older
    # than this many days (or missing).
    keyword_market_refresh_days: int = 30
    # Competitive SERP Snapshot (diagnostic store). Captured WEEKLY alongside the
    # DataForSEO rank refresh. `serp_snapshot_depth` is how deep the SERP is
    # pulled; `serp_snapshot_top_n` is how many top organic results get the
    # (pricier) Backlinks enrichment — including the client's own page.
    serp_snapshot_depth: int = 20
    serp_snapshot_top_n: int = 10
    # DataForSEO — GBP review enrichment (shared with pipeline-api modules)
    dataforseo_login: str = ""
    dataforseo_password: str = ""

    # Maps / local-pack geo-grid ranker (Module #5) — Local Dominator API.
    local_dominator_api_key: str = ""
    local_dominator_base_url: str = "https://api.localdominator.co"
    # Weekly geo-grid scans fire on this weekday (0=Mon..6=Sun) via the shared
    # scheduler; the scheduler also polls in-flight scans each tick until done.
    maps_scan_weekday: int = 1
    # How long (minutes) to keep polling a scan before marking it failed.
    maps_scan_poll_timeout_minutes: int = 30
    # Local Rank Analysis report (auto-generated per keyword when a scan completes).
    # Sonnet writes the client-facing narrative from the deterministic geo-grid
    # rollups + competitor data; Top-5 competitors are those rated >= this with
    # the most reviews. The octant pin generator runs under this rule (R1 = 4 pins
    # across the 4 weakest octants; R3/R5 = 2 far-apart; R8 = none).
    maps_report_model: str = "claude-sonnet-4-6"
    # The full templated report (10 sections + 4 tables) is large; too small a
    # budget truncates the forced tool-use JSON and yields an empty summary.
    maps_report_max_tokens: int = 8192
    maps_report_competitor_min_rating: float = 4.7
    maps_report_octant_rule: str = "R1"
    # Weak-zone geocoding (turns the geo-grid's weakest pins into real city names
    # for SEO targeting). Reverse-geocodes via the Google Geocoding web service —
    # set `google_maps_api_key` to a key with the Geocoding API enabled (a
    # server-side key, NOT the referer-restricted frontend Maps JS key). Absent a
    # key the report still generates; it just carries no place names.
    #
    # A pin is an "opportunity" when it's unranked or ranks worse than
    # `maps_strong_rank_threshold` (ranks at/inside that are "in the pack" and
    # excluded). Each opportunity pin is scored for priority so the team knows
    # which cities to target FIRST:
    #     opportunity = severity × proximity × beatability × core_adjacency
    #   - severity: how bad the rank is, anchored at the pack edge and scaling to
    #     `maps_unranked_effective_rank` for unranked pins (so rank 5-9 score low,
    #     unranked dead zones score highest);
    #   - proximity: closer-to-business pins weighted higher (own your backyard);
    #   - beatability: areas where weaker competitors (fewer reviews than the
    #     client) outrank us score higher — bounded to
    #     [`maps_beatability_min`, `maps_beatability_max`].
    #   - core_adjacency: a weak pin bordering STRONG (in-pack) coverage is a fringe
    #     of an area we already own, so it's down-weighted in proportion to how many
    #     of its 8 neighbors are in the pack, floored at `maps_core_adjacency_floor`.
    # A city's priority is the sum of its pins' opportunity, normalized 0-100 per
    # keyword. `maps_weak_rank_threshold` is the Weak/Watch tier boundary.
    #
    # THIN-AREA FILTER: a suburb is only flagged as a weak coverage area when it
    # holds >= `maps_min_area_pins` weak/missing pins. A neighborhood with just one
    # or two stray weak pins is dropped from the flagged list — its pins still feed
    # the octant pins / analytics, they're just not called out as a weak suburb.
    #
    # At most `maps_geocode_max_cells` cells per keyword are geocoded (highest
    # priority first, so a cap only drops the lowest "Watch" cells); the rest are
    # counted but not named. The cross-client `maps_geocode_cache` makes repeats
    # free.
    google_maps_api_key: str = ""
    maps_strong_rank_threshold: int = 4  # ranks <= this are "in the pack" — not an opportunity
    maps_weak_rank_threshold: int = 10   # rank >= this (ranked) is "Weak"; between is "Watch"
    maps_unranked_effective_rank: int = 25  # rank an unranked pin stands in for, when scaling severity
    maps_beatability_min: float = 0.6
    maps_beatability_max: float = 1.4
    maps_core_adjacency_floor: float = 0.5  # score a weak pin keeps when ALL 8 neighbors are in the pack
    maps_min_area_pins: int = 3  # a suburb needs >= this many weak pins to be flagged as a weak area
    maps_geocode_max_cells: int = 100

    # SERP analysis cache (keyword_analyses): how long a cached AnalysisResponse
    # stays fresh before it's re-scraped. Shared across clients by (keyword,
    # location). Set to 0 to disable caching.
    analysis_cache_ttl_days: int = 14

    # Silo candidate management (Platform PRD v1.4 §7.7 / §8.5)
    silo_dedup_cosine_threshold: float = 0.85
    silo_frequent_threshold: int = 3
    # text-embedding-3-large supports a `dimensions` parameter (1..3072);
    # we use 1536 because pgvector's HNSW index is capped at 2000 dims.
    silo_embedding_dimensions: int = 1536
    silo_embedding_model: str = "text-embedding-3-large"

    # Local SEO silo planner — neighborhood discovery. After the Fanout pipeline
    # builds the service silos, the planner proposes neighborhoods within the
    # target city (Haiku tool-use), then forward-geocodes each and keeps only
    # those that resolve to a neighborhood-level place inside that city — adjacent
    # towns and bogus names are dropped — offering "<service> <neighborhood>" page
    # targets as a dedicated "Neighborhoods" silo. Verification needs
    # `google_maps_api_key` (Geocoding-enabled); absent it (or the Anthropic key),
    # the neighborhood silo is skipped with a degraded note rather than offering
    # unverified names.
    local_seo_neighborhood_model: str = "claude-haiku-4-5-20251001"
    local_seo_max_neighborhoods: int = 20

    # Service Page scoring: after a service_page run generates, it auto-scores
    # (nlp-api national mode) and auto-reoptimizes ONCE if the composite is below
    # this threshold. Manual Score/Reoptimize controls remain available in the UI.
    service_page_score_threshold: float = 90.0

    class Config:
        env_file = ".env"


settings = Settings()
