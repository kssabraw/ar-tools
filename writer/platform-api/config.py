from typing import List, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    pipeline_api_url: str = "http://ar-tools.railway.internal:8080"
    nlp_api_url: str = "http://nlp.railway.internal:8080"
    # Global cap on concurrently-executing blog/service-page runs (each fires
    # brief+SIE in parallel — heavy Claude fan-outs in pipeline-api). Excess
    # runs wait in their queued status; see orchestrator._get_run_gate. Also
    # bounds silo-promotion run creation (routers/silos.py). NOTE: this class
    # briefly carried a duplicate definition of this field (=5 further down,
    # which silently won) — keep it defined exactly once.
    max_concurrent_runs: int = 3
    # Auto-resume runs orphaned by a service restart (deploy/crash mid-run):
    # startup recovery re-dispatches them (the orchestrator skips completed
    # module_outputs, so only the interrupted stage re-runs) at most this many
    # times per run; past the cap the run fails with the old "Service restarted
    # mid-run" message. 0 disables auto-resume (always fail, the old behavior).
    run_auto_resume_max: int = 2
    scrapeowl_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # AI Visibility module (Brand Strength) — the two scan engines whose keys
    # aren't already shared. Absent either, that engine fails its scans with a
    # "not configured" reason; the other engines (chatgpt/claude via the keys
    # above, google_ai_* via DataForSEO) keep working.
    perplexity_api_key: str = ""
    gemini_api_key: str = ""
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
    # Competitive intelligence (strategist phase 2): weekly registry
    # auto-discovery + competitor content watch (sitemap reads only).
    competitor_intel_enabled: bool = True
    competitor_intel_interval_days: int = 7
    competitor_watch_max_pages: int = 2000
    # Trend watching (strategist phase 4): cross-client algo-update detection
    # (daily DB-reads-only sweep) + seasonal demand from cached volume history.
    # An event needs >= algo_min_clients AND >= algo_min_share of clients with
    # tracked keywords opening drops inside the same algo_window_days window.
    trend_watch_enabled: bool = True
    algo_min_clients: int = 3
    algo_min_share: float = 0.4
    algo_window_days: int = 3
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
    # Internal-linking analyzer + injector. WordPress (app-password) sources are
    # injectable after per-edit human approval; non-WP sites are crawled
    # (sitemap + ScrapeOwl) for recommend-only suggestions.
    internal_link_max_per_page: int = 3          # max new links added to one page
    internal_link_max_inbound_per_target: int = 5  # cap links funnelled to one target
    internal_link_min_anchor_words: int = 2      # anchors must be ≥ this many words
    internal_link_wp_max_pages: int = 200        # WP inventory fetch cap
    internal_link_crawl_max_pages: int = 40      # non-WP crawl cap
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
    # ------------------------------------------------------------------
    # Google Business Profile (GBP) performance-metrics ingestion.
    # DORMANT until (a) Google approves Business Profile API quota for the GCP
    # project the service account lives in and (b) the service account is added
    # as a Manager on each client's Business Profile. Reuses
    # `google_service_account_key` (with the added business.manage scope).
    # Left off by default so the scheduler pass + endpoints are no-ops until
    # access lands. See docs/modules/client-reporting-prd-v1_0.md (Phase 2).
    gbp_metrics_enabled: bool = False
    # Each daily run re-pulls the trailing window (GBP performance data arrives
    # ~3–5 days late — longer than GSC — so re-pull further back; idempotent
    # upserts make the overlap harmless and a missed run self-heals).
    gbp_metrics_repull_days: int = 7
    # The scheduler enqueues one ingest job per verified location once a day,
    # after this hour (UTC), same shared loop as the GSC ingest.
    gbp_metrics_hour_utc: int = 8
    # One-time historical pull window. The Performance API serves ~18 months.
    gbp_metrics_backfill_days: int = 540
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
    # Per-keyword report generation fans out concurrent Anthropic calls within one
    # scan's job. The account's concurrent-connections limit is low, so a wide
    # fan-out trips HTTP 429 ("Number of concurrent connections has exceeded your
    # rate limit") and the row fails. Cap the simultaneous per-keyword LLM calls
    # at (well under) the account ceiling so they don't collide with each other;
    # the image render + geocoding steps are not Anthropic-bound and stay parallel.
    maps_report_concurrency: int = 2
    # Retry transient failures (429 concurrent-connections / rate limit, 5xx,
    # connection drops) with exponential backoff + jitter rather than permanently
    # failing the row. The retry budget must outlast a competing ~1-min generation
    # elsewhere in the suite, so it stays generous (2/4/8/16/32/64s at base 2.0).
    maps_report_max_retries: int = 6
    maps_report_retry_base_seconds: float = 2.0
    # Provider for the report narrative. Defaults to OpenAI: a per-keyword scan
    # fans out concurrent report calls that collided with the rest of the suite
    # on one saturated Anthropic account (sustained 429s that outlasted the retry
    # budget), so the report runs on OpenAI's separate quota. Set
    # MAPS_REPORT_PROVIDER=anthropic to revert (uses maps_report_model then).
    maps_report_provider: str = "openai"          # openai | anthropic
    maps_report_openai_model: str = "gpt-5.4"

    # Organic Rank Analysis report — the per-keyword deep-dive (the organic
    # analogue of the Local Rank Analysis report). Sonnet writes an observational
    # narrative from the deterministic trajectory + competitive-landscape +
    # gap-to-close rollups (services/rank_analysis.py); it reuses the latest
    # stored SERP snapshot (no fresh capture). Generated on-demand per keyword,
    # automatically when a rank-drop alert opens, and weekly per keyword.
    rank_analysis_model: str = "claude-sonnet-4-6"
    rank_analysis_max_tokens: int = 8192
    # Provider for the report narrative — see maps_report_provider. Defaults to
    # OpenAI (the twin per-keyword report shares the same Anthropic 429 exposure).
    # Set RANK_ANALYSIS_PROVIDER=anthropic to revert (uses rank_analysis_model).
    rank_analysis_provider: str = "openai"        # openai | anthropic
    rank_analysis_openai_model: str = "gpt-5.4"
    rank_analysis_max_retries: int = 6
    rank_analysis_retry_base_seconds: float = 2.0
    # Weekly auto-generation: gated on this flag; runs the day after the weekly
    # SERP-snapshot capture so the latest landscape is available to analyze.
    rank_analysis_auto_enabled: bool = True
    rank_analysis_weekly_weekday: int = 3  # Thursday (after the weekly snapshot)

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
    # Debounce for automated (non-manual) action-plan rebuilds. The scheduler's
    # weekly day-gate is in-memory, so every platform-api restart on the weekly
    # day re-fires the "scheduled" pass; event triggers (drop/maps_drop/offpage)
    # can also fire several times a day. A "scheduled" rebuild is collapsed to at
    # most once per UTC day; event-driven rebuilds are collapsed within this many
    # hours of the last completed plan. A user-initiated "manual" refresh is never
    # debounced. Set to 0 to disable the event-trigger window (day-gate stays).
    reopt_plan_min_interval_hours: int = 6
    # Strict weekly cadence (owner decision): only the weekly "scheduled" pass and
    # user-initiated "manual" refreshes rebuild the Action Plan. Event triggers
    # (drop/maps_drop/offpage) are suppressed by default — the drop still notifies
    # via the alert/notifications path; the plan just folds it in on the next
    # weekly run or a manual refresh. Flip to True to restore the on-drop
    # auto-refresh (still debounced by reopt_plan_min_interval_hours).
    reopt_plan_event_refresh_enabled: bool = False

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
    # Broadcast mention on Slack notifications. slack_mention_token picks the
    # broadcast — "here" (<!here>, pings active members only), "channel"
    # (<!channel>, pings every member incl. away/offline), or "" (off). It is
    # applied only to notifications whose severity is in slack_mention_severities
    # (comma-separated), so info-level items never ping. Default: @here on
    # critical + warning (owner decision).
    slack_mention_token: str = "here"
    slack_mention_severities: str = "critical,warning"
    # Slack conversational assistant (SerMastr): respond to @mentions in channels
    # with a Claude answer grounded in the client's rank/GSC data. The signing
    # secret (Basic Information → App Credentials) verifies inbound Slack events;
    # without it the /slack/events endpoint rejects everything (fail-closed).
    slack_signing_secret: str = ""
    slack_assistant_enabled: bool = True
    slack_assistant_model: str = "claude-sonnet-4-6"
    # Reply length hard stop. 900 clipped SOP-grounded strategy answers
    # mid-sentence ("Want me to run a full…") — 2000 gives Director's-voice
    # replies (opinion + numbers + citations + next move) room; the prompt's
    # "be concise" rule is the real length governor. Still-truncated replies
    # get an explicit "say continue" marker appended (see interpret()).
    slack_assistant_max_tokens: int = 2000
    slack_assistant_max_keywords: int = 60   # cap keywords folded into the LLM context
    # Anthropic's server-side web_search tool on the assistant's Claude call —
    # lets SerMastr look up public info (reviews on TrustPilot/Google, competitor
    # sites, industry news) it recommended but couldn't previously read. Billed
    # per search by Anthropic; max_uses bounds spend per question. The tool type
    # requires a 4.6+ model (slack_assistant_model default qualifies).
    slack_assistant_web_search_enabled: bool = True
    slack_assistant_web_search_max_uses: int = 3
    # SOP grounding for the assistant (Slack + dashboard chat): strategy-shaped
    # questions inject a budgeted SOP selection into the prompt, and the model
    # can pull more via a read_sop tool (bounded rounds per message).
    slack_assistant_sop_budget_chars: int = 16_000
    slack_assistant_sop_rounds: int = 3
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

    # Backlink explorer tool (any-domain Site Explorer). The cheap views
    # (overview/referring-domains/anchors/history) are cached per target for this
    # many hours so repeat lookups don't re-bill DataForSEO; the expensive
    # per-link list is fetched on demand (never persisted) and capped per call.
    backlink_cache_ttl_hours: int = 24
    backlink_referring_domains_limit: int = 100
    backlink_anchors_limit: int = 100
    backlink_links_max_limit: int = 100
    backlink_pages_limit: int = 100  # per-page breakdown rows per snapshot
    # A shared daily ceiling on paid DataForSEO backlink calls (a refresh is ~4
    # endpoint calls, a link-list page is 1). 0 disables the guard. Ad-hoc
    # lookups and scheduled re-snapshots draw from the same day's budget.
    backlink_daily_call_budget: int = 1000
    # Tracked-target re-snapshot cadence + how many referring domains must be
    # gained/lost between snapshots before a tracked target alerts its client.
    backlink_tracking_enabled: bool = True
    backlink_tracking_interval_days: int = 7
    backlink_alert_new_domains_min: int = 10
    backlink_alert_lost_domains_min: int = 10
    # Cap on synthetic is_lost rows written per snapshot (surfaced in the UI).
    backlink_lost_rows_cap: int = 200
    # Auto-track each client's own domain for backlink monitoring (so alerts +
    # agent enrichment work without manual per-client setup). Idempotent and
    # respects a manual untrack; the daily budget caps the added spend.
    backlink_auto_track_client_domain: bool = True

    # Domain Intelligence module (the "SEMrush clone") — per-client competitive
    # intelligence over the DataForSEO Labs family. See
    # docs/modules/domain-intelligence-module-prd-v1_0.md.
    domain_intel_enabled: bool = True
    # A daily ceiling on paid DataForSEO Labs calls for this module, SEPARATE
    # from the backlink budget (own meter: domain_intel_usage). This is the
    # §10 open question #4 — start conservative; raise once real spend is known.
    # 0 disables the guard.
    domain_intel_daily_call_budget: int = 200
    # A fresh snapshot within this window is re-served, not re-fetched (cost).
    domain_intel_cache_hours: int = 24
    # Scheduled re-snapshot cadence for a client's registered competitors.
    domain_intel_interval_days: int = 7
    # Cap on ranked-keyword rows fetched/stored per domain snapshot.
    domain_intel_ranked_keyword_cap: int = 1000
    # Keyword-gap thresholds (§10 open questions #3): a gap keyword requires a
    # competitor ranking at or above _gap_competitor_max_position, the client
    # absent or ranking worse than _gap_client_min_position, and this much volume.
    domain_intel_gap_competitor_max_position: int = 10
    domain_intel_gap_client_min_position: int = 20
    domain_intel_gap_min_volume: int = 10
    # Keyword-gap run: how many registered competitors to compare against when
    # the request doesn't name an explicit set (one paid ranked-keywords call
    # per competitor + one for the client). Bounds spend per gap run.
    domain_intel_gap_max_competitors: int = 5
    # Weekly scheduled keyword-gap refresh per eligible client (registered
    # competitors + a website). A scheduled run whose newly-opened gap count
    # clears domain_intel_gap_alert_min emits a "new competitor keyword gaps"
    # notification. Off by disabling domain_intel_enabled.
    domain_intel_gap_alert_min: int = 5
    # How many top keyword-gap opportunities surface as Action Plan items.
    domain_intel_action_max: int = 3

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
    # Content Scheduler (suite bulk page creation + scheduling). Max keywords per
    # batch; per-content-type $/page cost estimate (the deliberate fix for the
    # Fanout scheduler's caveat of estimating every type at the blog constant);
    # and the VA approval threshold — a team_member whose batch estimate exceeds
    # it is blocked pending a senior operator (staff/admin never gated).
    content_batch_max_items: int = 200
    content_batch_cost_blog_usd: float = 0.75
    content_batch_cost_service_usd: float = 0.60
    content_batch_cost_location_usd: float = 0.60
    content_batch_cost_local_seo_usd: float = 0.90
    content_batch_approval_threshold_usd: float = 90.0
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
    # gemini-2.0-flash was shut down by Google on 2026-06-01; gemini-3.5-flash
    # is the current GA Flash model (alias gemini-flash-latest). Override via
    # BRAND_ENGINE_GEMINI_MODEL when Google rotates the GA Flash tier again.
    brand_engine_gemini_model: str = "gemini-3.5-flash"
    brand_engine_perplexity_model: str = "sonar"
    # Auxiliary OpenAI features: invisibility diagnosis + keyword suggestions.
    # Diagnosis runs per not-found cell during a scan (auto-diagnose, below), so
    # at scale it's a per-row cost driver — keep it on the cheaper `mini` tier.
    # Keyword suggestions are genuinely on-demand (a manual click), low volume,
    # so they stay on the flagship where generation quality matters more.
    brand_diagnose_model: str = "gpt-5.4-mini"
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
    # Per keyword×engine attempt budget for transient errors (429 rate-limit,
    # 5xx, connection drops), retried with exponential backoff + jitter.
    # Auth/payment errors are terminal (no retry).
    brand_scan_max_retries: int = 3
    brand_scan_retry_base_seconds: float = 2.0
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
    # Reputation alarm (LABS parity): a completed cell with sentiment below the
    # threshold at at-least this classifier confidence counts as a negative
    # mention; alerts fire only for cells that weren't negative last scan.
    brand_alert_sentiment_threshold: float = -0.3
    brand_alert_confidence_min: float = 0.7

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
    # Durable "already ran this week" guard for the scheduled pass. The weekly
    # weekday gate lives in process memory (`last_strategist_date`), so a
    # redeploy/restart on the strategist weekday would otherwise re-fire the
    # whole active-signal pass. A client with a `scheduled` run inside this many
    # days is skipped, so scheduled runs stay at most weekly regardless of how
    # often the process restarts. 6 (not 7) leaves a day of margin so next
    # week's legitimate run at the same weekday isn't suppressed. 0 disables.
    strategist_weekly_interval_days: int = 6
    # Proactive opportunity sweep: a QUIET client (no active signals) still gets
    # a scheduled run when its last strategist run is older than this — so
    # opportunity mining (review themes, competitor gaps, coverage holes)
    # reaches every client ~monthly, not just clients with open problems.
    # Bounded: ≤1 extra run per quiet client per interval; 0 disables.
    strategist_opportunity_interval_days: int = 28
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

    # Native In-App Task Manager (docs/modules/in-app-task-manager-prd-v1_0.md).
    # Master flag for the parallel-run: while False, the native scheduler hooks
    # (monthly generation, due sweep, native workload alert) stay dormant and
    # the Workload page keeps reading Asana — the team's execution surface is
    # unchanged. Flip to true at cutover (or during the parallel-run cycle).
    # On-demand endpoints (generate-month, native workload read) work
    # regardless: they only touch the new task_* tables. The monthly cadence
    # reuses asana_month_generate_day / asana_month_target_offset, and the
    # workload thresholds reuse the asana_* defaults above — one knob set for
    # both systems during the transition.
    native_tasks_enabled: bool = False
    # Per-file cap for task attachments (the bucket also enforces 20 MB).
    task_attachment_max_mb: int = 20
    # Suite auto-integration producers (PRD §11) — each is double-gated on
    # native_tasks_enabled AND its own flag, so they can be enabled one at a
    # time. content_run is opt-in (the PRD marks it optional).
    task_producer_rank_drop_enabled: bool = True
    task_producer_maps_alert_enabled: bool = True
    task_producer_action_plan_enabled: bool = True
    # Only the top-N plan actions become tasks (the plan is priority-sorted).
    task_producer_action_plan_max: int = 10
    task_producer_content_run_enabled: bool = False

    # PACE — Project Assignment, Coordination & Execution agent
    # (docs/modules/project-manager-agent-plan-v1_0.md). Phase 0A ships only the
    # deterministic pm_signals layer (pure reads, no LLM, no writes, wired to
    # nothing) — these knobs parameterize the pure builders; the master gate +
    # persona/model land with later phases.
    pace_enabled: bool = False
    # Staleness thresholds — days-in-current-status by status KEY; the coarse
    # category fallback covers any status key not listed (configurable statuses).
    pace_stale_thresholds: dict = {
        "blocked": 3, "in_review": 5, "sent_to_client": 5, "in_progress": 10,
    }
    pace_stale_category_fallback: dict = {"blocked": 3, "in_progress": 10}
    # Month-pace heuristic (§2b): grace, min board size to judge, and the
    # first-N-business-days suppression window.
    pace_month_pace_grace: float = 0.15
    pace_month_pace_min_tasks: int = 4
    pace_month_pace_suppress_business_days: int = 3
    # Untriaged: don't flag a brand-new unassigned/dateless task until it's this
    # many days old (so freshly-created work isn't nagged immediately).
    pace_untriaged_grace_days: int = 2
    # Cap the (later) daily digest.
    pace_digest_max_items: int = 8
    # Suppress the daily digest on weekends (Sat/Sun) — VA-facing, workdays only.
    pace_digest_weekday_only: bool = True
    # Permission matrix — the two "via policy" cells (PRD §3.2). Defaults:
    # any internal user can read a board (internal-tool norm); month generation
    # is admin-only (loosen to "staff" to let leads generate).
    pace_perm_read_board_min_role: str = "team_member"
    pace_perm_generate_month_min_role: str = "admin"
    # PACE persona (Phase 3) — cheap model, small budget (delivery Q&A + action
    # arg-filling, not strategy prose).
    pace_model: str = "claude-haiku-4-5-20251001"
    pace_max_tokens: int = 1200
    # PACE v1.3 Phase 5 — role/skill placement (§4.6). Whether producer tasks
    # (rank_drop/maps_alert/action_plan) are auto-placed on creation (default off
    # — approved proposals always are). When the skilled+eligible pool is over
    # capacity: "hold" (leave unassigned + flag) or "least_over" (assign anyway).
    pace_autoplace_producers: bool = False
    pace_placement_overload: str = "hold"
    # PACE v1.3 Phase 6 — delivery reports (§4.7). Default window + the weekday
    # (0=Mon…6=Sun) for the optional weekly portfolio auto-digest. None ⇒ the
    # weekly digest is off (on-demand + the Reports card still work).
    pace_report_period_days: int = 7
    pace_report_weekday: Optional[int] = None
    # PACE v1.3 Phase 7 — dedicated channel (§10.2). A Slack channel id (C…): when
    # set, PACE owns that channel (answers every message, defers strategy to
    # SerMaStr) and SerMaStr is excluded there; PACE stays out of other channels.
    # Empty ⇒ shared-channel shape-routing (backward-compatible). PACE's digest +
    # weekly report also post here when set.
    pace_slack_channel: str = ""

    # --- LeadOff (market intelligence; docs/modules/leadoff-prd-v1_0.md) ---
    # Read-only v1 serves the precomputed market_scanner.leadoff_board.
    # Board queries pre-rank on the stored sort column and fetch this many rows
    # before exact re-sorting under non-default capture/lead-tier assumptions.
    leadoff_prefetch_rows: int = 1500
    # Paid actions (PRD §5 item 1): per-user daily budget across tryout
    # (~$0.20/run) + scout (~$0.10–1/market, cache-cheapened). Every enqueue
    # records its estimate to leadoff_spend; the guard sums today's UTC rows.
    leadoff_daily_budget_usd: float = 5.0

    class Config:
        env_file = ".env"


settings = Settings()
