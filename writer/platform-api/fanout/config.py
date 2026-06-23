from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration, sourced from environment variables.

    On Railway most of these are inherited from the AR Tools project-level env
    (PRD §14.2). Service-specific values have sensible defaults so the service
    boots in any environment.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase. The service-role and anon keys accept the AR Tools project-level
    # names (SUPABASE_SERVICE_KEY / SUPABASE_KEY) as aliases so the service works
    # with the inherited env without renaming shared variables.
    supabase_url: str = ""
    supabase_service_role_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY"
        ),
    )
    supabase_anon_key: str = Field(
        default="",
        validation_alias=AliasChoices("SUPABASE_ANON_KEY", "SUPABASE_KEY"),
    )

    # The Postgres schema all this app's tables live under (PRD §14.3).
    fanout_schema: str = "fanout"

    # OpenAI — silo discovery (GPT-5.4 w/ browsing) + embeddings (PRD §14.2).
    openai_api_key: str = ""
    openai_silo_model: str = "gpt-5.4"
    openai_embedding_model: str = "text-embedding-3-small"
    # Responses API browsing tool type. Configurable so the exact name can be
    # corrected without a code change if OpenAI's differs (e.g. web_search_preview).
    openai_web_search_tool: str = "web_search"

    # Embeddings provider (locked-decision override 2026-06-15, owner: OpenAI ->
    # Google Gemini, whole-app, quality/consistency). Ships DORMANT: default
    # "openai" so prod is untouched until GEMINI_API_KEY is provisioned + a live
    # smoke test passes; THEN set EMBEDDING_PROVIDER=gemini and recalibrate every
    # cosine threshold below (the Gemini similarity distribution differs from
    # OpenAI's). gemini-embedding-001 @ 1536 dims (Matryoshka truncation) keeps the
    # existing vector(1536) columns, so no schema migration of stored vectors.
    embedding_provider: str = "openai"  # "openai" | "gemini"
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"  # GA. Dormant — provider is openai (Gemini deferred 2026-06-16). Embedding-2 preview gave poor write-time relevance discrimination; override via GEMINI_EMBEDDING_MODEL to revisit.
    gemini_embedding_dim: int = 1536
    gemini_embedding_task_type: str = "SEMANTIC_SIMILARITY"
    # Concurrent batchEmbedContents calls (Gemini caps each at 100 inputs, so a
    # 1000-keyword batch is 10 calls run in parallel). Lower if region RPM bites.
    gemini_embedding_max_workers: int = 8

    # Disambiguation gate (PRD §7.1.2 / Q16). The LLM's ambiguity signal is
    # corroborated by embedding separation between candidate interpretations:
    # ambiguity is confirmed only if the two most-distinct interpretations have a
    # cosine distance >= this threshold. Tunable during MVP testing.
    ambiguity_separation_threshold: float = 0.5

    # Anthropic — article planning orchestrator (Claude Opus 4.7, tool-use /
    # strict-schema JSON; PRD §7.10, §14.2). Reuses the AR Tools ANTHROPIC_API_KEY.
    anthropic_api_key: str = ""
    orchestrator_model: str = "claude-opus-4-7"
    orchestrator_max_tokens: int = 16000
    orchestrator_timeout_s: int = 120         # PRD §16.2: >120s -> retry once then degrade
    # The orchestrator runs per silo, but a silo with many groupings overruns a
    # single call (huge prompt + output -> timeout/truncation). Plan in chunks of
    # this many groupings, run in parallel, so each call stays small and fast.
    orchestrator_groupings_per_call: int = 12
    orchestrator_max_workers: int = 2         # parallel orchestrator calls (M6
    # architect lesson: 5 burst Anthropic's concurrent-connection 429s and the
    # chunks degraded to passthrough; 2 + the client's transport backoff holds)

    # M5 article planning (PRD §7.10).
    candidate_serp_top_n: int = 10            # top organic URLs per candidate primary
    candidate_serp_max_workers: int = 8
    candidate_serp_time_budget_s: int = 120
    # Cross-topic dedup thresholds (§7.10.4).
    dedup_primary_cosine_threshold: float = 0.85
    dedup_serp_overlap_min: float = 2 / 3     # top-3 SERP overlap fraction

    # Salience split (PRD §7.10 granularity): after planning, an over-large article
    # is sub-clustered by keyword-embedding similarity (Louvain at a higher
    # resolution) and split into multiple articles when it cleanly divides. Runs
    # automatically in the plan job. Embedding-based (no extra DataForSEO spend);
    # only articles above the keyword threshold are touched, and tiny sub-clusters
    # fold back into the largest so the long-tail isn't shattered into thin stubs.
    split_oversized_articles: bool = True
    split_min_keywords: int = 40              # only articles larger than this split
    split_resolution: float = 1.2             # > base -> finer sub-communities
    split_edge_threshold: float = 0.55        # cosine edge for the sub-graph
    # No floor on sub-article size: every sub-community becomes its own article,
    # even a 1-keyword stub. Owner-accepted maximal granularity (stub explosion is
    # acceptable; raise this knob if a future seed needs stub-suppression).
    split_min_subarticle_size: int = 1

    # Peer-entity-aware article grouping (owner-requested). After planning, any
    # keyword that names a known peer entity (from grounding's `peer_entities`) is
    # pulled into an article dedicated to that peer's relationship with the seed.
    # All "X vs Y" / "switching from X to Y" / "X alternative to Y" variants for
    # the same peer end up in one article; single-keyword peer matches still spawn
    # their own primary (no minimum — the peer-name signal is deterministic).
    peer_entity_grouping: bool = True
    # Below this many keywords, a peer-comparison bucket folds into one
    # "retatrutide vs competitors" roundup instead of shipping as a thin
    # single-keyword stub (a lone `cagrisema vs retatrutide`). 1 disables the
    # fold (every competitor its own article). 2 folds only 1-keyword stubs.
    peer_min_keywords: int = 2

    # Orphan promotion: after all planning passes finish, every active keyword
    # that the orchestrator silently omitted (singletons, redundant long-tail,
    # cross-topic-dedup loser-side losses) becomes its own singleton article.
    # Owner-requested after seeing "what is retatrutide" land in the active pool
    # but in no cluster. Zero LLM / embedding cost.
    promote_orphan_keywords: bool = True
    # Quality floor for orphan promotion: cosine score (vs. silo anchor) below
    # which silently-omitted keywords stay as orphans rather than becoming their
    # own thin article. Tightens the editorial bar without touching the gate's
    # `relevance_threshold` (which gates the pool used for clustering).
    # Empirically: 0.65 keeps the strong + foundational orphans, drops the
    # marginal long-tail (cf. retatrutide validation, 2026-05-28).
    orphan_promotion_min_score: float = 0.65

    # Enriched silo anchor (routing-calibration follow-up). At finalize, the LLM
    # generates ~N example keywords per accepted silo; their embeddings are
    # centroided with the rationale embedding to form a more discriminative anchor
    # (the rationale embedding alone is seed-dominated -> all silo anchors cluster,
    # M5 noted ~71% routing accuracy). Owner-requested. One-off LLM cost at
    # finalize (~$0.05 per session); routing at gate time stays pure-embedding.
    enriched_silo_anchor: bool = True
    silo_anchor_example_count: int = 30
    silo_anchor_max_workers: int = 5

    # LLM routing for ambiguous keywords (second-pass calibration). After the
    # gate's cosine Lever-3 picks a best silo, keywords whose top-1 vs top-2
    # silo-anchor cosine margin is below `llm_routing_margin_threshold` are
    # re-routed in batches by an LLM call. Catches the genuinely ambiguous
    # cases (where embeddings can't decide) without per-keyword LLM cost on the
    # easy ones. ~$0.40-1 per run when ~half the pool is ambiguous.
    llm_routing_enabled: bool = True
    llm_routing_margin_threshold: float = 0.04
    llm_routing_batch_size: int = 50
    llm_routing_max_workers: int = 4

    # DataForSEO — demand sample + SERP structure during silo discovery.
    dataforseo_login: str = ""
    dataforseo_password: str = ""
    dataforseo_base_url: str = "https://api.dataforseo.com"

    # M3 expansion knobs (PRD §7.3 / §7.5).
    keyword_ideas_limit: int = 1000
    keyword_suggestions_limit: int = 500
    query_fanouts_limit: int = 300
    paa_tier1_seeds: int = 8          # tier-1 questions used as tier-2 seeds
    paa_tier2_cap: int = 40           # max tier-2 questions per silo (PRD §7.3)
    autocomplete_max: int = 500       # safety cap on autocomplete calls per run
                                      # (autocomplete is the noisiest/slowest source;
                                      #  most of it gets filtered by the relevance gate)
    expansion_max_workers: int = 8    # parallel endpoint/silo workers
    expansion_time_budget_s: int = 240  # hard cap on a single expansion run (4 min)

    # M4 competitor mining (PRD §7.4).
    competitor_top_n_standard: int = 5       # top organic URLs mined per silo
    competitor_top_n_comprehensive: int = 10
    ranked_keywords_limit: int = 500         # ranked keywords pulled per domain
    competitor_max_position: int = 20        # organic rank ceiling (1..N)
    competitor_max_workers: int = 8
    competitor_time_budget_s: int = 240

    # M4 relevance gate (PRD §7.6) + clustering (§7.9).
    # 0.65 is an aggressive cutoff (owner decision) — keeps only clearly on-topic
    # keywords, roughly halving the active pool vs the prior 0.52. Re-tune via env
    # (RELEVANCE_THRESHOLD) or a per-run /regate without redeploying.
    relevance_threshold: float = 0.65        # cosine cutoff vs parent topic embedding

    # Pre-embedding language ID filter (PRD §7.6 follow-up). DataForSEO is
    # locked to en/US but its related/autocomplete endpoints occasionally
    # surface non-English Latin-script phrases when the dominant terms share
    # spelling with English (e.g. "wat is een managed service provider"). The
    # embedding-cosine gate would then accept them. The filter runs over each
    # unique candidate keyword BEFORE embedding: a curated starter regex catches
    # mixed-language patterns ("wat is een…"), and lingua-py catches pure-non-
    # English on >=3-token strings. Either firing tags the keyword as
    # filtered_language. Confidence threshold only affects layer 2 (lingua);
    # layer 1 is deterministic. Disable for a no-redeploy rollback.
    language_filter_enabled: bool = True
    language_filter_confidence: float = 0.6
    # Lever 3: assign each keyword to its single best silo (argmax cosine to the
    # silo anchor) instead of keeping it active in every silo it passes in. Kills
    # the cross-silo duplication that dedup otherwise has to clean up.
    relevance_assign_best_silo: bool = True
    relevance_embed_batch: int = 1000        # keywords per embedding request
    clustering_edge_threshold: float = 0.55  # min cosine for a graph edge
    # Louvain resolution: >1 favors more, smaller communities (finer granularity).
    clustering_resolution: float = 1.0
    # Cap on keywords clustered per topic. The similarity graph is O(n^2), so
    # bound n to keep memory in check; the top-N most-relevant actives are
    # clustered, the long-tail remainder stays active but unclustered.
    clustering_max_nodes: int = 2500
    # Hard cap on active keywords per silo, applied AFTER the relevance gate
    # scores everything. The top-N most-relevant keywords per silo stay 'active'
    # and feed clustering / the Table View; the rest are demoted to
    # 'filtered_relevance'. Directly bounds article count and dedup work — sits
    # below clustering_max_nodes so a tightening of this cap visibly shrinks the
    # active pool, not just what reaches the similarity graph.
    active_per_silo_cap: int = 1000

    # §7.8 keyword metrics enrichment (DataForSEO Labs keyword_overview): per-
    # keyword search volume / CPC / KD / competition. Run against the active
    # pool after the gate + cap, so cost scales with active_per_silo_cap × silos
    # (~$0.40 for a typical 5-silo run at list price). Tunable per session via
    # CreateSessionBody.enrich_with_metrics; this is the workspace default.
    enrich_with_metrics_default: bool = True
    metrics_batch_size: int = 500            # keywords per keyword_overview call
    metrics_max_workers: int = 4             # parallel keyword_overview calls
    metrics_time_budget_s: int = 120

    # Recursive Fanout (PRD §7.7, Phase 1). RF deepens each silo by re-expanding
    # its top cluster representatives as sub-anchors. Mining at this level is off
    # (M5 finding: mining adds noise the gate rejects).
    fanout_subanchors_per_silo: int = 6      # top-N cluster reps re-expanded per silo
    fanout_subanchor_max_workers: int = 8
    # RF expands N silos x fanout_subanchors_per_silo anchors in one run, so a flat
    # budget that suits a base /expand (a handful of silos) starves a wide fan-out
    # and truncates its tail. Scale the budget by the sub-anchor count instead:
    # max(floor, per_anchor x count), capped. RF runs in the background worker, so
    # the cap can exceed Railway's 5-min edge limit (that only bounds the request).
    fanout_time_budget_per_anchor_s: float = 25.0
    fanout_time_budget_floor_s: float = 60.0
    fanout_time_budget_cap_s: int = 900
    # Cost surfaced to the owner before an RF run (§7.7: 5x-8x the base run).
    fanout_cost_multiplier_low: float = 5.0
    fanout_cost_multiplier_high: float = 8.0

    # M6 site architecture (PRD §7.11). Fully deterministic — no LLM (the writer
    # module owns pillar editorial as of 2026-06-09); only the linking matrix +
    # placeholder editorial fields are produced here.
    # Pillars link laterally only above this topic-embedding cosine (§15.2 #4).
    architecture_pillar_lateral_cosine: float = 0.55
    # Per-page internal-link budget (owner rule, 2026-06-09): NO page emits more
    # than 5 outbound internal links. A pillar's 5 = up to `pillar_down_links_max`
    # children + up to `pillar_lateral_links_max` peer pillars; an article's 5 =
    # 1 up-link to its pillar + up to `lateral_article_links_max` laterals. The
    # §15.2 #3 no-orphan guarantee no longer comes from "pillar links to ALL its
    # articles" (that produced 60+ links on big silos) — it now comes from a
    # within-silo article cycle: each article links to a successor, so every
    # article receives ≥1 inbound link by construction even though the pillar
    # links to only a few children.
    architecture_pillar_lateral_links_max: int = 2
    # The pillar links down to its most-central children (nearest the silo mean
    # centroid); the rest stay reachable via the article cycle. Small silos
    # (≤ this many articles) link to all their children.
    architecture_pillar_down_links_max: int = 3
    # Lateral peer links per supporting article. One slot is the within-silo cycle
    # successor (the no-orphan edge); the rest are nearest peers. 4 laterals + the
    # 1 up-link = the 5-link ceiling.
    architecture_lateral_article_links_max: int = 4

    # M8 VA mode (PRD §10.2 / §15.2 §7.2 #3). A VA may deep-mine at most the seed
    # + this many additional silos; the seed is always mined and never counts.
    va_deep_mine_max_silos: int = 2

    # Display-time within-cluster keyword dedup (Cluster View / PRD §9.2). After
    # surface-form normalization collapses obvious variants (plurals, articles,
    # "what is/are X", aliases like msp <-> managed service provider), the
    # remaining canonicals get a cosine pass over the per-keyword embeddings
    # persisted by the relevance gate. Pairs at or above this threshold collapse
    # to the higher-volume / higher-relevance winner. Set to 1.0 to disable the
    # cosine half without touching surface-form dedup; lower the value to
    # collapse more semantic dupes ("definition" vs "meaning") at the cost of a
    # few legitimate variants. Pure display-time pass; no DB writes.
    cluster_display_dedupe_cosine_threshold: float = 0.95

    # M10 CSV export (PRD §12). Downloads are served via a time-limited signed URL
    # the backend mints from the private csv-snapshots bucket; this is its TTL.
    # Re-issued fresh on every download, so a short window is fine.
    csv_signed_url_ttl_s: int = 3600

    # Observability (PRD §16.3)
    log_level: str = "INFO"
    # Cost attribution (PRD §16.4): the background jobs flush the running actual
    # cost to sessions.actual_cost_usd + cost_breakdown on this cadence, so the
    # live cost banner (§8.4) updates while the pipeline runs.
    cost_flush_interval_s: float = 10.0

    # SIE Term & Entity module (M12, docs/sie-module-plan.md). Keys provisioned
    # 2026-06-15 on the Railway service (reads SCRAPEOWL_API_KEY / TEXTRAZOR_API_KEY).
    scrapeowl_api_key: str = ""
    scrapeowl_base_url: str = "https://api.scrapeowl.com/v1"
    textrazor_api_key: str = ""
    textrazor_base_url: str = "https://api.textrazor.com"
    # Anthropic tiers for SIE LLM calls (M3 classify / M11 pass-2 entities).
    sie_classifier_model: str = "claude-haiku-4-5"
    sie_entity_model: str = "claude-sonnet-4-6"
    # Tunable SIE thresholds (PRD #3 defaults).
    sie_serp_depth: int = 20
    sie_coverage_threshold: int = 3            # M8: 3-of-top-10
    sie_tfidf_threshold: float = 0.005         # M9
    sie_semantic_threshold: float = 0.65       # M10 (dynamic 0.60/0.70)
    sie_textrazor_relevance_min: float = 0.40  # M11 pass-1 salience proxy
    sie_min_eligible_pages: int = 5            # below -> degraded-confidence warning
    sie_scrape_max_workers: int = 6
    sie_textrazor_max_workers: int = 2         # TextRazor 401s on a high concurrent fan-out
    sie_max_transport_attempts: int = 3
    sie_scrapeowl_premium_on_500: bool = True  # retry a 5xx page with premium proxies
    # Per-unit cost-meter estimates until first invoices (sie_analysis phase).
    scrapeowl_cost_per_scrape: float = 0.0008
    scrapeowl_cost_per_scrape_premium: float = 0.005   # premium proxies cost ~5x
    textrazor_cost_per_request: float = 0.0006

    # ----- M13 Brief Generator (answer-engine-first) -----
    # Dual/triple embedding spaces (aio plan §0 #1): 3-large for the organic gates +
    # ChatGPT proximity; Gemini (RETRIEVAL_* task types) for AIO proximity. The Gemini
    # path here is INDEPENDENT of the app-wide embedding_provider (which stays openai).
    brief_embedding_model_large: str = "text-embedding-3-large"
    # Clustered-keyword coverage audit (2b): a supporting keyword counts as "covered" when
    # its 3-large cosine to some brief heading clears this (lexical subset match also counts).
    brief_coverage_threshold: float = 0.62
    # Auto-split: uncovered keywords within this cosine (3-small) are grouped into one new
    # article (so near-duplicate phrasings don't each spawn a thin, cannibalizing page).
    auto_split_group_threshold: float = 0.85
    # M15 scheduler — in-process asyncio loop that drains due scheduled_article_runs.
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 60
    scheduler_concurrency_cap: int = 3        # in-flight article writes (LLM rate-limit guard)
    scheduler_stuck_minutes: int = 30         # startup sweep: running rows older than this requeue
    scheduler_shutdown_grace_s: float = 20.0  # max wait for in-flight writes on shutdown
    writer_schedule_approval_threshold_usd: float = 90.0   # VA Schedule-all > this -> M9 approval
    writer_article_cost_estimate_usd: float = 0.30         # per-article preview figure (§9.4)
    # Publishing destinations (dormant until provisioned). GitHub: fine-grained PAT with
    # Contents:write on the target repo; the repo/branch/path are per-session in publish_config.
    github_publish_token: str = ""
    github_default_branch: str = "main"
    github_default_content_path: str = "src/content/blog"
    # Google Drive save (OAuth-as-user, personal Gmail has no Shared Drives). The refresh
    # token is minted once; publish the consent screen to production so it doesn't expire.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_refresh_token: str = ""
    brief_aio_query_task_type: str = "RETRIEVAL_QUERY"     # heading side (asymmetric)
    brief_aio_doc_task_type: str = "RETRIEVAL_DOCUMENT"    # answer side
    brief_gen_model: str = "claude-haiku-4-5"              # MCS candidate generation
    brief_intent_model: str = "claude-haiku-4-5"           # intent + A1 classification
    brief_title_model: str = "claude-sonnet-4-6"           # title/scope (quality cascades)
    # Answer-contract (query understanding → must/must-not-cover guardrail for MCS). Opus
    # on purpose: it sets the brief's whole direction + must correct a false premise; one
    # small call, well under the per-brief ceiling. Env-overridable.
    brief_answer_contract_model: str = "claude-opus-4-8"
    # DataForSEO AI-Optimization "LLM Responses" requires a per-provider model_name
    # (omitting it -> task error 40501 "Invalid Field: 'model_name'"). Env-overridable;
    # confirmed-valid values from the provider models endpoints (tune to a cheaper
    # flash tier once verified against /llm_responses/models).
    brief_chatgpt_model: str = "gpt-4.1-mini"
    brief_gemini_model: str = "gemini-2.5-pro"

    # ----- M14 Content Writer (degraded 1.7-no-context + no_citations path) -----
    # Sonnet for prose (sections/intro/FAQ/conclusion/takeaways), Haiku for short calls
    # (CTA); no Opus (PRD §17). Embeddings reuse the app embedder (3-small, 1536-dim).
    writer_section_model: str = "claude-sonnet-4-6"
    writer_short_model: str = "claude-haiku-4-5"
    writer_word_budget: int = 2500
    # §7 names 90s, but that target predates sequential Sonnet section writing: one
    # section ran ~30s live, so a 4-6 section article needs more headroom. The job is an
    # async polled background job (not request-bound), so a larger budget is safe.
    writer_timeout_s: float = 240.0                # end-to-end budget -> generation_timeout
    writer_claim_coverage_enabled: bool = True     # §8 #1: keep §5.8.8 detect+soften in no-citations mode
    # Topic-adherence drop (§5.4.2). The PRD's 0.62 (calibrated on generic 3-small)
    # over-drops here: brief H2s are already MCS-vetted on-topic yet score 0.48-0.58
    # vs the specific title, so 0.62 left only 1 of 4 sections live. Lowered to 0.40 —
    # still cleanly separates genuinely off-topic headings (~0 cosine). Env-overridable.
    writer_adherence_threshold: float = 0.40

    # CORS — comma-separated list of allowed frontend origins. "*" allows all.
    cors_allow_origins: str = "*"

    @property
    def brief_llm_response_models(self) -> dict[str, str]:
        """provider -> model_name for the DataForSEO LLM-Responses calls."""
        return {"chat_gpt": self.brief_chatgpt_model, "gemini": self.brief_gemini_model}

    @property
    def cors_origins_list(self) -> list[str]:
        raw = self.cors_allow_origins.strip()
        if raw == "*" or raw == "":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
