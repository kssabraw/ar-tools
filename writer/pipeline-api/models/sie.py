"""Pydantic models for the SIE (SERP Intelligence Engine) module - schema v1.0."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


OutlierMode = Literal["safe", "aggressive"]
RecommendationCategory = Literal["required", "avoid"]
Confidence = Literal["high", "medium", "low"]
RecommendationType = Literal[
    "primary_supporting_term",
    "secondary_supporting_term",
    "entity_candidate",
    "overused_noisy_term",
    "boilerplate_term",
    "brand_specific_term",
    "location_specific_term",
]
TermSource = Literal["ngram", "entity_only", "ngram_and_entity"]
EntityCategory = Literal[
    "services", "products", "tools", "equipment", "brands",
    "locations", "people", "organizations", "regulations",
    "concepts", "problems", "symptoms", "materials",
    "methods", "comparisons", "pricing_factors",
]


class SIERequest(BaseModel):
    run_id: str
    attempt: int = 1
    keyword: str = Field(..., min_length=1, max_length=150)
    location_code: int = 2840
    language_code: str = "en"
    device: Literal["desktop", "mobile"] = "desktop"
    depth: int = 20
    outlier_mode: OutlierMode = "safe"
    force_refresh: bool = False


class WordCountTarget(BaseModel):
    min: int
    target: int
    max: int
    source_word_counts: list[int] = []


class ZoneUsage(BaseModel):
    min: int
    target: int
    max: int


class TermUsage(BaseModel):
    title: ZoneUsage
    h1: ZoneUsage
    h2: ZoneUsage
    h3: ZoneUsage
    paragraphs: ZoneUsage


class UsageRecommendation(BaseModel):
    term: str
    mode: OutlierMode
    usage: TermUsage
    outlier_pages_excluded: int = 0
    outlier_page_url: Optional[str] = None
    confidence: Confidence
    warning: Optional[str] = None


class TermRecord(BaseModel):
    """Unified term entry - n-gram terms, entity-only terms, or merged."""

    term: str
    source: TermSource = "ngram"
    n_gram_length: int = 1
    is_entity: bool = False
    is_target_keyword: bool = False
    # SIE v1.3 - n-gram terms whose tokens are a contiguous subsequence
    # of the seed keyword (e.g. "tiktok shop" / "roi" / "how to" for
    # the seed "how to increase roi for a tiktok shop"). Frontend should
    # bucket these separately from "related concepts" - they're echoes
    # of the input, not topical adjacent terms. Writer still uses them
    # via the per-zone targets in usage_recommendations. Entities and
    # the seed keyword itself are NEVER flagged as fragments.
    is_seed_fragment: bool = False
    entity_category: Optional[EntityCategory] = None
    avg_salience: Optional[float] = None
    ner_variants: list[str] = []
    subsumed_terms: list[str] = []

    total_count: int = 0
    pages_found: int = 0
    source_urls: list[str] = []
    zone_counts: dict[str, int] = {}
    zone_pages: dict[str, int] = {}

    semantic_similarity: float = 0.0
    corpus_tfidf_score: float = 0.0
    zone_boost_applied: bool = False
    zone_boost_reason: Optional[str] = None

    recommendation_score: float = 0.0
    recommendation_category: RecommendationCategory = "required"
    recommendation_type: RecommendationType = "primary_supporting_term"
    confidence: Confidence = "medium"
    reason: str = ""
    minimum_usage: Optional[dict[str, int]] = None


class TermBuckets(BaseModel):
    required: list[TermRecord] = []
    avoid: list[TermRecord] = []
    low_coverage_candidates: list[TermRecord] = []


class TermSignals(BaseModel):
    coverage_threshold_applied: bool = True
    tfidf_threshold_applied: bool = True
    terms_filtered_by_coverage: int = 0
    terms_filtered_by_tfidf: int = 0
    terms_passed_to_embedding: int = 0
    subsumption_merges: int = 0


class ExcludedURL(BaseModel):
    url: str
    rank: Optional[int] = None
    page_category: Optional[str] = None
    exclusion_reason: str
    duplicate_of: Optional[str] = None
    similarity: Optional[float] = None


class FailedURL(BaseModel):
    url: str
    rank: Optional[int] = None
    failure_reason: str


class SERPSummary(BaseModel):
    analyzed_urls: list[str] = []
    excluded_urls: list[ExcludedURL] = []
    failed_urls: list[FailedURL] = []
    dominant_page_type: str = ""


class SIEWarning(BaseModel):
    level: Literal["info", "warning", "critical"] = "warning"
    code: str
    message: str
    details: Optional[dict] = None


class TargetKeywordRecord(BaseModel):
    term: str
    is_target_keyword: bool = True
    recommendation_score: float = 1.00
    recommendation_category: RecommendationCategory = "required"
    confidence: Confidence = "high"
    minimum_usage: dict[str, int] = {"title": 1, "h1": 1, "paragraphs": 1}


class CategoryTarget(BaseModel):
    """SIE v1.4 - per-zone per-category aggregate target.

    `target` is 0.50 × trimmed-max competitor count of distinct items
    in that (zone, category). `max` is the trimmed-max itself (the
    highest competitor count after outlier removal).
    """

    target: int = 0
    max: int = 0


class ZoneCategoryAggregate(BaseModel):
    """Three-bucket distinct-item aggregate per zone (SIE v1.4).

    Categories partition the SIE required-term set:
      - entities: terms flagged as entities (Google NLP and/or TextRazor)
      - related_keywords: required n-gram terms that aren't entities
        and aren't seed-keyword fragments
      - keyword_variants: terms whose tokens are a contiguous
        subsequence of the seed keyword (is_seed_fragment=True)
    """

    entities: CategoryTarget = CategoryTarget()
    related_keywords: CategoryTarget = CategoryTarget()
    keyword_variants: CategoryTarget = CategoryTarget()


class SIEResponse(BaseModel):
    schema_version: Literal["1.4"] = "1.4"
    keyword: str
    location_code: int
    language_code: str
    outlier_mode: OutlierMode
    cached: bool = False
    cache_date: Optional[str] = None
    sie_cache_hit: bool = False  # alias for `cached` per platform-api contract
    run_date: str
    serp_summary: SERPSummary
    word_count: WordCountTarget
    word_count_target: int = 0  # convenience top-level for platform-api contract
    terms: TermBuckets
    term_signals: TermSignals
    usage_recommendations: list[UsageRecommendation] = []
    # SIE v1.4 - distinct-item aggregate per zone, per category. Keys
    # are zone names (title / h1 / h2 / h3 / paragraphs); values carry
    # entities / related_keywords / keyword_variants targets benchmarked
    # at 0.50 × trimmed-max competitor count. Writer consumes these to
    # drive prompt-level category coverage instead of summing per-term
    # zone targets.
    zone_category_targets: dict[str, ZoneCategoryAggregate] = {}
    target_keyword: TargetKeywordRecord
    warnings: list[SIEWarning] = []
