"""The Service Page Brief's OWN research pipeline (PRD §4).

Runs in order; Stage 1 (SERP composition) gates the rest. Reuses helper CODE
from the blog brief + SIE modules (DataForSEO client, SERP/AIO parsers, the
ScrapeOwl scraper, zone extraction, entity extraction) but never reads another
module's stored outputs — it fetches fresh.

Stages:
  1. SERP composition + intent/shape  -> SerpProfile (mode, length_band)
  2. Competitor teardown              -> competitor_skeletons[], gaps[]
  3. Entity & term coverage           -> entity_coverage[]
  4. Question mining                  -> questions[]
  5. AI Overview presence             -> aio_presence
"""

from __future__ import annotations

import logging
import statistics

from models.service_brief import (
    AioPresence,
    EntityCoverageItem,
    MinedQuestion,
    ResearchBundle,
)
from modules.brief.dataforseo import (
    DataForSEOError,
    autocomplete,
    serp_organic_advanced,
)
from modules.brief.parsers import parse_aio_insights, parse_serp
from modules.sie.entities import extract_entities

from .competitor import derive_gaps, teardown_competitors
from .entity_benchmark import aggressive_entity_target, counts_from_source_urls
from .errors import ServiceBriefError
from .serp import (
    band_for_word_count,
    classify_serp,
    competitor_avg_words,
    filter_service_page_urls,
    serp_word_target,
    target_words_for_band,
)

logger = logging.getLogger(__name__)

MAX_COMPETITORS = 5
MAX_QUESTIONS = 25


def _infer_intent(service_pages: int, directories: int, informational: int) -> str:
    """Lightweight intent validation from SERP composition (PRD §4.1).

    Service/landing keywords should surface commercial SERPs. When informational
    results dominate, flag it so synthesis knows the page is fighting intent.
    """
    commercial = service_pages + directories
    if informational > commercial:
        return "informational"
    return "commercial"


def _anchor_query(
    *,
    page_type: str,
    primary_query: str,
    services: list[str] | None,
    location: str | None,
) -> str:
    """Pick the single representative SERP query.

    For a service page that's the `primary_query`. A location page covers many
    services, so it anchors research on the most representative single query —
    the first listed service in the target location (e.g. "emergency plumber
    Austin") — falling back to `primary_query` when services/location are absent.
    """
    if page_type == "location" and services:
        head = (services[0] or "").strip()
        if head:
            return f"{head} {location}".strip() if location else head
    return primary_query


async def run_research(
    *,
    service: str,
    primary_query: str,
    location: str | None,
    location_code: int,
    page_type: str = "service",
    services: list[str] | None = None,
) -> ResearchBundle:
    """Execute the standalone research pipeline and return the bundle."""
    notes: list[str] = []
    anchor = _anchor_query(
        page_type=page_type,
        primary_query=primary_query,
        services=services,
        location=location,
    )

    # ---- Stage 1: SERP composition (gating) ----
    try:
        serp = await serp_organic_advanced(anchor, location_code=location_code)
    except (DataForSEOError, Exception) as exc:
        # No SERP → no market truth to build from. This is fatal (PRD §4.1).
        raise ServiceBriefError(
            "serp_unavailable",
            f"Could not fetch SERP for '{primary_query}': {exc}",
        ) from exc

    items = serp.get("items") or []
    _headings, signals, paa_questions, _titles, _metas = parse_serp(items)
    service_urls = filter_service_page_urls(items)

    profile = classify_serp(
        items,
        location=location,
        has_local_pack=signals.local_pack,
        has_featured_snippet=signals.featured_snippet,
    )
    # Intent validation off the authoritative bucket counts from the profile.
    profile.search_intent = _infer_intent(
        service_pages=profile.organic_service_pages,
        directories=profile.directory_aggregator_count,
        informational=profile.informational_count,
    )
    if profile.search_intent == "informational":
        notes.append("serp_intent_informational")

    # ---- Stage 2: Competitor teardown ----
    skeletons, page_zones, teardown_notes = await teardown_competitors(
        service_urls, max_pages=MAX_COMPETITORS
    )
    notes.extend(teardown_notes)
    gaps = derive_gaps(skeletons)

    # SERP-anchored length target: the competitor SERP average + 20%, floored
    # (mirrors nlp-api length_fit — SERP drives length). The band is kept only as a
    # coarse label + a fallback when too few competitor pages scraped to yield a
    # reliable average. Still fully SERP-derived (PRD §8.2), just anchored to the
    # real competitor length instead of a fixed 700/1200/1800 bucket.
    word_counts = [sk.word_count for sk in skeletons if sk.word_count > 0]
    if word_counts:
        median_words = int(statistics.median(word_counts))
        profile.length_band = band_for_word_count(median_words)  # coarse label only
        avg = competitor_avg_words(word_counts)
        profile.serp_avg_word_count = int(round(avg)) if avg else 0
        profile.target_word_count = serp_word_target(avg) or target_words_for_band(
            profile.length_band
        )

    # ---- Stage 3: Entity & term coverage (reuse already-scraped pages) ----
    entity_coverage: list[EntityCoverageItem] = []
    entity_benchmark_target = 0
    if page_zones:
        try:
            entities, failed = await extract_entities(page_zones, keyword=anchor)
            for ent in entities:
                entity_coverage.append(EntityCoverageItem(
                    term=ent.name,
                    category=ent.category,
                    pages_found=ent.pages_found,
                    salience=round(ent.avg_salience, 3),
                ))
            # Benchmark the required entity count against the most aggressive
            # competitor: the single page covering the most distinct entities
            # (spam outliers excluded). Uses each entity's source_urls to derive
            # per-competitor distinct-entity counts.
            per_url = counts_from_source_urls(ent.source_urls for ent in entities)
            entity_benchmark_target = aggressive_entity_target(per_url.values())
            if failed:
                notes.append(f"entity_extract_failed:{len(failed)}")
        except Exception as exc:
            logger.warning("service_brief.research.entities_failed", extra={"error": str(exc)})
            notes.append("entity_extract_unavailable")

    # ---- Stage 4: Question mining (PAA + related searches + autocomplete) ----
    questions: list[MinedQuestion] = [
        MinedQuestion(question=q, source="paa") for q in paa_questions
    ]
    # Related searches come from the SERP we already fetched — no extra API call.
    for item in items:
        if item.get("type") != "related_searches":
            continue
        for rs in item.get("items") or []:
            text = rs if isinstance(rs, str) else (rs.get("title") or rs.get("query") or "")
            if text and text.strip():
                questions.append(MinedQuestion(question=text.strip(), source="related_search"))
    try:
        for sug in await autocomplete(anchor, location_code=location_code):
            if "?" in sug or sug.lower().startswith(("how", "what", "why", "can", "do", "is")):
                questions.append(MinedQuestion(question=sug, source="autocomplete"))
    except Exception as exc:
        logger.warning("service_brief.research.autocomplete_failed", extra={"error": str(exc)})
        notes.append("autocomplete_unavailable")
    # De-dup while preserving order; cap.
    seen: set[str] = set()
    deduped: list[MinedQuestion] = []
    for q in questions:
        key = q.question.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(q)
    questions = deduped[:MAX_QUESTIONS]

    # ---- Stage 5: AI Overview presence ----
    aio = parse_aio_insights(items)
    aio_presence = AioPresence(
        available=aio.available,
        cited_domains=aio.cited_domains,
        fanout_questions=aio.fanout_questions,
    )

    logger.info(
        "service_brief.research.complete",
        extra={
            "primary_query": primary_query,
            "mode": profile.mode,
            "length_band": profile.length_band,
            "competitors": len(skeletons),
            "entities": len(entity_coverage),
            "questions": len(questions),
            "aio": aio_presence.available,
            "degraded_notes": notes,
        },
    )

    return ResearchBundle(
        serp_profile=profile,
        mode=profile.mode,
        length_band=profile.length_band,
        competitor_skeletons=skeletons,
        gaps=gaps,
        entity_coverage=entity_coverage,
        entity_benchmark_target=entity_benchmark_target,
        questions=questions,
        aio_presence=aio_presence,
        degraded_notes=notes,
    )
