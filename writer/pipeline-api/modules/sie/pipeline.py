"""SIE pipeline orchestrator (schema v1.0).

Runs all 14 modules from the SIE PRD, including 7-day cache check, parallel
Track A (n-grams) / Track B (entities + word count), and entity-term merge.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from config import settings
from models.sie import (
    ExcludedURL,
    FailedURL,
    SERPSummary,
    SIERequest,
    SIEResponse,
    SIEWarning,
    TargetKeywordRecord,
    TermBuckets,
    TermRecord,
    TermSignals,
    TermUsage,
    UsageRecommendation,
    WordCountTarget,
    ZoneUsage,
)
from modules.brief import dataforseo as dfs

from . import cache
from .classification import (
    ClassifiedURL,
    classify_all,
    dominant_page_type,
    near_duplicate_pairs,
)
from .entities import extract_entities, merge_entities_into_terms
from .filters import (
    DEFAULT_TFIDF_THRESHOLD,
    compute_tfidf,
    filter_semantic,
    is_zone_protected,
    passes_tfidf,
)
from .ngrams import (
    TermAggregate,
    analyze_pages,
    apply_coverage_gate,
    apply_subsumption,
    flag_template_boilerplate,
    lemmatize,
    tokenize,
)
from .scoring import score_terms
from .scraper import scrape_many
from .usage import build_usage
from .word_count import compute_word_count_target
from .zones import PageZones, cross_page_fingerprint_filter, extract_zones

logger = logging.getLogger(__name__)


class SIEError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def run_sie(req: SIERequest) -> SIEResponse:
    started = time.perf_counter()
    keyword = req.keyword.strip()

    # ---- Cache check ----
    if not req.force_refresh:
        cached = await cache.get_cached(keyword, req.location_code, req.outlier_mode)
        if cached:
            cached["cached"] = True
            cached["sie_cache_hit"] = True
            return SIEResponse.model_validate(cached)

    warnings: list[SIEWarning] = []

    # ---- Module 2: SERP collection ----
    try:
        serp = await dfs.serp_organic_advanced(keyword, location_code=req.location_code, depth=req.depth)
    except Exception as exc:
        raise SIEError("serp_failed", f"DataForSEO SERP failed: {exc}")

    organic = [
        item for item in serp["items"]
        if item.get("type") == "organic" and item.get("url")
    ]
    if not organic:
        raise SIEError("serp_no_results", "DataForSEO returned 0 organic results.")

    classified = classify_all([
        (item["url"], item.get("rank_absolute") or item.get("rank_group") or 99, item.get("title", ""))
        for item in organic
    ])

    eligible = [c for c in classified if c.content_eligible]
    if len(eligible) < settings.sie_min_pages:
        warnings.append(SIEWarning(
            level="critical",
            code="few_eligible_pages",
            message=(
                f"Only {len(eligible)} content-eligible pages were available. "
                "Recommendations may be unreliable due to insufficient sample size."
            ),
            details={"pages_available": len(eligible)},
        ))

    # ---- Module 4: Scrape eligible URLs ----
    eligible_urls = [c.url for c in eligible]
    scrape_results = await scrape_many(eligible_urls, concurrency=5)

    failed: list[FailedURL] = []
    successful_html: list[tuple[ClassifiedURL, str]] = []
    for c, sr in zip(eligible, scrape_results):
        if sr.success and sr.html:
            successful_html.append((c, sr.html))
        else:
            failed.append(FailedURL(
                url=sr.url,
                rank=c.rank,
                failure_reason=sr.failure_reason or "unknown",
            ))

    if not successful_html:
        raise SIEError("scrape_all_failed", "All page scrapes failed; cannot continue.")

    failure_rate = len(failed) / max(len(eligible), 1)
    if failure_rate > 0.30:
        warnings.append(SIEWarning(
            level="warning",
            code="high_scrape_failure_rate",
            message=f"{int(failure_rate*100)}% of eligible pages failed to scrape.",
        ))

    # ---- Module 5: Zone extraction ----
    pages: list[PageZones] = []
    page_to_classified: dict[str, ClassifiedURL] = {}
    for c, html in successful_html:
        zones = extract_zones(c.url, html)
        if zones is None or not zones.body_text:
            failed.append(FailedURL(url=c.url, rank=c.rank, failure_reason="zone_extraction_empty"))
            continue
        pages.append(zones)
        page_to_classified[c.url] = c

    if not pages:
        raise SIEError("no_pages_extracted", "No pages survived zone extraction.")

    # ---- Module 3 (post-scrape): near-duplicate detection ----
    excluded: list[ExcludedURL] = []
    for c in classified:
        if not c.content_eligible:
            excluded.append(ExcludedURL(
                url=c.url,
                rank=c.rank,
                page_category=c.page_category,
                exclusion_reason=c.reason,
            ))

    duplicates = near_duplicate_pairs([(p.url, page_to_classified[p.url].rank, p.body_text) for p in pages])
    duplicate_urls = {dup_url for dup_url, _, _ in duplicates}
    pages = [p for p in pages if p.url not in duplicate_urls]
    for dup_url, canonical_url, sim in duplicates:
        excluded.append(ExcludedURL(
            url=dup_url,
            page_category="duplicate",
            exclusion_reason=f"near-duplicate of {canonical_url}",
            duplicate_of=canonical_url,
            similarity=sim,
        ))

    # ---- Module 6 Layer 3: cross-page fingerprinting ----
    cross_page_fingerprint_filter(pages)

    # ---- Track A + Track B in parallel ----
    track_a = asyncio.create_task(_run_track_a(pages, keyword, page_to_classified))
    track_b = asyncio.create_task(_run_track_b(pages, keyword=keyword))

    aggregates, sem_scores, tfidf_scores, signals = await track_a
    entities, nlp_failed_urls, word_count_min, word_count_target_p50, word_count_max, source_word_counts = await track_b

    if nlp_failed_urls:
        warnings.append(SIEWarning(
            level="info",
            code="google_nlp_partial",
            message=f"Google NLP API failed for {len(nlp_failed_urls)} pages.",
            details={"failed_urls": nlp_failed_urls},
        ))

    # ---- Module 11 merge: entities into terms ----
    aggregates, entity_meta = merge_entities_into_terms(aggregates, entities)

    # ---- Module 13: scoring ----
    rank_by_url = {p.url: page_to_classified[p.url].rank for p in pages}
    page_categories_by_url = {p.url: page_to_classified[p.url].page_category for p in pages}
    dominant = dominant_page_type([page_to_classified[p.url] for p in pages])

    scored = score_terms(
        aggregates=aggregates,
        semantic_scores=sem_scores,
        tfidf_scores=tfidf_scores,
        rank_by_url=rank_by_url,
        page_categories_by_url=page_categories_by_url,
        dominant_category=dominant,
        entity_meta=entity_meta,
    )

    # Build TermRecord lists, splitting by required/avoid/low_coverage
    required: list[TermRecord] = []
    avoid: list[TermRecord] = []
    low_coverage: list[TermRecord] = []

    for term, agg in aggregates.items():
        # Apply post-filter: only terms passing all gates AND scored go to required
        score_data = scored.get(term)
        meta = entity_meta.get(term, {})

        record_kwargs = dict(
            term=term,
            n_gram_length=agg.n_gram_length,
            source=meta.get("source", "ngram"),
            is_entity=meta.get("is_entity", False),
            entity_category=meta.get("entity_category"),
            avg_salience=meta.get("avg_salience"),
            ner_variants=meta.get("ner_variants", []),
            subsumed_terms=agg.subsumed_terms,
            total_count=agg.total_count,
            pages_found=agg.pages_found,
            source_urls=sorted(agg.source_urls),
            zone_counts=dict(agg.zone_counts),
            zone_pages={z: len(urls) for z, urls in agg.zone_pages.items()},
            semantic_similarity=round(sem_scores.get(term, 0.0), 4),
            corpus_tfidf_score=round(tfidf_scores.get(term, 0.0), 4),
        )

        if agg.low_coverage_candidate:
            record_kwargs["recommendation_score"] = round((score_data or {}).get("score", 0.0), 4)
            record_kwargs["recommendation_category"] = "required"
            record_kwargs["confidence"] = "low"
            record_kwargs["reason"] = "Low coverage — fewer than 3 pages."
            low_coverage.append(TermRecord(**record_kwargs))
            continue

        if not score_data:
            continue

        record_kwargs["recommendation_score"] = score_data["score"]
        record_kwargs["recommendation_category"] = score_data["category"]
        record_kwargs["recommendation_type"] = score_data["type"]
        record_kwargs["confidence"] = score_data["confidence"]
        record_kwargs["reason"] = score_data["reason"]
        record_kwargs["zone_boost_applied"] = score_data["zone_boost_applied"]
        record_kwargs["zone_boost_reason"] = score_data["zone_boost_reason"]

        record = TermRecord(**record_kwargs)
        if score_data["category"] == "avoid":
            avoid.append(record)
        else:
            required.append(record)

    # Sort required by score desc
    required.sort(key=lambda r: r.recommendation_score, reverse=True)
    avoid.sort(key=lambda r: r.recommendation_score, reverse=True)

    # ---- Module 14: usage recommendations ----
    target_word_count = word_count_target_p50 or 1500
    # Build usage only for top required terms (cap to keep payload reasonable)
    top_for_usage = {r.term: aggregates[r.term] for r in required[:50] if r.term in aggregates}
    usage_dicts = build_usage(top_for_usage, pages, target_word_count, req.outlier_mode)

    usage_models: list[UsageRecommendation] = []
    for u in usage_dicts:
        zones = u["usage"]
        usage_models.append(UsageRecommendation(
            term=u["term"],
            mode=u["mode"],
            usage=TermUsage(
                title=ZoneUsage(**zones.get("title", {"min": 0, "target": 0, "max": 0})),
                h1=ZoneUsage(**zones.get("h1", {"min": 0, "target": 0, "max": 0})),
                h2=ZoneUsage(**zones.get("h2", {"min": 0, "target": 0, "max": 0})),
                h3=ZoneUsage(**zones.get("h3", {"min": 0, "target": 0, "max": 0})),
                paragraphs=ZoneUsage(**zones.get("paragraphs", {"min": 0, "target": 0, "max": 0})),
            ),
            outlier_pages_excluded=u["outlier_pages_excluded"],
            outlier_page_url=u["outlier_page_url"],
            confidence=u["confidence"],
            warning=u["warning"],
        ))

    # ---- Target keyword: always required ----
    target_record = TargetKeywordRecord(
        term=keyword,
        recommendation_score=1.00,
        confidence="high",
        minimum_usage={"title": 1, "h1": 1, "paragraphs": 1},
    )

    # Make sure the target keyword shows up in required list at the top
    target_term_norm = " ".join(tokenize(keyword))
    if not any(r.term == target_term_norm or r.term == keyword.lower() for r in required):
        required.insert(0, TermRecord(
            term=keyword.lower(),
            is_target_keyword=True,
            recommendation_score=1.00,
            recommendation_category="required",
            recommendation_type="primary_supporting_term",
            confidence="high",
            reason="Target keyword (always required).",
            minimum_usage={"title": 1, "h1": 1, "paragraphs": 1},
        ))

    duration_ms = int((time.perf_counter() - started) * 1000)

    response = SIEResponse(
        keyword=keyword,
        location_code=req.location_code,
        language_code=req.language_code,
        outlier_mode=req.outlier_mode,
        cached=False,
        cache_date=None,
        sie_cache_hit=False,
        run_date=datetime.now(timezone.utc).isoformat(),
        serp_summary=SERPSummary(
            analyzed_urls=[p.url for p in pages],
            excluded_urls=excluded,
            failed_urls=failed,
            dominant_page_type=dominant,
        ),
        word_count=WordCountTarget(
            min=word_count_min,
            target=word_count_target_p50,
            max=word_count_max,
            source_word_counts=source_word_counts,
        ),
        word_count_target=word_count_target_p50,
        terms=TermBuckets(
            required=required,
            avoid=avoid,
            low_coverage_candidates=low_coverage,
        ),
        term_signals=signals,
        usage_recommendations=usage_models,
        target_keyword=target_record,
        warnings=warnings,
    )

    # Write to cache (non-blocking via fire-and-forget; await for now to ensure write before return)
    await cache.write_cache(
        keyword=keyword,
        location_code=req.location_code,
        outlier_mode=req.outlier_mode,
        schema_version="1.1",
        output_payload=response.model_dump(mode="json"),
        duration_ms=duration_ms,
    )

    return response


async def _run_track_a(
    pages: list[PageZones],
    keyword: str,
    page_to_classified: dict,
) -> tuple[dict[str, TermAggregate], dict[str, float], dict[str, float], TermSignals]:
    """Track A: n-grams → subsumption → coverage gate → TF-IDF → semantic filter."""
    aggregates = analyze_pages(pages)
    merges = apply_subsumption(aggregates)

    top_pages_by_rank = {p.url: page_to_classified[p.url].rank for p in pages}
    coverage_filtered, _low_cov = apply_coverage_gate(
        aggregates, len(pages), keyword, top_pages_by_rank=top_pages_by_rank,
    )
    flag_template_boilerplate(aggregates)

    tfidf_scores, tfidf_filtered = compute_tfidf(aggregates, pages)
    sem_scores, sem_threshold = await filter_semantic(keyword, aggregates, tfidf_scores)

    # Apply semantic filter — drop terms below threshold unless zone-protected
    surviving: dict[str, TermAggregate] = {}
    for term, agg in aggregates.items():
        if agg.template_boilerplate:
            # Keep boilerplate so it ends up in `avoid` bucket
            surviving[term] = agg
            continue
        if not agg.passes_coverage_threshold:
            continue
        if not passes_tfidf(agg, tfidf_scores.get(term, 0.0)):
            continue
        sim = sem_scores.get(term, 0.0)
        if sim < sem_threshold and not is_zone_protected(agg):
            continue
        surviving[term] = agg

    signals = TermSignals(
        terms_filtered_by_coverage=coverage_filtered,
        terms_filtered_by_tfidf=tfidf_filtered,
        terms_passed_to_embedding=len(sem_scores),
        subsumption_merges=merges,
    )

    return (surviving, sem_scores, tfidf_scores, signals)


async def _run_track_b(
    pages: list[PageZones],
    *,
    keyword: str = "",
) -> tuple[list, list[str], int, int, int, list[int]]:
    """Track B: entity extraction + word count analysis.

    `keyword` is forwarded to entity scoring so any entity whose tokens
    appear in the user's seed keyword is auto-promoted (highest-priority
    `keyword_match` reason in PromotionReason).
    """
    entities_task = asyncio.create_task(extract_entities(pages, keyword=keyword))

    wc_min, wc_target, wc_max, source_counts = compute_word_count_target(pages)

    entities, failed_urls = await entities_task
    return (entities, failed_urls, wc_min, wc_target, wc_max, source_counts)
