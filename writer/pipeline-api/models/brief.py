"""Pydantic models for the Brief Generator module (schema v1.7)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


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
]


class BriefRequest(BaseModel):
    """Input envelope to POST /brief."""

    run_id: str = Field(..., description="Idempotency key from platform-api")
    attempt: int = 1
    keyword: str = Field(..., min_length=1, max_length=150)
    location_code: int = 2840  # United States
    intent_override: Optional[IntentType] = None


class HeadingItem(BaseModel):
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


class FAQItem(BaseModel):
    question: str
    source: FAQSource
    faq_score: float = 0.0


class StructuralConstants(BaseModel):
    class _Conclusion(BaseModel):
        type: Literal["conclusion"] = "conclusion"
        level: Optional[str] = None
        text: str = "[Conclusion placeholder]"

    conclusion: _Conclusion = _Conclusion()


class FormatDirectives(BaseModel):
    require_bulleted_lists: bool = True
    require_tables: bool = True
    min_lists_per_article: int = 2
    min_tables_per_article: int = 1
    preferred_paragraph_max_words: int = 80
    answer_first_paragraphs: bool = True


class DiscardedHeading(BaseModel):
    text: str
    source: HeadingSource
    original_source: Optional[str] = None
    semantic_score: float = 0.0
    serp_frequency: int = 0
    avg_serp_position: Optional[float] = None
    llm_fanout_consensus: int = 0
    heading_priority: float = 0.0
    discard_reason: DiscardReason


class SiloSourceHeading(BaseModel):
    text: str
    semantic_score: float
    heading_priority: float
    discard_reason: Literal["global_cap_exceeded", "below_priority_threshold"]


class SiloCandidate(BaseModel):
    suggested_keyword: str
    cluster_coherence_score: float
    review_recommended: bool = False
    recommended_intent: IntentType
    source_headings: list[SiloSourceHeading]


class LLMFanoutCounts(BaseModel):
    chatgpt: int = 0
    claude: int = 0
    gemini: int = 0
    perplexity: int = 0


class LLMUnavailable(BaseModel):
    chatgpt: bool = False
    claude: bool = False
    gemini: bool = False
    perplexity: bool = False


class IntentSignals(BaseModel):
    shopping_box: bool = False
    news_box: bool = False
    local_pack: bool = False
    featured_snippet: bool = False
    comparison_tables: bool = False


class BriefMetadata(BaseModel):
    word_budget: int = 2500
    faq_count: int = 0
    h2_count: int = 0
    h3_count: int = 0
    total_content_subheadings: int = 0
    discarded_headings_count: int = 0
    silo_candidates_count: int = 0
    competitors_analyzed: int = 20
    reddit_threads_analyzed: int = 0
    llm_fanout_queries_captured: LLMFanoutCounts = LLMFanoutCounts()
    llm_response_subtopics_extracted: LLMFanoutCounts = LLMFanoutCounts()
    intent_signals: IntentSignals = IntentSignals()
    embedding_model: str = "text-embedding-3-small"
    semantic_filter_threshold: float = 0.55
    low_serp_coverage: bool = False
    reddit_unavailable: bool = False
    llm_fanout_unavailable: LLMUnavailable = LLMUnavailable()
    # Root domains of all SERP results — consumed by Research & Citations
    # to exclude competitor URLs from citation candidates.
    competitor_domains: list[str] = []
    schema_version: Literal["1.7"] = "1.7"


class BriefResponse(BaseModel):
    """Brief Generator output (schema v1.7)."""

    keyword: str
    intent_type: IntentType
    intent_confidence: float
    intent_review_required: bool = False
    heading_structure: list[HeadingItem]
    faqs: list[FAQItem]
    structural_constants: StructuralConstants = StructuralConstants()
    format_directives: FormatDirectives = FormatDirectives()
    discarded_headings: list[DiscardedHeading] = []
    silo_candidates: list[SiloCandidate] = []
    metadata: BriefMetadata
