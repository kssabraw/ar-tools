"""Pydantic models for the Brief Generator module — schema v2.0.

Implements the output schema specified in
docs/modules/content-brief-generator-prd-v2_0.md §6.

Key v2.0 architectural changes versus v1.7/v1.8:
- Title + scope statement are now first-class outputs (Step 3.5)
- Hypothetical searcher persona is captured (Step 6)
- `semantic_score` renamed to `title_relevance` (cosine to title, not seed)
- `region_id` and `scope_classification` carried on every heading
- New discard reasons gate on title relevance + region elimination + scope
- Coverage-graph regions replace v1.7's two-tier semantic clusters; the
  cluster_id / cluster_evidence fields are gone
- Silos now reuse Step 5 regions (`routed_from`) and absorb scope-rejects
- spin_off_articles[] removed; silo_candidates is the unified concept
- Embedding model upgraded to text-embedding-3-large

All models lock to extra='forbid' (Pydantic equivalent of JSON Schema
additionalProperties: false), per PRD §12 strict-validation requirement.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


_FORBID_EXTRA = ConfigDict(extra="forbid")


# ---- Enumerations ----

IntentType = Literal[
    "informational",
    "listicle",
    "how-to",
    "comparison",
    "ecom",
    "local-seo",
    "news",
    "informational-commercial",
]

HeadingLevel = Literal["H1", "H2", "H3"]
HeadingType = Literal["content", "faq-header", "faq-question", "conclusion"]

HeadingSource = Literal[
    "serp",
    "paa",
    "reddit",
    "authority_gap_sme",
    "synthesized",
    "autocomplete",
    "keyword_suggestion",
    "llm_fanout_chatgpt",
    "llm_fanout_claude",
    "llm_fanout_gemini",
    "llm_fanout_perplexity",
    "llm_response_chatgpt",
    "llm_response_claude",
    "llm_response_gemini",
    "llm_response_perplexity",
    "persona_gap",
]

FAQSource = Literal["paa", "reddit", "llm_extracted", "persona_gap"]

ScopeClassification = Literal["in_scope", "borderline"]

DiscardReason = Literal[
    "below_relevance_floor",
    "above_restatement_ceiling",
    "region_off_topic",
    "region_restates_title",
    "below_priority_threshold",
    "global_cap_exceeded",
    "duplicate",
    "low_cluster_coherence",
    "scope_verification_out_of_scope",
    # Step 8.6 (H3 Selection) additions — PRD v2.0.x
    "h3_below_parent_relevance_floor",
    "h3_above_parent_restatement_ceiling",
    "displaced_by_authority_gap_h3",
]

SiloRoutedFrom = Literal[
    "non_selected_region",
    "scope_verification",
    # Step 8.5b — Authority Gap H3 rejected by H3 scope verification (PRD v2.0.3)
    "scope_verification_h3",
    # Step 5.1 relevance gate — heading discarded as below_relevance_floor.
    # These candidates are below the title's relevance floor (so excluded
    # from the parent article) but may still represent adjacent topics
    # worth surfacing as standalone silos (filtered by search demand + the
    # Step 12.4 viability LLM check before reaching the user).
    "relevance_floor_reject",
]


# ---- Request envelope ----

class BriefRequest(BaseModel):
    """Input envelope to POST /brief."""
    model_config = _FORBID_EXTRA

    run_id: str = Field(..., description="Idempotency key from platform-api")
    attempt: int = 1
    keyword: str = Field(..., min_length=1, max_length=150)
    location_code: int = 2840  # United States

    # Captured for audit trail. The brief content is client-agnostic per
    # PRD §2; client_id never feeds into LLM inputs and never scopes the
    # cache. Two clients running the same keyword share the cached output.
    client_id: Optional[str] = None

    # When true, skip the cache lookup and force regeneration. Successful
    # regeneration overwrites the cached row.
    force_refresh: bool = False

    intent_override: Optional[IntentType] = None


# ---- Persona (Step 6 output) ----

class PersonaInfo(BaseModel):
    """Hypothetical searcher persona derived from topic + SERP signal.

    Per PRD §2: brand and ICP context never feed into persona generation;
    the persona is always inferred from the keyword and SERP alone.
    """
    model_config = _FORBID_EXTRA

    description: str = ""
    background_assumptions: list[str] = []
    primary_goal: str = ""


# ---- Heading items ----

class HeadingItem(BaseModel):
    model_config = _FORBID_EXTRA

    level: HeadingLevel
    text: str
    type: HeadingType
    source: HeadingSource
    original_source: Optional[str] = None
    title_relevance: float = 0.0
    exempt: bool = False
    serp_frequency: int = 0
    avg_serp_position: Optional[float] = None
    llm_fanout_consensus: int = 0
    information_gain_score: float = 0.0
    heading_priority: float = 0.0
    region_id: Optional[str] = None
    scope_classification: Optional[ScopeClassification] = None
    # Step 8.6 (H3 Selection): only set on H3 entries that flow through
    # the parent-relevance MMR; null for H1, H2, and authority-gap H3s.
    parent_h2_text: Optional[str] = None
    parent_relevance: float = 0.0
    # Step 9 (v2.0.3): populated only for source='authority_gap_sme' entries —
    # the agent's own justification that the H3 stays within the brief's scope.
    scope_alignment_note: Optional[str] = None
    order: int = 0


# ---- FAQs ----

class FAQItem(BaseModel):
    model_config = _FORBID_EXTRA

    question: str
    source: FAQSource
    faq_score: float = 0.0


# ---- Structural + format directives ----

class StructuralConstants(BaseModel):
    model_config = _FORBID_EXTRA

    class _Conclusion(BaseModel):
        model_config = _FORBID_EXTRA

        type: Literal["conclusion"] = "conclusion"
        level: Optional[str] = None
        text: str = "[Conclusion placeholder]"

    conclusion: _Conclusion = _Conclusion()


class FormatDirectives(BaseModel):
    model_config = _FORBID_EXTRA

    require_bulleted_lists: bool = True
    require_tables: bool = True
    min_lists_per_article: int = 2
    min_tables_per_article: int = 1
    preferred_paragraph_max_words: int = 80
    answer_first_paragraphs: bool = True


# ---- Discarded headings ----

class DiscardedHeading(BaseModel):
    model_config = _FORBID_EXTRA

    text: str
    source: HeadingSource
    original_source: Optional[str] = None
    title_relevance: float = 0.0
    serp_frequency: int = 0
    avg_serp_position: Optional[float] = None
    llm_fanout_consensus: int = 0
    heading_priority: float = 0.0
    region_id: Optional[str] = None
    discard_reason: DiscardReason


# ---- Silo candidates ----

class SiloSourceHeading(BaseModel):
    """A heading that contributed to a silo candidate.

    `discard_reason` is nullable because non-selected-region members may
    have been eligible for selection but lost the MMR competition (no
    discard reason yet); scope-verification rejects always carry one.
    """
    model_config = _FORBID_EXTRA

    text: str
    source: HeadingSource
    title_relevance: float = 0.0
    heading_priority: float = 0.0
    discard_reason: Optional[DiscardReason] = None


class SiloCandidate(BaseModel):
    model_config = _FORBID_EXTRA

    suggested_keyword: str
    cluster_coherence_score: float = 0.0
    review_recommended: bool = False
    recommended_intent: IntentType
    routed_from: SiloRoutedFrom
    source_headings: list[SiloSourceHeading] = []

    # Step 12 refinements (PRD §5 Step 12.6)
    # Counts of each discard_reason among the silo's member headings —
    # gives consumers a quick view of why these headings were rejected.
    discard_reason_breakdown: dict[str, int] = {}
    # Step 12.3 — five-signal demand score, hard floor 0.30 to qualify.
    search_demand_score: float = 0.0
    # Step 12.4 — viability LLM verdict; defaults true under double-failure
    # fallback (see metadata.silo_viability_fallback_applied).
    viable_as_standalone_article: bool = True
    viability_reasoning: str = ""
    estimated_intent: IntentType = "informational"
    # Step 12.5 — populated by v2.1 cross-brief dedup; defaults to 1 in v2.0.
    cross_brief_occurrence_count: int = 1


# ---- Metadata ----

class LLMFanoutCounts(BaseModel):
    model_config = _FORBID_EXTRA

    chatgpt: int = 0
    claude: int = 0
    gemini: int = 0
    perplexity: int = 0


class LLMUnavailable(BaseModel):
    model_config = _FORBID_EXTRA

    chatgpt: bool = False
    claude: bool = False
    gemini: bool = False
    perplexity: bool = False


class IntentSignals(BaseModel):
    model_config = _FORBID_EXTRA

    shopping_box: bool = False
    news_box: bool = False
    local_pack: bool = False
    featured_snippet: bool = False
    comparison_tables: bool = False


class BriefMetadata(BaseModel):
    """Operational + tuning metadata. Threshold values used during the
    run are echoed back so consumers (and offline tuners) know exactly
    which configuration produced the output."""
    model_config = _FORBID_EXTRA

    word_budget: int = 2500
    faq_count: int = 0
    h2_count: int = 0
    h3_count: int = 0
    total_content_subheadings: int = 0
    discarded_headings_count: int = 0
    silo_candidates_count: int = 0
    competitors_analyzed: int = 20
    reddit_threads_analyzed: int = 0

    # Shortfall tracking (PRD §5 Step 8 — accept shortfall, don't pad)
    h2_shortfall: bool = False
    h2_shortfall_reason: Optional[str] = None

    # H3 distribution (PRD §5 Step 8.6)
    h3_count_average: float = 0.0
    h2s_with_zero_h3s: int = 0

    # Coverage graph stats (PRD §5 Step 5)
    regions_detected: int = 0
    regions_eliminated_off_topic: int = 0
    regions_eliminated_restate_title: int = 0
    regions_contributing_h2s: int = 0

    # Scope verification stats (PRD §5 Step 8.5)
    scope_verification_borderline_count: int = 0
    scope_verification_rejected_count: int = 0

    # Silo pipeline rejection counters (PRD §5 Step 12.1 / 12.3 / 12.4)
    silo_candidates_rejected_by_discard_reason: int = 0
    silo_candidates_rejected_by_search_demand: int = 0
    silo_candidates_rejected_by_viability_check: int = 0
    silo_viability_fallback_applied: bool = False

    llm_fanout_queries_captured: LLMFanoutCounts = LLMFanoutCounts()
    llm_response_subtopics_extracted: LLMFanoutCounts = LLMFanoutCounts()
    intent_signals: IntentSignals = IntentSignals()

    # Threshold values used during this run (echoed for tuning)
    embedding_model: Literal["text-embedding-3-large"] = "text-embedding-3-large"
    relevance_floor_threshold: float = 0.55
    restatement_ceiling_threshold: float = 0.78
    inter_heading_threshold: float = 0.75
    edge_threshold: float = 0.65
    mmr_lambda: float = 0.7

    # Step 8.6 H3 thresholds (echoed for tuning)
    parent_relevance_floor_threshold: float = 0.60
    parent_restatement_ceiling_threshold: float = 0.85
    inter_h3_threshold: float = 0.78

    # Step 12.3 silo search-demand floor
    silo_search_demand_threshold: float = 0.30

    low_serp_coverage: bool = False
    reddit_unavailable: bool = False
    llm_fanout_unavailable: LLMUnavailable = LLMUnavailable()

    # Root domains of all SERP results — consumed by Research & Citations
    # to exclude competitor URLs from citation candidates.
    competitor_domains: list[str] = []

    schema_version: Literal["2.0"] = "2.0"


# ---- Top-level response ----

class BriefResponse(BaseModel):
    """Brief Generator output (schema v2.0, see PRD §6)."""
    model_config = _FORBID_EXTRA

    keyword: str
    title: str
    scope_statement: str
    title_rationale: str = ""
    intent_type: IntentType
    intent_confidence: float = 0.0
    intent_review_required: bool = False
    persona: PersonaInfo = PersonaInfo()
    heading_structure: list[HeadingItem] = []
    faqs: list[FAQItem] = []
    structural_constants: StructuralConstants = StructuralConstants()
    format_directives: FormatDirectives = FormatDirectives()
    discarded_headings: list[DiscardedHeading] = []
    silo_candidates: list[SiloCandidate] = []
    metadata: BriefMetadata
