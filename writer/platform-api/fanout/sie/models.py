"""SIE Final Output Model (M12) — the PRD's SIE schema, which is the Writer's
**Input C** (docs/blog-writer-pipeline-bundle.md §20.3, `schema_version "1.4"`).

This is the persisted `keyword_analyses.output_json` shape and the native contract
the M14 Writer adapter consumes (no adaptation layer). The Writer reads the 1.4
fields below; `warnings` + `pages` are M12 report/provenance extras (the Writer
ignores unknown fields) used by the owner-only Term-analysis report (plan §6).

Keep field names/shape byte-faithful to §20.3 — the Writer keys off them directly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.4"

# entity_category values seen in the contract; kept as a plain str (the PRD's
# category set is open-ended / LLM-assigned) rather than an enum so a new
# category from pass-2 never hard-fails serialization.
EntityCategory = str


class ZoneRange(BaseModel):
    """Per-zone occurrence range for a term (min ≤ target ≤ max)."""

    min: int = Field(ge=0)
    target: int = Field(ge=0)
    max: int = Field(ge=0)


class WordCount(BaseModel):
    """Recommended article length (Module 12: p25/p50/p75 over eligible pages)."""

    target: int = Field(ge=0)
    min: int = Field(ge=0)
    max: int = Field(ge=0)


class MinimumUsage(BaseModel):
    """Per-zone occurrence floors for the seed keyword (Module 13/14)."""

    h2: int = Field(default=0, ge=0)
    h3: int = Field(default=0, ge=0)
    paragraphs: int = Field(default=0, ge=0)


class TargetKeyword(BaseModel):
    term: str
    minimum_usage: MinimumUsage


class RequiredTerm(BaseModel):
    """A term the writer must incorporate, with its score + entity flags."""

    term: str
    recommendation_score: float = Field(ge=0.0, le=1.0)
    is_entity: bool = False
    entity_category: EntityCategory | None = None


class Terms(BaseModel):
    required: list[RequiredTerm] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class UsageRecommendation(BaseModel):
    """Per-zone min/target/max for one term. The writer targets `target`, hard-caps
    at `max` (bundle §20.3 / writer §5.7)."""

    term: str
    h2: ZoneRange
    h3: ZoneRange
    paragraphs: ZoneRange


class Entity(BaseModel):
    """A merged NER entity (Module 11: TextRazor pass-1 + LLM pass-2)."""

    term: str
    entity_category: EntityCategory | None = None
    example_context: str | None = None
    ner_variants: list[str] = Field(default_factory=list)
    recommendation_score: float = Field(ge=0.0, le=1.0)


class AnalyzedPage(BaseModel):
    """M12 report provenance — which SERP URLs were analyzed vs excluded + why.
    Not part of the Writer's Input C; surfaced only in the Term-analysis report."""

    url: str
    rank: int | None = None
    included: bool
    reason: str | None = None  # exclusion / near-dup / scrape-failure reason


class SIEOutput(BaseModel):
    """The SIE Final Output Model (Writer Input C, schema_version 1.4) + M12 report
    extras (`warnings`, `pages`). Persisted as `keyword_analyses.output_json`."""

    schema_version: str = SCHEMA_VERSION
    keyword: str
    word_count: WordCount
    target_keyword: TargetKeyword
    terms: Terms
    usage_recommendations: list[UsageRecommendation] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    # M12 extras (Writer-ignored): degraded-confidence / conflict warnings, and the
    # analyzed/excluded URL provenance for the owner report (plan §6).
    warnings: list[str] = Field(default_factory=list)
    pages: list[AnalyzedPage] = Field(default_factory=list)
