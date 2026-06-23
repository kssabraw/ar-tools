"""Brief Generator Step 11 — assemble the v2.6 Brief Output (M13 slice 5b).

Pure: combines the upstream pieces (intent, title/scope, main entity, MCS-selected H2s,
sources) into the `BriefOutput` (Writer Input A). H3 selection / persona / authority /
FAQ enrich this in 5c — they default empty here and the output is already valid.
"""

from __future__ import annotations

from statistics import mean

from dataclasses import asdict

from .entity import MainEntity
from .intent import IntentResult
from .mcs import MCSResult
from .models import SCHEMA_VERSION, BriefOutput
from .persona import Persona
from .sources import BriefSources
from .title import TitleScope


def build_brief_output(
    *, keyword: str, intent: IntentResult, title: TitleScope, entity: MainEntity,
    mcs: MCSResult, sources: BriefSources, persona: Persona | None = None,
    faqs: list[dict] | None = None, h3s_by_h2: dict[str, list[dict]] | None = None,
    decision_fit_directive: dict | None = None, extra_metadata: dict | None = None,
) -> BriefOutput:
    """Assemble the v2.6 BriefOutput. heading_structure = H1 (the title, verbatim per the
    Writer's D6 contract) + the MCS-selected H2s, with their H3s (regular Step-8.6 +
    authority-gap Step-9, already merged per `merge_h3s`) interleaved under each parent.
    The decision-fit `format_directive` (A5) attaches to its reserved anchor H2."""
    h3s_by_h2 = h3s_by_h2 or {}

    headings: list[dict] = [{
        "text": title.title, "type": "content", "level": "H1", "order": 1, "source": "title",
    }]
    order = 2
    for sh in mcs.selected:
        h2 = {
            "text": sh.text, "type": "content", "level": "H2", "order": order, "source": "mcs",
            # answer-engine proximity readouts (X.8) — extra fields kept by extra="allow".
            "aio_cosine": round(sh.aio_headline, 4),
            "chatgpt_cosine": round(sh.chatgpt_cosine, 4),
            "mcs_blended": round(sh.blended, 4),
        }
        if decision_fit_directive and decision_fit_directive.get("anchor_h2_text") == sh.text:
            d = {k: v for k, v in decision_fit_directive.items() if k != "anchor_h2_text"}
            d["section_id"] = order
            h2["format_directive"] = d
        headings.append(h2)
        order += 1
        for h3 in h3s_by_h2.get(sh.text, []):
            item = {
                "text": h3["text"], "type": "content", "level": "H3", "order": order,
                "parent_h2_text": sh.text, "source": h3.get("source", "coverage_graph"),
            }
            if h3.get("source") == "authority_gap_sme":
                item["exempt"] = True
                item["scope_alignment_note"] = h3.get("scope_alignment_note", "")
            else:
                item["parent_relevance"] = h3.get("parent_relevance")
                item["region_id"] = h3.get("region_id")
            headings.append(item)
            order += 1

    discarded = [{
        "text": d.text, "reason": "not_selected_by_mcs",
        "aio_cosine": round(d.aio_headline, 4), "chatgpt_cosine": round(d.chatgpt_cosine, 4),
    } for d in mcs.discarded]

    selected = mcs.selected
    metadata = {
        "brief_schema_version": SCHEMA_VERSION,
        "main_entity": {
            "canonical": entity.canonical, "variants": entity.variants,
            "source": entity.source, "confidence": entity.confidence,
            "multi_entity_flag": entity.multi_entity_flag,
            "secondary_entity": entity.secondary_entity, "emq_identical": entity.emq_identical,
        },
        "mcs": {
            "pool_size": len(mcs.pool), "selected_count": len(selected),
            "aio_present": bool(sources.aio.get("present")),
            "chatgpt_present": bool((sources.llm_answers.get("chat_gpt") or "").strip()),
            "set_mean_aio_cosine": round(mean([s.aio_headline for s in selected]), 4) if selected else 0.0,
            "set_mean_chatgpt_cosine": round(mean([s.chatgpt_cosine for s in selected]), 4) if selected else 0.0,
        },
        "decision_fit_qualifies": intent.decision_fit_qualifies,
        "decision_fit_directive_emitted": decision_fit_directive is not None,
        "sources": {
            "organic": len(sources.organic), "paa": len(sources.paa),
            "discussions": len(sources.reddit), "llm_answers": sorted(sources.llm_answers),
        },
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    return BriefOutput(
        schema_version=SCHEMA_VERSION,
        keyword=keyword,
        h1=title.title, title=title.title, title_rationale=title.title_rationale,
        scope_statement=title.scope_statement,
        intent_type=intent.intent_type, intent_confidence=intent.intent_confidence,
        intent_review_required=intent.intent_review_required,
        intent_format_template=intent.intent_format_template,
        format_directives=intent.format_directives,           # dict -> FormatDirectives (coerced)
        heading_structure=headings,
        faqs=list(faqs or []),
        persona=asdict(persona) if persona is not None else None,
        discarded_headings=discarded,
        metadata=metadata,
    )
