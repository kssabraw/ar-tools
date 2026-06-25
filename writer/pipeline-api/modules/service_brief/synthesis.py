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
    "headlines-as-copy. 'heading' is a working label, not finished copy.\n"
    "6. If a `client_reference_page_structure` is provided, mirror its section "
    "layout, ordering, and heading hierarchy as the page's structural baseline — "
    "then still apply rules 1-4 (the differentiator may reshape it). The "
    "reference shows how this client structures their own service pages; match "
    "that shape while adapting all wording to this service. If no reference is "
    "provided, design the structure from the research as usual.\n"
    "7. DECISION-FIT: if (and only if) this page genuinely serves a situational "
    "choice — the right answer depends on the buyer's situation (which "
    "tier/option/urgency level fits them, e.g. emergency vs scheduled, "
    "repair vs replace, residential vs commercial) — emit `decision_fit` with "
    "`applies:true` and 2+ DISTINCT condition->option branches grounded in what "
    "this business actually offers (never invent options). Otherwise emit "
    "`decision_fit` with `applies:false` and an empty branches list. Branches are "
    "condition-first; the writer weaves them into prose, so keep them plan-level "
    "(condition + which option), not finished copy.\n\n"
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
    '  "silo_candidates": [{"suggested_keyword": "...", "estimated_intent": "commercial"}],\n'
    '  "decision_fit": {"applies": true|false, "branches": '
    '[{"condition": "...", "option": "..."}], "default_statement": "..."}\n'
    "}"
)


# A location page is a multi-service hub for ONE location, not a single-service
# page. The architecture is section-per-service rather than a single deep service
# treatment, and the wedge is local (why this provider, in this area). The output
# JSON shape is identical to the service prompt so assembly is unchanged.
_LOCATION_SYNTHESIS_SYSTEM = (
    "You are a senior local-SEO conversion strategist producing the BRIEF (a "
    "plan, not copy) for one LOCATION landing page. This page targets a single "
    "location and must cover EACH major service the client offers in that area — "
    "it is a multi-service hub, not a single-service page. You receive (a) market "
    "truth from research, (b) the client's differentiator + ICP, and (c) the list "
    "of services to cover. Your job is RECONCILIATION + LOCAL relevance, not SERP "
    "echo.\n\n"
    "HARD RULES:\n"
    "1. Collapse ICP × differentiator × location into ONE positioning_angle (the "
    "wedge) — a specific local stance ('the <area> team that…'), not 'we offer X'.\n"
    "2. ARCHITECTURE must be section-per-service: open with a location intro / "
    "area-served section that establishes local relevance, then ONE H2 section "
    "per service in `services_to_cover` (each tied to this location — local proof, "
    "local intent, what the service means for buyers here), then a why-us / proof "
    "section, an FAQ, and a CTA. Do NOT collapse multiple services into one "
    "section and do NOT invent services beyond the provided list.\n"
    "3. The differentiator may OVERRIDE or RESHAPE the layout — resolve conflicts "
    "in the differentiator's favor unless it breaks local search-intent fit. The "
    "result must NOT be strategically identical to the ranking pages.\n"
    "4. Identify the top 2-3 OBJECTIONS a local buyer has and map each to a "
    "section or proof asset. For any section that deviates from the competitor "
    "skeleton, write a divergence_note explaining WHY.\n"
    "5. Directives are SECTION-LEVEL ONLY: purpose, what to cover, which proof "
    "asset, length target. NEVER write sentence-level prose, taglines, or "
    "headlines-as-copy. 'heading' is a working label, not finished copy.\n"
    "6. If a `client_reference_page_structure` is provided, mirror its section "
    "layout, ordering, and heading hierarchy as the structural baseline — then "
    "still apply rules 1-4 (the per-service sections are required regardless).\n"
    "7. DECISION-FIT: a location hub usually DOES serve a situational choice — "
    "'which of our services does your situation need here'. When that holds, emit "
    "`decision_fit` with `applies:true` and 2+ DISTINCT condition->option branches "
    "mapping a local buyer's situation to the right service/tier (grounded in "
    "services_to_cover — never invent options). If the page is single-purpose "
    "enough that no real choice exists, emit `applies:false` with an empty branches "
    "list. Branches are condition-first and plan-level (condition + which option), "
    "not finished copy.\n\n"
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
    '  "silo_candidates": [{"suggested_keyword": "...", "estimated_intent": "commercial"}],\n'
    '  "decision_fit": {"applies": true|false, "branches": '
    '[{"condition": "...", "option": "..."}], "default_statement": "..."}\n'
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
    page_type: str = "service",
    services: list[str] | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    """Run the reconciliation synthesis. Returns the raw JSON dict (assembly
    coerces it into the response schema).

    For a location page (`page_type='location'`) this uses the location-hub
    prompt and passes the services-to-cover + location so synthesis produces a
    section-per-service architecture; the output JSON shape is identical.
    """
    differentiator = _render_differentiator(client_context)
    if not differentiator:
        logger.warning(
            "service_brief.synthesis.no_differentiator",
            extra={"primary_query": primary_query},
        )

    is_location = page_type == "location"
    services = [s.strip() for s in (services or []) if s and s.strip()]

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

    # Location pages drive the section-per-service architecture off the explicit
    # services list + the target location.
    if is_location:
        payload["page_type"] = "location"
        payload["location"] = location or service
        payload["services_to_cover"] = services

    # Optional: mirror the client's own page layout for this page type. Additive —
    # when the client hasn't configured a reference page this key is omitted and
    # synthesis behaves exactly as before.
    if (client_context.reference_page_structure or "").strip():
        payload["client_reference_page_structure"] = client_context.reference_page_structure

    if is_location:
        user = (
            "Produce the LOCATION-page brief JSON for the following. Remember: one "
            "H2 section per service in services_to_cover, every section tied to the "
            "location, the differentiator reshapes the layout, and every divergence "
            "needs a note.\n\n" + str(payload)
        )
        system = _LOCATION_SYNTHESIS_SYSTEM
    else:
        user = (
            "Produce the service-page brief JSON for the following. Remember: the "
            "differentiator must reshape the skeleton, and every divergence needs a "
            "note.\n\n" + str(payload)
        )
        system = _SYNTHESIS_SYSTEM

    result = await claude_json_model(
        system,
        user,
        model=synthesis_model(),
        max_tokens=4000,
        temperature=0.4,
    )
    if not isinstance(result, dict):
        raise ValueError("synthesis returned a non-object payload")
    return result
