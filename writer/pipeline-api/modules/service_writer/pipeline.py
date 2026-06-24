"""Service Page Writer — top-level orchestration.

Consumes a Service Page Brief and produces a conversion-focused page: per-
section structured blocks (Sonnet), an FAQ section, a trailing CTA, then
deterministic Markdown / HTML / WordPress renderings + Service/FAQPage JSON-LD.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from models.service_writer import (
    SCHEMA_VERSION,
    Block,
    Renderings,
    ServiceWriterMetadata,
    ServiceWriterRequest,
    ServiceWriterResponse,
    WriterSection,
)
from modules.service_brief import cost
from modules.writer.distillation import distill_brand_voice

from . import generation
from .jsonld import build_jsonld
from .render import count_words, render_html, render_markdown, render_wordpress

logger = logging.getLogger(__name__)


def _objection_map(strategy: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for o in strategy.get("objections") or []:
        if isinstance(o, dict) and o.get("where_addressed") and o.get("objection"):
            out[str(o["where_addressed"]).strip().lower()] = str(o["objection"])
    return out


async def run_service_writer(request: ServiceWriterRequest) -> ServiceWriterResponse:
    cost.start_accounting()
    started = time.perf_counter()
    notes: list[str] = []

    brief = request.service_brief_output or {}
    service = str(brief.get("service", "")).strip()
    primary_query = str(brief.get("primary_query", "")).strip()
    strategy = brief.get("strategy") or {}
    positioning_angle = str(strategy.get("positioning_angle", "")).strip()
    architecture = brief.get("architecture") or []
    conversion = brief.get("conversion") or {}
    obj_map = _objection_map(strategy)

    # ---- Brand voice (reuse the blog writer's distillation) ----
    brand_card: Optional[dict] = None
    website_analysis: Optional[dict] = None
    if request.client_context is not None:
        website_analysis = request.client_context.website_analysis
        try:
            card = await distill_brand_voice(request.client_context)
            brand_card = card.model_dump() if card else None
        except Exception as exc:
            logger.warning("service_writer.distill_failed", extra={"error": str(exc)})
        if brand_card is None:
            notes.append("brand_distillation_unavailable")
    else:
        notes.append("no_client_context")
    brand_name = (brand_card or {}).get("brand_name", "") or ""
    brand_directive = generation._brand_directive(brand_card)

    # Reoptimization: fold the scorer's deficiencies into the per-call directive
    # so every section/title/FAQ generation addresses them. Same output shape.
    if request.mode == "reoptimize":
        brand_directive += generation.reopt_directive(request.deficiencies, request.prior_sections)
        notes.append(f"reoptimize:{len(request.deficiencies)}_deficiencies")

    # ---- Title / meta / CTA label ----
    tmc = await generation.generate_title_meta_cta(
        service=service,
        primary_query=primary_query,
        positioning_angle=positioning_angle,
        brand_name=brand_name,
        brand_directive=brand_directive,
    )

    sections: list[WriterSection] = []
    order = 1

    # ---- Architecture sections ----
    for sec in architecture:
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading", "")).strip()
        objection = obj_map.get(heading.lower())
        blocks = await generation.write_section_blocks(
            sec,
            positioning_angle=positioning_angle,
            objection=objection,
            brand_card=brand_card,
            brand_directive=brand_directive,
        )
        if not blocks and not heading:
            continue
        section = WriterSection(
            order=order,
            level=sec.get("level") if sec.get("level") in ("H1", "H2", "H3") else "H2",
            heading=heading,
            blocks=blocks,
            type="content",
        )
        section.word_count = count_words([section])
        sections.append(section)
        order += 1

    # ---- FAQ section ----
    faq_questions = [
        str(q).strip()
        for q in (list(conversion.get("faq_targets") or []) + list(conversion.get("paa_targets") or []))
        if str(q).strip()
    ]
    # De-dup, preserve order.
    seen: set[str] = set()
    faq_questions = [q for q in faq_questions if not (q.lower() in seen or seen.add(q.lower()))]
    faqs = await generation.write_faqs(
        faq_questions, service=service, positioning_angle=positioning_angle, brand_directive=brand_directive,
    )
    if faqs:
        faq_blocks: list[Block] = []
        for f in faqs:
            faq_blocks.append(Block(type="subheading", text=f["question"], level=3))
            faq_blocks.append(Block(type="paragraph", text=f["answer"]))
        faq_section = WriterSection(
            order=order, level="H2", heading="Frequently Asked Questions",
            blocks=faq_blocks, type="faq",
        )
        faq_section.word_count = count_words([faq_section])
        sections.append(faq_section)
        order += 1

    # ---- Trailing CTA ----
    cta_text = tmc.get("cta_text") or "Get a Free Quote"
    cta_section = WriterSection(
        order=order, level="H2",
        heading=(conversion.get("cta_strategy") and "Ready to get started?") or "Get in touch",
        blocks=[Block(type="cta", text=cta_text)],
        type="cta",
    )
    cta_section.word_count = count_words([cta_section])
    sections.append(cta_section)

    renderings = Renderings(
        markdown=render_markdown(sections),
        html=render_html(sections),
        wordpress=render_wordpress(sections),
    )
    schema_jsonld = build_jsonld(
        service=service,
        primary_query=primary_query,
        brand_name=brand_name,
        website_analysis=website_analysis,
        faqs=faqs,
    )

    metadata = ServiceWriterMetadata(
        schema_version=SCHEMA_VERSION,
        total_word_count=count_words(sections),
        cost_usd=cost.total_cost(),
        section_count=len(sections),
        faq_count=len(faqs),
        brand_voice_card_used=brand_card,
        degraded_notes=notes,
        generation_time_ms=int((time.perf_counter() - started) * 1000),
    )

    logger.info(
        "service_writer.complete",
        extra={
            "run_id": request.run_id,
            "primary_query": primary_query,
            "sections": len(sections),
            "faqs": len(faqs),
            "words": metadata.total_word_count,
        },
    )

    return ServiceWriterResponse(
        service=service,
        primary_query=primary_query,
        title=tmc.get("title", ""),
        meta_description=tmc.get("meta_description", ""),
        sections=sections,
        renderings=renderings,
        schema_jsonld=schema_jsonld,
        metadata=metadata,
    )
