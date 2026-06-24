"""Stage 2 — competitor teardown (PRD §4.2).

Scrape the top organic **service pages** (directories/listicles already
filtered out in `serp.py`), strip to main content, and use the cheap LLM tier
to extract each page's section structure, proof assets, and coverage — NOT raw
DOM heading parsing (service-page markup is too inconsistent). A single
unfetchable/unparseable competitor degrades gracefully and never fails the
brief (PRD §8.5).
"""

from __future__ import annotations

import logging
from collections import Counter

from models.service_brief import CompetitorSection, CompetitorSkeleton, Gap
from modules.sie.scraper import ScrapeResult, scrape_many
from modules.sie.zones import PageZones, extract_zones

from .llm import claude_json_model, extraction_model

logger = logging.getLogger(__name__)

# Conversion-critical section types we expect a strong service page to carry.
# When most competitors omit one, that's an exploitable gap (PRD §4.2).
_HIGH_VALUE_TYPES: tuple[str, ...] = (
    "pricing", "process", "faq", "proof", "guarantee", "service_area",
)

_EXTRACTION_SYSTEM = (
    "You analyze a single competitor SERVICE PAGE (one service a business "
    "offers) and return its STRUCTURE only — never rewrite or summarize the "
    "marketing copy. Work from the provided headings and body text.\n\n"
    "Return ONLY this JSON object:\n"
    "{\n"
    '  "sections": [{"heading": "...", "section_type": "hero|services|benefits|'
    'process|pricing|service_area|proof|faq|cta|about|other", "approx_words": <int>}],\n'
    '  "proof_assets": ["case_study"|"certification"|"guarantee"|"review"|'
    '"award"|"stat"],\n'
    '  "coverage": ["short topic/entity phrases the page covers"]\n'
    "}\n\n"
    "Rules: classify each section by its conversion role; list proof_assets "
    "that actually appear; keep coverage to <= 15 concise phrases. No prose, "
    "no commentary."
)


def _truncate(text: str, limit: int = 6000) -> str:
    return text[:limit]


async def _extract_skeleton(zones: PageZones) -> CompetitorSkeleton:
    """Cheap-tier extraction of one page's structure. Falls back to a
    heading-derived skeleton if the LLM call fails (degraded, not fatal)."""
    heading_outline = {
        "h1": zones.h1[:5],
        "h2": zones.h2[:25],
        "h3": zones.h3[:30],
    }
    user = (
        f"HEADINGS:\n{heading_outline}\n\n"
        f"BODY (truncated):\n{_truncate(zones.body_text)}"
    )
    try:
        result = await claude_json_model(
            _EXTRACTION_SYSTEM,
            user,
            model=extraction_model(),
            max_tokens=1500,
            temperature=0.1,
        )
    except Exception as exc:
        logger.warning(
            "service_brief.teardown.extract_failed",
            extra={"url": zones.url, "error": str(exc)},
        )
        return _fallback_skeleton(zones)

    if not isinstance(result, dict):
        return _fallback_skeleton(zones)

    sections = [
        CompetitorSection(
            heading=str(s.get("heading", "")),
            section_type=str(s.get("section_type", "other")),
            approx_words=int(s.get("approx_words", 0) or 0),
        )
        for s in (result.get("sections") or [])
        if isinstance(s, dict)
    ]
    proof = [str(p) for p in (result.get("proof_assets") or []) if p]
    coverage = [str(c) for c in (result.get("coverage") or []) if c]
    return CompetitorSkeleton(
        url=zones.url,
        sections=sections or _fallback_skeleton(zones).sections,
        proof_assets=sorted(set(proof)),
        coverage=coverage[:15],
        word_count=zones.word_count,
    )


def _fallback_skeleton(zones: PageZones) -> CompetitorSkeleton:
    """Degraded skeleton straight from the page headings (LLM unavailable)."""
    sections = [
        CompetitorSection(heading=h, section_type="other")
        for h in zones.h2[:15]
    ]
    return CompetitorSkeleton(
        url=zones.url,
        sections=sections,
        word_count=zones.word_count,
    )


async def teardown_competitors(
    urls: list[str],
    *,
    max_pages: int = 5,
) -> tuple[list[CompetitorSkeleton], list[PageZones], list[str]]:
    """Scrape + tear down up to `max_pages` competitor service pages.

    Returns (skeletons, page_zones, degraded_notes). `page_zones` is returned
    so the caller can reuse the already-scraped content for entity extraction
    (one scrape, two consumers — no double fetch).
    """
    target = urls[:max_pages]
    notes: list[str] = []
    if not target:
        return [], [], ["no_service_page_urls"]

    results: list[ScrapeResult] = await scrape_many(target)

    page_zones: list[PageZones] = []
    skeletons: list[CompetitorSkeleton] = []
    for res in results:
        if not res.success:
            notes.append(f"scrape_failed:{res.url}:{res.failure_reason}")
            continue
        zones = extract_zones(res.url, res.html)
        if zones is None or not zones.body_text.strip():
            notes.append(f"unparseable:{res.url}")
            continue
        page_zones.append(zones)
        skeletons.append(await _extract_skeleton(zones))

    if not skeletons:
        notes.append("all_competitors_failed")
    return skeletons, page_zones, notes


def derive_gaps(skeletons: list[CompetitorSkeleton]) -> list[Gap]:
    """Heuristic gaps: conversion-critical section types most competitors omit.

    Deterministic (no LLM) so it's cheap and testable. A high-value section
    type present in fewer than 40% of analyzed competitors is flagged as an
    exploitable gap for the client to win on.
    """
    total = len(skeletons)
    if total == 0:
        return []
    type_counts: Counter[str] = Counter()
    for sk in skeletons:
        present = {s.section_type for s in sk.sections}
        for t in present:
            type_counts[t] += 1

    gaps: list[Gap] = []
    for t in _HIGH_VALUE_TYPES:
        count = type_counts.get(t, 0)
        if count / total < 0.4:
            gaps.append(Gap(
                topic=t,
                rationale=(
                    f"Only {count}/{total} analyzed competitors include a "
                    f"'{t}' section — an opportunity to differentiate."
                ),
            ))
    return gaps
