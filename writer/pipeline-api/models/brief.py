"""Pydantic models for the Brief Generator module (schema v1.8).

v1.8 changes (Content Quality PRD v1.0 R1, R2, R3):
- HeadingItem gains cluster_id, cluster_size, cluster_evidence
- DiscardedHeading gains cluster_id, semantic_duplicate_of, raw_text
- DiscardReason enum extended with semantic_duplicate_of_higher_priority_h2,
  definitional_restatement, too_short_after_sanitization,
  non_descriptive_after_sanitization, low_topic_adherence_in_writer
- BriefMetadata gains semantic_dedup_threshold, semantic_dedup_collapses_count,
  definitional_restatements_discarded_count, mmr_lambda
- spin_off_articles[] introduced; silo_candidates[] retained for one release
- All models lock to extra='forbid' (Pydantic equivalent of JSON Schema
  additionalProperties: false)
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


_FORBID_EXTRA = ConfigDict(extra="forbid")


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
]

FAQSource = Literal["paa", "reddit", "llm_extracted"]

DiscardReason = Literal[
    "below_semantic_threshold",
    "below_priority_threshold",
    "global_cap_exceeded",
    "duplicate",
    "low_cluster_coherence",
    "semantic_duplicate_of_higher_priority_h2",
    "definitional_restatement",
    "too_short_after_sanitization",
    "non_descriptive_after_sanitization",
    "low_topic_adherence_in_writer",
]


class BriefRequest(BaseModel):
    """Input envelope to POST /brief."""
    model_config = _FORBID_EXTRA

    run_id: str = Field(..., description="Idempotency key from platform-api")
    attempt: int = 1
    keyword: str = Field(..., min_length=1, max_length=150)
    location_code: int = 2840  # United States
    intent_override: Optional[IntentType] = None


class HeadingClusterEvidence(BaseModel):
    """One paraphrase variant that was merged into a cluster's canonical."""
    model_config = _FORBID_EXTRA

    text: str
    source: HeadingSource
    source_url: Optional[str] = None
    cosine_to_canonical: float = 0.0
    heading_priority: float = 0.0


class HeadingItem(BaseModel):
    model_config = _FORBID_EXTRA

    level: HeadingLevel
    text: str
    type: HeadingType
    source: HeadingSource
    original_source: Optional[str] = None
    semantic_score: float = 0.0
    exempt: bool = False
    serp_frequency: int = 0
    avg_serp_position: Optional[float] = None
    llm_fanout_consensus: int = 0
    heading_priority: float = 0.0
    order: int = 0
    # CQ PRD v1.0 R1 — cluster info
    cluster_id: Optional[int] = None
    cluster_size: int = 1
    cluster_evidence: list[HeadingClusterEvidence] = []


class FAQItem(BaseModel):
    model_config = _FORBID_EXTRA

    question: str
    source: FAQSource
    faq_score: float = 0.0


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


class DiscardedHeading(BaseModel):
    model_config = _FORBID_EXTRA

    text: str
    source: HeadingSource
    original_source: Optional[str] = None
    semantic_score: float = 0.0
    serp_frequency: int = 0
    avg_serp_position: Optional[float] = None
    llm_fanout_consensus: int = 0
    heading_priority: float = 0.0
    discard_reason: DiscardReason
    # CQ PRD v1.0 R1 / R2
    cluster_id: Optional[int] = None
    semantic_duplicate_of: Optional[int] = None  # `order` of the canonical kept
    raw_text: Optional[str] = None  # pre-sanitization text (R2)


class SiloSourceHeading(BaseModel):
    model_config = _FORBID_EXTRA

    text: str
    semantic_score: float
    heading_priority: float
    discard_reason: Literal["global_cap_exceeded", "below_priority_threshold"]


class SiloCandidate(BaseModel):
    """Legacy v1.7 silos. Retained for one release alongside spin_off_articles."""
    model_config = _FORBID_EXTRA

    suggested_keyword: str
    cluster_coherence_score: float
    review_recommended: bool = False
    recommended_intent: IntentType
    source_headings: list[SiloSourceHeading]


SpinOffSourceReason = Literal[
    "low_topic_adherence",
    "semantic_duplicate",
    "global_cap_exceeded",
    "below_priority_threshold",
    "definitional_restatement",
]


class SpinOffArticle(BaseModel):
    """CQ PRD v1.0 R3 — off-topic / displaced headings routed to future pieces."""
    model_config = _FORBID_EXTRA

    suggested_keyword: str
    source_heading_text: str
    source_reason: SpinOffSourceReason
    topic_adherence_score: float = 0.0
    cluster_coherence_score: float = 0.0
    review_recommended: bool = False
    recommended_intent: IntentType
    supporting_headings: list[str] = []


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
    model_config = _FORBID_EXTRA

    word_budget: int = 2500
    faq_count: int = 0
    h2_count: int = 0
    h3_count: int = 0
    total_content_subheadings: int = 0
    discarded_headings_count: int = 0
    silo_candidates_count: int = 0
    spin_off_articles_count: int = 0
    competitors_analyzed: int = 20
    reddit_threads_analyzed: int = 0
    llm_fanout_queries_captured: LLMFanoutCounts = LLMFanoutCounts()
    llm_response_subtopics_extracted: LLMFanoutCounts = LLMFanoutCounts()
    intent_signals: IntentSignals = IntentSignals()
    embedding_model: str = "text-embedding-3-small"
    semantic_filter_threshold: float = 0.55
    # CQ PRD v1.0 R1 — semantic dedup & MMR
    semantic_dedup_threshold: float = 0.85
    semantic_dedup_collapses_count: int = 0
    soft_cluster_pairs_examined: int = 0
    soft_cluster_pairs_merged: int = 0
    definitional_restatements_discarded_count: int = 0
    mmr_lambda: float = 0.6
    # CQ PRD v1.0 R2 — sanitization
    sanitization_discards_count: int = 0
    low_serp_coverage: bool = False
    reddit_unavailable: bool = False
    llm_fanout_unavailable: LLMUnavailable = LLMUnavailable()
    # Root domains of all SERP results — consumed by Research & Citations
    # to exclude competitor URLs from citation candidates.
    competitor_domains: list[str] = []
    schema_version: Literal["1.8"] = "1.8"


class BriefResponse(BaseModel):
    """Brief Generator output (schema v1.8)."""
    model_config = _FORBID_EXTRA

    keyword: str
    title: str = Field(
        default="",
        description=(
            "Title-cased article title (PRD v2.0.0 Step 3.5). "
            "Equals the H1 text. Writer copies this verbatim into the article H1."
        ),
    )
    intent_type: IntentType
    intent_confidence: float
    intent_review_required: bool = False
    heading_structure: list[HeadingItem]
    faqs: list[FAQItem]
    structural_constants: StructuralConstants = StructuralConstants()
    format_directives: FormatDirectives = FormatDirectives()
    discarded_headings: list[DiscardedHeading] = []
    silo_candidates: list[SiloCandidate] = []
    spin_off_articles: list[SpinOffArticle] = []
    metadata: BriefMetadata
