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
    # How long after boot the orphan-run recovery sweep waits before it looks.
    # MUST outlast Railway's deploy handover: the incoming container is live
    # while the outgoing one keeps working for ~15s, so a sweep at second 0
    # re-dispatches runs that are still genuinely executing over there — two
    # orchestrators driving one run, double module spend, racing module_outputs
    # writes. (The retired fanout orphan sweep delayed itself for exactly this
    # reason; this path never got the same treatment.) The cost of waiting is
    # only that a genuinely-orphaned run resumes a couple of minutes later —
    # it has been stalled since the previous deploy anyway. 0 = sweep inline at
    # startup (the old, racy behavior).
    run_recovery_delay_seconds: float = 120.0
    # Run-level transient-failure auto-retry (resilience layer, distinct from the
    # orphan-recovery resume above). When a run fails at a stage because a
    # transient upstream outage (a multi-minute DataForSEO SERP outage, an
    # upstream 5xx, a module timeout) outlasted the in-call HTTP retries, the
    # orchestrator parks it in `retry_scheduled` and the shared scheduler
    # re-dispatches it after a backoff delay (resuming — only the failed stage
    # re-runs) instead of leaving it terminally failed for a human to re-run.
    # Only the transient band is retried (module_timeout / module_unavailable /
    # HTTP 5xx / serp_failed); permanent failures (schema mismatch, content
    # validation, genuinely-empty SERP) fail immediately as before. Backoff is
    # base * factor**(attempt-1) minutes → 5 / 15 / 45 at the defaults, a ~65-min
    # recovery window matching DataForSEO's "re-set the task after a few minutes"
    # guidance. 0 disables (always fail immediately, the old behavior).
    run_transient_retry_max: int = 3
    run_transient_retry_base_minutes: float = 5.0
    run_transient_retry_factor: float = 3.0
    # Google Apps Script webhook (the Docs/Sheets/PDF publish leg) is a single
    # HTTP hop to a notoriously cold-start-prone Apps Script web app: sporadic
    # 5xx / timeouts are common and clear on a quick retry. Retry the transient
    # band only (5xx + timeouts/transport); a config error or an app-level
    # success=false (e.g. a bad folder id) fails fast. In-process backoff, small
    # budget (each attempt already has a 60s transport timeout).
    google_docs_max_retries: int = 2
    google_docs_retry_base_seconds: float = 1.5
    scrapeowl_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # Secondary Anthropic account key for SAME-MODEL failover. When the primary
    # Anthropic account hits a *transient* concurrency/rate limit (429) or 5xx
    # overload that outlasts its per-key retry budget, the SAME call is retried on
    # this second account's key — same Claude models, so output quality is
    # identical (unlike the cross-provider fallback below, which swaps models).
    # Empty ⇒ no second key and every failover path degrades to primary-only. Set
    # on all three services (PLATFORM/pipeline/nlp) since each calls Anthropic.
    anthropic_api_key_secondary: str = ""
    # AI Visibility module (Brand Strength) — the two scan engines whose keys
    # aren't already shared. Absent either, that engine fails its scans with a
    # "not configured" reason; the other engines (chatgpt/claude via the keys
    # above, google_ai_* via DataForSEO) keep working.
    perplexity_api_key: str = ""
    gemini_api_key: str = ""
    # ── Content illustration (hero + inline body images/charts) ──────────────
    # Master switch for the auto path (after a run completes). Per-client opt-in
    # is clients.illustrate_content (default off); on-demand illustration ignores
    # both flags. Reuses the shared OPENAI_API_KEY — no new vendor.
    illustration_enabled: bool = False
    illustration_image_model: str = "gpt-image-1"      # AI illustration renderer
    illustration_image_size: str = "1536x1024"         # landscape hero/body ratio
    illustration_brief_model: str = "gpt-5.4-mini"     # art-direction + chart-series extraction
    # Nano Banana — Gemini 2.5 Flash Image text-to-image (reuses GEMINI_API_KEY).
    # Overridable when Google rotates the image tier (e.g. gemini-3.1-flash-image).
    nano_banana_model: str = "gemini-2.5-flash-image"
    # ── Cross-provider LLM fallback ──────────────────────────────────────────
    # When a primary-provider call (usually Anthropic) hits a *transient* failure
    # that outlasts its per-provider retry budget — a 429 rate/concurrency limit,
    # a 5xx overload, or a connection drop — the same call is retried on the next
    # provider in the chain instead of failing. Applies to the non-agentic call
    # sites (plain text + single forced-tool-use); the agentic tool-use loops
    # (Slack assistant, strategist, PACE) rely on Anthropic-specific server tools
    # and stay Anthropic-retry-only. Non-transient errors (bad request, auth) do
    # NOT fall back — they surface immediately so real bugs aren't masked.
    llm_fallback_enabled: bool = True
    # Providers tried, in order, AFTER the call's primary provider. A provider
    # with no configured API key is skipped. Comma-separated: openai | gemini.
    llm_fallback_providers: str = "openai,gemini"
    # Default models used when a call falls back to a given provider (each call
    # site keeps its own primary/Anthropic model). Tunable per env.
    llm_fallback_anthropic_model: str = "claude-sonnet-4-6"
    llm_fallback_openai_model: str = "gpt-5.4"
    llm_fallback_gemini_model: str = "gemini-3.5-flash"
    # Backoff attempts on ONE provider before advancing to the next. Kept low so
    # the chain reaches an alternate provider quickly rather than exhausting a
    # long backoff on a saturated primary (2 → ~2s + 4s, then advance).
    llm_fallback_max_retries_per_provider: int = 2
    # ── Second-Anthropic-account failover (SAME model, distinct account) ──────
    # Independent of the cross-provider chain above and tried FIRST: an Anthropic
    # call that a transient limit outlasts is retried on `anthropic_api_key_secondary`
    # (same models) before any thought of OpenAI/Gemini. No-op when the secondary
    # key is unset, so it's safe to leave enabled. Covers both the non-agentic
    # report_llm chain AND the agentic loops (Slack/strategist/PACE), which the
    # cross-provider chain deliberately does not.
    anthropic_key_failover_enabled: bool = True
    # Backoff attempts on the PRIMARY Anthropic key before switching to the
    # secondary account. Low, so a saturated primary yields to the second account
    # quickly instead of burning a long backoff (2 → ~2s + 4s, then switch).
    anthropic_key_failover_max_retries: int = 2
    job_worker_poll_interval_seconds: int = 10
    # Stale-job reaper. In-process jobs (asyncio.to_thread) aren't resumable, so a
    # redeploy or crash mid-run orphans them as status='running' forever. Each
    # worker tick sweeps jobs stuck 'running' longer than this many minutes:
    # re-queued (back to pending) while retry attempts remain, else marked failed.
    # Must exceed the longest legitimate job (the GSC backfill / silo plan run a
    # few minutes; maps_scan's 30-min poll lives on a separate table, not here).
    # Set to 0 to disable the reaper.
    job_stale_timeout_minutes: int = 30
    # Per-job-type stale-timeout overrides (minutes) for legitimately long jobs.
    # rank_keyword_report and gsc_page_ingest both grazed the 30-min default in
    # production (reaped mid-run at ~1802s and re-run — doubling their cost).
    job_stale_timeout_overrides: dict = {
        "rank_keyword_report": 60,
        "gsc_page_ingest": 60,
        "task_import_asana": 60,
        # A content_batch_item drives a full run (writer alone is 600s) and waits
        # unbounded on the shared 3-slot run gate, so it can pass the 30-min
        # default while genuinely live. Reaping it mid-run requeues the job and
        # (before the source_ref dedupe) spawned a duplicate article; 90 min
        # keeps the reaper as a real backstop without firing on healthy runs.
        "content_batch_item": 90,
        # Ecommerce generation chains a 600s nlp generate with up to
        # `ecommerce_structure_max_passes` (2) structure-gate regenerations at
        # 600s each, plus the score call — ~35 min worst case, PAST the 30-min
        # default while perfectly healthy. The reaper doesn't cancel the running
        # asyncio task, so firing early means the original finishes and persists
        # a page while a second worker re-runs the whole thing: two
        # `ecommerce_pages` rows and double the SERP + Claude spend. Unlike Local
        # SEO there is no cached SERP analysis to soften the re-run, so the
        # backstop has to clear the real ceiling.
        "ecommerce_generate": 60,
        # Same rule for reoptimize-by-URL: scrape + score (300s) + a rewrite pass
        # that itself loops up to MAX_ECOMMERCE_AUTO_PASSES inside nlp (600s).
        # Its requeue re-scrapes and re-scores from scratch too.
        "ecommerce_reoptimize_url": 60,
        # A Fanout expansion (expand + competitor mining) compounds two ~4-min
        # budgets plus autocomplete/gate, so it can legitimately run well past the
        # 30-min default. The reaper requeue is a re-run from scratch, so it MUST
        # exceed the longest real run or it would spawn a second concurrent
        # expansion (double spend). 45 min keeps it a genuine backstop only.
        "fanout_expand": 45,
        # The remaining durable Fanout pipeline stages (issue #686 Phase 3). Same
        # rule: the reaper requeue re-runs the stage, so the timeout must exceed
        # the longest real run. plan (SERP + per-silo orchestrator) and recursive
        # fanout (paid re-expansion, up to a 15-min budget) both re-spend on
        # requeue; regate + architecture are cheap re-derivations. 45 min keeps
        # the reaper a genuine backstop for all of them.
        "fanout_plan": 45,
        "fanout_regate": 45,
        "fanout_fanout": 45,
        "fanout_architecture": 45,
    }
    # Dedicated worker lane for the (long, blocking) Fanout pipeline jobs, so a
    # ~10-min expansion can't tie up the MAIN lane — which owns the stale-job
    # reaper and every other background job. The MAIN lane excludes these types;
    # this lane claims only them. Empty list disables the dedicated lane (the
    # types then fall back to the MAIN lane). See issue #686 Phase 1.
    fanout_job_types: List[str] = [
        "fanout_expand", "fanout_plan", "fanout_regate", "fanout_fanout",
        "fanout_architecture",
    ]
    # How many concurrent workers the dedicated fanout lane runs (issue #686
    # Phase 3). Before Phase 3 the pipeline stages ran on a 2-slot
    # ThreadPoolExecutor; once they all moved to this single lane, cross-session
    # pipeline work serialized. 2 restores that parallelism (the async_jobs claim
    # is an atomic guarded UPDATE, so N workers never double-claim a row). Set to
    # 1 to throttle to one paid DataForSEO pipeline run at a time.
    fanout_lane_workers: int = 2
    # NOTE: the fanout_resumable_expand_enabled flag (issue #686 Phase 2) lives in
    # the VENDORED fanout config (fanout/config.py), not here — fanout/jobs.py
    # reads it via fanout.config.get_settings(), a different Settings class, so a
    # copy here is dead. (fanout_durable_expand_enabled was retired in Phase 3:
    # every pipeline stage is durable unconditionally now, so the flag and the old
    # in-process executor path are gone. FANOUT_DURABLE_EXPAND_ENABLED on PLATFORM
    # is now an inert leftover env var and can be removed.)
    # Interactive worker lane: a second in-process claim loop dedicated to
    # short, user-awaited job types so a just-clicked action never queues
    # behind long background work (brand scans, DataForSEO rank pulls were
    # producing 10–20 min waits). Same async_jobs table; the status='pending'
    # claim guard makes the two lanes race-safe. Empty list disables the lane.
    interactive_job_types: List[str] = [
        "website_scrape", "brand_voice_scan", "icp_scan",
        "page_structure_scrape", "gsc_research", "gsc_materialize",
        "keyword_market", "maps_scan", "maps_analyze", "client_report",
        "notification_dispatch", "local_seo_generate",
        "local_seo_reoptimize_url", "local_seo_silo", "asana_push",
        # Interactive local-SEO actions the user awaits on-screen (precheck /
        # analyze / score / find_page / related_pages / social_posts). Sibling of
        # local_seo_generate above — must not queue behind the daily scheduler
        # burst on the MAIN lane (ops fix: the "Create new page" precheck crawl
        # stalled 10–30 min behind reopt_plan/gsc_page_ingest/strategy_review).
        "local_seo_action",
        # User-awaited GitHub publish with image generation (minutes-long, like
        # local_seo_generate) — must not queue behind the daily scheduler burst.
        "blog_github_publish",
        # Service-page score / reoptimize — the user is watching the run screen
        # while these execute (formerly in-request SSE; jobs so a deploy can't
        # kill them). Same must-not-queue rationale as local_seo_action.
        "service_page_score", "service_page_reoptimize",
        # Blog article score / reoptimize (blog/AEO rubric) — same on-screen,
        # deploy-proof rationale as the service-page pair above.
        "blog_score", "blog_reoptimize",
        # User-awaited on-demand actions moved from synchronous requests to jobs
        # (so the user can navigate away): the PDF reports (WeasyPrint render) and
        # the backlink lookup (DataForSEO pull on a cache miss).
        "keyword_research_report", "fanout_report", "backlink_lookup",
    ]
    # Content-compliance guardrail: block publishing content that gives human
    # dosing/administration instructions, claims branded-drug equivalence,
    # promises guaranteed results, or advocates buying — for clients in a
    # regulated content_compliance_mode (peptide vendors). Global kill switch;
    # per-client opt-in is clients.content_compliance_mode.
    content_compliance_enabled: bool = True
    # Fan-out brand-voice enforcement: for client-linked sessions, resolve the
    # client's distilled voice card, prime the fan-out writer's prompts with it,
    # and run the voice review + corrective rewrite on the finished article. Off
    # → the fan-out writer generates client-agnostically (its prior behaviour).
    fanout_brand_voice_enabled: bool = True
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

    # Client site inventory — the pages the client's live site actually has,
    # so strategy answers can tell what already exists. Refreshed weekly by the
    # site_inventory job; the paid fallback is one DataForSEO `site:` query and
    # only fires when no sitemap is readable.
    site_inventory_enabled: bool = True
    site_inventory_interval_days: int = 7
    site_inventory_paid_fallback: bool = True
    site_inventory_max_urls: int = 2000      # stored per client
    site_inventory_context_paths: int = 80   # landing paths carried into a prompt
    competitor_watch_max_pages: int = 2000
    # Trend watching (strategist phase 4): cross-client algo-update detection
    # (daily DB-reads-only sweep) + seasonal demand from cached volume history.
    # An event needs >= algo_min_clients AND >= algo_min_share of clients with
    # tracked keywords opening drops inside the same algo_window_days window.
    trend_watch_enabled: bool = True
    algo_min_clients: int = 3
    algo_min_share: float = 0.4
    algo_window_days: int = 3
    # Scan-health watch: alert (in-app + Slack) when a client's scheduled data-
    # collection jobs (maps geo-grid / organic rank) fail in a streak, so a
    # silent upstream outage can't starve the drop alerts unnoticed. Daily
    # DB-reads-only sweep over async_jobs; deduped per streak-episode (re-nudges
    # at most weekly while unresolved).
    scan_health_enabled: bool = True
    scan_health_min_streak: int = 3      # consecutive failed scheduled runs to fire
    scan_health_min_days: int = 3        # ...the failing run must also span this many days
    scan_health_lookback_days: int = 21  # async_jobs history read per sweep
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
    # User-Agent sent on every WP REST call. httpx's default (`python-httpx/x.y`)
    # is a well-known trigger for managed-host bot filters — SiteGround's Anti-Bot
    # AI answers it with an `/.well-known/sgcaptcha/` challenge page instead of the
    # API response, which surfaces as `wordpress_http_error_400` on a request that
    # is otherwise valid and authenticated. A browser-like UA is what those filters
    # expect from a human-driven admin client, which is what this is: an authorized
    # publish with the client's own application password. Overridable per
    # deployment so a host that wants a different string can be satisfied without a
    # code change.
    #
    # KEEP THE VERSION CURRENT. A pinned browser version does not stay benign: it
    # ages into the *other* half of the same filter. SiteGround flagged our traffic
    # for "legacy Chrome signatures" while this read Chrome/140 (a ~2025 release),
    # i.e. the first attempt at this fix escaped the "script" rule only to land in
    # the "outdated browser" rule. Treat a stale string here as a live defect, not
    # cosmetic drift, and re-check it whenever a host starts challenging publishes.
    # Impersonation is confined to this one path on purpose — everything that
    # merely *reads* a client's site identifies itself honestly via
    # `crawler_user_agent` below.
    wordpress_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    )
    # User-Agent for our first-party reads of a client's own site (sitemap
    # discovery, the QA agent's page fetches, the freeze homepage probe, the
    # location-page index). These are crawls, not an admin client, so they say so.
    #
    # The shape matters as much as the honesty: `Mozilla/5.0 (compatible; Foo/1.0)`
    # is the classic generic-scraper signature and managed hosts rule on it
    # directly — SiteGround matched exactly that pattern from our egress IPs, which
    # came from four services each hardcoding their own variant of it. One honest
    # token with a contact URL is both truthful and unmatched by that rule; a host
    # that wants to allow us can key on it, and one that wants to block us can do
    # that too, which is the point of identifying yourself.
    crawler_user_agent: str = "AR-Tools/1.0 (+https://amazingrankings.com/bot)"
    # A fixed header identifying this tool on every request to a client's own
    # WordPress host, so a managed host can scope a bot-filter exemption to us
    # specifically instead of to a shared egress IP. The value is a shared secret
    # agreed with the host: a rule keyed on a guessable header is spoofable by
    # anyone who learns the name, so the exemption is only as narrow as the value
    # is unguessable. Dormant until the value is set (no header is sent), and it
    # is deliberately NOT set at the httpx client level — the publish client also
    # fetches source images from third-party CDNs, and a client-level header
    # would broadcast the secret to every one of them.
    wordpress_publisher_header_name: str = "X-Publisher-Tool"
    wordpress_publisher_header_value: str = ""
    # ---- Interim SSH publish transport -------------------------------------
    # A managed host's WAF can challenge the REST API from our egress IP while
    # leaving SSH untouched (SiteGround's Anti-Bot AI does exactly this). For an
    # affected client, publishing can be routed over SSH + WP-CLI instead, which
    # the filter never sees.
    #
    # Config is env-only and gated to explicit client ids ON PURPOSE. This is an
    # interim measure, so it takes no migration and — more importantly — keeps
    # the SSH private key in the deployment's secret store rather than in the
    # clients table. An SSH key is shell access to the client's hosting account,
    # a categorically larger secret than the application password it stands in
    # for, and it should not sit in a database row alongside ordinary content.
    # If a second client ever needs this, replace it with proper per-client
    # storage rather than widening these.
    wordpress_ssh_client_ids: str = ""     # comma-separated client uuids
    wordpress_ssh_host: str = ""
    wordpress_ssh_port: int = 22
    wordpress_ssh_username: str = ""
    wordpress_ssh_private_key: str = ""    # PEM contents, not a path
    wordpress_ssh_wp_path: str = ""        # WordPress root on the remote host
    # Optional known_hosts line for the target. When empty the host key is not
    # verified — logged as a warning, since it leaves the connection open to a
    # man-in-the-middle who could observe or alter published content.
    wordpress_ssh_known_host: str = ""
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
    # Per-content-type server defaults (used when a client has no inferred pattern
    # and no per-type/single override) so a service/location page doesn't land in
    # the blog collection. github_default_content_path remains the final fallback.
    github_default_content_paths: dict[str, str] = {
        "blog_post": "src/content/blog",
        "service_page": "src/content/services",
        "location_page": "src/content/locations",
        "local_seo_page": "src/content/locations",
        "product": "src/content/shop",
        "ecom_page": "src/content/shop",
    }
    # Existing-site discovery: cap + concurrency for reading content-file frontmatter
    # (to index slug overrides for the duplicate reconcile). Bounded so a large
    # site's discovery stays sane; 0 disables the frontmatter read (path-key
    # reconcile only).
    github_infer_max_frontmatter_reads: int = 300
    github_infer_frontmatter_concurrency: int = 8
    # ── Media pipeline (planner-driven, GitHub/Astro) ────────────────────────
    # The production media pipeline: an LLM media plan (hero + ≤2 inline
    # images/charts) validated + placed + committed by the app. Supersedes the
    # simple blog_image_* path above as it lands. Gated: off unless enabled AND
    # OPENAI_API_KEY set.
    blog_media_enabled: bool = True
    # The media-planning model (proposes the plan; the app validates + owns
    # counts/IDs/placement). Anthropic with the shared fallback.
    blog_media_planner_model: str = "claude-sonnet-4-6"
    blog_media_planner_max_tokens: int = 8000
    # Image rendering — gpt-image-2 (reasoning image model; reads the article),
    # WebP output at configured dimensions.
    blog_media_image_model: str = "gpt-image-2"
    blog_media_image_quality: str = "medium"          # low | medium | high
    blog_media_hero_width: int = 2048
    blog_media_hero_height: int = 1152
    # 1536x1024 — a gpt-image-2-native size. (1200x900 was rejected with 400
    # Bad Request on the first live run; the render ladder's auto-size rung
    # recovered, but a supported default avoids burning retry attempts.)
    blog_media_inline_width: int = 1536
    blog_media_inline_height: int = 1024
    # Allow transparent arithmetic derivations of chart values from explicit
    # article values (Phase 2 charts); false → only values stated verbatim.
    blog_media_allow_derived_values: bool = True
    # When a chart is dropped ONLY because the planner left a value's
    # source_quote blank (missing_source_quote — the data may still be in the
    # article, e.g. inside a table), attempt one targeted re-grounding call that
    # asks the model to supply a verbatim quote per value. The result is
    # re-validated the same way, so this recovers real charts without weakening
    # the no-fabrication rule.
    blog_media_chart_reground_enabled: bool = True
    # When a chart is ultimately rejected, fill its (already-budgeted) inline
    # slot with a section-specific editorial image instead of leaving it empty.
    blog_media_chart_replace_enabled: bool = True
    # Confidence gates (the app drops optional assets below threshold).
    blog_media_hero_min_confidence: float = 0.75
    blog_media_inline_min_confidence: float = 0.75
    blog_media_chart_min_confidence: float = 0.90
    # Repo path the committed media lives under (post slug appended).
    blog_media_repo_path: str = "public/images/blog"
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
    # Google Analytics (GA4) ingestion — Client Reporting Phase 2.
    # DORMANT until (a) the GA4 Data + Admin APIs are enabled on the GCP
    # project the service account lives in and (b) the service account is added
    # as a Viewer on each client's GA4 property. Reuses
    # `google_service_account_key` (with the added analytics.readonly scope) via
    # REST + a minted token (no new dependency). Left off by default so the
    # scheduler pass + ingest are no-ops until access lands. Run
    # `scripts/verify_ga4_api_access.py` to confirm access before flipping this on.
    # See docs/modules/client-reporting-prd-v1_0.md (Phase 2).
    ga4_ingest_enabled: bool = False
    # Each daily run re-pulls the trailing window (GA4 data settles over ~1–2
    # days; idempotent upserts make the overlap harmless and a missed run
    # self-heals on the next pull).
    ga4_repull_days: int = 3
    # The scheduler enqueues one ingest job per verified property once a day,
    # after this hour (UTC), same shared loop as the GSC/GBP ingest.
    ga4_ingest_hour_utc: int = 8
    # One-time historical backfill window (days). GA4 keeps data for the
    # property's retention setting; pull a generous window so the store keeps it.
    ga4_backfill_days: int = 400
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
    # ------------------------------------------------------------------
    # Google Business Profile (GBP) Posts module.
    # Publishes GBP posts ("What's New" / Event / Offer) to a client's Business
    # Profile via Google's v4 localPosts API, reusing the agency service account
    # (business.manage scope) added as a Manager on the client's profile.
    # `gbp_api_enabled` is the shared gate for the GBP *connection* layer (account
    # /location resolution + verify) — flip it on once the verify script is green.
    # `gbp_posts_enabled` gates the Posts feature on top of it. Both default off so
    # the routes + scheduler pass no-op until access lands. GBP-metrics keeps its
    # own `gbp_metrics_enabled` flag independently. See
    # docs/modules/gbp-posts-module-prd-v1_0.md.
    gbp_api_enabled: bool = False
    gbp_posts_enabled: bool = False
    # Anthropic model for AI-drafted post copy (client-facing tone — same family
    # as the other client copy; Haiku rejected for brand-voice fidelity).
    gbp_post_model: str = "claude-sonnet-4-6"
    gbp_post_max_tokens: int = 1024
    # Google caps a localPost summary at 1500 chars; enforce app-side.
    gbp_post_max_chars: int = 1500
    # Append utm_source=gbp&utm_medium=post&utm_campaign=<slug> to CTA links so
    # post→site clicks are attributable (GA4, once connected).
    gbp_post_default_utm: bool = True
    # Bulk "create N posts from a page URL": the page content fed to each draft
    # (chars), and the stagger between the per-post jobs (short — a draft is one
    # fast Claude call, unlike the 180s local-seo page generation).
    gbp_post_source_chars: int = 5000
    gbp_post_bulk_spacing_seconds: int = 5
    gbp_post_max_bulk: int = 99
    # Daily live-state reconciliation (catches async REJECTED + imports external
    # posts). One sync job per client with an ok location, after this hour (UTC).
    gbp_posts_sync_hour_utc: int = 9
    # ------------------------------------------------------------------
    # GBP OAuth (alternative to the service account for the Posts/GBP APIs).
    # Google's Business Profile API is OAuth-first; a bare service account may
    # not be accepted as a listing Manager (unlike GSC). With a Google Workspace
    # agency account we publish an **Internal** OAuth app (no verification, tokens
    # don't expire) and authorize ONCE as the agency account that already manages
    # the client listings — no per-client OAuth, no "add the SA as Manager" step.
    # When these are set, services/gbp_auth mints the API token from the refresh
    # token instead of the service account (service account stays the fallback,
    # and GSC is unaffected). Obtain the refresh token via
    # scripts/get_gbp_refresh_token.py (run once, locally). See the module PRD.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # Optional env fallback for the refresh token (the in-app Connect flow stores
    # it in gbp_oauth_credentials instead; DB wins, env is the fallback).
    gbp_oauth_refresh_token: str = ""
    # Redirect URI for the in-app "Connect Google Business Profile" flow. Must
    # EXACTLY match an authorized redirect URI on the GCP **Web application**
    # OAuth client, e.g. https://<platform-domain>/gbp/oauth/callback.
    google_oauth_redirect_uri: str = ""
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
    # Gradual-drop alert: a slow, sustained multi-week slide the window-over-window
    # rank rules miss (e.g. ~1 spot/week erosion that never accumulates ≥6 spots
    # inside a single 7- or 30-day window). Opens a `gradual_drop` rank alert with
    # the same notification/episode machinery as the sudden drops. The numeric
    # thresholds are module constants in services/rank_alerts.py; this only gates
    # the detector on/off. Set False if it proves noisy.
    rank_gradual_drop_enabled: bool = True
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
    # Default hour-of-day (0-23) a scheduled scan fires at, expressed in the
    # CLIENT'S local timezone. Used when a config's own maps_scan_configs.scan_hour
    # is unset/out-of-range. The scheduler evaluates maps due-ness every cycle so a
    # client fires near this local hour rather than at a single global UTC time.
    maps_scan_hour: int = 8
    # How long (minutes) to keep polling a scan before marking it failed.
    maps_scan_poll_timeout_minutes: int = 30
    # ── Maps geo-grid provider switch (Local Dominator → DataForSEO) ──────────
    # Which provider a NEW scan uses. In-flight/historic scans are routed by
    # their stored maps_scans.provider column, so both coexist across the flip;
    # rollback is flipping this env var back. 'dataforseo' (default) |
    # 'local_dominator' (retired 2026-08-27 — the vendor account lapsed and every
    # scheduled scan on it 500'd for weeks; DataForSEO is now the geo-grid source).
    maps_scan_provider: str = "dataforseo"
    # DataForSEO Maps SERP per-pin params. The zoom in location_coordinate
    # ("lat,lng,<zoom>") sets the simulated viewport WIDTH at each pin, and the
    # viewport must cover the pin→business distance (the grid RADIUS, not the
    # pin spacing) or the client can't appear at outer pins at all: at 15z
    # (~1-mile viewport) a 5-mile grid collapsed to the ~12 pins nearest the
    # business (parallel-run finding, 2026-08-07 — LD found the client on 76–92
    # of 97 pins where DFS found exactly 12). Zoom is therefore derived from
    # each scan's radius_miles (maps_dataforseo.zoom_for_radius, anchored 5 mi
    # ↔ 13z per the LeadOff scanner's calibration); this setting is a manual
    # override — leave empty for auto. depth 20 mirrors LD's top-20/pin and
    # fits DataForSEO's base price.
    maps_dfs_zoom: str = ""
    maps_dfs_depth: int = 20
    # Per polling tick, per DataForSEO scan: cap on task_get calls (oldest pins
    # first) and how many run concurrently. task_get is free — this just paces
    # the collection so one big scan doesn't hog a tick.
    maps_dfs_poll_tasks_per_tick: int = 200
    maps_dfs_poll_concurrency: int = 10
    # A pin task that comes back a DataForSEO error is reposted (fresh task) up
    # to this many attempts, then marked failed (a null hole in the grid).
    maps_dfs_pin_max_attempts: int = 3
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

    # Outreach "Why call?" hook — the loss-framed LLM phrasing pass over the deterministic
    # justification facts (services/outreach_call_hook.py). ONE small call per report, cached per
    # (prospect, snapshot), best-effort with a deterministic fallback, and a hard grounding guard
    # (no invented money / lead-volume numbers). Low volume + cached, so it defaults to Anthropic
    # (no fan-out 429 exposure like the maps report); flip the provider to reuse OpenAI's quota.
    outreach_call_hook_llm_enabled: bool = True
    outreach_call_hook_provider: str = "anthropic"   # anthropic | openai
    outreach_call_hook_model: str = "claude-sonnet-4-6"
    outreach_call_hook_openai_model: str = "gpt-5.4"
    outreach_call_hook_max_tokens: int = 700
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
    # GBP reviews this-period-vs-last-period: fetch the dated review list (one paid
    # Outscraper call per report) to count new reviews per period + surface recent
    # highlights. Off → the report falls back to the review-count snapshot series.
    client_report_gbp_reviews_enabled: bool = True
    client_report_review_fetch_limit: int = 200

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
    # A director-mode strategy covers three channels in sequence and is long by
    # design. At 2000 the Pompano plan was guillotined mid-Maps section — the
    # off-page and AI halves were never written, and the user reasonably read
    # that as "it only does on-page". The truncation handler ("say continue")
    # papered over it.
    slack_assistant_max_tokens: int = 8000
    # Post-turn memory capture. The `remember` TOOL can barely fire in practice:
    # it competes with writing the answer inside the same bounded tool loop, and
    # the round that produces the reply has tool_choice="none". So a cheap second
    # pass reads the finished turn and decides what was worth keeping.
    slack_assistant_memory_enabled: bool = True
    slack_assistant_memory_model: str = "claude-haiku-4-5-20251001"
    slack_assistant_memory_max_notes: int = 2   # per turn
    slack_assistant_memory_min_reply_chars: int = 400  # skip trivial exchanges
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
    # Raised 16k→24k (2026-07-30): at 16k the _ORCHESTRATOR router doc alone
    # consumed most of the block and the SOP that answered the question was
    # truncated away. Grounding is on by default now, so the block has to be
    # big enough to carry a real doc (~+2k tokens/turn).
    # 24k left the last doc in the queue with scraps — AIO_AEO_SOP got 1,973 of
    # its 12,741 chars on a growth turn, i.e. the theory and none of the
    # tactics. Every SOP but the three large ones is under 13k and is meant to
    # arrive whole; this funds that. ~15k tokens per grounded turn.
    # Sized so nothing defers. Measured across growth/drop/links/content/AI
    # questions on both quiet and alerting clients: the heaviest real block is
    # ~74k, and every domain active at once is ~86k. This is a CEILING, not a
    # floor — a turn that needs three docs still sends three docs — so headroom
    # costs nothing on ordinary turns and keeps deferral a genuine safety net.
    # That matters because a deferred doc depends on the model choosing to call
    # read_sop, which is a weaker guarantee than simply sending it.
    slack_assistant_sop_budget_chars: int = 90_000
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
    # Gradual local-pack decline: a slow, sustained slide across many scheduled
    # scans that no single scan-over-scan threshold catches (the local-pack
    # analogue of the organic gradual_drop). Measured over a trailing window on
    # the scan time series (grid-resize-normalized), opens a `gradual_decline`
    # maps alert. Numeric bars are cumulative-over-the-window, deliberately below
    # the per-scan sudden thresholds above. Set enabled False to disable.
    maps_gradual_decline_enabled: bool = True
    maps_gradual_window_days: int = 56      # ~8 weeks of scheduled scans
    maps_gradual_min_points: int = 4        # scan points (per metric) needed to judge a trend
    maps_gradual_rank_drop: float = 3.0     # cumulative avg-grid-rank worsening (spots) to fire
    maps_gradual_top3_drop: float = 15.0    # cumulative Top-3 coverage fall (points) to fire
    maps_gradual_max_scans: int = 60        # ABSOLUTE ceiling on scans loaded (bounds load); the
                                            # operative cap is derived from the window (see _gradual_signals)

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

    # Keyword Research module (the seed-keyword explorer) — per-client keyword
    # ideas from the DataForSEO Labs keyword_ideas endpoint, enriched + clustered.
    # This backs the "Keyword Research" workspace card (replaced the Topic Fanout
    # there; the Fanout remains behind "Create Mass Posts").
    keyword_research_enabled: bool = True
    # Daily ceiling on paid Labs calls for this module (own meter:
    # keyword_research_usage). One billed call per run, so this is generous;
    # 0 disables the guard.
    keyword_research_daily_call_budget: int = 500
    # Max keyword ideas fetched/stored per run (Labs caps at 1000).
    keyword_research_idea_limit: int = 700
    # Max seed keywords accepted per run (Labs caps the ideas seed set at 200).
    keyword_research_max_seeds: int = 20
    # Relevance gate: drop brand-homonym / off-topic drift from the Labs ideas
    # before scoring (only engages for brand+topic seeds; pure-service seeds pass
    # through untouched). Set False to keep every idea Labs returns.
    keyword_research_relevance_filter: bool = True
    # A seed is flagged as "essentially the business name" (advisory warning) when
    # at least this fraction of its tokens are the client's brand tokens.
    keyword_research_brand_seed_ratio: float = 0.6
    # Below this many RAW keyword candidates (unique, before any gate), a run warns
    # that the seeds are too specific for the expansion sources — the niche-seed
    # guidance. Measured on the raw pool, so a big pool trimmed by the gates never
    # trips it. FreightOptics' 3-word "3pl audit software" seeds returned ~16.
    keyword_research_thin_pool_min: int = 25
    # Primary expansion source: keyword_suggestions (phrase-containment — every
    # result contains the seed phrase, so it stays tightly on-topic). One billed
    # call per seed. Set False to use keyword_ideas alone (the old behaviour).
    keyword_research_use_suggestions: bool = True
    # Also fetch keyword_ideas (category-based) as a broadener alongside
    # suggestions, cleaned by the relevance gate before merging. OFF by default:
    # keyword_ideas expands by category, not phrase, so it reliably drifts on
    # entity/branded seeds (e.g. "historic preservation" → "mesopotamia important
    # facts"), and the phrase-containment suggestions alone give a rich, on-topic
    # set. Turn on for extra cross-topic reach at the cost of some noise. When
    # suggestions are off, ideas run regardless (there must be at least one source).
    keyword_research_broaden_with_ideas: bool = True
    # Broaden with related_keywords (Google's "searches related to" graph). ON by
    # default: unlike keyword_ideas it surfaces adjacent terms that don't contain
    # the seed phrase ("historic preservation" → "adaptive reuse") while staying
    # on Google's related graph, so it broadens without the category drift.
    keyword_research_broaden_with_related: bool = True
    # Brand-flood gate on the related_keywords adjacency layer (KR's one ungated
    # broadener). related_keywords can surface a competitor brand or homonym and
    # then flood the run with its namespace — e.g. "third party claims adjuster"
    # pulled a "Mitchell" (claims-software vendor) cluster of ~45 keywords
    # ("mitchell connect", "mitchell prodemand") including homonym skincare
    # ("mitchell usa serum"), ~14% of the whole run. The gate looks only at the
    # SEEDLESS neighbours (those sharing no seed token — legit seed-anchored
    # adjacency like "historic preservation office" is never a candidate) and
    # drops any dominated by a single non-seed token that appears in >= _fraction
    # AND >= _min of them; diverse legit adjacency ("adaptive reuse") has no
    # dominant token and survives. Deliberately conservative (validated on live
    # runs: catches Mitchell 73%/Frontline 76%, leaves lower-concentration topical
    # drift and clean runs untouched). Set False to disable.
    keyword_research_brand_flood_filter: bool = True
    keyword_research_brand_flood_fraction: float = 0.4
    keyword_research_brand_flood_min: int = 8
    # Generic filler-token drift gate on the same related_keywords layer. A
    # multi-word entity seed can carry a bleached filler word that is a huge
    # standalone category — "third PARTY claims administrator" — and the related
    # graph wanders into the filler's own sense ("party" → "party rentals",
    # "birthday party"). Those share the filler SEED token, so the brand-flood
    # gate (non-seed tokens only) and the ≥2-overlap coherence gate (withheld from
    # the trusted related layer) both miss them. This gate drops a related keyword
    # whose ONLY seed overlap is a single filler token, but ONLY when the seed has
    # ≥2 DISTINCTIVE (non-filler) tokens carrying the topic — so a seed genuinely
    # ABOUT the filler ("party rental company", "party planning") is never gated.
    # A filler needs >= _min such solo-overlap keywords to be flagged. Set False
    # to disable.
    keyword_research_generic_drift_filter: bool = True
    keyword_research_generic_drift_min: int = 5
    # related_keywords expansion hops (0 = seed only, 1 = its related searches,
    # 2 = related-of-related; higher = broader but more wander) + per-seed cap.
    keyword_research_related_depth: int = 2
    keyword_research_related_limit: int = 500
    # Max related-search NEIGHBOUR terms (Google's adjacency layer) enriched +
    # merged per run. Bounds the follow-up keyword_overview enrichment to one
    # billed call (≤700 keywords/call). Set 0 to skip neighbour harvesting.
    keyword_research_related_neighbor_cap: int = 700
    # Max phrase-containment suggestions fetched per seed (Labs caps at 1000).
    keyword_research_suggestion_limit: int = 500
    # Max keywords a single "Send to Content Scheduler" handoff turns into
    # scheduled articles (one article per keyword) — bounds the batch a user can
    # queue in one click.
    keyword_research_scheduler_max: int = 100
    # SERP enrichment pass (People Also Ask + competitive intelligence). For the
    # first _serp_max_seeds seeds, one live Google SERP call each yields BOTH the
    # PAA questions (folded into the keyword universe AND surfaced as a list) and
    # the SERP-competitor landscape (top organic domains across the seeds + who's
    # cited in the AI Overview). One paid call per analyzed seed (~$0.002 each),
    # metered against the daily budget. Set False to skip the pass entirely.
    keyword_research_serp_enrichment: bool = True
    keyword_research_serp_depth: int = 20          # SERP depth (top organic + PAA + AIO)
    keyword_research_serp_max_seeds: int = 5       # cap SERP calls (first N seeds only)
    keyword_research_serp_top_competitors: int = 10  # competitor domains surfaced
    # Client-facing keyword research PDF report: the exec-summary LLM (best-effort,
    # Anthropic with OpenAI→Gemini fallback via report_llm; deterministic fallback
    # summary when no key is set).
    keyword_research_report_model: str = "claude-sonnet-4-6"
    keyword_research_report_max_tokens: int = 600
    # Seed/topic suggestions ("give me seeds to start with"): a cheap LLM call
    # (Haiku — categorization only) grounded on the client's business context,
    # with a deterministic GBP-derived fallback when no key is set.
    keyword_research_seed_model: str = "claude-haiku-4-5-20251001"
    keyword_research_seed_max_tokens: int = 400
    # Client-grounded topical research (keyword_research_topics): read the client's
    # site topics + fan out the seed INTENT, so the run researches the client's
    # real topics (not just the literal seed string) and the relevance gate anchors
    # on a rich on-topic set. Master switch + its parts (each best-effort — a
    # missing site/LLM/key degrades to the token gates, never aborts the run).
    keyword_research_topical: bool = True
    keyword_research_site_topics: bool = True          # read the client's site pages for topics
    keyword_research_site_topic_cap: int = 40          # max site topics harvested
    keyword_research_intent_fanout: bool = True        # LLM fan-out of the seed intent
    keyword_research_intent_model: str = "claude-haiku-4-5-20251001"
    keyword_research_intent_max_tokens: int = 500
    keyword_research_intent_max: int = 12              # max sub-intents surfaced/anchored
    keyword_research_intent_expansion_cap: int = 4     # extra expansion seeds fed to suggestions
    # Gemini semantic relevance gate (keyword_research_relevance): score each merged
    # keyword by max cosine similarity to the anchor set (seeds + intents + site
    # topics) and drop those below the floor (phrase-containment keywords are always
    # kept). Best-effort — skipped when GEMINI_API_KEY is unset. The floor is
    # calibrated conservatively for gemini-embedding-2 SEMANTIC_SIMILARITY cosine;
    # every keyword keeps its score (relevance_score) so it's sortable and the floor
    # is tunable from real runs. Set False to disable the semantic layer entirely.
    keyword_research_semantic_relevance: bool = True
    # Calibrated on a live BSA Claims run (2026-08-08): the on-topic core scores
    # ≥ ~0.72, clear junk ("mattress firm warranty claim", "is life extension third
    # party tested") sits below 0.70, and real competitor brands (Crawford ~0.67,
    # Pilot Catastrophe ~0.58) sit in between. Set to 0.62 (owner ruling) to KEEP
    # competitor-brand visibility while still trimming the clearest junk; the
    # biggest drift source (a domain-ambiguous expansion seed) is removed at the
    # source by domain_anchored, so the floor is only a backstop. Raise toward ~0.68
    # for stricter, brand-free results.
    keyword_research_relevance_floor: float = 0.62
    keyword_research_relevance_anchor_cap: int = 60    # bound the embedded anchor set
    keyword_research_embedding_model: str = "gemini-embedding-2"
    # Audience-fit filter (keyword_research_audience): drop keywords that target the
    # WRONG audience for the client's buyer — the universal job-seeker/career guard
    # (salary/jobs/how-to-become/…) plus an ICP-grounded LLM pass that returns the
    # client-specific wrong-audience vocabulary (for a B2B TPA: public-adjuster /
    # licensing / DIY-consumer terms). Relevance ≠ buyer fit: "insurance adjuster
    # salary" is on-topic but targets job-seekers, not the carriers who hire a TPA
    # (55% of a live BSA Claims run). Best-effort — the ICP layer degrades to the
    # universal guard; set _filter False to disable entirely.
    # Navigational + competitor-brand filter (keyword_research_navigational): drop
    # support/lookup keywords ("<brand> phone number", "login", "claim status") and
    # competitor-brand lookups, keeping competitor COMPARISON keywords.
    keyword_research_navigational_filter: bool = True
    keyword_research_competitor_filter: bool = True    # the competitor-brand half
    keyword_research_audience_filter: bool = True
    keyword_research_audience_icp: bool = True         # the ICP-grounded LLM off-audience pass
    keyword_research_audience_model: str = "claude-haiku-4-5-20251001"
    keyword_research_audience_max_tokens: int = 400
    keyword_research_audience_max_terms: int = 30      # cap ICP off-audience terms
    # Blog-topic idea generator (keyword_research_content): on-demand, turns a run's
    # BUYER-FIT keywords + the ICP into blog post ideas (title + angle + target
    # keywords). One LLM call, cached on the run.
    keyword_research_topic_model: str = "claude-sonnet-4-6"
    keyword_research_topic_max_tokens: int = 1500
    keyword_research_topic_count: int = 12             # blog ideas per generation
    keyword_research_topic_keyword_cap: int = 60       # buyer-fit keywords fed to the LLM
    # Problem-first Topic Research (keyword_topic_research): start from the buyer's
    # PROBLEMS (ICP + differentiators + the client's own site themes), validate each
    # theme with real demand (a live SERP → People Also Ask + suggestions), and mine
    # the top competitors' informational keywords → ranked topic cards. Paid calls
    # per run ≈ themes×2 + competitors, budget-metered on the shared keyword_research
    # meter. Distinct from keyword expansion (which researches the seed's variations).
    keyword_topic_model: str = "claude-sonnet-4-6"
    keyword_topic_max_tokens: int = 2000
    keyword_topic_max_themes: int = 8                  # buyer problem-themes per run
    keyword_topic_serp_depth: int = 20                 # SERP depth per theme (PAA + organic)
    keyword_topic_serp_top: int = 10                   # top organic results kept per theme
    keyword_topic_suggestion_limit: int = 200          # suggestions fetched per theme
    keyword_topic_max_competitors: int = 3             # competitor domains mined
    keyword_topic_competitor_kw_limit: int = 300       # ranked keywords pulled per competitor
    keyword_topic_competitor_sample: int = 15          # informational competitor kws kept
    # Strategist-grade Topic Research (keyword_topic_strategist): a bounded tool-use
    # reasoning loop that grounds the plan on the agency content SOPs (Seed Keyword /
    # On-Page Coverage / AEO / Site Architecture) + the client's REAL position (from
    # the shared context providers) and emits a topical-authority plan (pillars →
    # clusters). Falls back to the deterministic topic cards when disabled/unavailable.
    keyword_topic_strategist_enabled: bool = True
    keyword_topic_strategist_max_tokens: int = 8000    # room for a full pillar/cluster plan
    keyword_topic_max_drilldowns: int = 4              # investigation tool calls per run
    keyword_topic_sop_char_budget: int = 16000         # SOP grounding block size
    keyword_topic_context_char_budget: int = 12000     # client-position JSON size

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
    # Recalibrated 0.85->0.87 for gemini-embedding-2 (P99 of cross-silo cosines +
    # margin, over 83 live silo keywords) — cross-silo pairs sit low under the new
    # space so this gate barely shifts. Runs together with the silo backfill.
    silo_dedup_cosine_threshold: float = 0.87
    silo_frequent_threshold: int = 3
    # text-embedding-3-large supports a `dimensions` parameter (1..3072);
    # we use 1536 because pgvector's HNSW index is capped at 2000 dims.
    silo_embedding_dimensions: int = 1536
    # Gemini (suite standardized off OpenAI). Must support outputDimensionality =
    # silo_embedding_dimensions; the silo_candidates column stays vector(1536).
    # Env-overridable — verify the model ID resolves before deploy.
    silo_embedding_model: str = "gemini-embedding-2"

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
    # Structural-fidelity gate on Local SEO page generation. The client's stored
    # reference page structure is injected into the nlp prompt as a "mirror this
    # layout" block, but nothing measured whether the output actually matched it —
    # so the writer drifted on section count/order and dropped blocks (FAQ/table/
    # CTA). When enabled, each generated page is scored against the reference
    # outline with the deterministic structural eval (page_structure_eval); if it
    # drifts on layout below `min_composite`, generation is retried with the
    # specific corrections fed back — keep-best by structural composite, capped at
    # `max_passes`. Only fires when a reference structure actually drove the page;
    # fully best-effort (a scoring/regen failure keeps the best page so far).
    local_seo_structure_gate_enabled: bool = True
    local_seo_structure_min_composite: float = 85.0
    local_seo_structure_max_passes: int = 2
    # Same structural-fidelity gate on Ecommerce PRODUCT generation, scored against
    # the client's scraped page_structures['product'] reference (only when a house
    # template URL is NOT set — the house template is its own explicit mirror).
    # Collections are excluded (no reference structure). Keep-best, capped.
    ecommerce_structure_gate_enabled: bool = True
    ecommerce_structure_min_composite: float = 85.0
    ecommerce_structure_max_passes: int = 2
    # Cache for the ecommerce writer's invariant public-spec research (CAS
    # number, molecular weight, sequence, solubility, …). That research cost
    # $0.372 and 1m24s on a reference reoptimize and re-ran from scratch on every
    # reoptimize of the same product, for values that by definition never change.
    # Keyed globally on a normalized compound name (a CAS number does not depend
    # on who sells it). The TTL is long because it is a re-verification cadence,
    # not an expiry; set to 0 to treat every entry as stale. Empty results are
    # never cached. Lives in platform-api because nlp-api has no database.
    ecommerce_fact_cache_enabled: bool = True
    ecommerce_fact_cache_days: int = 180
    # Structural-fidelity gate on SERVICE / LOCATION pages (the runs pipeline). The
    # reference (page_structures['service'|'location']) is already injected into the
    # brief; this scores the writer's output against it and, when it drifts, folds
    # the corrections into the single auto-reoptimize pass as a synthetic
    # deficiency (no extra reopt beyond the existing content-score budget).
    service_page_structure_gate_enabled: bool = True
    service_page_structure_min_composite: float = 85.0
    # Reference-page scrape: when the cheap (datacenter, no-JS) ScrapeOwl fetch
    # captures 0 content sections — the usual sign a WordPress/CDN bot-wall
    # served an empty shell — retry ONCE with JS rendering + premium residential
    # proxies. Bounded cost (only on an empty first pass); flip off if credits
    # get tight.
    page_structure_premium_fallback: bool = True
    # Bulk background jobs (bulk-create / bulk-reoptimize) enqueue one async_jobs
    # row per item. The single worker claims the OLDEST pending scheduled_at and
    # has no <=now gate, so staggering each bulk item's scheduled_at this many
    # seconds into the future makes a now-dated interactive/scheduled job (and
    # other clients' work) interleave ahead of the rest of the batch — bulk
    # becomes background priority. There's no delay when the queue is otherwise
    # empty (no gate). Keep ≳ a single item's runtime so an interactive job waits
    # behind at most the currently-running bulk item.
    local_seo_bulk_job_spacing_seconds: int = 180
    # WheelHouse IT location/service page poster (client-gated via the per-client
    # clients.wheelhouse_cpt_enabled flag). LLM that fills the 33 ACF fields.
    wheelhouse_provider: str = "anthropic"
    wheelhouse_model: str = "claude-sonnet-4-6"
    # Headroom for 25 fields incl. a 200-word body + several 50–90-word bodies;
    # too low truncates the tool_use JSON and silently drops fields.
    wheelhouse_max_tokens: int = 6000
    # Spacing between per-leaf jobs in a mass (city×service) run — same rationale
    # as local_seo_bulk_job_spacing_seconds (background priority + reaper safety).
    wheelhouse_bulk_job_spacing_seconds: int = 120
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
    content_batch_cost_ecommerce_usd: float = 0.90
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
    # Goal-driven trigger: a campaign goal currently behind/overdue (with a
    # captured baseline) is treated as an active signal, so a quietly slipping
    # goal summons the normal weekly strategist review instead of waiting for
    # the ~monthly opportunity sweep. This is the yardstick the whole strategist
    # stack judges against (priority-0 goal accountability) actually driving the
    # cadence. Adds one campaign_goals scan + a bounded assess_goals per
    # goal-having client to the daily scheduler pass; set False to switch off
    # that added read load. The review itself is still proposes-only + human-
    # approved — this changes WHEN it runs, never what it may do.
    strategist_goal_trigger_enabled: bool = True
    # Input budget per run before drill-downs (spec §2: ≤ ~25k tokens). The
    # digest assembler converts at ~4 chars/token and splits this between the
    # signal digest and the SOP block.
    strategist_digest_budget_tokens: int = 25_000
    # --- SerMaStr monthly plan review → PACE assignment handoff ---
    # A once-a-month strategist run fired `_lead_days` BEFORE monthly task
    # generation (the asana/native month roll on `asana_month_generate_day`).
    # It reviews the client's Recipe Engine monthly task plan + campaign data and
    # proposes ADDITIONS/MODIFICATIONS to next month's plan — advice + proposals
    # only, exactly like every other strategist run. A human approves each
    # proposal in the Action Plan; approval creates the native task AND hands it
    # to PACE, which assigns it to the skilled, eligible, least-loaded member
    # under their weekly cap (asana_push.push_proposal → pm_assign.place_task —
    # already wired). Ships dark; the whole cadence no-ops while this is False.
    strategist_monthly_plan_review_enabled: bool = False
    # Fire this many days before `asana_month_generate_day` so the reviewed +
    # human-approved changes land before next month's tasks are generated.
    strategist_monthly_plan_review_lead_days: int = 3
    # Optional pilot allowlist (comma-separated client ids). Empty = every
    # eligible non-archived retainer client. Set to one id to pilot the cadence
    # on a single client before opening it to the whole book.
    strategist_monthly_plan_review_client_ids: str = ""

    # --- Intervention-outcome loop (services/interventions.py) ---
    # The measurement half of decide+assign: register a goal-linked, in-scope
    # (link-building / reoptimization) proposal or native task, snapshot its
    # target metric's baseline, and at +2w/+6w judge whether the metric moved
    # (worked/partial/no_effect). Report-only in v1 — the strategist reads the
    # per-tactic rollup in its digest and can cite it, but nothing auto-adjusts.
    # Ships dark; every hook + the daily sweep no-op while this is False.
    intervention_tracking_enabled: bool = False

    # --- Autonomous SEO agent (autonomous-seo-agent-plan-v1_0.md) ---
    # Master gate. While False the whole closed loop is dormant — the policy
    # engine + budget governor are libraries, nothing runs autonomously, and
    # behaviour is exactly today's per-action-human-confirm model.
    autonomy_enabled: bool = False
    # The highest per-client tier the executor will ever auto-approve, even if a
    # client is opted higher. v1 ships Tiers 1–2 built; Tier 3 (auto-publish to
    # client sites) is held for a separate decision, so the ceiling is 2.
    autonomy_max_tier: int = 2
    # The executor reuses the strategist's reasoning; a Sonnet-class model.
    autonomy_model: str = "claude-sonnet-4-6"
    # Weekly scheduled loop: the day AFTER the strategist pass (0=Mon..6=Sun) so
    # it acts on a fresh review. Wednesday by default (strategist = Tue).
    autonomy_weekly_weekday: int = 2
    # Per-client content rate ceiling: at most this many content pieces
    # (start_content_run / generate_local_seo_page / reoptimize_page) commissioned
    # autonomously per client per week. Beyond it the executor PROPOSES instead.
    autonomy_max_content_per_week: int = 3
    # Which Recipe Engine figure funds autonomous work: "discretionary" (what a
    # strategy can fund on top of the baseline stack — the honest ceiling) or
    # "deployable" (retainer × margin, gross). Clamped at 0.
    autonomy_budget_source: str = "discretionary"
    # Estimated cost of one autonomously-commissioned Local SEO page generation
    # (a local_seo_generate job: SERP analysis + Claude + scoring). The budget
    # governor reserves this per auto-run, so a low estimate under-gates spend —
    # set it at or above the real per-page cost.
    autonomy_local_seo_cost_usd: float = 1.0
    # Estimated cost of a content candidate that is only PROPOSED (blog/service
    # run or a reoptimize) — display-only in the ledger (proposals never reserve).
    autonomy_content_cost_usd: float = 2.0

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
    # Proactive "staff hours overloaded" daily alert. When False, the scheduler
    # never emits the suite-wide overload notification (Slack/in-app) for either
    # the Asana or native-tasks path — the Workload page's on-demand read is
    # unaffected. Owner turned this off (2026-07-12): overload reporting was
    # noise, not signal.
    workload_overload_alert_enabled: bool = False

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
    # Parallel-period Asana auto-import: once native is the system of record
    # (native_tasks_enabled), the suite no longer writes to Asana, but the team
    # may still create/move tasks directly in Asana while they wean off it. This
    # daily job re-runs the (idempotent, gap-fill) Asana→native importer so those
    # changes flow into the native board automatically instead of needing a
    # manual "Import Asana boards" click. Default True but inert unless it should
    # run: gated on native_tasks_enabled (native is the live board), Asana being
    # configured (token + workspace), AND >=1 client→project mapping — so a fresh
    # environment does nothing, a rollback quiesces it, and it self-retires once
    # the Asana subscription is cancelled (creds removed).
    asana_auto_import_enabled: bool = True
    # Skip the daily import if a completed one ran within this window — robust to
    # the daily scheduler block re-firing across a same-day deploy restart.
    asana_auto_import_interval_hours: int = 20
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
    # Client-facing "content ready" Slack ping (services/content_ready.py):
    # PACE posts one summary message to a client's own channel (falling back to
    # the master PACE channel when none is set) whenever a Blog/Service run,
    # Local SEO page, Ecommerce page, or Website Builder page finishes
    # generating. Independent of native_tasks_enabled/pace_enabled — it only
    # needs the shared notifications pipe (notifications_enabled + Slack
    # creds), which is already live. Default True per owner request
    # 2026-08-29; flip off here if it turns out noisier than wanted.
    content_ready_notifications_enabled: bool = True
    # scan_health: open a board task when a client's scheduled data pulls (maps
    # geo-grid / organic rank) keep failing, so a silent upstream outage becomes
    # owned work PACE tracks (its untriaged/producer/overdue signals pick it up),
    # not just a Slack ping. Auto-closes when the streak recovers.
    task_producer_scan_health_enabled: bool = True

    # ------------------------------------------------------------------
    # Everhour time-tracking integration
    # (docs/modules/everhour-time-tracking-integration-plan-v1_0.md)
    # ------------------------------------------------------------------
    # Staff track time in Everhour (extension / manual entry); it flows
    # ONE-WAY into the suite as actual_hours per native task, per-client, and
    # per-member. Everhour is a satellite time layer, never a task manager —
    # the native `tasks` table stays the source of truth. The only outbound
    # write is a thin metadata-only task mirror (name/assignee), purely to
    # establish the join key a task's logged time reads back against.
    # Absent the key → every feature is skipped-with-a-note, never an error
    # (the GSC / Slack / Asana provisioning pattern).
    everhour_api_key: str = ""     # X-Api-Key header value (per-user key)
    everhour_enabled: bool = False
    # Lets the task-mirror (write) half be turned off independently of the
    # time-pull (read) half — e.g. to validate reads before allowing any
    # outbound writes during rollout. Sub-gate under everhour_enabled.
    everhour_mirror_enabled: bool = True
    # Rolling re-pull window for the daily time-record sync — staff edit past
    # entries in Everhour, so a sync that only looked at "since last run"
    # would miss corrections. Mirrors gsc_ingest's re-pull days.
    everhour_sync_repull_days: int = 14
    # Max time records requested per page from GET /team/time (API max 50000).
    everhour_sync_page_limit: int = 10000
    # Spacing (seconds) between staggered scheduled_at times for the one-time
    # task-mirror backfill's per-task jobs — keeps a large backlog's outbound
    # POSTs well under Everhour's 100-req/10s ceiling (plan §11.7). The daily
    # inline/producer mirror is one task at a time, so it needs no spacing.
    everhour_backfill_spacing_seconds: float = 1.0
    # Phase 4 consumers (Recipe Engine actual-margin + PACE utilization + reads).
    # A loaded fully-burdened hourly cost of delivery. 0.0 = disabled (the
    # default): the actual-margin read then surfaces logged HOURS only and never
    # invents a dollar cost. Set it to compute a measured labor margin
    # (1 − actual_hours × cost / retainer) alongside the target margin.
    everhour_loaded_hourly_cost: float = 0.0
    # Default lookback windows for the read surfaces (both caller-overridable).
    everhour_client_time_window_days: int = 30   # client "Time" card
    everhour_utilization_window_days: int = 7     # PACE per-member utilization

    # Deliverables Sheet Sync (docs/modules/deliverables-sheet-sync-prd-v1_0.md)
    # — auto-maintain each client's Google deliverables sheet: append a row on
    # task Complete, watch the client-facing Notes column. Master gate default
    # OFF; per-client enablement is implicit (a client with no
    # deliverables_sheet_id is skipped). Uses the shared service-account key
    # with the Sheets/Drive scopes (additive — the GSC credential is unchanged).
    deliverables_sheet_enabled: bool = False
    deliverables_write_enabled: bool = True          # the task-Complete append hook
    deliverables_notes_watch_enabled: bool = True    # the Notes-column poller
    deliverables_notes_scan_interval_minutes: int = 15
    # Auto-provisioning (PRD §5.5): Drive files.copy of the master template at
    # client creation. Needs both ids set; the template must be a NATIVE Google
    # Sheet living in the agency Shared Drive (where the service account is a
    # member, so copies are instantly writable — no per-client sharing).
    deliverables_provision_enabled: bool = True
    deliverables_template_sheet_id: str = ""
    deliverables_drive_folder_id: str = ""           # Shared-Drive folder the copies land in

    # QA Agent (docs/modules/qa-agent-plan-v1_0.md; grounding standard
    # docs/sops/QA_Checklists.md). Deterministic-first reviewer of task
    # deliverables, triggered on entry into the In QA status (the plan's
    # 'for_qa' was superseded — in_qa already existed in the live workflow).
    # qa_enabled gates the AUTOMATIC status trigger only; the on-demand
    # POST /tasks/{id}/qa endpoint works regardless.
    qa_enabled: bool = False                     # QA_ENABLED — master gate
    qa_trigger_status: str = "in_qa"             # status key that enqueues a review
    # Where a passing task goes. Empty = stay in In QA (verdict on the activity
    # feed; the human sends + drags — moving to sent_to_client ourselves would
    # claim a send that hasn't happened). Set to 'sent_to_client' to auto-advance.
    qa_pass_status: str = ""
    qa_fail_status: str = "in_progress"          # bounce target on a failed review
    qa_fail_creates_subtasks: bool = True        # rework checklist from failed checks
    qa_notify_on_pass: bool = False              # silent clean passes
    qa_citation_sample: int = 3                  # QA_Checklists §Citations sample size
    qa_fetch_timeout_seconds: float = 20.0
    qa_max_urls_per_review: int = 5              # cap external fetches per review
    # Map-embed assertion sentence judge (the one LLM call in QA; owner ruling:
    # plain-English + grammatically correct → an LLM read, kept on cheap Haiku).
    qa_assertion_model: str = "claude-haiku-4-5-20251001"
    # Structural design-fit floor for posted pages (page_structure_eval
    # composite). Below it the check reads needs_human — page-type attribution
    # is heuristic, so QA flags rather than auto-bounces on structure alone.
    qa_structural_threshold: float = 70.0
    # Flap guard: an automatic re-trigger within this window of a PASSED
    # review is skipped (drag-out-drag-back must not re-pay the review).
    # Pass-only — fail re-entry is the rework loop, needs_human re-entry is
    # the recovery path. Manual Run QA always bypasses. 0 disables.
    qa_recheck_cooldown_minutes: int = 30
    # Phase 3: SOP-grounded narrative for FAIL / NEEDS_HUMAN reviews — one
    # cheap Haiku call that phrases the deterministic findings with
    # QA_Checklists / On-Page-Criteria citations. NEVER changes the verdict;
    # any failure falls back to the deterministic narrative. Pass reviews
    # skip it (nothing to explain).
    qa_narrative_enabled: bool = True
    qa_narrative_model: str = "claude-haiku-4-5-20251001"
    qa_narrative_max_tokens: int = 500
    # Must fit BOTH grounding docs whole (QA_Checklists ~9.4k + On-Page
    # Criteria ~5.8k + headers): an 8k budget served only a truncated
    # QA_Checklists and never On-Page (adversarial review 2026-07-12).
    qa_sop_budget_chars: int = 16000
    # Phase 4: producer auto-queue — a completed content run's "Review &
    # publish" task is moved straight to In QA so generated content is QA'd
    # before a human touches it. Rides the content_run producer (both its
    # gates apply) AND qa_enabled.
    qa_autoqueue_producers: bool = False
    # Visual design-fit for posted pages (the checklist's "later phase", now
    # built): DataForSEO page_screenshot (fractions of a cent; no Chromium in
    # the image) + a Claude vision judge. Only HIGH-confidence breakage
    # bounces; low confidence / capture failure is fail-open needs_human.
    # The free asset-integrity layer (404'd CSS/images) always runs.
    qa_visual_enabled: bool = True
    qa_visual_model: str = "claude-haiku-4-5-20251001"
    qa_visual_max_tokens: int = 400
    qa_asset_check_cap: int = 12                 # HEAD checks per page review
    # Cost gate: skip the (paid) screenshot + vision call when the FREE
    # deterministic layers already say the render is fine — every checked asset
    # (CSS + images) loads AND structural fidelity is comfortably above the
    # floor (>= qa_structural_threshold + qa_visual_skip_structural_margin). A
    # dead asset, a weak/missing structure score, or the margin not cleared all
    # keep the screenshot. Default-safe: only skips on two strong clean signals.
    qa_visual_skip_when_clean: bool = True
    qa_visual_skip_structural_margin: float = 10.0
    # QA chat persona (the dedicated /qa sidebar surface — the reviewer sibling
    # of SerMaStr's /assistant and PACE's /pace). Its own master gate so the
    # chat can ship dark independently of the automatic in_qa trigger
    # (qa_enabled). Sonnet + a wide budget for the same reason PACE is: a real
    # reviewer that enumerates recent verdicts and reasons about the board, not
    # a cheap model that collapses lists into counts. Reuses ANTHROPIC_API_KEY.
    qa_chat_enabled: bool = False                # QA_CHAT_ENABLED — sidebar gate
    qa_chat_model: str = "claude-sonnet-4-6"
    qa_chat_max_tokens: int = 2400
    # Default rubric for a bare-URL QA (no task on the board) — the "QA this
    # page" case. website_page is the common ask; the chat lets the user name
    # another URL rubric (guest post / press release / citation / map embed).
    qa_url_default_rubric: str = "website_page"

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
    # Cap per-bucket (Overdue/Due today/This week) lines in the pushed personal
    # morning brief DM before "…and N more" — generous, since chat.postMessage
    # comfortably supports far longer text than a handful of task lines.
    pace_brief_max_lines_per_bucket: int = 25
    # Suppress the daily digest on weekends (Sat/Sun) — VA-facing, workdays only.
    pace_digest_weekday_only: bool = True
    # Quiet the shared PACE channel (owner ruling 2026-09-01): the per-event task
    # alerts (task_assigned / task_mention / task_comment / task_nudge) used to post
    # one message each into the master #pace channel, flooding it. When True they are
    # instead delivered to the concerned person's DM AND the client's own Slack
    # channel where one is configured — never the shared #pace channel — so #pace
    # stays a portfolio-summary surface (the daily digest, Chase Plan, escalations).
    # In-app bells + the client feed always carry them regardless. Set False to
    # restore the previous shared-channel behaviour without a code change.
    pace_quiet_task_alerts: bool = True
    # Permission matrix — the two "via policy" cells (PRD §3.2). Defaults:
    # any internal user can read a board (internal-tool norm); month generation
    # is admin-only (loosen to "staff" to let leads generate).
    pace_perm_read_board_min_role: str = "team_member"
    pace_perm_generate_month_min_role: str = "admin"
    # PACE persona (Phase 3) — a real conversational PM: Sonnet (owner ruling
    # 2026-07-16) so it enumerates tasks + reasons about the board like a PM,
    # not a cheap model that collapses lists into counts. Larger budget so it can
    # actually list the overdue/stuck rows across a client, a member, or the
    # whole agency rather than summarizing them.
    pace_model: str = "claude-sonnet-4-6"
    # 2400 was too tight for "ALWAYS ENUMERATE" — a member/portfolio-scope answer
    # listing ~10 overdue/stuck tasks with client+assignee+due-date+proposed lever
    # per line routinely ran past it and cut off mid-sentence (2026-08-28 report).
    pace_max_tokens: int = 6000
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
    # Separate PACE Slack app (owner ruling 2026-08-28) — give PACE its own bot
    # identity so its posts/replies don't come from SerMaStr. Empty ⇒ PACE shares
    # the SerMaStr bot (byte-for-byte unchanged). When BOTH are set, PACE posts
    # (digest / chase plan / escalations / task_* notifications / nudges /
    # conversational replies) go out under pace_slack_bot_token, inbound
    # PACE-channel events arrive on /slack/pace/events verified with
    # pace_slack_signing_secret, and the SerMaStr app stays out of the PACE
    # channel entirely (the dedicated app owns it). Setup: create a second Slack
    # app, add it to pace_slack_channel, point its Event Request URL at
    # /slack/pace/events, then set these two vars.
    pace_slack_bot_token: str = ""       # PACE_SLACK_BOT_TOKEN — the PACE app's xoxb- bot token
    pace_slack_signing_secret: str = ""  # PACE_SLACK_SIGNING_SECRET — the PACE app's signing secret
    # PACE nudge delivery: DM the assignee directly (chat.postMessage to their
    # slack_user_id — needs the Slack app's `im:write` scope) instead of an
    # @mention in the shared channel. Graceful: an unlinked assignee or a missing
    # scope falls back to the channel @mention (then to in-app only), so this is
    # safe to leave on before the scope is granted — it self-heals on grant.
    pace_nudge_via_dm: bool = True
    # PACE v1.4 — initiative (§4.8–§4.13). Master gate for the Chase Plan engine,
    # follow-through episodes, triage, rebalancing, slip forecasting, DM briefs.
    pace_initiative_enabled: bool = False
    # Per-action-kind autonomy: "propose" (default — every actionable write rides
    # the confirm-gated Chase Plan) | "auto" (execute at plan build, reported as
    # done). All-propose in v1.4 by owner ruling; graduating a kind is a config
    # flip, not a rebuild.
    pace_autonomy: dict = {}
    # Chase Plan cap (overflow summarized, priority-ranked first).
    pace_chase_max_items: int = 10
    # Aggressive cadence (owner ruling): re-propose daily while stuck; escalate
    # publicly after N business days without movement.
    pace_chase_renudge_days: int = 1
    pace_chase_escalate_business_days: int = 3
    # Slip-forecast look-ahead window (§4.12).
    pace_slip_horizon_days: int = 5
    # --- Proactive Interventions (docs/modules/pace-proactive-interventions-plan-v1_0.md) ---
    # The managerial layer: PACE scans for SYSTEMIC delivery problems and opens a
    # durable intervention (problem + fix plan) the PM dispositions four ways.
    # Ships dark — needs pace_enabled + pace_initiative_enabled + this flag.
    pace_interventions_enabled: bool = False
    # Who may approve/deny/defer an intervention (execution re-authorizes each
    # action through the PACE_ACTIONS matrix on top of this).
    pace_intervention_decider_min_role: str = "admin"
    # Cap on actions surfaced/executed per intervention (overflow re-proposes).
    pace_intervention_max_actions: int = 25
    # member_overload: fire when a member's open-hours ≥ pct × cap; critical ≥ pct.
    pace_intervention_overload_pct: float = 1.5
    pace_intervention_overload_critical_pct: float = 2.0
    # duplicate_names: min group size to count as a collision; the client's total
    # colliding count at which the intervention is critical.
    pace_intervention_dupe_min_group: int = 2
    pace_intervention_dupe_critical_count: int = 10
    # Aggregate thresholds for the three reused detectors (a cluster, not a chore).
    pace_intervention_untriaged_min: int = 8
    pace_intervention_overdue_min: int = 5
    pace_intervention_slip_min: int = 3
    # A denied signature isn't re-proposed for this many days (a deny is
    # time-bounded, not forever-silent); an executed one waits this long before
    # re-proposing (lets the fix take effect / metrics recompute).
    pace_intervention_deny_cooldown_days: int = 14
    pace_intervention_reexecute_cooldown_days: int = 3
    # LLM that parses free-text approve-with-conditions into a structured directive
    # (applied deterministically). Reuses the PACE model by default.
    pace_intervention_conditions_model: str = "claude-sonnet-4-6"
    # Min minutes between the per-tick SEVERE scans (the scheduler ticks every
    # gsc_scheduler_poll_interval_seconds, so this throttles the full-board scan
    # a severe pass does). Lower → nearer-immediate severe detection, more DB
    # load; 0 → run every tick.
    pace_intervention_severe_min_interval_minutes: int = 15
    # Weekly intervention rollup to the PACE channel — open interventions + this
    # week's decisions/outcomes. Fires on this weekday (Mon=0 … Fri=4) at the
    # scheduler hour; suppressed on a totally-quiet week (nothing open, no
    # activity). Gated on the interventions feature being enabled.
    pace_intervention_report_enabled: bool = True
    pace_intervention_report_weekday: int = 4  # Friday
    # Per-person morning DM briefs (§4.13) — off until the Slack app has the
    # im:write scope (grant + reinstall, then flip this on).
    pace_daily_brief_push: bool = False
    # Weekly Pulse — the copy-paste client update block on each client
    # workspace ("done last week / on tap this week"). Deterministic, free,
    # staff-delivered (never auto-sent). Categories in the itemize list appear
    # as individual task names; everything else is summarized as counts (the
    # owner's category-filter ruling — link-building detail stays internal).
    pulse_enabled: bool = True
    pulse_weekday: int = 0                # Monday: last week closed, this week ahead
    pulse_itemize_categories: List[str] = ["content", "gbp_authority"]
    pulse_retention_days: int = 14        # owner ruling: deleted after 2 weeks
    # Narrative mode (owner request): a short LLM pass turns the deterministic,
    # category-filtered facts into a warm client email — what we did AND WHY,
    # what's next and why, closing with a questions invitation. Grounded: the
    # model only sees the already-filtered items, so it can't leak internal
    # detail or invent results. Falls back to the bullet format on any failure.
    pulse_narrative_enabled: bool = True
    pulse_model: str = "claude-sonnet-4-6"
    pulse_max_tokens: int = 700

    # --- LeadOff (market intelligence; docs/modules/leadoff-prd-v1_0.md) ---
    # Read-only v1 serves the precomputed market_scanner.leadoff_board.
    # Board queries pre-rank on the stored sort column and fetch this many rows
    # before exact re-sorting under non-default capture/lead-tier assumptions.
    leadoff_prefetch_rows: int = 1500
    # Paid actions (PRD §5 item 1): per-user daily budget across tryout
    # (~$0.20/run) + scout (~$0.10–1/market, cache-cheapened). Every enqueue
    # records its estimate to leadoff_spend; the guard sums today's UTC rows.
    leadoff_daily_budget_usd: float = 5.0
    # Calibration surface Phase 0 (leadoff-calibration-plan-v1_0.md):
    # prediction capture at create-client + the monthly outcome-check sweep
    # (DB reads only, $0). Read-only instrumentation — never touches scoring.
    leadoff_calibration_enabled: bool = True
    # Building-permits prospect pipeline (leadoff-permits-plan-v1_0.md):
    # app-side BPS flat-file pull (keyless, $0) into public.city_permits,
    # joined onto board/brief reads. Context column only — never a grade
    # input. Refresh check is cheap; the vintage only changes ~annually.
    leadoff_permits_enabled: bool = True
    leadoff_permits_refresh_days: int = 30
    # Proximity signal (leadoff-proximity-plan-v1_0.md): the leadoff_geocode
    # job turns imported competitor addresses into coordinates. Census
    # geocoding of addressed rows is free; the Outscraper fill for
    # service-area businesses (blank address) is PAID, so off by default —
    # flip only after the free ~88% version validates the signal.
    leadoff_geocode_sab_outscraper: bool = False
    # Proximity octant read (plan §2) over the geocoded pins: analysis radius
    # around the city centre (strays beyond it are geocode noise), the
    # thin-data floor (no verdict off a handful of pins — same discipline as
    # the field-momentum floor), and the underserved cut (defense below this
    # fraction of the market median = weak octant).
    leadoff_proximity_radius_miles: float = 10.0
    leadoff_proximity_min_pins: int = 5
    leadoff_proximity_weak_frac: float = 0.25
    # Agency cost-to-win ROI (leadoff_roi.py, owner ruling 2026-08-28) — replaces
    # the mislabelled "$/mo per review" with expected value vs. what the agency
    # pays to win + hold the ranking. Unit costs are sourced from the Recipe
    # Engine SOP catalog (content page price is imported from there directly);
    # these are the tunable market-selection assumptions. All are forecasts that
    # sharpen post-scout (real RD gap) / post-client (real retainer).
    leadoff_roi_enabled: bool = True
    leadoff_roi_cost_per_review: float = 10.0   # loaded labour to earn one review
    leadoff_roi_cost_per_link: float = 30.0     # blended per-RD cost (DAS $10 … niche edit $75)
    leadoff_roi_content_pages: float = 4.0      # pages assumed to rank a market
    # Monthly maintenance is a SLIDING SCALE, not a flat number: holding rank in
    # a brutal field costs more per month (more links/content to defend) than in
    # a soft one. Slides on the same field-difficulty signal as the ramp
    # (Beatability / win-likelihood) between these bounds.
    leadoff_roi_maint_min_month: float = 135.0  # softest field (≈ Recipe Engine Baseline Stack)
    leadoff_roi_maint_max_month: float = 600.0  # brutal field (heavier defensive spend)
    # The FIRST month costs this multiple of the normal monthly spend — the
    # client needs the site set up, initial citations submitted, GBP configured,
    # etc., which later months don't. The surcharge = (mult − 1) × that market's
    # (sliding) monthly maintenance, added to the one-time cost to win.
    leadoff_roi_first_month_multiplier: float = 2.0
    leadoff_roi_rd_target_mult: float = 1.0     # RD-to-win = competitor field median true RD × this
    # Ramp-to-rank: SEO doesn't rank instantly — you pay the monthly spend for
    # months of ramp BEFORE the ranking (and its value) arrive, and that sunk
    # ramp cost is what makes payback realistic. The ramp is NOT fixed — it's
    # derived per market from field difficulty (Beatability, or win-likelihood
    # when absent): a soft field ranks near the floor, a brutal one near the
    # ceiling. And because the incumbents are usually still doing SEO, an
    # actively-growing field (review-velocity momentum, scouted markets) extends
    # the ramp — you're chasing a moving target.
    leadoff_roi_ramp_min_months: float = 3.0     # softest field
    leadoff_roi_ramp_max_months: float = 9.0     # brutal field
    leadoff_roi_ramp_accel_mult: float = 1.35    # field accelerating → longer (chasing a moving target)
    leadoff_roi_ramp_cooling_mult: float = 1.05  # field cooling/dead → still growing a little
    # Gap-grows-during-the-ramp: while you spend the ramp closing the review/RD
    # gap, the incumbents keep building, so the EFFECTIVE gap (and its cost) is
    # larger than the static snapshot. Reviews use the field's MEASURED velocity
    # on scouted markets (field_vel30 / vel_matched ≈ the #3's monthly review
    # gain), falling back to this flat default board-wide. RD has no growth-rate
    # data pre-client, so it uses a flat %-per-month assumption applied to the
    # scouted RD gap only. Both grow over the ramp horizon. Note: this compounds
    # with the momentum ramp-extension (an active field is worse on both time and
    # quantity) — deliberate (owner ruling 2026-08-28, Option B).
    leadoff_roi_gap_growth_enabled: bool = True
    leadoff_roi_field_review_growth: float = 2.0     # board-wide default reviews/mo the field adds
    leadoff_roi_rd_growth_pct_month: float = 0.055   # RD gap grows this fraction per ramp month
    # GBP Placement Advisor (leadoff-gbp-placement-plan-v1_0.md §10): the
    # demand-aware "where should the GBP live" read. Free core = the Census
    # ACS block-group demand surface (census_demand.py, $0) ÷ the live
    # competitor-GBP pressure field, scored on the same 1-mile lattice as the
    # geo-grid and computed on read by leadoff_placement.py. Advice/display
    # only — NEVER a grade input (grade safety, plan §7).
    leadoff_placement_enabled: bool = True
    placement_analysis_radius_miles: float = 10.0   # the candidate lattice extent
    placement_demand_decay_miles: float = 5.0       # D_DEMAND — customers travel far
    placement_pressure_decay_miles: float = 2.0     # D_DECAY — locked to proximity's
    placement_zone_count: int = 4                   # top zones surfaced
    placement_min_separation_miles: float = 2.0     # neighborhood-sized, not clumped
    # Coverage-greedy zone selection: each chosen pin CLAIMS the demand within its
    # catchment, so later pins are scored on the REMAINING (uncovered) demand and
    # spread to distinct demand pockets instead of clustering in the metro's peak
    # (a Manhattan pin can't rank in Queens). `_coverage_radius_miles` = how far a
    # GBP realistically ranks/serves (the demand it owns); smaller → more distinct
    # pins per metro. Off ⇒ the legacy top-N + min-separation selection.
    placement_coverage_greedy: bool = True
    placement_coverage_radius_miles: float = 3.0
    # Target-area focus: when the user picks a spot to serve (a dropped map pin /
    # pasted address), rank the zones WITHIN this radius of it — "best spot to
    # serve Queens" instead of the citywide demand peak (a GBP only ranks near
    # its pin). Default radius when the request doesn't specify one.
    placement_target_radius_miles: float = 5.0
    placement_min_pins: int = 5                     # thin-data floor (== proximity)
    placement_min_blockgroups: int = 8              # below this the advisor declines
    # w_cat demand weights on the same free Census pull — ships ON but weight-0
    # until the calibration loop (plan §8) earns them; 0 → pure households.
    placement_income_weight: float = 0.0
    placement_housing_age_weight: float = 0.0
    # Phase 3 opt-in paid ZIP-volume layer (gated on the §4.3.2 feasibility
    # probe passing) — off until then; a scan is "inconclusive" when more than
    # this share of ZIPs return null volume (Google thresholds small geos).
    leadoff_zip_demand_enabled: bool = False
    placement_zip_null_share_inconclusive: float = 0.6
    # Phase 0b feasibility probe (services/leadoff_zip_demand.py): a ~$0.05
    # DataForSEO check on a known high-volume market (default Chicago ZIPs,
    # "plumber") confirming per-ZIP volumes come back non-null before Phase 3 is
    # built. Prefix is a leading ZIP substring ('606' = Chicago, '900' = LA).
    leadoff_zip_probe_keyword: str = "plumber"
    leadoff_zip_probe_zip_prefix: str = "606"
    leadoff_zip_probe_count: int = 10
    # Score enrichment (owner ruling 2026-07-12): today's context signals are
    # promoted to grade inputs as bounded, config-weighted multipliers on the
    # winnability (rankability) and demand pillars. Deliberately conservative
    # priors — no single signal flips a grade; the calibration loop tunes these
    # from real outcomes. Absent signals contribute 0. See leadoff_scoring.py.
    leadoff_scoring_enabled: bool = True
    leadoff_score_w_proximity: float = 0.10   # undefended zones → easier
    leadoff_score_w_site: float = 0.08        # big incumbent sites → harder
    leadoff_score_w_brand: float = 0.08       # strong incumbent brands → harder
    leadoff_score_w_permit: float = 0.06      # housing pipeline → more demand
    leadoff_score_w_seasonal: float = 0.05    # same-month YoY demand direction
    leadoff_score_w_peer_cohort: float = 0.07  # field weak/strong vs comparable
    #                                            (size + income) cities → easier/harder
    # Market-signal cache (score-enrichment increment 2): the board reads
    # precomputed proximity + footprint pressure from leadoff_market_signals;
    # the refresh job self-gates, re-running when the cache is older than this.
    leadoff_signal_refresh_days: int = 7
    # Household-income backfill (peer-cohort field-strength input): per-city
    # median household income from the free Census ACS 5-year API (table
    # B19013). One value per city, refreshed ~annually; the peer-cohort signal
    # compares each market's field against comparable-size, comparable-income
    # cities. See services/leadoff_income.py + services/leadoff_peer_cohort.py.
    leadoff_income_enabled: bool = True
    # --- Outreach pipeline (the Outreacher project) --------------------------
    # A SEPARATE Supabase PROJECT, not a second schema — the difference from
    # LeadOff's market_scanner client. The pipeline's storage projection is
    # ~64M grid_result rows/year, which would eat this project's headroom, so
    # the DATA lives apart; the API lives here so staff authenticate against
    # the suite once and never need an Outreacher account (outreach/HANDOFF.md
    # §2). Same variable names the outreach Railway job already uses, carrying
    # the same values. Absent them every /outreach route answers 503
    # outreach_not_configured rather than failing inside a query.
    outreach_supabase_url: str = ""
    outreach_supabase_service_role_key: str = ""
    # Kill switch independent of the credentials, so the module can be taken
    # off the suite without unsetting keys the Railway job also needs.
    outreach_enabled: bool = True

    # --- Any-city onboarding: geo enumeration of a typed city's sub-areas -------
    # A scan targets a submarket (a city sub-area) with a fixed 81-point grid. To
    # let an operator type ANY city instead of picking a pre-seeded one, the suite
    # resolves the city (Google geocoding), enumerates its real sub-areas from
    # OpenStreetMap (`place=<type>` nodes via Overpass — Google has no
    # "list a city's neighbourhoods" endpoint), then keeps only those Google
    # geocoding VERIFIES as inside the city. Same pipeline the Local SEO
    # neighbourhood silo rides; these knobs are outreach-scoped so tuning one
    # tool never moves the other.
    outreach_subarea_place_types: str = "suburb,neighbourhood,quarter,city_district,borough"
    # Overpass search radius (km) around the city centre — only used as a fallback
    # when the city's geocoded bounding box is unavailable (rare); normally the
    # box drives containment.
    outreach_subarea_radius_km: float = 20.0
    # Cap OSM candidates BEFORE Google verification, so a huge metro can't fan out
    # into hundreds of paid geocode calls in one enumeration.
    outreach_subarea_max_candidates: int = 60
    # Final cap on sub-areas returned to the picker.
    outreach_subarea_max_results: int = 60
    # Bounds padding (fraction of the box span) for the inside-the-city test —
    # slack for a sub-area sitting right on the city edge.
    outreach_subarea_bounds_pad: float = 0.15

    # Geometry for the rows the any-city "City + Business type" form creates. The
    # market row's radius is a rough metro extent (used only for that row); the
    # sub-area's SCAN grid is 5-mile / 1-mile — the pinned 81-point grid the
    # geometry generator produces. Grid geometry is immutable once scanned, so a
    # repeat pick of the same sub-area reuses the existing submarket, never a new
    # one with a drifted centre.
    outreach_onboard_market_radius_miles: float = 25.0
    outreach_onboard_grid_radius_miles: float = 5.0
    outreach_onboard_grid_spacing_miles: float = 1.0

    # --- Call-hook justification (the caller's "why this is a lead" talking points) ------------
    # The per-prospect phone-call hook (outreach PRD §716; HANDOFF §12 item 1) — deterministic
    # talking points assembled from scan data a caller reads before dialing. Read-only; spends
    # nothing. `pack_size` is the Google map-pack depth used to decide "who is beating you here"
    # (the pack is 3 spots); `max_competitors` caps how many rivals the hook names; the review
    # comparison is withheld unless at least `field_review_min_sample` businesses in the submarket
    # have a known review count, so a thin sample never invents a field median to pitch against.
    outreach_call_hook_pack_size: int = 3
    outreach_justification_max_competitors: int = 3
    outreach_field_review_min_sample: int = 5
    # White-label name in the footer of the client-facing report PDF (increment 4). Mirrors the
    # suite's client_report_agency_name; a prospect-facing asset should carry the agency's name.
    outreach_report_agency_name: str = "Amazing Rankings"
    # The approved client-facing PDF is stored in the private `outreach-reports` bucket and delivered
    # as a signed URL (reporting-layer-spec §5) so a client gets a link, not an emailed file. Default
    # 90 days per the spec; the URL is re-signable from the stored path without re-approving.
    outreach_report_bucket: str = "outreach-reports"
    outreach_report_url_ttl_days: int = 90
    # Paid-placement: how much of the area a business must be MISSING from before "paying and
    # losing" is a fair thing to say about it. Config rather than a literal because it decides
    # whether a prospect-facing sentence is made at all — a threshold buried in a function body is
    # one nobody can find when a pitch reads wrong (the same complaint as land_mask_null_scans).
    outreach_paying_losing_deficit_pct: float = 50.0

    # --- Emit (Phase 3 — the optional outbound-queue webhook; outreach PRD §C) ------------------
    # Emit posts an AUDIT-READY QUEUE (not generated assets) as plain JSON to whatever URL is set
    # here — any HTTP receiver (Zapier, Make, a custom endpoint, ...). The PRD named n8n / Encharge
    # only as EXAMPLES of a downstream sender; nothing depends on them. LEAVE EMPTY if you have no
    # automated sender: emit still writes the lead + outcome (the non-backfillable substrate) and
    # reports delivered=false, and logging a call (the `touch` path) captures outcomes with no
    # webhook at all — that is the primary capture path for a manual phone workflow.
    outreach_emit_webhook_url: str = ""
    # Optional bearer token sent as `Authorization: Bearer <token>` when the webhook needs one.
    outreach_emit_webhook_token: str = ""
    outreach_emit_webhook_timeout_s: float = 10.0
    # The outcome's modelling metadata, stamped at emit / first-touch. Config, never hardcoded
    # (scoring-spec §10 — zero hardcoded params). `sequence_version` is the Phase-6 confounder stamp;
    # `touches_per_sequence` is the planned sequence length recorded at send (DECISIONS — 5).
    outreach_sequence_version: str = "phone_v1"
    outreach_touches_per_sequence: int = 5
    outreach_emit_channel_default: str = "phone"
    # Pre-Phase-4 default selection_reason (scoring-spec §7; ISSUES I-102). 'manual' because a
    # hand-picked pre-model contact is neither a Thompson draw nor the random-control hold-out —
    # labelling it 'random_control' would poison the baseline that bucket exists to measure.
    outreach_default_selection_reason: str = "manual"

    # --- Lead enrichment (contact names / phones / emails) --------------------------------------
    # The PLACEMENT side of the spend gate: platform-api writes a signed `enrichment_request` order
    # (it never spends — the outreach `tick` drains it) and enforces the per-user daily budget here,
    # mirroring LeadOff's leadoff_spend guard but using the order rows themselves as the ledger. The
    # cost rate drives the free preflight estimate + the budget check; keep it in sync with the
    # outreach job's enrich_cost_per_place_cents (that one drives the drain's cost_ledger write).
    outreach_enrich_cost_per_place_cents: int = 5
    # Per-user daily enrichment ceiling (USD). Enforced against the sum of a user's orders placed
    # today. Set from the real Outscraper plan before a production run (I-022 — the guard is exactly
    # as honest as the rate above).
    outreach_enrich_daily_budget_usd: float = 10.0
    # The enricher set frozen onto each order at placement. The correct slug is `leads_n_contacts`
    # (Outscraper's "Leads & Contacts" enricher) — confirmed 2026-08-26 from a real dashboard export and
    # validated live: it returns the full contact shape (emails / phones / socials / domain + the
    # decision-maker person fields where Outscraper has them). The earlier `domains_service` (+
    # validators) was the wrong enricher and returned no contacts on our calls — five LA plumbers that
    # were email-null under it returned real emails under `leads_n_contacts`. Kept as a comma-joined
    # string; overridable by one env var. Must stay in sync with outreach api `enrich_enrichments`.
    outreach_enrich_enrichments: str = "leads_n_contacts"
    # A selection larger than this is refused at placement (the drain enforces the same cap). A bigger
    # "select all" is split into several orders by the UI.
    outreach_enrich_max_places_per_order: int = 200

    # --- Enigma card revenue (per-prospect 1m/3m/12m card_revenue_amount) -----------------------
    # The PLACEMENT side of the Enigma card-revenue rung (the proven half). platform-api writes a signed
    # `enigma_request` order (it never spends — the outreach `tick` drains it, billing one Enigma
    # `search` per prospect) and enforces the per-user daily budget here, same shape as enrichment. The
    # cost rate drives the free preflight estimate + the budget check; keep it in sync with the outreach
    # job's enigma_cost_per_lookup_cents (that one drives the drain's cost_ledger write). Placeholder
    # until the probe's real bill lands (I-022 — the guard is only as honest as this number).
    outreach_enigma_cost_per_lookup_cents: int = 50
    # Per-user daily Enigma ceiling (USD), enforced against the sum of a user's orders placed today.
    outreach_enigma_daily_budget_usd: float = 10.0
    # A selection larger than this is refused at placement (the drain enforces the same cap). A bigger
    # "select all" is split into several orders by the UI.
    outreach_enigma_max_places_per_order: int = 200
    # Default entity path stamped on an order that doesn't specify one. 'brand' returned the card
    # windows in the probe; 'operating_location' is the alternative for a future owner-bearing vertical.
    # Must be one of the outreach drain's accepted values (brand | operating_location).
    outreach_enigma_entity_type: str = "brand"

    # Site name-scrape (the FREE owner/manager fallback). A per-selection cap mirroring the enrich
    # one; the outreach job's name_scrape_max_places_per_order enforces the same bound in the drain.
    # No cost/budget keys — the scrape is an own HTTP GET and spends nothing (PRD §B3), so unlike
    # enrichment it is staff-gated, not admin-gated + budget-guarded.
    outreach_name_scrape_max_places_per_order: int = 200

    # Web-search owner-name (the PAID third-rung fallback). BILLS one OpenAI web-search call per
    # prospect, so it mirrors enrichment's spend model: this drives the free preflight estimate + the
    # per-user daily budget guard; keep the cost rate in sync with the outreach job's
    # name_search_cost_cents (that one drives the drain's cost_ledger write).
    outreach_name_search_cost_cents: int = 3
    outreach_name_search_daily_budget_usd: float = 10.0
    outreach_name_search_max_places_per_order: int = 100

    leadoff_income_acs_year: int = 2023
    leadoff_income_refresh_days: int = 365
    # Per-city county map (public.city_counties) — reverse-geocoded from each
    # city's lat/lng via the free US Census endpoint; powers the board's county
    # filter. See services/leadoff_counties.py.
    leadoff_counties_enabled: bool = True
    # Optional Census Data API key (free, instant from api.census.gov/data/key_signup.html).
    # Not required for low volume, but keyed requests bypass the anonymous
    # throttle if the ~51-state backfill gets edge-blocked.
    census_api_key: str = ""
    # Peer-cohort math: the minimum comparable cities needed for a stable
    # cohort median before the signal is trusted (else the fallback ladder
    # widens the cohort, or the signal drops out → contributes 0 to the grade).
    leadoff_peer_cohort_min_peers: int = 5
    # City-finder (assistant "which cities for category X"): default per-lead
    # value used when a NEW category has no CPL on file (CPL is user-supplied
    # per category — flagged as an assumption in the run result).
    leadoff_finder_default_lead_value: float = 50.0
    # Category smart-search: one forced Sonnet tool call maps a free-text search
    # to a scanned board category + confidence. Below the threshold (or no real
    # match) the API returns "No Data Provided" rather than guessing.
    leadoff_category_match_model: str = "claude-sonnet-4-6"
    leadoff_category_match_threshold: float = 0.85

    # --- Website Builder (docs/modules/website-builder-module-plan-v1_0.md) ---
    # Ships dark. While false the routes 503 and the scheduler hooks are inert.
    website_builder_enabled: bool = False
    # Deliberately NOT github_publish_token: that credential belongs to the blog
    # publishing path. This one can create repos, which is a materially bigger
    # capability and is scoped/rotated on its own.
    github_sites_token: str = ""
    github_sites_owner: str = ""
    # The house template repo every site is generated from. Must have GitHub's
    # "Template repository" flag set, or /generate returns 422.
    website_template_repo: str = "ar-site-template"
    website_default_branch: str = "main"
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    # Bulk publishing reuses the Local SEO stagger rationale: one job per page,
    # spaced so a batch runs at background priority behind interactive work.
    website_publish_job_spacing_seconds: int = 20
    # Deploys are polled (GitHub does not call us). Past this age, a deploy
    # whose Actions run we cannot find is recorded as 'unknown' — NOT failed
    # (PRD §6.3): the site is very likely serving fine and we simply stopped
    # being able to see the run, so the recovery is "re-check", not "re-push".
    website_deploy_timeout_minutes: int = 20
    website_theme_model: str = "claude-sonnet-4-6"
    # Home/about/contact copy. Sonnet, not Haiku: this is the client's first
    # impression in their own voice, not a categorization task — the same tier
    # the service writer uses. No SERP or scoring loop, so it stays cheap.
    website_core_pages_model: str = "claude-sonnet-4-6"
    website_core_pages_max_tokens: int = 2000
    # Where uploaded design exports and their compiled tokens.css live. Private:
    # a design is a client's brand before it is anyone else's business.
    website_theme_bucket: str = "website-themes"
    # A Claude Design export is a single HTML file plus a runtime; anything much
    # larger than this is not one, and reading it into memory to find out is the
    # part worth bounding.
    website_theme_max_mb: int = 25
    # A hero image per hero-eligible page (home + service/location/post). Ships
    # dark and on its own axis from the builder flag: turning the builder on must
    # not start spending on images, and a 40-page bulk-create is 40 renders.
    website_images_enabled: bool = False
    # No provider key here on purpose: heroes render through the suite's one
    # image path (services/illustration.py) and are tuned by its
    # illustration_image_* settings. A second knob that nothing reads only
    # invites someone to set it and expect a different renderer.

    # --- Director of Operations (docs/modules/director-of-operations-plan-v1_0.md,
    # docs/modules/director-of-operations-phase1-spec-v1_0.md) — Phase 1 ---
    # A read-only cross-agent read model + reversible reconciler over SerMaStr
    # (proposes), PACE (executes), QA (judges), the autonomy executor (dark),
    # and the deterministic producers — all writing the native task board.
    # NEVER a scheduling/priority authority; it never touches reopt_planner
    # tiers, autonomy_policy.classify, or a pm_assign capacity hold — it reads
    # their outputs and escalates conflicts as proposals. Ships dark; every
    # piece below is independently flag-gated.
    director_enabled: bool = False                       # master gate — read model + daily reconcile
    director_digest_weekday: int = 0                      # weekly ops-flow digest weekday (0=Mon)
    director_autonomy_veto_enabled: bool = False           # decision 4 — ships dark even within Phase 1
    # Seam thresholds (owner decision 1 — suggested defaults, all tunable
    # without a code change once real dwell times are observed).
    director_seam_approved_unplaced_days: int = 3
    director_seam_proposal_pending_days: int = 5           # a strategist proposal nobody approves/dismisses
    director_seam_qa_idle_days: int = 7
    director_seam_autonomy_unactioned_days: int = 7
    # content_shipped_degraded is immediate (no dwell) — no threshold key.
    director_content_degraded_lookback_days: int = 14      # how far back to scan for degraded ships
    director_autonomy_ledger_lookback_runs: int = 8        # per-client autonomy_runs rows to read
    # DORA — the Director of Operations conversational persona + its own surfaces
    # (the /director web chat page + a dedicated Slack channel). Owner ruling
    # 2026-08-29 reverses the earlier "surfaced through SerMaStr, not a fifth
    # persona" framing: DORA gets its own surface. It stays READ-ONLY / answer-only
    # (no actions), and `director_enabled` (above) gates the persona too — while
    # off, /director/* 503s and the sidebar entry stays hidden.
    director_model: str = "claude-sonnet-4-6"   # DORA's chat model (reasons over the cross-agent read model)
    director_max_tokens: int = 6000
    # A Slack channel id (C…) for DORA's OWN channel: the daily seam flags + the
    # weekly ops-flow digest post here instead of the PACE channel. Empty ⇒ they
    # fall back to the PACE channel (current behavior), so this is safe to leave
    # unset until #dora exists. Invite the posting bot (the PACE bot, or a
    # dedicated DORA app) to the channel first.
    director_slack_channel: str = ""            # DIRECTOR_SLACK_CHANNEL
    # Dedicated DORA Slack app (owner ruling 2026-08-29) — a separate app gives
    # DORA its own bot identity (name/avatar) on its posts AND lets the team chat
    # with DORA inside #dora. When BOTH vars are set, DORA's posts (seam flags +
    # weekly ops digest) go out under director_slack_bot_token, inbound #dora
    # messages arrive on /slack/director/events verified with
    # director_slack_signing_secret, and the SerMaStr app stays out of #dora
    # entirely. Empty bot token ⇒ DORA posts under the PACE bot (which must be a
    # member of #dora), else the shared SerMaStr bot. Empty signing secret ⇒ no
    # inbound (the /director web page is the conversational surface until then).
    # Setup: create a DORA Slack app, add it to #dora, point its Event Request URL
    # at /slack/director/events (Socket Mode OFF — see the PACE gotcha), then set
    # these two vars + director_slack_channel.
    director_slack_bot_token: str = ""          # DIRECTOR_SLACK_BOT_TOKEN — the DORA app's xoxb- bot token
    director_slack_signing_secret: str = ""     # DIRECTOR_SLACK_SIGNING_SECRET — the DORA app's signing secret

    class Config:
        env_file = ".env"


settings = Settings()
