"""Research & Citations pipeline orchestrator (schema v1.1).

8 steps from the Research PRD:
0. Validate brief, extract H2s + top-3 authority gap H3s + competitor domains
1. LLM query generation per target (parallel)
2. DataForSEO web search per target (parallel)
3. Tier + recency filter
4. Content fetch (ScrapeOwl + PDF) with paywall/bot-block/language gates
5. Pre-LLM winner selection + claim extraction + verification + fallback chain
6. Citation scoring (>= 0.45 threshold; flag below) + dedup
7. Up to 4 supplemental article-level citations
8. Output assembly: citation_ids on every heading, citations array, metadata
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from models.research import (
    Citation,
    CitationsByScope,
    CitationsByTier,
    CitationsMetadata,
    ResearchClaim,
    ResearchRequest,
    ResearchResponse,
)
from modules.brief import dataforseo as dfs
from modules.brief.llm import cosine, embed_batch

from .extraction import ExtractedClaim, extract_claims, fallback_stub
from .fetcher import FetchedContent, fetch_many
from .queries import (
    generate_authority_gap_queries,
    generate_h2_queries,
    generate_supplemental_queries,
)
from .recency import recency_label_and_score
from .tiering import classify_tier, is_excluded, root_domain, tier_score

logger = logging.getLogger(__name__)

CITATION_SCORE_THRESHOLD = 0.45
MAX_AUTHORITY_GAP_CITATIONS = 3
MAX_SUPPLEMENTAL_CITATIONS = 4
TOP_CANDIDATES_PER_TARGET = 5
ACCESSIBLE_CANDIDATES_PER_TARGET = 3


class ResearchError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class CitationTarget:
    """A heading we need to find citations for."""

    target_id: str
    scope: str  # "heading" | "authority_gap" | "article"
    heading_text: str
    heading_order: Optional[int]
    parent_h2_text: Optional[str] = None
    h3_texts: list[str] = field(default_factory=list)


@dataclass
class CandidateSource:
    url: str
    title: str
    description: str
    fetched: Optional[FetchedContent] = None
    tier: Optional[int] = None
    recency_label: Optional[str] = None
    recency_score: float = 0.0
    recency_exception: bool = False
    pre_llm_score: float = 0.0
    meta_snippet_match: float = 0.0


def _extract_targets(brief: dict[str, Any]) -> tuple[list[CitationTarget], list[CitationTarget]]:
    """Returns (h2_targets, authority_gap_targets)."""
    structure = brief.get("heading_structure") or []
    if not isinstance(structure, list):
        raise ResearchError("invalid_brief", "heading_structure missing or not a list")

    h2_targets: list[CitationTarget] = []
    auth_gap_h3s: list[dict] = []
    for item in structure:
        if not isinstance(item, dict):
            continue
        level = item.get("level")
        item_type = item.get("type")
        text = item.get("text", "")
        if level == "H2" and item_type == "content" and "frequently asked" not in text.lower():
            order = item.get("order", 0)
            # Find H3s nested under this H2 (until next H2 in order)
            h3s_under = []
            for inner in structure:
                if not isinstance(inner, dict):
                    continue
                if inner.get("order", 0) <= order:
                    continue
                if inner.get("level") == "H2":
                    break
                if inner.get("level") == "H3" and inner.get("type") == "content":
                    h3s_under.append(inner.get("text", ""))
            h2_targets.append(CitationTarget(
                target_id=f"h2_{order}",
                scope="heading",
                heading_text=text,
                heading_order=order,
                h3_texts=h3s_under,
            ))
        elif (
            level == "H3"
            and item.get("source") == "authority_gap_sme"
        ):
            auth_gap_h3s.append(item)

    if not h2_targets:
        raise ResearchError("no_content_h2s", "Brief contains 0 content H2s")

    # Top 3 authority gap H3s by heading_priority
    auth_gap_h3s.sort(key=lambda h: h.get("heading_priority", 0.0), reverse=True)
    top_auth_gaps = auth_gap_h3s[:MAX_AUTHORITY_GAP_CITATIONS]

    auth_targets: list[CitationTarget] = []
    for h3 in top_auth_gaps:
        order = h3.get("order", 0)
        # Find the parent H2 (highest H2 order less than this H3's order)
        parent_text = ""
        for item in structure:
            if (
                isinstance(item, dict)
                and item.get("level") == "H2"
                and item.get("type") == "content"
                and item.get("order", 0) < order
            ):
                parent_text = item.get("text", "")
        auth_targets.append(CitationTarget(
            target_id=f"auth_{order}",
            scope="authority_gap",
            heading_text=h3.get("text", ""),
            heading_order=order,
            parent_h2_text=parent_text,
        ))

    return (h2_targets, auth_targets)


async def _generate_all_queries(
    keyword: str,
    intent_type: str,
    h2_targets: list[CitationTarget],
    auth_targets: list[CitationTarget],
) -> dict[str, list[str]]:
    """Generate queries per target in parallel. Returns target_id -> queries."""
    coros = []
    keys = []
    for t in h2_targets:
        coros.append(generate_h2_queries(keyword, t.heading_text, t.h3_texts, intent_type))
        keys.append(t.target_id)
    for t in auth_targets:
        coros.append(generate_authority_gap_queries(keyword, t.parent_h2_text or "", t.heading_text, intent_type))
        keys.append(t.target_id)
    results = await asyncio.gather(*coros, return_exceptions=True)
    out: dict[str, list[str]] = {}
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            out[key] = []
        else:
            out[key] = result
    return out


async def _search_for_target(
    queries: list[str],
    competitor_domains: frozenset[str],
) -> list[CandidateSource]:
    """Run DataForSEO web search per query, dedup, and return candidate URLs."""
    if not queries:
        return []
    search_coros = [
        dfs.serp_organic_advanced(q, depth=5) for q in queries
    ]
    results = await asyncio.gather(*search_coros, return_exceptions=True)

    seen: dict[str, CandidateSource] = {}
    for q_idx, result in enumerate(results):
        if isinstance(result, Exception):
            continue
        items = (result or {}).get("items") or []
        for item in items:
            if item.get("type") != "organic":
                continue
            url = item.get("url", "")
            if not url:
                continue
            if is_excluded(url, competitor_domains):
                continue
            if url in seen:
                continue
            seen[url] = CandidateSource(
                url=url,
                title=item.get("title", ""),
                description=item.get("description", ""),
            )
    return list(seen.values())


def _filter_and_sort(candidates: list[CandidateSource]) -> list[CandidateSource]:
    """Apply tier classification + sort by tier then recency. Drop dateless."""
    out: list[CandidateSource] = []
    for c in candidates:
        c.tier = classify_tier(c.url)
        out.append(c)
    # Sort by (tier, recency placeholder) — recency comes after fetch
    out.sort(key=lambda c: c.tier or 99)
    return out[:TOP_CANDIDATES_PER_TARGET]


def _accessible(c: CandidateSource) -> bool:
    if not c.fetched or not c.fetched.success:
        return False
    if c.fetched.paywall_detected or c.fetched.bot_block_detected:
        return False
    if c.fetched.language != "en":
        return False
    if not c.fetched.published_iso:
        return False
    return True


async def _fetch_and_filter(candidates: list[CandidateSource]) -> list[CandidateSource]:
    """Fetch candidates, set recency, and return top-3 accessible."""
    if not candidates:
        return []
    contents = await fetch_many([c.url for c in candidates])
    for c, fc in zip(candidates, contents):
        c.fetched = fc
        if fc.published_iso:
            from datetime import datetime as _dt

            try:
                published_dt = _dt.fromisoformat(fc.published_iso)
            except Exception:
                published_dt = None
            label, score, exception = recency_label_and_score(
                published_dt, c.tier or 3, is_foundational=False,
            )
            c.recency_label = label
            c.recency_score = score
            c.recency_exception = exception

    accessible = [c for c in candidates if _accessible(c) and c.recency_label]
    # Sort by tier then recency
    recency_order = {"fresh": 0, "dated": 1, "stale": 2}
    accessible.sort(key=lambda c: (c.tier or 99, recency_order.get(c.recency_label or "stale", 99)))
    return accessible[:ACCESSIBLE_CANDIDATES_PER_TARGET]


async def _select_and_extract(
    keyword: str,
    target: CitationTarget,
    candidates: list[CandidateSource],
) -> Optional[tuple[CandidateSource, list[ExtractedClaim], bool]]:
    """Returns (winner, verified_claims, used_fallback) or None on full failure."""
    if not candidates:
        return None

    # Pre-LLM scoring with meta snippet relevance
    snippet_texts = [target.heading_text] + [c.description or c.title for c in candidates]
    try:
        vectors = await embed_batch(snippet_texts)
        heading_vec = vectors[0]
        for c, v in zip(candidates, vectors[1:]):
            c.meta_snippet_match = cosine(heading_vec, v)
    except Exception:
        for c in candidates:
            c.meta_snippet_match = 0.0

    for c in candidates:
        c.pre_llm_score = (
            0.50 * tier_score(c.tier or 3)
            + 0.35 * c.recency_score
            + 0.15 * c.meta_snippet_match
        )

    candidates.sort(key=lambda c: c.pre_llm_score, reverse=True)

    # Try winner, then rank 2, then rank 3
    for candidate in candidates[:ACCESSIBLE_CANDIDATES_PER_TARGET]:
        claims = await extract_claims(
            keyword=keyword,
            heading_text=target.heading_text,
            source_text=candidate.fetched.body_text if candidate.fetched else "",
        )
        if claims:
            return (candidate, claims, False)

    # Fallback stub on rank-1
    rank1 = candidates[0]
    stub = fallback_stub(rank1.title, rank1.fetched.body_text[:200] if rank1.fetched else "")
    return (rank1, [stub], True)


async def _process_target(
    keyword: str,
    target: CitationTarget,
    queries: list[str],
    competitor_domains: frozenset[str],
) -> Optional[Citation]:
    """End-to-end: search → filter → fetch → extract → score for one target."""
    candidates = await _search_for_target(queries, competitor_domains)
    candidates = _filter_and_sort(candidates)
    accessible = await _fetch_and_filter(candidates)
    if not accessible:
        return None

    selection = await _select_and_extract(keyword, target, accessible)
    if not selection:
        return None
    winner, claims, used_fallback = selection

    max_relevance = max((c.relevance_score for c in claims), default=0.30)
    citation_score = (
        0.40 * tier_score(winner.tier or 3)
        + 0.30 * winner.recency_score
        + 0.30 * max_relevance
    )
    quality_low = citation_score < CITATION_SCORE_THRESHOLD or used_fallback

    return Citation(
        citation_id="",  # assigned later
        heading_order=target.heading_order,
        heading_text=target.heading_text,
        scope=target.scope,  # type: ignore[arg-type]
        url=winner.url,
        title=winner.fetched.title or winner.title,
        author=winner.fetched.author if winner.fetched else None,
        publication=winner.fetched.publication if winner.fetched else None,
        published_date=winner.fetched.published_iso if winner.fetched else None,
        tier=winner.tier or 3,  # type: ignore[arg-type]
        recency_label=winner.recency_label or "stale",  # type: ignore[arg-type]
        recency_exception=winner.recency_exception,
        pdf_source=winner.fetched.is_pdf if winner.fetched else False,
        language_detected=winner.fetched.language if winner.fetched else "en",
        citation_score=round(citation_score, 4),
        citation_quality_low=quality_low,
        paywall_detected=False,
        bot_block_detected=False,
        claim_extraction_failed=used_fallback,
        claims=[
            ResearchClaim(
                claim_text=c.claim_text,
                relevance_score=c.relevance_score,
                extraction_method=c.extraction_method,
                verification_method=c.verification_method,
            )
            for c in claims
        ],
    )


async def run_research(req: ResearchRequest) -> ResearchResponse:
    brief = req.brief_output
    if not isinstance(brief, dict):
        raise ResearchError("invalid_brief", "brief_output must be a dict")

    keyword = req.keyword.strip()
    intent_type = brief.get("intent_type", "informational")

    metadata = brief.get("metadata") or {}
    competitor_list = metadata.get("competitor_domains") or []
    competitor_domains = frozenset(competitor_list)
    competitor_unavailable = not competitor_list

    h2_targets, auth_targets = _extract_targets(brief)
    all_targets = h2_targets + auth_targets

    # Step 1: query generation in parallel
    queries_by_target = await _generate_all_queries(keyword, intent_type, h2_targets, auth_targets)

    # Steps 2-6: process each target in parallel
    target_coros = [
        _process_target(
            keyword=keyword,
            target=t,
            queries=queries_by_target.get(t.target_id, []),
            competitor_domains=competitor_domains,
        )
        for t in all_targets
    ]
    target_citations = await asyncio.gather(*target_coros, return_exceptions=True)

    citations: list[Citation] = []
    target_to_citation_id: dict[str, str] = {}
    citation_counter = 1

    for target, citation in zip(all_targets, target_citations):
        if isinstance(citation, Exception):
            logger.warning("Target %s failed: %s", target.target_id, citation)
            continue
        if citation is None:
            continue
        cid = f"cit_{citation_counter:03d}"
        citation_counter += 1
        citation.citation_id = cid
        target_to_citation_id[target.target_id] = cid
        citations.append(citation)

    # Step 7: supplemental citations (article scope)
    supplemental_added = 0
    try:
        supp_queries = await generate_supplemental_queries(keyword, intent_type)
        supp_target = CitationTarget(
            target_id="article_supplemental",
            scope="article",
            heading_text=keyword,
            heading_order=None,
        )
        supp_candidates = await _search_for_target(supp_queries, competitor_domains)
        # Skip URLs we've already cited
        already_used = {c.url for c in citations}
        supp_candidates = [c for c in supp_candidates if c.url not in already_used]
        supp_candidates = _filter_and_sort(supp_candidates)
        supp_accessible = await _fetch_and_filter(supp_candidates)

        for candidate in supp_accessible[:MAX_SUPPLEMENTAL_CITATIONS]:
            single = await _select_and_extract(keyword, supp_target, [candidate])
            if not single:
                continue
            winner, claims, used_fb = single
            max_rel = max((c.relevance_score for c in claims), default=0.30)
            score = (
                0.40 * tier_score(winner.tier or 3)
                + 0.30 * winner.recency_score
                + 0.30 * max_rel
            )
            cid = f"cit_{citation_counter:03d}"
            citation_counter += 1
            supplemental_added += 1
            citations.append(Citation(
                citation_id=cid,
                heading_order=None,
                heading_text=None,
                scope="article",
                url=winner.url,
                title=winner.fetched.title or winner.title,
                author=winner.fetched.author if winner.fetched else None,
                publication=winner.fetched.publication if winner.fetched else None,
                published_date=winner.fetched.published_iso if winner.fetched else None,
                tier=winner.tier or 3,  # type: ignore[arg-type]
                recency_label=winner.recency_label or "stale",  # type: ignore[arg-type]
                recency_exception=winner.recency_exception,
                pdf_source=winner.fetched.is_pdf if winner.fetched else False,
                language_detected=winner.fetched.language if winner.fetched else "en",
                citation_score=round(score, 4),
                citation_quality_low=score < CITATION_SCORE_THRESHOLD or used_fb,
                claim_extraction_failed=used_fb,
                claims=[
                    ResearchClaim(
                        claim_text=c.claim_text,
                        relevance_score=c.relevance_score,
                        extraction_method=c.extraction_method,
                        verification_method=c.verification_method,
                    )
                    for c in claims
                ],
            ))
    except Exception as exc:
        logger.warning("Supplemental citations failed: %s", exc)

    # Mark shared citations
    url_count: dict[str, int] = {}
    for c in citations:
        url_count[c.url] = url_count.get(c.url, 0) + 1
    for c in citations:
        if url_count[c.url] > 1:
            c.shared_citation = True

    # Step 8: Output assembly
    enriched_brief = dict(brief)  # shallow copy
    new_structure = []
    for item in brief.get("heading_structure") or []:
        if not isinstance(item, dict):
            new_structure.append(item)
            continue
        new_item = dict(item)
        # Find citation IDs for this item
        order = item.get("order", -1)
        ids: list[str] = []
        for t in all_targets:
            if t.heading_order == order and t.target_id in target_to_citation_id:
                ids.append(target_to_citation_id[t.target_id])
        new_item["citation_ids"] = ids
        new_structure.append(new_item)
    enriched_brief["heading_structure"] = new_structure

    # Build metadata
    h2s_with = sum(1 for t in h2_targets if t.target_id in target_to_citation_id)
    auth_with = sum(1 for t in auth_targets if t.target_id in target_to_citation_id)
    by_scope = CitationsByScope()
    by_tier = CitationsByTier()
    for c in citations:
        if c.scope == "heading":
            by_scope.heading += 1
        elif c.scope == "authority_gap":
            by_scope.authority_gap += 1
        else:
            by_scope.article += 1
        if c.tier == 1:
            by_tier.tier_1 += 1
        elif c.tier == 2:
            by_tier.tier_2 += 1
        else:
            by_tier.tier_3 += 1

    citations_metadata = CitationsMetadata(
        total_citations=len(citations),
        unique_urls=len({c.url for c in citations}),
        citations_by_scope=by_scope,
        citations_by_tier=by_tier,
        h2s_with_citations=h2s_with,
        h2s_without_citations=len(h2_targets) - h2s_with,
        authority_gap_h3s_with_citations=auth_with,
        supplemental_citations_added=supplemental_added,
        competitor_exclusion_unavailable=competitor_unavailable,
    )

    # Inject citations array + citations_metadata into the enriched brief
    enriched_brief["citations"] = [c.model_dump(mode="json") for c in citations]
    new_metadata = dict(enriched_brief.get("metadata") or {})
    new_metadata["citations_metadata"] = citations_metadata.model_dump(mode="json")
    enriched_brief["metadata"] = new_metadata

    return ResearchResponse(
        enriched_brief=enriched_brief,
        citations=citations,
        citations_metadata=citations_metadata,
    )
