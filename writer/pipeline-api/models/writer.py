"""Pydantic models for the Content Writer module — schema v1.7.

Per writer-module-v1_5-change-spec_2.md plus content-writer-module-prd-v1.3.md.
PRD v2.3 / Phase 3: bumped to 1.6 with new Step 6.7 H2 body length
validator + `under_length_h2_sections` metadata field.
PRD v1.7 / Phase 4: bumped to 1.7 with new Step 4F.1 citation-coverage
validator (C1-C9 patterns + auto-soften for operational claims) +
new `under_cited_sections` and `operational_claims_softened` metadata.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


SchemaVersion = Literal["1.7", "1.7-no-context", "1.7-degraded"]
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
    brand_name: str = ""
    tone_adjectives: list[str] = []
    voice_directives: list[str] = []
    audience_summary: str = ""
    audience_personas: list[str] = []
    audience_verticals: list[str] = []
    audience_company_size: str = ""
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
    schema_version_effective: SchemaVersion = "1.7"


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
    # Banned terms that leaked into body content after the section LLM's
    # one-retry attempt. The run does NOT abort on body leakage (the
    # distillation LLM occasionally over-classifies common words like
    # "leverage" as banned). Headings remain hard-abort. Reviewers can
    # find and fix these terms during article QA.
    banned_terms_leaked_in_body: list[str] = []
    # PRD v2.3 / Phase 3 — Step 6.7 H2 body length validator outcomes.
    # `under_length_h2_sections` carries the H2 sections (by their order
    # in heading_structure) that fell below `format_directives.
    # min_h2_body_words` after a single retry. The retry pass is
    # warn-and-accept — production never aborts on under-length, but the
    # flagged sections are surfaced so editors can review or expand
    # them post-publish.
    under_length_h2_sections: list[dict] = []
    h2_body_length_retries_attempted: int = 0
    h2_body_length_retries_succeeded: int = 0
    # PRD v1.7 / Phase 4 — Step 4F.1 citation-coverage validator outcomes.
    # `under_cited_sections` carries the H2 sections whose detected
    # citable claims (C1-C9) fell under the 50% citation-coverage
    # threshold even after a single retry. `operational_claims_softened`
    # records every C7-C9 phrase that was deterministically rewritten
    # to hedge phrasing because no citation could be added during the
    # retry. Both are warn-and-accept — runs never abort on coverage.
    under_cited_sections: list[dict] = []
    operational_claims_softened: list[dict] = []
    citation_coverage_retries_attempted: int = 0
    citation_coverage_retries_succeeded: int = 0
    schema_version: SchemaVersion = "1.7"
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
    # Per-zone term usage breakdown (related keywords, entities, quadgrams).
    # Keyed by zone name: "title", "h1", "subheadings", "body". Computed
    # post-hoc by modules.writer.term_usage; always present.
    term_usage_by_zone: dict[str, dict] = {}
    metadata: WriterMetadata
