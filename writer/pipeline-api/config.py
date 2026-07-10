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
    # Gemini embeddings — dual-space AIO proximity (Brief v2.8, advisory only).
    # The asymmetric RETRIEVAL_QUERY/RETRIEVAL_DOCUMENT spaces match how Google
    # scores AI Overview retrieval better than OpenAI's symmetric space. Empty
    # key → the AIO-proximity metric silently falls back to OpenAI 3-large.
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dim: int = 1536
    # SIE v1.2 - TextRazor entity extraction (parallel to Google NLP).
    # Free tier: 500 requests/day. A brief calls TextRazor once per
    # scraped page (typically ~10), so the free tier supports ~50 briefs
    # per day. Empty key disables TextRazor extraction silently - the
    # SIE pipeline falls back to Google-NLP-only entities.
    textrazor_api_key: str = ""
    sie_cache_ttl_days: int = 7
    sie_min_pages: int = 5
    log_level: str = "INFO"

    # ------------------------------------------------------------
    # Brief Generator v2.0 - threshold tuning (PRD §12.6)
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

    # PRD v2.4 - Step 7.6 LLM scoring blend.
    # `brief_llm_scoring_weight` is the LLM share of the combined priority
    # (0.30 by default). Set to 0.0 to disable LLM scoring entirely and
    # fall back to pure vector priority. `brief_llm_scoring_top_k` caps
    # the number of candidates LLM-scored - only the top-K by vector
    # priority are sent to the LLM, keeping cost bounded.
    brief_llm_scoring_weight: float = 0.30
    brief_llm_scoring_top_k: int = 25

    # PRD §5 Step 12.3 - silo search-demand threshold.
    # Originally 0.30, designed for multi-source clusters. Lowered to
    # 0.15 because the same threshold applied to singletons (one PAA, one
    # SERP heading) was rejecting every candidate - production was
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

    # Global cap on concurrent Anthropic API calls - protects against
    # the per-account "concurrent connections" rate limit (HTTP 429
    # rate_limit_error). Wraps every `claude_json` / `claude_text` entry
    # point in `modules/brief/llm.py`. Production hit this on the silo
    # viability burst (6+ parallel checks); the global cap also covers
    # the LLM fan-out subtopic extraction (up to 4 parallel Claude
    # calls) and any future concurrent Claude paths. Tune up for higher
    # account tiers; 5 is safe for the default Anthropic plan.
    anthropic_max_concurrency: int = 5

    # Transient-error retry for every Claude call (429 rate limit, 529
    # overloaded, 5xx, connection drops): exponential backoff + jitter,
    # sleeping OUTSIDE the concurrency semaphore so a backing-off call
    # doesn't hold a slot. The semaphore only prevents self-inflicted
    # concurrency 429s — account-wide saturation (other suite services
    # sharing the key) still surfaces as 429 here, and without retries a
    # single 429 failed the whole module and therefore the whole run.
    # Budget: 2/4/8/16s (×0.5-1.5 jitter) ≈ up to ~45s, well inside the
    # brief/writer module timeouts.
    anthropic_max_retries: int = 4
    anthropic_retry_base_seconds: float = 2.0

    # SIE v1.1 - Hybrid entity scoring (replaces the prior hard
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

    # Intent classification Step 3.3 - LLM arbitration for low-confidence
    # outcomes. When the deterministic passes (keyword pattern precheck 3.1 +
    # SERP-signal rules 3.2) land below `intent_llm_fallback_max_confidence`,
    # a cheap Haiku call (keyword + top SERP titles) arbitrates instead of
    # accepting the weak answer; the deterministic result remains the
    # degraded path when the call fails or returns an invalid label. With
    # today's rule confidences (matches 0.80-0.95, no-match default 0.55)
    # the 0.80 threshold fires exactly on the no-match case; raise it via
    # env to have Haiku double-check weaker signal matches too.
    intent_llm_fallback_enabled: bool = True
    intent_llm_fallback_model: str = "claude-haiku-4-5-20251001"
    intent_llm_fallback_max_confidence: float = 0.80

    # Listicle minimum ranked-item enforcement (Step 11.6). A `ranked_items`
    # (listicle) brief must present at least the intent template's
    # `min_h2_count` ranked H2s - one section per item (e.g. one per product
    # / vendor / tool). The core assembly selects ranked H2s from the SERP /
    # fanout heading pool and MMR-picks up to `max_h2_count`, but never PADS
    # to reach `min_h2_count`: when the pool yields few ranked-shaped headings
    # (e.g. a "best X software" SERP whose per-tool headings were dropped as
    # bare entities by the relevance gate) the outline can land with a single
    # ranked item - a listicle in name only. When enabled, one LLM call names
    # the real items the listicle should rank and appends them as ranked
    # sections until the floor is met (capped at `max_h2_count`). Honest-
    # fallback by design: if the model can't name enough REAL items (or the
    # call fails) the outline is left short rather than padded with invented
    # entries. Sonnet (not Haiku) because naming real, current products needs
    # world knowledge. Set False to restore the prior accept-a-short-listicle
    # behavior.
    brief_listicle_min_items_enabled: bool = True
    brief_listicle_min_items_model: str = "claude-sonnet-4-6"

    # Writer end-of-run format QA. One cheap Haiku call after final assembly
    # asking "given this keyword, is this H2 outline the right article
    # archetype?" - the only check that validates the PLAN (the brief's
    # intent) rather than the article's conformance to it. Warn-and-accept:
    # a mismatch flags writer metadata for the run-detail QA panel, never
    # aborts. Best-effort - any API error leaves the fields None (unknown).
    writer_format_qa_enabled: bool = True
    writer_format_qa_model: str = "claude-haiku-4-5-20251001"
    # Companion end-of-run check: did the article actually honor the user's
    # per-run writer notes? One Haiku call (shares writer_format_qa_model)
    # splits the notes into distinct directives and judges each landed /
    # not-landed against the final article text - an LLM judge (like the
    # ICP callout check) because paraphrase defeats string matching
    # ("ZDSCS" vs "Zero Down Supply Chain Services"). Warn-and-accept.
    writer_notes_qa_enabled: bool = True

    # Term-coverage enforcement (owner spec 2026-07-09). Deterministic, no
    # LLM for the check itself - both sides (SIE targets + article usage)
    # are already computed.
    # - Quadgrams: the corpus-derived 4-word phrases in the SIE required
    #   pool (top N tracked) must each appear at least once; any required
    #   term above the occurrence cap flags as stuffing.
    # - Entities: if unique-entity coverage OR total entity occurrences
    #   fall below the 75% bar (either bar), the weakest sections are
    #   auto-rewritten ONCE with the missing entities, then flagged if
    #   still short (same warn-and-accept retry pattern as the word-floor
    #   and citation-coverage validators).
    writer_term_coverage_enabled: bool = True
    writer_quadgram_track_max: int = 10
    writer_term_occurrence_cap: int = 10
    writer_entity_coverage_min: float = 0.75
    writer_entity_rewrite_enabled: bool = True
    writer_entity_rewrite_max_sections: int = 3

    # ------------------------------------------------------------
    # Service Page Brief Generator (PRD §7 - model tiering + cache)
    # ------------------------------------------------------------
    # Cheap tier for per-page competitor teardown extraction; strong tier
    # reserved for the synthesis/reconciliation step. Overridable via env so
    # the tiering can be tuned without a code change.
    service_brief_extraction_model: str = "claude-haiku-4-5-20251001"
    service_brief_synthesis_model: str = "claude-sonnet-4-6"
    # Research-bundle cache TTL (keyword + location_code; client-agnostic). The
    # competitor SERP for a service doesn't move much week-to-week, so a 7-day
    # window pays for itself while synthesis stays per-client.
    service_brief_cache_ttl_days: int = 7

    # Writer §4 - per-section term cap, bucket-aware. The section prompt
    # sends this many of each (entities, related keywords, keyword
    # variants) from the reconciled SIE pool to each H2 group's LLM
    # call. A single combined top-N cap (the prior v1.4 default of 10)
    # routinely starved entities, which tend to score mid-band on SIE's
    # composite recurrence+salience metric - articles shipped with only
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
