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
    # AI Visibility module (Brand Strength) — the two scan engines whose keys
    # aren't already shared. Absent either, that engine fails its scans with a
    # "not configured" reason; the other engines (chatgpt/claude via the keys
    # above, google_ai_* via DataForSEO) keep working.
    perplexity_api_key: str = ""
    gemini_api_key: str = ""
    max_concurrent_runs: int = 5
    job_worker_poll_interval_seconds: int = 10
    # Stale-job reaper. In-process jobs (asyncio.to_thread) aren't resumable, so a
    # redeploy or crash mid-run orphans them as status='running' forever. Each
    # worker tick sweeps jobs stuck 'running' longer than this many minutes:
    # re-queued (back to pending) while retry attempts remain, else marked failed.
    # Must exceed the longest legitimate job (the GSC backfill / silo plan run a
    # few minutes; maps_scan's 30-min poll lives on a separate table, not here).
    # Set to 0 to disable the reaper.
    job_stale_timeout_minutes: int = 30
    # Freeze Protocol: daily homepage-indexation check (GSC URL Inspection with a
    # DataForSEO site: warn-only fallback) that can auto-open a deindexing freeze.
    freeze_check_enabled: bool = True
    # Response-episode tracking: the SOPs' verify loop (2-week rechecks, 6-week
    # escalation) over open rank/maps drop responses.
    episode_tracking_enabled: bool = True
    # Offpage agent extensions: weekly citation-liveness sweep + monthly
    # page-level RD-imbalance capture (paid DataForSEO page summaries).
    citation_check_enabled: bool = True
    page_backlink_intel_enabled: bool = True
    # Auto-generate a new client's brand voice + ICP at creation (async, best-
    # effort) so the assets exist without a manual scan. Skips clients with no
    # website and no GBP (nothing to analyze). Never overrides user-authored
    # structured voice/ICP.
    auto_generate_brand_voice_icp: bool = True
    allowed_origins: List[str] = ["*"]
    log_level: str = "INFO"
    google_apps_script_url: str = ""
    # WordPress direct publishing (#3) — media sideload. When a published post's
    # content references images, each is uploaded to the client's WP media
    # library (/wp-json/wp/v2/media) and the <img> src rewritten to the WP-hosted
    # URL; the first becomes the post's featured image. Best-effort and bounded:
    # at most `wordpress_media_max_images` images, each up to
    # `wordpress_media_max_bytes`. Images already on the client's WP host are left
    # as-is. Set max_images to 0 to disable sideloading entirely.
    wordpress_media_max_images: int = 20
    wordpress_media_max_bytes: int = 15_000_000  # 15 MB per image
    # GitHub direct publishing — commit finished content to the client's repo as
    # Astro content Markdown (matches the Topic Fan-out convention). Dormant until
    # a token is set; each client supplies the target repo/branch/content_path.
    github_publish_token: str = ""
    github_default_branch: str = "main"
    github_default_content_path: str = "src/content/blog"
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

    # Action Plan (reoptimization planner) — SOP-grounded enrichment. One Claude
    # call per plan rewrites every action's recommendation into the agency's own
    # methodology + voice, grounded in the SOP store (agency-wide + per-client) and
    # the client's existing context (ICP, differentiators, services, location).
    # Skipped entirely when no SOPs exist, so it stays free until a playbook is loaded.
    reopt_enrich_model: str = "claude-sonnet-4-6"
    reopt_enrich_max_tokens: int = 8192
    # Auto-refresh the competitor-GBP + backlink intelligence (the inputs behind
    # the GBP competitor benchmark + backlink-gap action) when a plan is built and
    # the stored data is missing or older than reopt_intel_refresh_days. Each fetch
    # makes paid Outscraper/DataForSEO calls, so it's interval-gated + dedupe-guarded.
    reopt_auto_intel: bool = True
    reopt_intel_refresh_days: int = 30

    # Competitive SERP Snapshot — topical-focus classifier. One cheap Haiku call
    # per snapshot labels each ranking site (and the client) specialist vs
    # generalist for the keyword's topic (a rankability input: a specialist can
    # out-rank generalist incumbents even with weaker backlinks). Best-effort.
    serp_topic_model: str = "claude-haiku-4-5-20251001"
    serp_topic_max_tokens: int = 1024
    # Capture cadence: snapshots/rankability run on keyword first-entry (opt-in),
    # when a rank drop is detected (bounded to once per `_drop_min_days`), and
    # on-demand. The blanket weekly auto-capture is OFF by default (cost) — flip
    # serp_snapshot_auto_weekly to re-enable dense SERP-trend history.
    serp_snapshot_auto_weekly: bool = False
    serp_snapshot_drop_min_days: int = 30

    # GSC Research (cannibalization / quick wins / hidden wins) auto-cadence: a
    # first run as soon as a client is GSC-eligible (verified property + service
    # account), then every `_interval_days`. On-demand always works regardless.
    gsc_research_auto_enabled: bool = True
    gsc_research_interval_days: int = 30

    # Client Reporting — campaign-health narrative (Phase 4). One Claude call per
    # report synthesizes the gathered sections + signals (open drops, Action Plan)
    # into an executive summary (health label, headline, wins/risks/next steps).
    # Best-effort: absent the Anthropic key or on failure, the section is omitted.
    client_report_health_model: str = "claude-sonnet-4-6"
    client_report_health_max_tokens: int = 1100
    # White-label: the agency name shown in the client-facing report footer.
    client_report_agency_name: str = "Amazing Rankings"

    # Reoptimization planner — turns rank-tracker signals (open drops, rankability
    # Quick wins, GSC-Research cannibalization/hidden-wins) into a ranked,
    # recommend-only action plan per client. A weekly digest (the only auto
    # notification trigger), plus an on-drop refresh that rides the rank-drop
    # alert. On-demand always works regardless.
    reopt_plan_auto_enabled: bool = True
    reopt_plan_weekday: int = 0    # Monday=0 … Sunday=6 (weekly digest day, UTC)

    # Notifications service — shared delivery pipe (in-app card/feed + email +
    # Slack). In-app always works (DB row); email/Slack are best-effort and only
    # fire when their creds are configured. Recipients/channel are agency-level for
    # v1 (per-client routing later).
    notifications_enabled: bool = True
    # Email via SMTP (Gmail/Workspace app password).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""            # From address (defaults to smtp_user if blank)
    notify_email_to: str = ""      # comma-separated recipients (the agency team)
    # Slack app bot token (xoxb-…) + default channel id/name.
    slack_bot_token: str = ""
    slack_default_channel: str = ""
    # Slack conversational assistant (SerMastr): respond to @mentions in channels
    # with a Claude answer grounded in the client's rank/GSC data. The signing
    # secret (Basic Information → App Credentials) verifies inbound Slack events;
    # without it the /slack/events endpoint rejects everything (fail-closed).
    slack_signing_secret: str = ""
    slack_assistant_enabled: bool = True
    slack_assistant_model: str = "claude-sonnet-4-6"
    slack_assistant_max_tokens: int = 900
    slack_assistant_max_keywords: int = 60   # cap keywords folded into the LLM context
    # Frontend base URL for deep links in email/Slack (e.g. https://ar-internal.netlify.app).
    app_base_url: str = ""
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
    # `maps_geocode_max_cells` is a SAFETY bound on geocode calls per keyword, set
    # above any real grid's opportunity-cell count (a 15x15 grid's inscribed circle
    # is < 180 cells) so it does not bite in practice — keeping suburb pin-counts
    # exact. If a pathological grid ever exceeds it, the lowest-priority cells are
    # dropped (logged, not silent) and counts become approximate. The cross-client
    # `maps_geocode_cache` makes repeats free.
    google_maps_api_key: str = ""
    maps_strong_rank_threshold: int = 4  # ranks <= this are "in the pack" — not an opportunity
    maps_weak_rank_threshold: int = 10   # rank >= this (ranked) is "Weak"; between is "Watch"
    maps_unranked_effective_rank: int = 25  # rank an unranked pin stands in for, when scaling severity
    maps_beatability_min: float = 0.6
    maps_beatability_max: float = 1.4
    maps_core_adjacency_floor: float = 0.5  # score a weak pin keeps when ALL 8 neighbors are in the pack
    maps_min_area_pins: int = 3  # a suburb needs >= this many weak pins to be flagged as a weak area
    maps_geocode_max_cells: int = 250  # safety bound on geocode calls (above any real grid's cell count)

    # Geo-grid analyzer + alerting (maps_analyzer): scan-over-scan decline
    # thresholds for the `maps_analyze` job (each keyword's newest scan vs its
    # previous completed scan). Conservative defaults — tune to taste.
    maps_alert_grid_rank_drop_min: float = 1.5      # avg grid-rank worsening (spots) to alert
    maps_alert_coverage_drop_pct: float = 15.0      # Top-3/Top-10 coverage drop (pts) to alert
    maps_alert_found_drop_pct: float = 20.0         # found-pin coverage collapse (pts) → lost_pack
    maps_alert_area_coverage_drop_pct: float = 25.0  # per-octant Top-3 coverage drop (pts) → area_decline
    maps_alert_area_rank_drop: float = 2.0          # per-octant avg-rank worsening (spots) → area_decline
    maps_alert_competitor_surge_pins: int = 5       # min newly-above pins for competitor_surge

    # Competitor GBP intelligence (Tier B / B1): how many of the latest scan's
    # top local-pack competitors to fetch full GBP profiles for (each fetch is an
    # Outscraper call — capped to bound spend), and the auto-refresh interval.
    competitor_gbp_max: int = 8
    competitor_gbp_interval_days: int = 30

    # Review analytics (Tier B / B3): how many newest reviews to pull per listing
    # (client + each competitor) for volume/velocity/rating analysis, and the min
    # reviews/month the client must trail the competitor median by to flag a gap.
    review_intel_depth: int = 100
    review_gap_min_behind: float = 2.0

    # Backlink profiling (Tier B / B4): thresholds for flagging an authority gap
    # vs the competitor median (DR points behind; referring-domains behind).
    backlink_dr_min_behind: float = 10.0
    backlink_rd_min_behind: int = 25

    # On-site content comparison (Tier B / B5): how many competitor pages to
    # scrape per keyword, and the thresholds to flag a content gap (words thinner
    # than the competitor median; distinct topics competitors cover the client lacks).
    content_intel_max_pages: int = 4
    content_depth_behind_min: int = 300
    content_topic_gap_min: int = 3

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
    # Service-variation generation: an LLM pass expands the input service into
    # the distinct service-variation landing pages (availability / audience /
    # problem-type modifiers) grouped into silos, keeping the service's qualifier
    # and excluding suburbs (the Neighborhoods silo's job). Best-effort + gated on
    # the Anthropic key. Sonnet (not Haiku) here: the silo-relevance judgement
    # (which buckets genuinely fit the service) and the trade-specific job/problem
    # modifiers need stronger world knowledge + instruction-following than Haiku —
    # Haiku stamped generic urgency/audience buckets onto non-urgency services
    # (e.g. "after hours roof restoration") and anchored on the prompt's examples.
    local_seo_service_model: str = "claude-sonnet-4-6"
    # Verification is geographic + country-agnostic: a proposed sub-area is kept
    # only if it geocodes to a place INSIDE the target city's footprint (its
    # geocoded bounds), which works for US neighborhoods and AU/UK suburbs alike.
    # `local_seo_city_bounds_pad` expands the city box by this fraction on each
    # side (slack for edge suburbs); `local_seo_neighborhood_radius_km` is the
    # fallback containment radius when a city has no bounds/viewport (rare).
    local_seo_city_bounds_pad: float = 0.1
    local_seo_neighborhood_radius_km: float = 30.0
    # Existing-page detection: the silo planner checks the client's live site for
    # generic location pages (e.g. site.com/los-angeles/) so an area that already
    # has a location page is flagged `on_site` instead of `missing` and isn't
    # re-created. Discovery reads the site's sitemap(s) first, falling back to a
    # DataForSEO `site:` query of Google's index. Caps keep a large sitemap from
    # ballooning the scan; the DataForSEO fallback uses its own SERP depth.
    local_seo_sitemap_max_urls: int = 5000
    local_seo_sitemap_max_files: int = 30
    local_seo_site_index_dataforseo_depth: int = 100
    # Bulk background jobs (bulk-create / bulk-reoptimize) enqueue one async_jobs
    # row per item. The single worker claims the OLDEST pending scheduled_at and
    # has no <=now gate, so staggering each bulk item's scheduled_at this many
    # seconds into the future makes a now-dated interactive/scheduled job (and
    # other clients' work) interleave ahead of the rest of the batch — bulk
    # becomes background priority. There's no delay when the queue is otherwise
    # empty (no gate). Keep ≳ a single item's runtime so an interactive job waits
    # behind at most the currently-running bulk item.
    local_seo_bulk_job_spacing_seconds: int = 180
    # Target-city discovery: the silo planner serves the seed city plus the other
    # cities a business targets — from its GBP service area, a manual list on the
    # client, place-names on its own site, and cities within
    # `local_seo_nearby_city_radius_km` (10 miles) enumerated from OpenStreetMap via
    # Overpass (free/keyless). Discovered (website/nearby) candidates must geocode
    # to a city-level locality; website candidates are bounded to this radius times
    # `local_seo_website_city_radius_mult`. The whole set is capped at
    # `local_seo_max_target_cities` so a dense metro can't explode the plan.
    local_seo_nearby_city_radius_km: float = 16.09  # 10 miles
    local_seo_max_target_cities: int = 12
    local_seo_website_city_radius_mult: float = 5.0
    local_seo_overpass_url: str = "https://overpass-api.de/api/interpreter"
    local_seo_overpass_mirror_url: str = "https://overpass.kumi.systems/api/interpreter"
    local_seo_overpass_place_types: str = "city,town"

    # ── Content Syndication module ───────────────────────────────────────────
    # Daily scan watches a client's site for new content (blog/pages/products),
    # rewrites each new piece into a unique version, and publishes it as a public
    # Google Doc + Google Sheet with a backlink to the source. Discovery reuses
    # the sitemap crawler (local_seo_sitemap_* caps) + the DataForSEO `site:`
    # fallback. The rewrite is a heavier, new-angle reworking (Sonnet). Per-item
    # publish jobs are staggered (reuses the bulk-spacing idea) so a large first
    # scan runs at background priority and each item stays under the stale-job
    # reaper window.
    syndication_rewrite_model: str = "claude-sonnet-4-6"
    syndication_rewrite_max_tokens: int = 8192
    syndication_default_interval_days: int = 1
    # Manual select-and-publish: the scan only lists discovered pages; the user
    # ticks pages and publishes them. Selected items are enqueued as lightly
    # staggered per-item jobs (this spacing) — kept ≈ the worker poll interval so
    # the selection processes about as fast as the single worker can drain it,
    # while staying >0 so a now-dated interactive job still interleaves ahead of
    # the rest of a large batch.
    syndication_item_job_spacing_seconds: int = 10

    # ── AI Visibility (Brand Strength) module ────────────────────────────────
    # Mention classifier (post-processes each engine's answer into mention/type/
    # sentiment via OpenAI function-calling). Runs once per keyword×engine plus
    # once per competitor, so it uses the cost-efficient `mini` tier of the latest
    # OpenAI model rather than the flagship. No web search needed here.
    brand_classifier_model: str = "gpt-5.4-mini"
    # Scan-engine models. Each engine measures its OWN assistant surface, so the
    # provider is fixed per engine; only the model within it is tunable. The
    # `claude` engine uses the suite default; `chatgpt` uses the latest OpenAI
    # flagship; the others keep their provider's representative model.
    brand_engine_claude_model: str = "claude-sonnet-4-6"
    brand_engine_chatgpt_model: str = "gpt-5.4"
    # OpenAI Responses API web-search tool type. GA name is "web_search";
    # tunable (like the Fanout client) so it can be flipped to
    # "web_search_preview" without a code change if the account needs it.
    brand_chatgpt_web_search_tool: str = "web_search"
    brand_engine_gemini_model: str = "gemini-2.0-flash"
    brand_engine_perplexity_model: str = "sonar"
    # Auxiliary OpenAI features: invisibility diagnosis + keyword suggestions.
    # Use the latest OpenAI flagship (these are quality reasoning/generation
    # tasks run on demand, not per-row, so flagship cost is fine).
    brand_diagnose_model: str = "gpt-5.4"
    brand_suggest_model: str = "gpt-5.4"
    # Keyword suggestions transform the client's already-tracked organic +
    # geo-grid keywords into ICP-grounded conversational AI queries (3-5 each).
    # Cap the seed set so the single suggestion call stays bounded/parseable.
    brand_suggest_max_seed_keywords: int = 25
    # Auto-generate the invisibility diagnosis during the scan for every
    # completed not-found cell (vs. lazily on first click). Best-effort: a
    # failed/unconfigured diagnose never fails the cell, and the on-demand
    # /diagnose endpoint still backfills older rows. Set False to revert to
    # purely on-demand diagnosis (one gpt-5.4 call per invisible cell saved).
    brand_autodiagnose_enabled: bool = True
    # Visibility report narrative (published as a Google Doc). Suite-default
    # Claude, matching the Maps Local Rank Analysis report.
    brand_report_model: str = "claude-sonnet-4-6"
    # Per keyword×engine attempt budget for transient errors (matches the source
    # app's 2 retries). Auth/quota/rate-limit errors are terminal (no retry).
    brand_scan_max_retries: int = 2
    # How many keyword×engine cells a scan processes concurrently. Bounds the
    # network-bound LLM/SERP calls so a large scan doesn't monopolise the shared
    # job worker for many minutes (each cell still awaits its providers).
    brand_scan_concurrency: int = 6
    # Max competitors classified against a single scan's response (no extra
    # search calls — the same raw response is re-classified per competitor).
    brand_scan_max_competitors: int = 5
    # AI Visibility alerting: after a scan completes, compare it to the previous
    # scan and emit a notification (in-app + Slack/email) on a regression — a
    # visibility drop of at least this many points, an engine the brand went
    # fully invisible on, or newly-detected misinformation. Set False to mute.
    brand_alerts_enabled: bool = True
    brand_alert_visibility_drop_pct: int = 15

    # Service Page scoring: after a service_page run generates, it auto-scores
    # (nlp-api national mode) and auto-reoptimizes ONCE if the composite is below
    # this threshold. Manual Score/Reoptimize controls remain available in the UI.
    service_page_score_threshold: float = 90.0
    # Service-page planner: an already-published page is only dropped from the plan
    # when it ranks within the top N for its keyword (domain-level, DataForSEO); a
    # page ranking worse (or not at all) is surfaced for reoptimization instead.
    # The rank check bills DataForSEO per page, so it's bounded per plan run.
    service_page_rank_top_n: int = 5
    service_page_plan_max_rank_checks: int = 25

    # ------------------------------------------------------------------
    # SerMaStr — Search Marketing Strategist Agent
    # (docs/modules/seo-strategist-agent-plan-v1_0.md)
    # ------------------------------------------------------------------
    # Master switch. DEFAULT FALSE until the smoke gate (spec §7): with it off,
    # nothing runs — the on-demand API returns 409, the weekly scheduler pass
    # and the escalation-event triggers all no-op, and the Slack action refuses.
    # Flip STRATEGIST_ENABLED=true on PLATFORM to activate.
    strategist_enabled: bool = False
    # Sonnet-class everywhere (spec §9 default; revisit Opus for escalation
    # briefs after the smoke gate).
    strategist_model: str = "claude-sonnet-4-6"
    strategist_max_tokens: int = 4096
    # Drill-down bounds (spec §2): ≤ N tool calls per run; the paid one
    # (audit_page → an nlp-api scoring run) is capped separately and tighter.
    strategist_max_drilldowns: int = 4
    strategist_max_paid_drilldowns: int = 1
    # Each drill-down result is truncated to ~this many characters (~2k tokens).
    strategist_tool_result_chars: int = 8_000
    # The two LLM drill-down subagents (serp_deep_dive / geogrid_history).
    strategist_subagent_model: str = "claude-sonnet-4-6"
    strategist_subagent_max_tokens: int = 1200
    # Weekly scheduled runs: the day after the Monday reopt-plan build so the
    # strategist reads a fresh Action Plan (0=Mon..6=Sun). Active-signal
    # clients only (spec §9 default).
    strategist_weekly_weekday: int = 1
    # Input budget per run before drill-downs (spec §2: ≤ ~25k tokens). The
    # digest assembler converts at ~4 chars/token and splits this between the
    # signal digest and the SOP block.
    strategist_digest_budget_tokens: int = 25_000

    # ------------------------------------------------------------------
    # Asana task integration (docs/modules/asana-task-integration-plan-v1_0.md)
    # ------------------------------------------------------------------
    # Two features on one token: (A) monthly section automation — clone a
    # hand-maintained "Template" section forward into a new "<Month YYYY>"
    # section per client project; (B) Team Workload — read a defined team list's
    # open tasks across all client projects + proactive overload alerts. Both
    # degrade gracefully: absent the token / workspace the features are skipped
    # with a note, never an error (the GSC / Slack provisioning pattern).
    asana_token: str = ""          # Asana PAT / service-account token (Bearer)
    asana_workspace_gid: str = ""  # scopes the per-assignee task queries
    asana_monthly_enabled: bool = True
    asana_workload_enabled: bool = True
    # Auto-distribution: a template row marked auto_assign is handed to the
    # client's eligible team member with the most remaining capacity at run time.
    # When off, auto rows are created unassigned.
    asana_auto_distribute_enabled: bool = True
    # Monthly section automation cadence. The scheduler fires once per month on
    # `asana_month_generate_day`; the target month = today shifted by
    # `asana_month_target_offset` (0 = the month that just started, 1 = next
    # month, to pre-stage ahead). Tasks come from each client's app-defined
    # template (asana_client_task_templates) — there is no Asana "Template"
    # section (the source of truth is the app).
    asana_month_generate_day: int = 1
    asana_month_target_offset: int = 0
    # Custom-field resolution. Client-project custom fields are typically
    # PROJECT-LOCAL (each project has its own copies → different GIDs), so the
    # monthly job resolves them **by name** per project at task-creation time:
    # find the field named `asana_status_field_name` (+ its option named
    # `asana_status_not_started_option_name`), `asana_category_field_name`, and
    # the number field `asana_effort_field_name`. The *_gid settings below are an
    # optional explicit override / fallback when a name isn't found (or is blank).
    asana_status_field_name: str = "Status"
    asana_status_not_started_option_name: str = "Not Started"
    asana_category_field_name: str = "Service Type"
    asana_effort_field_name: str = ""   # e.g. "Hours" / "Estimated time"; blank = none
    asana_status_field_gid: str = ""
    asana_status_not_started_option_gid: str = ""
    asana_category_field_gid: str = ""
    # Team Workload: the Asana user GIDs to track (comma-separated). Used as a
    # fallback seed only — the source of truth is the asana_team_members table
    # (editable in the Workload page). Absent both → the feature is skipped.
    asana_team_member_gids: str = ""
    # Effort-weighting (Phase 3). Overload is computed from estimated *hours*,
    # not task counts. The monthly job stamps each task's est_hours into this
    # Asana number custom field; the workload read pulls it back off the task.
    asana_effort_field_gid: str = ""
    # Fallback hours for a task with no estimate (so the signal isn't blind).
    asana_default_task_hours: float = 1.0
    # Default weekly capacity for a tracked member with no weekly_hours set.
    asana_default_weekly_hours: float = 30.0
    # Workdays per week — daily capacity = weekly_hours / this (same-day check).
    asana_workload_daily_workdays: int = 5
    # Flag a member whose open backlog exceeds this many weeks of their capacity.
    asana_workload_backlog_weeks: float = 2.0

    class Config:
        env_file = ".env"


settings = Settings()
