"""Brief Generator pipeline orchestrator — schema v2.0.

Wires every step from PRD §5 in the order the spec mandates. The
orchestration shape:

    [Cache lookup] → Steps 1–2 in parallel → Step 3 → Step 3.5 →
    Step 4 (pass 1) → Step 5 (gates + graph + regions) →
    Step 6 (persona) → Step 4 (pass 2 with persona gap) →
    Step 5 augmentation (embed + add to graph) →
    Step 7 → Step 8 → Step 8.5 → Step 9 → Step 10 →
    Step 11 → Step 12 → assemble response → cache write

Failure handling matches PRD §7. The hard aborts:
  - SERP returns 0 organic results → BriefError("serp_no_results")
  - Title generation fails twice → BriefError("title_generation_failed")
  - Aggregation produces 0 candidates → BriefError("no_candidates")
  - Step 5 gates eliminate every candidate → BriefError("all_below_threshold")
  - Step 8 selects 0 H2s → BriefError("no_h2s_selected")

Everything else degrades gracefully: scope verification falls back to
accept-all, persona returns empty, FAQ extraction returns empty,
authority gap returns empty, etc.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional
from urllib.parse import urlparse

from config import settings
from models.brief import (
    BriefMetadata,
    BriefRequest,
    BriefResponse,
    DiscardedHeading,
    LLMFanoutCounts,
    LLMUnavailable,
    PersonaInfo,
)

from . import dataforseo
from .aggregation import aggregate_candidates
from .errors import BriefError
from .assembly import (
    assemble_structure,
    attach_authority_h3s_with_displacement,
    reorder_how_to,
)
from .authority import authority_gap_headings
from .cache import get_cached, write_cache
from .faqs import (
    llm_concern_extraction,
    regex_faq_pool,
    score_faqs,
    select_faqs,
)
from .graph import (
    Candidate,
    apply_region_outcomes,
    build_coverage_graph,
    detect_regions,
    embed_with_gates,
    score_regions,
)
from .h3_selection import select_h3s_for_h2s
from .intent import classify_intent
from .llm import claude_json, embed_batch_large
from .mmr import select_h2s_mmr
from .parsers import (
    aggregate_serp_stats,
    normalize_text,
    parse_reddit,
    parse_serp,
)
from .persona import generate_persona
from .priority import compute_priority
from .scope_verification import verify_h3_scope, verify_scope
from .silos import identify_silos, verify_silo_viability
from .title_scope import generate_title_and_scope

logger = logging.getLogger(__name__)


SCHEMA_VERSION = "2.0"


# Re-export for callers that historically imported BriefError from pipeline.
# Step modules raise it directly via .errors to avoid the circular import
# (title_scope → pipeline → title_scope).
__all__ = ["BriefError", "SCHEMA_VERSION", "run_brief"]


# Map LLM identifier → (model_name, force_web_search_capable). Mirrors v1.7
# until we wire upgraded models centrally.
FANOUT_LLMS: list[tuple[str, str, bool]] = [
    ("chatgpt", "gpt-4o", True),
    ("claude", "claude-3-5-sonnet-latest", True),
    ("gemini", "gemini-1.5-pro", False),
    ("perplexity", "sonar", False),
]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

async def _swallow(coro):
    """Run coroutine; log + return None on failure. Used for non-fatal sources."""
    try:
        return await coro
    except Exception as exc:
        logger.warning("brief.source.failed", extra={"error": str(exc)})
        return None


async def _safe_fanout(
    keyword: str,
    llm_id: str,
    model: str,
    force_web_search: bool,
) -> tuple[str, Optional[dict]]:
    """Returns (llm_id, result_or_none). None on failure → flagged unavailable."""
    try:
        result = await dataforseo.llm_response(
            keyword=keyword,
            model=model,
            web_search=True,
            force_web_search=force_web_search,
        )
        return (llm_id, result)
    except Exception as exc:
        logger.warning(
            "brief.llm_fanout.failed",
            extra={"llm_id": llm_id, "error": str(exc)},
        )
        return (llm_id, None)


async def _extract_subtopics(text: str) -> list[str]:
    """Pull subtopic strings out of an LLM response body (Step 2D Output B)."""
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
        logger.warning("brief.subtopic.extract_failed", extra={"error": str(exc)})
    return []


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


# ----------------------------------------------------------------------
# Cache → BriefResponse
# ----------------------------------------------------------------------

def _hydrate_cached(payload: dict) -> BriefResponse:
    """Rehydrate a cached payload into a BriefResponse.

    Pydantic v2 enforces extra='forbid' so cached rows from older schema
    versions raise ValidationError — caller catches that and treats as
    cache miss.
    """
    return BriefResponse.model_validate(payload)


# ----------------------------------------------------------------------
# Main orchestrator
# ----------------------------------------------------------------------

async def run_brief(req: BriefRequest) -> BriefResponse:
    """Execute the full v2.0 brief pipeline."""
    keyword = req.keyword.strip()
    if not keyword:
        raise BriefError("validation_error", "Keyword is empty.")
    if len(keyword) > 150:
        raise BriefError("validation_error", "Keyword exceeds 150 characters.")

    started_at = time.monotonic()

    # ---- Cache lookup (skip on force_refresh) ----
    if not req.force_refresh:
        cached = await get_cached(keyword=keyword, location_code=req.location_code)
        if cached is not None:
            try:
                return _hydrate_cached(cached)
            except Exception as exc:
                logger.warning(
                    "brief.cache.hydrate_failed",
                    extra={"error": str(exc)},
                )

    # ---- Steps 1 + 2 in parallel ----
    serp_task = asyncio.create_task(
        dataforseo.serp_organic_advanced(
            keyword, location_code=req.location_code, depth=20,
        )
    )
    reddit_task = asyncio.create_task(
        _swallow(dataforseo.serp_reddit(
            keyword, location_code=req.location_code, depth=5,
        ))
    )
    autocomplete_task = asyncio.create_task(
        _swallow(dataforseo.autocomplete(keyword, location_code=req.location_code))
    )
    suggestions_task = asyncio.create_task(
        _swallow(dataforseo.keyword_suggestions(
            keyword, location_code=req.location_code, limit=50,
        ))
    )
    fanout_tasks = [
        asyncio.create_task(_safe_fanout(keyword, llm_id, model, force))
        for llm_id, model, force in FANOUT_LLMS
    ]

    serp_result = await serp_task
    serp_items = serp_result["items"]
    if not serp_items:
        raise BriefError(
            "serp_no_results",
            "DataForSEO returned 0 organic results.",
        )

    reddit_items = await reddit_task or []
    autocomplete_items = await autocomplete_task or []
    suggestion_items = await suggestions_task or []
    fanout_results = await asyncio.gather(*fanout_tasks)

    # ---- Step 1 parsing (now returns 5-tuple incl. meta_descriptions) ----
    serp_headings, signals, paa_questions, organic_titles, meta_descriptions = parse_serp(
        serp_items
    )
    serp_stats = aggregate_serp_stats(serp_headings)

    organic_urls = [
        item["url"] for item in serp_items
        if item.get("type") == "organic" and item.get("url")
    ]
    organic_h1s = list(organic_titles)  # Step 3.5 treats SERP titles as H1s
    top_3_domains = [_domain(u) for u in organic_urls[:3]]
    competitor_domains = sorted({_domain(u) for u in organic_urls if _domain(u)})
    low_serp_coverage = len(serp_headings) < 10

    # ---- Step 2 parsing ----
    reddit_titles, reddit_comments = (
        parse_reddit(reddit_items) if reddit_items else ([], [])
    )
    reddit_unavailable = not reddit_items

    fanout_by_source: dict[str, list[str]] = {}
    response_by_source: dict[str, list[str]] = {}
    fanout_counts = LLMFanoutCounts()
    response_counts = LLMFanoutCounts()
    unavailable = LLMUnavailable()
    raw_fanout_bodies: list[str] = []  # for Step 3.5

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
        if text_body:
            raw_fanout_bodies.append(text_body)
        extraction_tasks.append(
            (llm_id, asyncio.create_task(_extract_subtopics(text_body)))
        )

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

    # ---- Step 3.5 — title + scope ----
    title_scope = await generate_title_and_scope(
        seed_keyword=keyword,
        intent_type=intent,
        serp_titles=organic_titles,
        serp_h1s=organic_h1s,
        meta_descriptions=meta_descriptions,
        fanout_response_bodies=raw_fanout_bodies,
    )

    # ---- Step 4 (pass 1) — aggregate without persona gap ----
    pass1 = aggregate_candidates(
        serp_stats=serp_stats,
        paa_questions=paa_questions,
        autocomplete=autocomplete_items,
        keyword_suggestions=suggestion_items,
        llm_fanout_by_source=fanout_by_source,
        llm_response_by_source=response_by_source,
    )
    if not pass1:
        raise BriefError("no_candidates", "No heading candidates after aggregation.")

    # ---- Step 5 — embed + gates ----
    gate_result = await embed_with_gates(
        seed=keyword,
        title=title_scope.title,
        scope_statement=title_scope.scope_statement,
        candidates=pass1,
        relevance_floor=settings.brief_relevance_floor,
        restatement_ceiling=settings.brief_restatement_ceiling,
    )
    title_embedding = gate_result.title_embedding
    if not gate_result.eligible:
        raise BriefError(
            "all_below_threshold",
            "No candidates above relevance gate after Step 5.",
        )

    # ---- Step 6 — persona generation (informational; never aborts) ----
    persona = await generate_persona(
        seed_keyword=keyword,
        intent_type=intent,
        title=title_scope.title,
        scope_statement=title_scope.scope_statement,
        serp_h1s=organic_h1s,
        meta_descriptions=meta_descriptions,
        candidate_headings=[c.text for c in gate_result.eligible],
    )
    persona_questions = [g.question for g in persona.gap_questions]

    # ---- Step 4 (pass 2) — re-aggregate with persona gap ----
    # We re-run aggregation so persona_gap can fuzzy-merge with existing
    # candidates (PRD §5 Step 4 ordering note). The Levenshtein dedup is
    # idempotent so this is safe.
    pass2 = aggregate_candidates(
        serp_stats=serp_stats,
        paa_questions=paa_questions,
        autocomplete=autocomplete_items,
        keyword_suggestions=suggestion_items,
        llm_fanout_by_source=fanout_by_source,
        llm_response_by_source=response_by_source,
        persona_gap_questions=persona_questions,
    )
    # Identify the new candidates (those not in pass1) and embed them.
    pass1_norms = {normalize_text(c.text) for c in pass1}
    new_candidates = [
        c for c in pass2 if normalize_text(c.text) not in pass1_norms
    ]

    # Carry forward gate decisions for the pass1 candidates: each pass2
    # candidate matching a pass1 candidate's normalized text inherits its
    # embedding + relevance + discard_reason (so the graph stays consistent).
    by_norm_p1 = {normalize_text(c.text): c for c in pass1}
    candidate_pool: list[Candidate] = []
    for c in pass2:
        existing = by_norm_p1.get(normalize_text(c.text))
        if existing is not None:
            # Pull pass1 state forward
            c.embedding = existing.embedding
            c.title_relevance = existing.title_relevance
            c.discard_reason = existing.discard_reason
        candidate_pool.append(c)

    # Embed the genuinely new (mostly persona_gap) candidates and apply
    # gates. embed_with_gates mutates the candidates in place — the
    # GateResult itself is unused here (the new candidates flow into
    # candidate_pool via shared object references).
    if new_candidates:
        await embed_with_gates(
            seed=keyword,
            title=title_scope.title,
            scope_statement=title_scope.scope_statement,
            candidates=new_candidates,
            relevance_floor=settings.brief_relevance_floor,
            restatement_ceiling=settings.brief_restatement_ceiling,
        )

    # Eligible pool for graph construction = pool members with embeddings
    # that survived the relevance/restatement gates.
    eligible_pool = [
        c for c in candidate_pool
        if c.embedding and c.discard_reason not in (
            "below_relevance_floor",
            "above_restatement_ceiling",
        )
    ]

    # ---- Step 5.3 / 5.4 / 5.5 — graph construction + regions ----
    graph = build_coverage_graph(
        eligible_pool, edge_threshold=settings.brief_edge_threshold,
    )
    regions = detect_regions(
        graph,
        resolution=settings.brief_louvain_resolution,
        seed=settings.brief_louvain_seed,
    )
    scored_regions = score_regions(
        regions, eligible_pool, title_embedding,
        relevance_floor=settings.brief_relevance_floor,
        restatement_ceiling=settings.brief_restatement_ceiling,
    )
    region_kept, region_eliminated = apply_region_outcomes(scored_regions, eligible_pool)

    if not region_kept:
        raise BriefError(
            "all_regions_eliminated",
            "Every coverage region was eliminated as off-topic or restating the title.",
        )

    # ---- Step 7 — priority scoring on remaining eligible pool ----
    compute_priority(region_kept)

    # ---- Step 8 — MMR H2 selection ----
    target_h2 = 6  # PRD §5 Step 8 baseline target; assembly will cap further
    selection = select_h2s_mmr(
        region_kept,
        target_count=target_h2,
        inter_heading_threshold=settings.brief_inter_heading_threshold,
        mmr_lambda=settings.brief_mmr_lambda,
    )
    if not selection.selected:
        raise BriefError(
            "no_h2s_selected",
            "MMR selected 0 H2s; outline cannot be assembled.",
        )

    # ---- Step 8.5 — scope verification ----
    scope_result = await verify_scope(
        title=title_scope.title,
        scope_statement=title_scope.scope_statement,
        selected_h2s=selection.selected,
    )
    selected_h2s = scope_result.kept

    if not selected_h2s:
        # If scope verification rejected every H2, accept the original
        # selection rather than abort — this is an extreme edge case.
        logger.warning(
            "brief.scope.all_rejected_falling_back",
            extra={"original_count": len(selection.selected)},
        )
        selected_h2s = selection.selected

    # ---- how-to reorder must run BEFORE Step 8.6 ----
    # Step 8.6's H3 attachments are keyed by H2 index. Reordering H2s
    # after attachment would put H3s under the wrong parents. Running
    # reorder first also lets the authority-gap agent see H2s in
    # narrative (setup → execution → validation) order.
    if intent == "how-to":
        selected_h2s = await reorder_how_to(selected_h2s, keyword)

    # ---- Step 8.6 — H3 selection (NEW in v2.0.x) ----
    # Per-H2 MMR over the eligible pool with parent_relevance bounds.
    # Non-authority H3s come from the MMR-loser pool; the H3 pool is
    # `selection.not_selected` PLUS region_kept members that were never
    # picked but stayed eligible.
    h3_pool = list(selection.not_selected)
    h3_selection_result = select_h3s_for_h2s(
        selected_h2s=selected_h2s,
        h3_pool=h3_pool,
        regions=scored_regions,
    )
    # Candidates attached as H3s should NOT carry below_priority_threshold.
    attached_h3_ids: set[int] = set()
    for arr in h3_selection_result.attachments.values():
        for h3 in arr:
            attached_h3_ids.add(id(h3))
            # Clear the MMR-loser stamp; this candidate is now an H3.
            if h3.discard_reason == "below_priority_threshold":
                h3.discard_reason = None

    # ---- Step 9 — authority gap H3s (PRD v2.0.3: scope-aware) ----
    existing_texts = [c.text for c in selected_h2s]
    for arr in h3_selection_result.attachments.values():
        existing_texts.extend(c.text for c in arr)
    auth_h3s = await authority_gap_headings(
        keyword=keyword,
        existing_headings=existing_texts,
        reddit_context=reddit_titles + reddit_comments,
        title=title_scope.title,
        scope_statement=title_scope.scope_statement,
        intent_type=intent,
    )
    if auth_h3s:
        try:
            ah_vecs = await embed_batch_large([c.text for c in auth_h3s])
            for c, v in zip(auth_h3s, ah_vecs):
                c.embedding = v
                # Stamp title_relevance for completeness; exempt=True bypasses gate.
                c.title_relevance = (
                    sum(a * b for a, b in zip(v, title_embedding))
                    if v and title_embedding else 0.0
                )
        except Exception as exc:
            logger.warning(
                "brief.authority.embed_failed",
                extra={"error": str(exc)},
            )

    # ---- Step 8.5b — Authority Gap H3 scope verification (PRD v2.0.3) ----
    # Catches H3s the agent produced that drift outside the brief's scope.
    # Out-of-scope H3s are removed from the attachment pool and routed to
    # silos with routed_from='scope_verification_h3'. Failures fall back
    # to accept-all-as-in_scope (never aborts the run).
    h3_scope_result = await verify_h3_scope(
        title=title_scope.title,
        scope_statement=title_scope.scope_statement,
        h3s=auth_h3s,
    )
    auth_h3s_kept = h3_scope_result.kept

    # Merge authority gap H3s into the per-H2 attachments with the
    # priority-comparison + recursive routing rules from PRD §5 Step 8.6.
    auth_attach = attach_authority_h3s_with_displacement(
        h2s=selected_h2s,
        authority_h3s=auth_h3s_kept,
        existing_attachments=h3_selection_result.attachments,
    )
    h3_attachments = auth_attach.attachments

    # ---- Step 10 — FAQ generation ----
    # Persona gap questions that did NOT make it into the H2 outline feed
    # the FAQ pool (PRD §5 Step 10 Source C).
    selected_norms = {normalize_text(c.text) for c in selected_h2s}
    persona_unused = [
        q for q in persona_questions
        if normalize_text(q) not in selected_norms
    ]

    faq_pool = regex_faq_pool(
        paa_questions=paa_questions,
        reddit_titles=reddit_titles,
        reddit_comments=reddit_comments,
        persona_gap_questions=persona_unused,
    )
    if reddit_titles or reddit_comments:
        reddit_blob = "\n\n".join(reddit_titles + reddit_comments)
        faq_pool.extend(await llm_concern_extraction(reddit_blob))

    heading_norm_set = {normalize_text(c.text) for c in selected_h2s}
    scored_faqs = await score_faqs(
        faq_pool, title_embedding, heading_norm_set,
    )
    faqs = select_faqs(scored_faqs)

    # ---- Step 11 — structure assembly ----
    # how-to reorder ran before Step 8.6 so attachment indices already
    # match the final H2 order; assemble_structure consumes them as-is.
    heading_structure, cap_cuts = assemble_structure(
        keyword=keyword,
        intent=intent,
        h2s=selected_h2s,
        h3_attachments=h3_attachments,
        faqs=faqs,
        title=title_scope.title,
    )

    # ---- Step 12 — silos (12.1 + 12.2 + 12.3 sync, then 12.4 async) ----
    contributing_region_ids = {
        c.region_id for c in selected_h2s if c.region_id is not None
    }
    silo_id_result = identify_silos(
        regions=scored_regions,
        candidate_pool=eligible_pool,
        contributing_region_ids=contributing_region_ids,
        scope_rejects=scope_result.rejected,
        h3_scope_rejects=h3_scope_result.rejected,
    )
    viability_result = await verify_silo_viability(
        silo_id_result.candidates,
        title=title_scope.title,
        scope_statement=title_scope.scope_statement,
    )
    silos = viability_result.candidates
    low_coherence = silo_id_result.low_coherence_candidates

    # ---- Build discarded_headings ----
    # The discarded list has multiple sources:
    #  - relevance gate (below_relevance_floor / above_restatement_ceiling)
    #  - region elimination (region_off_topic / region_restates_title)
    #  - MMR losers that didn't get promoted to H3 (below_priority_threshold)
    #  - scope verification rejects (scope_verification_out_of_scope)
    #  - Step 8.6 globally-rejected H3s (h3_below_parent_relevance_floor /
    #    h3_above_parent_restatement_ceiling)
    #  - authority-gap displacements (displaced_by_authority_gap_h3)
    #  - silos low_coherence (low_cluster_coherence)
    #  - global cap cuts (global_cap_exceeded)
    discarded: list[Candidate] = []

    for c in candidate_pool:
        if c.discard_reason in (
            "below_relevance_floor", "above_restatement_ceiling",
        ):
            discarded.append(c)

    discarded.extend(region_eliminated)
    # selection.not_selected: include only those NOT promoted to H3
    discarded.extend(
        c for c in selection.not_selected if id(c) not in attached_h3_ids
    )
    discarded.extend(scope_result.rejected)
    discarded.extend(h3_scope_result.rejected)
    discarded.extend(h3_selection_result.globally_rejected)
    discarded.extend(auth_attach.displaced)
    discarded.extend(low_coherence)

    for c in cap_cuts:
        c.discard_reason = "global_cap_exceeded"
        discarded.append(c)

    # Build DiscardedHeading models. Dedup by id() since some candidates
    # might appear in multiple buckets (e.g., a scope-rejected H2 is in
    # selection.selected but also scope_result.rejected — we want one row).
    seen_ids: set[int] = set()
    discarded_models: list[DiscardedHeading] = []
    for c in discarded:
        if id(c) in seen_ids:
            continue
        seen_ids.add(id(c))
        if not c.discard_reason:
            continue
        discarded_models.append(DiscardedHeading(
            text=c.text,
            source=c.source,
            original_source=c.original_source,
            title_relevance=round(c.title_relevance, 4),
            serp_frequency=c.serp_frequency,
            avg_serp_position=(
                round(c.avg_serp_position, 2)
                if c.avg_serp_position is not None else None
            ),
            llm_fanout_consensus=c.llm_fanout_consensus,
            heading_priority=round(c.heading_priority, 4),
            region_id=c.region_id,
            discard_reason=c.discard_reason,
        ))

    # ---- Build BriefMetadata ----
    h2_content_count = sum(
        1 for h in heading_structure if h.level == "H2" and h.type == "content"
    )
    h3_content_count = sum(
        1 for h in heading_structure if h.level == "H3" and h.type == "content"
    )

    region_off_topic = sum(
        1 for r in scored_regions if r.eliminated and r.elimination_reason == "off_topic"
    )
    region_restate = sum(
        1 for r in scored_regions
        if r.eliminated and r.elimination_reason == "restates_title"
    )

    # Step 8.6 H3 distribution stats (PRD §5 §6 metadata fields)
    h3_count_average = (
        h3_content_count / max(1, h2_content_count) if h2_content_count else 0.0
    )

    metadata = BriefMetadata(
        word_budget=2500,
        faq_count=len(faqs),
        h2_count=h2_content_count,
        h3_count=h3_content_count,
        total_content_subheadings=h2_content_count + h3_content_count,
        discarded_headings_count=len(discarded_models),
        silo_candidates_count=len(silos),
        competitors_analyzed=20,
        reddit_threads_analyzed=len(reddit_items),
        h2_shortfall=selection.shortfall,
        h2_shortfall_reason=selection.shortfall_reason,
        h3_count_average=round(h3_count_average, 4),
        h2s_with_zero_h3s=h3_selection_result.h2s_with_zero_h3s,
        regions_detected=len(scored_regions),
        regions_eliminated_off_topic=region_off_topic,
        regions_eliminated_restate_title=region_restate,
        regions_contributing_h2s=len(contributing_region_ids),
        scope_verification_borderline_count=scope_result.borderline_count,
        scope_verification_rejected_count=scope_result.rejected_count,
        silo_candidates_rejected_by_discard_reason=(
            silo_id_result.rejected_by_discard_reason_count
        ),
        silo_candidates_rejected_by_search_demand=(
            silo_id_result.rejected_by_search_demand_count
        ),
        silo_candidates_rejected_by_viability_check=viability_result.rejected_count,
        silo_viability_fallback_applied=viability_result.fallback_applied,
        llm_fanout_queries_captured=fanout_counts,
        llm_response_subtopics_extracted=response_counts,
        intent_signals=signals,
        embedding_model="text-embedding-3-large",
        relevance_floor_threshold=settings.brief_relevance_floor,
        restatement_ceiling_threshold=settings.brief_restatement_ceiling,
        inter_heading_threshold=settings.brief_inter_heading_threshold,
        edge_threshold=settings.brief_edge_threshold,
        mmr_lambda=settings.brief_mmr_lambda,
        # Step 8.6 + Step 12.3 thresholds (echoed for tuning)
        parent_relevance_floor_threshold=0.60,
        parent_restatement_ceiling_threshold=0.85,
        inter_h3_threshold=0.78,
        silo_search_demand_threshold=0.30,
        low_serp_coverage=low_serp_coverage,
        reddit_unavailable=reddit_unavailable,
        llm_fanout_unavailable=unavailable,
        competitor_domains=competitor_domains,
    )

    response = BriefResponse(
        keyword=keyword,
        title=title_scope.title,
        scope_statement=title_scope.scope_statement,
        title_rationale=title_scope.title_rationale,
        intent_type=intent,
        intent_confidence=round(confidence, 4),
        intent_review_required=review_required,
        persona=PersonaInfo(
            description=persona.description,
            background_assumptions=persona.background_assumptions,
            primary_goal=persona.primary_goal,
        ),
        heading_structure=heading_structure,
        faqs=faqs,
        discarded_headings=discarded_models,
        silo_candidates=silos,
        metadata=metadata,
    )

    # ---- Cache write (best-effort) ----
    duration_ms = int((time.monotonic() - started_at) * 1000)
    await write_cache(
        keyword=keyword,
        location_code=req.location_code,
        schema_version=SCHEMA_VERSION,
        output_payload=response.model_dump(mode="json"),
        triggered_by_client_id=req.client_id,
        duration_ms=duration_ms,
    )

    logger.info(
        "brief.complete",
        extra={
            "run_id": req.run_id,
            "keyword": keyword,
            "duration_ms": duration_ms,
            "h2_count": h2_content_count,
            "h3_count": h3_content_count,
            "faq_count": len(faqs),
            "silo_count": len(silos),
            "discard_count": len(discarded_models),
            "regions_detected": len(scored_regions),
            "h2_shortfall": selection.shortfall,
        },
    )
    return response
