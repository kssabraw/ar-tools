from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    dataforseo_login: str = ""
    dataforseo_password: str = ""
    scrapeowl_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_nlp_api_key: str = ""
    perplexity_api_key: str = ""
    # SIE v1.2 — TextRazor entity extraction (parallel to Google NLP).
    # Free tier: 500 requests/day. A brief calls TextRazor once per
    # scraped page (typically ~10), so the free tier supports ~50 briefs
    # per day. Empty key disables TextRazor extraction silently — the
    # SIE pipeline falls back to Google-NLP-only entities.
    textrazor_api_key: str = ""
    sie_cache_ttl_days: int = 7
    sie_min_pages: int = 5
    log_level: str = "INFO"

    # ------------------------------------------------------------
    # Brief Generator v2.0 — threshold tuning (PRD §12.6)
    # ------------------------------------------------------------
    # All thresholds must be configurable per the PRD. Defaults match the
    # PRD's starting values; expect first-week tuning, especially on the
    # restatement ceiling.
    brief_relevance_floor: float = 0.55
    brief_restatement_ceiling: float = 0.78
    brief_inter_heading_threshold: float = 0.75
    brief_edge_threshold: float = 0.65
    brief_mmr_lambda: float = 0.7
    brief_louvain_resolution: float = 1.0
    brief_louvain_seed: int = 42

    # When true, the pipeline includes per-candidate scores in the response
    # metadata (even for discards) so operators can tune thresholds offline.
    brief_tuning_mode: bool = False

    # PRD v2.4 — Step 7.6 LLM scoring blend.
    # `brief_llm_scoring_weight` is the LLM share of the combined priority
    # (0.30 by default). Set to 0.0 to disable LLM scoring entirely and
    # fall back to pure vector priority. `brief_llm_scoring_top_k` caps
    # the number of candidates LLM-scored — only the top-K by vector
    # priority are sent to the LLM, keeping cost bounded.
    brief_llm_scoring_weight: float = 0.30
    brief_llm_scoring_top_k: int = 25

    # PRD §5 Step 12.3 — silo search-demand threshold.
    # Originally 0.30, designed for multi-source clusters. Lowered to
    # 0.15 because the same threshold applied to singletons (one PAA, one
    # SERP heading) was rejecting every candidate — production was
    # producing zero silos on most keywords. Singletons with strong
    # priority signal additionally bypass this floor (see
    # `brief_silo_strong_priority_bypass`).
    brief_silo_search_demand_threshold: float = 0.15
    # If a singleton candidate's `heading_priority` (computed in Step 7,
    # range 0-1) meets this threshold, the demand floor is bypassed. The
    # priority formula already aggregates title_relevance + serp signals
    # + LLM consensus + info gain, so a substantive candidate should
    # surface as a silo even when its demand-side signals are sparse.
    brief_silo_strong_priority_bypass: float = 0.30

    # Global cap on concurrent Anthropic API calls — protects against
    # the per-account "concurrent connections" rate limit (HTTP 429
    # rate_limit_error). Wraps every `claude_json` / `claude_text` entry
    # point in `modules/brief/llm.py`. Production hit this on the silo
    # viability burst (6+ parallel checks); the global cap also covers
    # the LLM fan-out subtopic extraction (up to 4 parallel Claude
    # calls) and any future concurrent Claude paths. Tune up for higher
    # account tiers; 5 is safe for the default Anthropic plan.
    anthropic_max_concurrency: int = 5

    # SIE v1.1 — Hybrid entity scoring (replaces the prior hard
    # salience >= 0.40 gate at NLP-extract time). Google NLP returns
    # everything above the floor; entities are then scored on a
    # composite of cross-SERP recurrence + salience + mentions - noise
    # and promoted into terms by either composite-score threshold OR
    # high-recurrence override. See `modules/sie/entities.py` and
    # `modules/sie/google_nlp.py`.
    google_nlp_min_salience_floor: float = 0.10
    entity_score_promotion_threshold: float = 0.15
    entity_recurrence_override_pages: int = 3
    # Single-page entity with avg_salience BELOW this floor gets the
    # noise-penalty multiplier (0.30) applied to its composite score.
    # Lowered 0.30 → 0.15 in v1.4 retuning to surface more entities.
    entity_single_page_low_salience_floor: float = 0.15
    # Standalone-promotion path: a single-page entity bypasses the
    # composite-score path when avg_salience >= this floor. Lowered
    # 0.50 → 0.33 in v1.4 retuning so mid-salience single-page
    # entities can promote without high recurrence.
    entity_high_salience_floor: float = 0.33
    entity_score_weights_recurrence: float = 0.45
    entity_score_weights_salience: float = 0.30
    entity_score_weights_mention: float = 0.20
    entity_score_weights_noise_penalty: float = 0.15

    # 7-day brief cache (keyword + location_code shared across clients).
    brief_cache_ttl_days: int = 7

    # Writer §4 — per-section term cap, bucket-aware. The section prompt
    # sends this many of each (entities, related keywords, keyword
    # variants) from the reconciled SIE pool to each H2 group's LLM
    # call. A single combined top-N cap (the prior v1.4 default of 10)
    # routinely starved entities, which tend to score mid-band on SIE's
    # composite recurrence+salience metric — articles shipped with only
    # 3-5 distinct entities used. Bucket-aware caps guarantee minimum
    # entity representation per section regardless of where entities
    # fell in SIE's combined ranking. Tunable via env var if 15 still
    # under-surfaces entities in production.
    writer_section_max_entities: int = 15
    writer_section_max_related_keywords: int = 15
    writer_section_max_keyword_variants: int = 15

    class Config:
        env_file = ".env"


settings = Settings()
