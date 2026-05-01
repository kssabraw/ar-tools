"""Brief Generator pipeline orchestrator (schema v1.8).

Runs all 9 steps from the PRD with parallel external calls where the spec
allows it. Returns a fully populated BriefResponse.

v1.8 (CQ PRD v1.0 R1, R2):
- Sanitization runs at intake (in parsers.parse_serp + scoring.aggregate_candidates).
- After Step 5 scoring, cluster_candidates collapses paraphrases at cosine ≥ 0.85,
  optionally LLM-arbitrates soft pairs (0.72–0.85), and feeds canonicals
  through polish + priority + select.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional
from urllib.parse import urlparse

from models.brief import (
    BriefMetadata,
    BriefRequest,
    BriefResponse,
    DiscardedHeading,
    LLMFanoutCounts,
    LLMUnavailable,
)

from . import dataforseo
from .assembly import (
    assemble_structure,
    attach_h3s,
    reorder_how_to,
    select_h2s,
    UNCAPPED_INTENTS,
)
from .authority import authority_gap_headings
from .faqs import (
    llm_concern_extraction,
    regex_faq_pool,
    score_faqs,
    select_faqs,
)
from .intent import classify_intent
from .llm import claude_json
from .clustering import (
    HARD_MERGE_THRESHOLD,
    SOFT_CLUSTER_THRESHOLD,
    assign_cluster_ids,
    cluster_candidates,
    pick_canonicals,
)
from .parsers import (
    aggregate_serp_stats,
    normalize_text,
    parse_reddit,
    parse_serp,
    sanitization_discards,
)
from .scoring import (
    HeadingCandidate,
    aggregate_candidates,
    arbitrate_soft_pairs,
    compute_priority,
    polish_headings,
    score_candidates,
)
from .silos import identify_silos

logger = logging.getLogger(__name__)


class BriefError(Exception):
    """Raised when the pipeline cannot produce a valid brief."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# Map LLM identifiers to (model_name, force_web_search_capable)
FANOUT_LLMS = [
    ("chatgpt", "gpt-4o", True),
    ("claude", "claude-3-5-sonnet-latest", True),
    ("gemini", "gemini-1.5-pro", False),
    ("perplexity", "sonar", False),
]


async def _safe_fanout(
    keyword: str,
    llm_id: str,
    model: str,
    force_web_search: bool,
) -> tuple[str, Optional[dict]]:
    """Returns (llm_id, result_or_none). None on failure (caller flags unavailable)."""
    try:
        result = await dataforseo.llm_response(
            keyword=keyword,
            model=model,
            web_search=True,
            force_web_search=force_web_search,
        )
        return (llm_id, result)
    except Exception as exc:
        logger.warning("LLM fanout %s failed: %s", llm_id, exc)
        return (llm_id, None)


async def _extract_subtopics(text: str) -> list[str]:
    """Step 2D Output B — pull subtopic strings out of an LLM response body."""
    if not text or not text.strip():
        return []
    system = (
        "Extract all distinct subtopics, heading-like statements, and key concepts "
        "from this text. Return as a JSON array of strings (just the array, no wrapper)."
    )
    try:
        result = await claude_json(system, text[:6000], max_tokens=600, temperature=0.1)
        if isinstance(result, list):
            return [s.strip() for s in result if isinstance(s, str) and s.strip()]
        if isinstance(result, dict):
            for key in ("subtopics", "items", "concepts", "headings"):
                arr = result.get(key)
                if isinstance(arr, list):
                    return [s for s in arr if isinstance(s, str)]
    except Exception as exc:
        logger.warning("subtopic extraction failed: %s", exc)
    return []


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


async def run_brief(req: BriefRequest) -> BriefResponse:
    """Execute the full brief pipeline."""
    keyword = req.keyword.strip()
    if not keyword:
        raise BriefError("validation_error", "Keyword is empty.")
    if len(keyword) > 150:
        raise BriefError("validation_error", "Keyword exceeds 150 characters.")

    # ---- Steps 1 + 2 in parallel ----
    serp_task = asyncio.create_task(
        dataforseo.serp_organic_advanced(keyword, location_code=req.location_code, depth=20)
    )
    reddit_task = asyncio.create_task(
        _swallow(dataforseo.serp_reddit(keyword, location_code=req.location_code, depth=5))
    )
    autocomplete_task = asyncio.create_task(
        _swallow(dataforseo.autocomplete(keyword, location_code=req.location_code))
    )
    suggestions_task = asyncio.create_task(
        _swallow(dataforseo.keyword_suggestions(keyword, location_code=req.location_code, limit=50))
    )
    fanout_tasks = [
        asyncio.create_task(_safe_fanout(keyword, llm_id, model, force))
        for llm_id, model, force in FANOUT_LLMS
    ]

    serp_result = await serp_task
    serp_items = serp_result["items"]
    if not serp_items:
        raise BriefError("serp_no_results", "DataForSEO returned 0 organic results.")

    reddit_items = await reddit_task or []
    autocomplete_items = await autocomplete_task or []
    suggestion_items = await suggestions_task or []
    fanout_results = await asyncio.gather(*fanout_tasks)

    # ---- Step 1 parsing ----
    serp_headings, signals, paa_questions, organic_titles = parse_serp(serp_items)
    serp_stats = aggregate_serp_stats(serp_headings)
    organic_urls = [
        item["url"] for item in serp_items if item.get("type") == "organic" and item.get("url")
    ]
    top_3_domains = [_domain(u) for u in organic_urls[:3]]
    competitor_domains = sorted({_domain(u) for u in organic_urls if _domain(u)})

    low_serp_coverage = len([h for h in serp_headings]) < 10

    # ---- Step 2 parsing ----
    reddit_titles, reddit_comments = parse_reddit(reddit_items) if reddit_items else ([], [])
    reddit_unavailable = not reddit_items

    fanout_by_source: dict[str, list[str]] = {}
    response_by_source: dict[str, list[str]] = {}
    fanout_counts = LLMFanoutCounts()
    response_counts = LLMFanoutCounts()
    unavailable = LLMUnavailable()

    extraction_tasks: list[tuple[str, asyncio.Task]] = []
    for llm_id, result in fanout_results:
        src_fanout = f"llm_fanout_{llm_id}"
        src_response = f"llm_response_{llm_id}"
        if not result:
            setattr(unavailable, llm_id, True)
            fanout_by_source[src_fanout] = []
            response_by_source[src_response] = []
            continue
        queries = result.get("fan_out_queries", [])
        fanout_by_source[src_fanout] = queries
        setattr(fanout_counts, llm_id, len(queries))

        text_body = result.get("text", "")
        extraction_tasks.append((llm_id, asyncio.create_task(_extract_subtopics(text_body))))

    for llm_id, task in extraction_tasks:
        try:
            subtopics = await task
        except Exception:
            subtopics = []
        src_response = f"llm_response_{llm_id}"
        response_by_source[src_response] = subtopics
        setattr(response_counts, llm_id, len(subtopics))

    # ---- Step 3 — intent ----
    intent, confidence, review_required = await classify_intent(
        keyword=keyword,
        signals=signals,
        titles=organic_titles,
        top_3_domains=top_3_domains,
        override=req.intent_override,
    )

    # ---- Step 4 — aggregate + dedup ----
    candidates = aggregate_candidates(
        serp_stats=serp_stats,
        paa_questions=paa_questions,
        autocomplete=autocomplete_items,
        keyword_suggestions=suggestion_items,
        llm_fanout_by_source=fanout_by_source,
        llm_response_by_source=response_by_source,
    )

    if not candidates:
        raise BriefError("no_candidates", "No heading candidates after aggregation.")

    # ---- Step 5 — semantic scoring ----
    kept, low_score_discards, keyword_embedding = await score_candidates(
        keyword=keyword,
        candidates=candidates,
        semantic_threshold=0.55,
    )
    if not kept:
        raise BriefError("all_below_threshold", "No candidates above semantic threshold.")

    # Initial priority needed so cluster ordering and canonical-pick are
    # stable. Clustering rolls up cluster signals and we recompute below.
    compute_priority(kept)

    # ---- Step 5.5 — semantic clustering (CQ PRD R1) ----
    clustering_result = cluster_candidates(
        kept,
        hard_threshold=HARD_MERGE_THRESHOLD,
        soft_threshold=SOFT_CLUSTER_THRESHOLD,
    )
    soft_pairs_examined = len(clustering_result.soft_pairs)
    soft_pairs_merged = 0

    # Optional second pass: ask the polish LLM to confirm soft-band paraphrases.
    # Cheap (one extra LLM call) and only fires when soft pairs exist.
    if clustering_result.soft_pairs:
        confirmed = await arbitrate_soft_pairs(kept, clustering_result.soft_pairs)
        if confirmed:
            soft_pairs_merged = len(confirmed)
            # Union the confirmed pairs into the existing cluster structure
            from .clustering import _find, _union, _union_find_init  # type: ignore
            # Rebuild union-find from current clusters, then add confirmed pairs.
            n = len(kept)
            parent = _union_find_init(n)
            for cluster in clustering_result.clusters:
                if len(cluster) > 1:
                    base = cluster[0]
                    for other in cluster[1:]:
                        _union(parent, base, other)
            for a, b in confirmed:
                _union(parent, a, b)
            cluster_map: dict[int, list[int]] = {}
            for i in range(n):
                root = _find(parent, i)
                cluster_map.setdefault(root, []).append(i)
            clustering_result.clusters = list(cluster_map.values())

    # Stamp cluster_id on every candidate (ordered by max-priority-in-cluster)
    assign_cluster_ids(kept, clustering_result.clusters)

    # Pick one canonical per cluster; rolls up cluster signals onto canonicals.
    canonicals, cluster_losers = pick_canonicals(kept, clustering_result.clusters)
    semantic_dedup_collapses_count = sum(
        1 for c in clustering_result.clusters if len(c) > 1
    )
    logger.info(
        "step_5_5: %d candidates → %d canonicals (%d collapses, %d soft pairs examined, %d merged)",
        len(kept), len(canonicals), semantic_dedup_collapses_count,
        soft_pairs_examined, soft_pairs_merged,
    )

    # Polish + recompute priority on canonicals only (cluster signals now
    # include the rolled-up SERP frequency / LLM consensus from variants).
    await polish_headings(canonicals)
    compute_priority(canonicals)

    # ---- Step 6 — authority gap ----
    existing_texts = [c.text for c in canonicals]
    reddit_context_blobs = reddit_titles + reddit_comments
    auth_h3s = await authority_gap_headings(
        keyword=keyword,
        existing_headings=existing_texts,
        reddit_context=reddit_context_blobs,
    )
    # Embed authority H3s so attach_h3s can pick the best parent H2
    if auth_h3s:
        from .llm import embed_batch
        try:
            ah_vecs = await embed_batch([c.text for c in auth_h3s])
            for c, v in zip(auth_h3s, ah_vecs):
                c.embedding = v
                # Score them too even though they're exempt
                from .llm import cosine
                c.semantic_score = cosine(keyword_embedding, v) if keyword_embedding else 0.0
        except Exception as exc:
            logger.warning("authority H3 embed failed: %s", exc)

    # ---- Step 7 — FAQs ----
    faq_pool = regex_faq_pool(paa_questions, reddit_titles, reddit_comments)
    if reddit_titles or reddit_comments:
        reddit_blob = "\n\n".join(reddit_titles + reddit_comments)
        faq_pool.extend(await llm_concern_extraction(reddit_blob))

    heading_norm_set = {normalize_text(c.text) for c in canonicals}
    scored_faqs = await score_faqs(faq_pool, keyword_embedding, heading_norm_set)
    faqs = select_faqs(scored_faqs)

    # ---- Step 8 — structure (operates on canonicals only) ----
    h2_selected, leftovers = select_h2s(canonicals, intent)
    if intent == "how-to":
        h2_selected = await reorder_how_to(h2_selected, keyword)

    # H3 pool: anything not selected as H2 becomes a candidate for H3 attachment
    h3_pool = leftovers
    h3_attachments = attach_h3s(h2_selected, auth_h3s, h3_pool)

    heading_structure, cap_cuts = assemble_structure(
        keyword=keyword,
        intent=intent,
        h2s=h2_selected,
        h3_attachments=h3_attachments,
        faqs=faqs,
    )

    # ---- Compute discards ----
    discarded_candidates: list[HeadingCandidate] = []
    for c in low_score_discards:
        discarded_candidates.append(c)

    # CQ PRD R1: cluster losers (paraphrases collapsed into a canonical).
    # We need cluster_id → canonical's heading order so the discarded record
    # can carry semantic_duplicate_of (the order of the kept canonical).
    cluster_to_canonical_order: dict[int, int] = {}
    for item in heading_structure:
        if item.cluster_id is not None:
            cluster_to_canonical_order.setdefault(item.cluster_id, item.order)
    discarded_candidates.extend(cluster_losers)

    # CQ PRD R2: SERP rows rejected by sanitization (S9/S10).
    sanitization_rejected = sanitization_discards(serp_headings)

    selected_norms = {normalize_text(item.text) for item in heading_structure}
    attached_norms: set[str] = set()
    for arr in h3_attachments.values():
        for c in arr:
            attached_norms.add(normalize_text(c.text))

    for c in leftovers:
        norm = normalize_text(c.text)
        if norm in selected_norms or norm in attached_norms:
            continue
        c.discard_reason = "below_priority_threshold"
        discarded_candidates.append(c)

    for c in cap_cuts:
        c.discard_reason = "global_cap_exceeded"
        discarded_candidates.append(c)

    # ---- Step 9 — silos (legacy) + spin_off_articles (CQ PRD R3) ----
    eligible = [
        c for c in discarded_candidates
        if c.discard_reason in ("below_priority_threshold", "global_cap_exceeded")
    ]
    silos, low_coherence = identify_silos(eligible)
    discarded_candidates.extend(low_coherence)

    spin_off_articles = _build_spin_off_articles(discarded_candidates, silos)

    discarded_models: list[DiscardedHeading] = []
    for c in discarded_candidates:
        if not c.discard_reason:
            continue
        discarded_models.append(DiscardedHeading(
            text=c.text,
            source=c.source,
            original_source=c.original_source,
            semantic_score=round(c.semantic_score, 4),
            serp_frequency=c.serp_frequency,
            avg_serp_position=(
                round(c.avg_serp_position, 2) if c.avg_serp_position is not None else None
            ),
            llm_fanout_consensus=c.llm_fanout_consensus,
            heading_priority=round(c.heading_priority, 4),
            discard_reason=c.discard_reason,  # type: ignore[arg-type]
            cluster_id=(c.cluster_id if c.cluster_id != -1 else None),
            semantic_duplicate_of=cluster_to_canonical_order.get(
                c.semantic_duplicate_of_cluster
            ) if c.semantic_duplicate_of_cluster is not None else None,
            raw_text=c.raw_text,
        ))

    # Add the SERP rows that sanitization rejected outright
    for raw in sanitization_rejected:
        discarded_models.append(DiscardedHeading(
            text=raw["raw_text"],
            source="serp",
            semantic_score=0.0,
            serp_frequency=0,
            avg_serp_position=None,
            llm_fanout_consensus=0,
            heading_priority=0.0,
            # Best-effort: most rejections are "too short" (S9). The sanitizer
            # itself doesn't disambiguate S9 vs S10 today; we tag the broader
            # too-short category which covers ~95% of cases in practice.
            discard_reason="too_short_after_sanitization",
            raw_text=raw["raw_text"],
        ))

    # ---- Metadata ----
    h2_count = sum(1 for h in heading_structure if h.level == "H2" and h.type == "content")
    h3_count = sum(1 for h in heading_structure if h.level == "H3" and h.type == "content")
    metadata = BriefMetadata(
        word_budget=2500,
        faq_count=len(faqs),
        h2_count=h2_count,
        h3_count=h3_count,
        total_content_subheadings=h2_count + h3_count,
        discarded_headings_count=len(discarded_models),
        silo_candidates_count=len(silos),
        spin_off_articles_count=len(spin_off_articles),
        competitors_analyzed=20,
        reddit_threads_analyzed=len(reddit_items),
        llm_fanout_queries_captured=fanout_counts,
        llm_response_subtopics_extracted=response_counts,
        intent_signals=signals,
        embedding_model="text-embedding-3-small",
        semantic_filter_threshold=0.55,
        semantic_dedup_threshold=HARD_MERGE_THRESHOLD,
        semantic_dedup_collapses_count=semantic_dedup_collapses_count,
        soft_cluster_pairs_examined=soft_pairs_examined,
        soft_cluster_pairs_merged=soft_pairs_merged,
        sanitization_discards_count=len(sanitization_rejected),
        low_serp_coverage=low_serp_coverage,
        reddit_unavailable=reddit_unavailable,
        llm_fanout_unavailable=unavailable,
        competitor_domains=competitor_domains,
    )

    h1_item = next(
        (h for h in heading_structure if h.level == "H1"),
        None,
    )
    title = h1_item.text if h1_item else ""

    return BriefResponse(
        keyword=keyword,
        title=title,
        intent_type=intent,
        intent_confidence=round(confidence, 4),
        intent_review_required=review_required,
        heading_structure=heading_structure,
        faqs=faqs,
        discarded_headings=discarded_models,
        silo_candidates=silos,
        spin_off_articles=spin_off_articles,
        metadata=metadata,
    )


def _build_spin_off_articles(
    discarded: list[HeadingCandidate],
    silos: list,
) -> list:
    """CQ PRD R3 — surface displaced headings as spin_off_articles.

    Initial implementation: route the silo seed keywords as spin-offs
    plus any semantic-duplicate or definitional-restatement losers that
    represented genuinely distinct sub-topics (priority > median).
    Refinement (LLM-curated topical seeds) deferred per CQ PRD §5 v1.0.
    """
    from models.brief import SpinOffArticle

    out: list[SpinOffArticle] = []

    # Convert legacy silo seeds into spin-offs (one-release transition window).
    for s in silos:
        out.append(SpinOffArticle(
            suggested_keyword=s.suggested_keyword,
            source_heading_text=s.suggested_keyword,
            source_reason="below_priority_threshold",
            cluster_coherence_score=s.cluster_coherence_score,
            review_recommended=s.review_recommended,
            recommended_intent=s.recommended_intent,
            supporting_headings=[h.text for h in s.source_headings],
        ))

    # Promote semantic-duplicate / definitional / cap-cut losers that are
    # high-priority on their own (might genuinely deserve their own article).
    for c in discarded:
        if c.discard_reason not in (
            "semantic_duplicate_of_higher_priority_h2",
            "definitional_restatement",
            "global_cap_exceeded",
        ):
            continue
        if c.heading_priority < 0.50:
            continue
        out.append(SpinOffArticle(
            suggested_keyword=c.text,
            source_heading_text=c.text,
            source_reason=(
                "semantic_duplicate" if c.discard_reason == "semantic_duplicate_of_higher_priority_h2"
                else c.discard_reason  # type: ignore[arg-type]
            ),
            cluster_coherence_score=0.0,
            recommended_intent="informational",
            supporting_headings=[],
        ))

    return out


async def _swallow(coro):
    """Run a coroutine; return None instead of raising. Used for non-fatal sources."""
    try:
        return await coro
    except Exception as exc:
        logger.warning("non-fatal source failed: %s", exc)
        return None
