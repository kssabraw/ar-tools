"""Pydantic models for the Content Writer module — schema v1.5.

Per writer-module-v1_5-change-spec_2.md plus content-writer-module-prd-v1.3.md.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


SchemaVersion = Literal["1.5", "1.5-no-context", "1.5-degraded"]
ArticleLevel = Literal["H1", "H2", "H3", "none"]
ArticleType = Literal[
    "content", "faq-header", "faq-question", "conclusion", "h1-enrichment", "title", "intro",
]
ReconciliationAction = Literal[
    "keep",
    "exclude_due_to_brand_conflict",
    "reduce_due_to_brand_preference",
    "use_due_to_brand_preference",
    "keep_avoiding",
]
SIEClassification = Literal["required", "avoid"]
ConflictResolution = Literal[
    "exclude_due_to_brand_conflict",
    "reduce_due_to_brand_preference",
    "brand_preference_overridden_by_sie",
]


class ClientContextInput(BaseModel):
    brand_guide_text: str = ""
    icp_text: str = ""
    website_analysis: Optional[dict[str, Any]] = None
    website_analysis_unavailable: bool = False


class WriterRequest(BaseModel):
    run_id: str
    attempt: int = 1
    brief_output: dict[str, Any]
    sie_output: dict[str, Any]
    research_output: Optional[dict[str, Any]] = None
    client_context: Optional[ClientContextInput] = None


# ---- Brand voice card (output of Step 3.5a) ----

class ClientContactInfo(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    hours: Optional[str] = None


class BrandVoiceCard(BaseModel):
    tone_adjectives: list[str] = []
    voice_directives: list[str] = []
    audience_summary: str = ""
    audience_pain_points: list[str] = []
    audience_goals: list[str] = []
    preferred_terms: list[str] = []
    banned_terms: list[str] = []
    discouraged_terms: list[str] = []
    client_services: list[str] = []
    client_locations: list[str] = []
    client_contact_info: ClientContactInfo = ClientContactInfo()


# ---- Brand conflict log entry (output of Step 3.5b) ----

class BrandConflictEntry(BaseModel):
    term: str
    sie_classification: SIEClassification
    resolution: ConflictResolution
    brand_guide_reasoning: str = ""
    applicable_section_ids: list[str] = []


class ClientContextSummary(BaseModel):
    brand_guide_provided: bool = False
    icp_provided: bool = False
    website_analysis_used: bool = False
    schema_version_effective: SchemaVersion = "1.5"


# ---- Article output ----

class ArticleSection(BaseModel):
    order: int
    level: ArticleLevel
    type: ArticleType
    heading: Optional[str] = None
    body: str = ""
    word_count: int = 0
    section_budget: int = 0
    citations_referenced: list[str] = []


class CitationUsageEntry(BaseModel):
    citation_id: str
    used: bool = False
    sections_used_in: list[int] = []
    marker_placed: bool = False


class CitationUsage(BaseModel):
    total_citations_available: int = 0
    citations_used: int = 0
    citations_unused: int = 0
    usage: list[CitationUsageEntry] = []


class FormatCompliance(BaseModel):
    lists_present: int = 0
    tables_present: int = 0
    lists_required: int = 0
    tables_required: int = 0
    answer_first_applied: bool = True
    directives_satisfied: bool = True


class WriterMetadata(BaseModel):
    total_word_count: int = 0
    word_budget: int = 2500
    faq_word_count: int = 0
    budget_utilization_pct: float = 0.0
    word_count_conflict: bool = False
    no_required_terms: bool = False
    section_count: int = 0
    faq_count: int = 0
    citations_used: int = 0
    citations_unused: int = 0
    no_citations: bool = False
    retry_count: int = 0
    schema_version: SchemaVersion = "1.5"
    brief_schema_version: str = "2.0"
    generation_time_ms: int = 0


class WriterResponse(BaseModel):
    keyword: str
    intent_type: str
    title: str
    article: list[ArticleSection]
    citation_usage: CitationUsage
    format_compliance: FormatCompliance
    brand_voice_card_used: Optional[BrandVoiceCard] = None
    brand_conflict_log: list[BrandConflictEntry] = []
    client_context_summary: ClientContextSummary = ClientContextSummary()
    metadata: WriterMetadata
