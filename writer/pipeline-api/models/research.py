"""Pydantic models for the Research & Citations module — schema v1.1."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


CitationScope = Literal["heading", "authority_gap", "article"]
RecencyLabel = Literal["fresh", "dated", "stale"]
ExtractionMethod = Literal["verbatim_extraction", "fallback_stub"]
VerificationMethod = Literal["verbatim_match", "fuzzy_match", "none"]


class ResearchRequest(BaseModel):
    """POST /research input.

    `brief_output` is the full Brief Generator response (as a dict so we can
    pass it through unchanged to the Writer). The Research module consumes
    only `keyword`, `intent_type`, `heading_structure`, and
    `metadata.competitor_domains`.
    """

    run_id: str
    attempt: int = 1
    keyword: str = Field(..., min_length=1, max_length=150)
    brief_output: dict[str, Any]


class ResearchClaim(BaseModel):
    claim_text: str
    relevance_score: float
    extraction_method: ExtractionMethod = "verbatim_extraction"
    verification_method: VerificationMethod = "verbatim_match"


class Citation(BaseModel):
    citation_id: str
    heading_order: Optional[int] = None
    heading_text: Optional[str] = None
    scope: CitationScope
    url: str
    title: str = ""
    author: Optional[str] = None
    publication: Optional[str] = None
    published_date: Optional[str] = None
    tier: Literal[1, 2, 3]
    recency_label: RecencyLabel
    recency_exception: bool = False
    pdf_source: bool = False
    language_detected: str = "en"
    citation_score: float = 0.0
    shared_citation: bool = False
    citation_quality_low: bool = False
    paywall_detected: bool = False
    bot_block_detected: bool = False
    claim_extraction_failed: bool = False
    claims: list[ResearchClaim] = []


class CitationsByScope(BaseModel):
    heading: int = 0
    authority_gap: int = 0
    article: int = 0


class CitationsByTier(BaseModel):
    tier_1: int = 0
    tier_2: int = 0
    tier_3: int = 0


class CitationsMetadata(BaseModel):
    total_citations: int = 0
    unique_urls: int = 0
    citations_by_scope: CitationsByScope = CitationsByScope()
    citations_by_tier: CitationsByTier = CitationsByTier()
    h2s_with_citations: int = 0
    h2s_without_citations: int = 0
    authority_gap_h3s_with_citations: int = 0
    supplemental_citations_added: int = 0
    competitor_exclusion_unavailable: bool = False
    citations_schema_version: Literal["1.1"] = "1.1"


class ResearchResponse(BaseModel):
    """Full citations-enriched brief.

    Pass-through of the upstream brief with `citation_ids` added to every
    heading_structure item, plus top-level `citations` array and
    `metadata.citations_metadata` block. We model it as a dict to avoid
    duplicating the full Brief schema; only the additions are typed.
    """

    enriched_brief: dict[str, Any]
    citations: list[Citation]
    citations_metadata: CitationsMetadata
