"""Assembly — coerce the synthesis output into the clean 3-layer brief.

Only known directive fields are copied into `BriefSection`, so the output is
structurally guaranteed to carry section-level directives and NO sentence-level
prose (PRD §8.4). MUST fields get deterministic fallbacks so a happy-path brief
is never left with empty required fields (PRD §8.1).
"""

from __future__ import annotations

from typing import Any

from models.service_brief import (
    SCHEMA_VERSION,
    BriefSection,
    ConversionLayer,
    DecisionFit,
    DecisionFitBranch,
    Objection,
    ResearchBundle,
    ServiceBriefMetadata,
    ServiceBriefResponse,
    ServiceBriefRequest,
    ServiceSiloCandidate,
    StrategyLayer,
)

_VALID_LEVELS = {"H1", "H2", "H3"}


def _coerce_level(value: Any) -> str:
    level = str(value or "H2").upper()
    return level if level in _VALID_LEVELS else "H2"


def _coerce_proof(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    return None if text in ("null", "none", "") else str(value)


def _build_sections(raw_sections: list, target_word_count: int) -> list[BriefSection]:
    sections: list[BriefSection] = []
    for s in raw_sections or []:
        if not isinstance(s, dict):
            continue
        heading = str(s.get("heading", "")).strip()
        purpose = str(s.get("purpose", "")).strip()
        if not heading and not purpose:
            continue
        sections.append(BriefSection(
            heading=heading or purpose[:60],
            level=_coerce_level(s.get("level")),
            purpose=purpose or f"Cover: {heading}",
            must_cover=[str(m) for m in (s.get("must_cover") or []) if m],
            proof_asset=_coerce_proof(s.get("proof_asset")),
            length_target=int(s.get("length_target", 0) or 0),
            citation_fit=bool(s.get("citation_fit", False)),
            divergence_note=(str(s["divergence_note"]).strip()
                             if s.get("divergence_note") else None),
        ))

    # Distribute the SERP-derived word budget across content sections that
    # didn't get an explicit length_target.
    content = [s for s in sections if s.level in ("H2", "H3")]
    unset = [s for s in content if s.length_target <= 0]
    if unset and content:
        per = max(80, target_word_count // max(len(content), 1))
        for s in unset:
            s.length_target = per
    return sections


def _build_objections(raw: list) -> list[Objection]:
    out: list[Objection] = []
    for o in raw or []:
        if isinstance(o, dict) and o.get("objection"):
            out.append(Objection(
                objection=str(o["objection"]).strip(),
                where_addressed=str(o.get("where_addressed", "")).strip(),
            ))
        elif isinstance(o, str) and o.strip():
            out.append(Objection(objection=o.strip()))
    return out[:3]


def _build_silos(raw: list, primary_query: str) -> list[ServiceSiloCandidate]:
    out: list[ServiceSiloCandidate] = []
    seen: set[str] = set()
    for c in raw or []:
        kw = ""
        if isinstance(c, dict):
            kw = str(c.get("suggested_keyword", "")).strip()
        elif isinstance(c, str):
            kw = c.strip()
        key = kw.lower()
        if kw and key not in seen and key != primary_query.strip().lower():
            seen.add(key)
            intent = "commercial"
            if isinstance(c, dict):
                intent = (
                    str(c.get("estimated_intent") or c.get("recommended_intent") or "commercial").strip()
                    or "commercial"
                )
            out.append(ServiceSiloCandidate(suggested_keyword=kw, estimated_intent=intent))
    return out


def _build_decision_fit(raw: Any) -> DecisionFit | None:
    """Coerce synthesis's optional `decision_fit` into the model. Kept only when it
    applies AND there are >=2 distinct, non-empty condition->option branches (mirrors
    the fanout decision_fit gate); otherwise None so the writer skips it entirely."""
    if not isinstance(raw, dict) or not raw.get("applies"):
        return None
    branches: list[DecisionFitBranch] = []
    seen: set[str] = set()
    for b in (raw.get("branches") or []):
        if not isinstance(b, dict):
            continue
        condition = str(b.get("condition", "")).strip()
        option = str(b.get("option", "")).strip()
        if not condition or not option:
            continue
        key = condition.lower()
        if key in seen:
            continue
        seen.add(key)
        branches.append(DecisionFitBranch(condition=condition, option=option))
    if len(branches) < 2:
        return None
    return DecisionFit(
        applies=True,
        branches=branches,
        default_statement=str(raw.get("default_statement", "")).strip(),
    )


def assemble(
    request: ServiceBriefRequest,
    bundle: ResearchBundle,
    synthesis: dict[str, Any],
    *,
    cache_hit: bool,
    cost_usd: float = 0.0,
) -> ServiceBriefResponse:
    """Build the final `ServiceBriefResponse` from the synthesis output."""
    primary_query = request.primary_query
    target_words = bundle.serp_profile.target_word_count

    positioning = str(synthesis.get("positioning_angle", "")).strip()
    if not positioning:
        positioning = (
            f"{request.service}: the choice for buyers who value "
            f"{(bundle.gaps[0].topic if bundle.gaps else 'proven results')}."
        )

    strategy = StrategyLayer(
        positioning_angle=positioning,
        primary_query=primary_query,
        secondary_queries=[str(q) for q in (synthesis.get("secondary_queries") or []) if q],
        objections=_build_objections(synthesis.get("objections")),
    )

    architecture = _build_sections(synthesis.get("sections"), target_words)

    conversion = ConversionLayer(
        cta_strategy=str(synthesis.get("cta_strategy", "")).strip(),
        cta_placement=[str(p) for p in (synthesis.get("cta_placement") or []) if p],
        objection_preemption_map={
            str(k): str(v)
            for k, v in (synthesis.get("objection_preemption_map") or {}).items()
        },
        schema_types=[str(s) for s in (synthesis.get("schema_types") or ["Service", "FAQPage"]) if s],
        internal_links=[str(s) for s in (synthesis.get("internal_links") or []) if s],
        faq_targets=[str(s) for s in (synthesis.get("faq_targets") or []) if s],
        paa_targets=[str(s) for s in (synthesis.get("paa_targets") or []) if s],
    )

    silo_candidates = _build_silos(synthesis.get("silo_candidates"), primary_query)
    decision_fit = _build_decision_fit(synthesis.get("decision_fit"))

    metadata = ServiceBriefMetadata(
        schema_version=SCHEMA_VERSION,
        mode=bundle.mode,
        length_band=bundle.length_band,
        cost_usd=round(cost_usd, 4),
        cache_hit=cache_hit,
        competitors_analyzed=len(bundle.competitor_skeletons),
        section_count=len(architecture),
        objection_count=len(strategy.objections),
        degraded_notes=bundle.degraded_notes,
    )

    return ServiceBriefResponse(
        service=request.service,
        primary_query=primary_query,
        strategy=strategy,
        architecture=architecture,
        conversion=conversion,
        silo_candidates=silo_candidates,
        decision_fit=decision_fit,
        research_bundle=bundle,
        metadata=metadata,
    )
