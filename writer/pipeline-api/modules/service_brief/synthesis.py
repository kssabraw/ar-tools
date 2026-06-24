"""Synthesis — the critical step (PRD §5).

Research describes market truth, which pulls every brief toward the same
skeleton the competitors already have. The client's `differentiator` + `icp`
are the only forces that push the brief AWAY from convergence. This step hands
the strong model BOTH the competitor skeleton and the differentiator and
instructs it to resolve conflicts in the differentiator's favor unless that
breaks intent-fit — collapsing `icp × differentiator × service` into a single
positioning angle (the wedge), mapping the top objections to sections, and
stamping a `divergence_note` on every section that deviates from the skeleton
(decision C: model reconciliation + divergence notes).
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from models.service_brief import ClientContextInput, ResearchBundle

from .llm import claude_json_model, synthesis_model

logger = logging.getLogger(__name__)


_SYNTHESIS_SYSTEM = (
    "You are a senior conversion strategist producing the BRIEF (a plan, not "
    "copy) for one commercial service page. You receive (a) the market truth "
    "from research and (b) the client's differentiator + ICP. Your job is "
    "RECONCILIATION, not SERP echo.\n\n"
    "HARD RULES:\n"
    "1. Collapse ICP × differentiator × service into ONE positioning_angle "
    "(the wedge) the whole page expresses — a specific stance for this buyer, "
    "not 'we offer X'.\n"
    "2. The differentiator may OVERRIDE or RESHAPE the competitor skeleton — "
    "not merely append a section. Resolve every conflict in the "
    "differentiator's favor UNLESS doing so breaks search-intent fit. The "
    "result must NOT be strategically identical to the current ranking pages.\n"
    "3. Identify the top 2-3 OBJECTIONS this page must win and map each to a "
    "section or proof asset.\n"
    "4. For every section that deviates from the competitor skeleton, write a "
    "divergence_note explaining WHY (tie it to the differentiator/ICP).\n"
    "5. Directives are SECTION-LEVEL ONLY: purpose, what to cover, which proof "
    "asset, length target. NEVER write sentence-level prose, taglines, or "
    "headlines-as-copy. 'heading' is a working label, not finished copy.\n\n"
    "Return ONLY this JSON object:\n"
    "{\n"
    '  "positioning_angle": "...",\n'
    '  "secondary_queries": ["..."],\n'
    '  "objections": [{"objection": "...", "where_addressed": "<section heading>"}],\n'
    '  "sections": [{"heading": "...", "level": "H1|H2|H3", "purpose": "...", '
    '"must_cover": ["entity/term"], "proof_asset": "case_study|certification|'
    'guarantee|review|stat|null", "length_target": <int words>, '
    '"citation_fit": true|false, "divergence_note": "... or null"}],\n'
    '  "cta_strategy": "...",\n'
    '  "cta_placement": ["after hero", "after proof", "end"],\n'
    '  "objection_preemption_map": {"objection": "section/tactic that defuses it"},\n'
    '  "internal_links": ["related service slug/topic"],\n'
    '  "faq_targets": ["question"],\n'
    '  "paa_targets": ["question"],\n'
    '  "silo_candidates": [{"suggested_keyword": "...", "recommended_intent": "commercial"}]\n'
    "}"
)


def _render_differentiator(ctx: ClientContextInput) -> str:
    """Render the wedge source from structured differentiators (or fallback)."""
    if ctx.differentiators:
        lines = []
        for d in ctx.differentiators:
            if not isinstance(d, dict):
                continue
            claim = d.get("claim") or ""
            mech = d.get("mechanism") or ""
            typ = d.get("type") or ""
            piece = claim
            if mech:
                piece += f" (because: {mech})"
            if typ:
                piece += f" [{typ}]"
            if piece.strip():
                lines.append(f"- {piece}")
        if lines:
            return "\n".join(lines)
    # Fallbacks when structured differentiators are absent.
    if ctx.brand_voice_text:
        return ctx.brand_voice_text[:1500]
    return ""


def _render_icp(ctx: ClientContextInput) -> str:
    if ctx.icp_text:
        return ctx.icp_text[:1500]
    if isinstance(ctx.icp, dict):
        return str({k: ctx.icp.get(k) for k in ("segments", "reasoning") if k in ctx.icp})[:1500]
    return ""


def _render_business_context(ctx: ClientContextInput) -> str:
    parts: list[str] = []
    if ctx.business_name:
        parts.append(f"Business: {ctx.business_name}")
    wa = ctx.website_analysis or {}
    if isinstance(wa, dict):
        if wa.get("services"):
            parts.append(f"Services offered: {wa['services'][:20]}")
        if wa.get("locations"):
            parts.append(f"Locations served: {wa['locations'][:20]}")
    gbp = ctx.gbp or {}
    if isinstance(gbp, dict):
        cat = gbp.get("gbp_category") or gbp.get("description")
        if cat:
            parts.append(f"GBP category/desc: {cat}")
        if gbp.get("gbp_review_count"):
            parts.append(
                f"Reviews: {gbp.get('gbp_review_count')} "
                f"(avg {gbp.get('gbp_rating')})"
            )
    return "\n".join(parts)


def _table_stakes(bundle: ResearchBundle) -> dict[str, Any]:
    """Compact summary of the competitor skeleton for the prompt."""
    type_counts: Counter[str] = Counter()
    proof_counts: Counter[str] = Counter()
    for sk in bundle.competitor_skeletons:
        for s in sk.sections:
            if s.section_type:
                type_counts[s.section_type] += 1
        for p in sk.proof_assets:
            proof_counts[p] += 1
    return {
        "common_section_types": [t for t, _ in type_counts.most_common(12)],
        "common_proof_assets": [p for p, _ in proof_counts.most_common(8)],
        "competitor_count": len(bundle.competitor_skeletons),
    }


async def synthesize(
    *,
    service: str,
    primary_query: str,
    bundle: ResearchBundle,
    client_context: ClientContextInput,
) -> dict[str, Any]:
    """Run the reconciliation synthesis. Returns the raw JSON dict (assembly
    coerces it into the response schema)."""
    differentiator = _render_differentiator(client_context)
    if not differentiator:
        logger.warning(
            "service_brief.synthesis.no_differentiator",
            extra={"primary_query": primary_query},
        )

    payload = {
        "service": service,
        "primary_query": primary_query,
        "mode": bundle.mode,
        "length_band": bundle.length_band,
        "target_word_count": bundle.serp_profile.target_word_count,
        "search_intent": bundle.serp_profile.search_intent,
        "table_stakes": _table_stakes(bundle),
        "competitor_skeletons": [
            {
                "url": sk.url,
                "sections": [
                    {"heading": s.heading, "type": s.section_type}
                    for s in sk.sections
                ],
                "proof_assets": sk.proof_assets,
            }
            for sk in bundle.competitor_skeletons
        ],
        "gaps": [{"topic": g.topic, "rationale": g.rationale} for g in bundle.gaps],
        "entity_coverage": [
            {"term": e.term, "category": e.category, "pages_found": e.pages_found}
            for e in bundle.entity_coverage[:30]
        ],
        "questions": [q.question for q in bundle.questions[:20]],
        "aio": {
            "present": bundle.aio_presence.available,
            "fanout": bundle.aio_presence.fanout_questions[:10],
        },
        "client_differentiator": differentiator,
        "client_icp": _render_icp(client_context),
        "client_business_context": _render_business_context(client_context),
    }

    user = (
        "Produce the service-page brief JSON for the following. Remember: the "
        "differentiator must reshape the skeleton, and every divergence needs a "
        "note.\n\n" + str(payload)
    )

    result = await claude_json_model(
        _SYNTHESIS_SYSTEM,
        user,
        model=synthesis_model(),
        max_tokens=4000,
        temperature=0.4,
    )
    if not isinstance(result, dict):
        raise ValueError("synthesis returned a non-object payload")
    return result
