"""Regression tests for `_validate_inputs` enriched_brief preference
(production bug discovered 2026-05-01: Writer was reading the unenriched
brief.heading_structure, missing Research's citation_id assignments)."""

from __future__ import annotations

import pytest

from models.writer import WriterRequest
from modules.writer.pipeline import _validate_inputs


def _base_brief(citation_ids_in_brief: list[str] | None = None) -> dict:
    return {
        "keyword": "what is a tiktok shop",
        "intent_type": "informational",
        "heading_structure": [
            {
                "level": "H1", "type": "content", "source": "serp",
                "text": "what is a tiktok shop", "order": 1,
                "citation_ids": [],
            },
            {
                "level": "H2", "type": "content", "source": "persona_gap",
                "text": "How does TikTok Shop's discovery model differ?",
                "order": 2,
                "citation_ids": citation_ids_in_brief or [],
            },
            {
                "level": "H2", "type": "faq-header", "source": "synthesized",
                "text": "Frequently Asked Questions", "order": 3,
            },
            {"level": "H3", "type": "faq-question", "source": "synthesized",
             "text": "How does it work?", "order": 4},
            {"level": "H3", "type": "faq-question", "source": "synthesized",
             "text": "Is it free?", "order": 5},
            {"level": "H3", "type": "faq-question", "source": "synthesized",
             "text": "Who can sell?", "order": 6},
        ],
        "faqs": [
            {"question": "How does it work?", "source": "paa", "faq_score": 0.85},
            {"question": "Is it free?", "source": "paa", "faq_score": 0.80},
            {"question": "Who can sell?", "source": "paa", "faq_score": 0.75},
        ],
    }


def _base_sie() -> dict:
    return {"keyword": "what is a tiktok shop", "terms": {"required": []}}


def test_validate_inputs_uses_enriched_brief_when_research_provides_it():
    """If research_output.enriched_brief.heading_structure exists,
    _validate_inputs MUST return that - not the original brief - so
    citation_ids attached by Research flow into section writing."""
    brief = _base_brief()  # citation_ids all empty
    enriched = _base_brief(citation_ids_in_brief=["cit_001"])
    research = {
        "enriched_brief": enriched,
        "citations": [{"citation_id": "cit_001", "url": "https://x.example.com",
                       "title": "x", "claims": []}],
    }
    req = WriterRequest(
        run_id="r1",
        brief_output=brief,
        sie_output=_base_sie(),
        research_output=research,
    )
    _, _, heading_structure, _, citations = _validate_inputs(req)

    h2 = next(h for h in heading_structure if h.get("level") == "H2"
              and h.get("type") == "content")
    assert h2["citation_ids"] == ["cit_001"]
    assert len(citations) == 1
    assert citations[0]["citation_id"] == "cit_001"


def test_validate_inputs_falls_back_to_brief_when_no_research_output():
    """Backward compat: if research_output is missing, the original
    brief.heading_structure is still consumed."""
    brief = _base_brief(citation_ids_in_brief=["cit_xyz"])
    req = WriterRequest(
        run_id="r2",
        brief_output=brief,
        sie_output=_base_sie(),
        research_output=None,
    )
    _, _, heading_structure, _, citations = _validate_inputs(req)
    h2 = next(h for h in heading_structure if h.get("level") == "H2"
              and h.get("type") == "content")
    assert h2["citation_ids"] == ["cit_xyz"]
    assert citations == []


def test_validate_inputs_falls_back_when_enriched_brief_lacks_heading_structure():
    """If research_output exists but enriched_brief.heading_structure is
    empty/missing, fall back to the original brief - never crash."""
    brief = _base_brief(citation_ids_in_brief=["cit_brief"])
    research = {
        "enriched_brief": {"keyword": "x"},  # no heading_structure key
        "citations": [],
    }
    req = WriterRequest(
        run_id="r3",
        brief_output=brief,
        sie_output=_base_sie(),
        research_output=research,
    )
    _, _, heading_structure, _, _ = _validate_inputs(req)
    h2 = next(h for h in heading_structure if h.get("level") == "H2"
              and h.get("type") == "content")
    assert h2["citation_ids"] == ["cit_brief"]
