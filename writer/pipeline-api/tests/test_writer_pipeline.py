"""Writer pipeline tests with mocked external APIs.

Covers:
- Happy path with brand-conflict reconciliation
- v1.4 fallback when client_context omitted (schema_version: 1.5-no-context)
- Banned-term in heading aborts run (no retry)
- Banned-term in body retries once successfully
- Cross-validation: keyword mismatch aborts
- FAQ count outside [3,5] aborts
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from models.writer import ClientContextInput, WriterRequest


SAMPLE_BRIEF = {
    "keyword": "best hvac systems 2026",
    "intent_type": "informational-commercial",
    "heading_structure": [
        {"level": "H1", "text": "best hvac systems 2026", "type": "content", "source": "serp", "order": 1, "heading_priority": 1.0},
        {"level": "H2", "text": "Energy Efficiency Ratings", "type": "content", "source": "serp", "order": 2, "heading_priority": 0.85, "citation_ids": ["cit_001"]},
        {"level": "H3", "text": "Hidden costs of installation", "type": "content", "source": "authority_gap_sme", "order": 3, "heading_priority": 0.8, "citation_ids": []},
        {"level": "H2", "text": "Top HVAC Brand Comparisons", "type": "content", "source": "serp", "order": 4, "heading_priority": 0.75, "citation_ids": []},
        {"level": "H2", "text": "Frequently Asked Questions", "type": "faq-header", "source": "synthesized", "order": 5},
        {"level": "H3", "text": "How long does an HVAC system last?", "type": "faq-question", "source": "synthesized", "order": 6},
        {"level": "H3", "text": "Are heat pumps worth the cost?", "type": "faq-question", "source": "synthesized", "order": 7},
        {"level": "H3", "text": "What SEER rating should I choose?", "type": "faq-question", "source": "synthesized", "order": 8},
    ],
    "faqs": [
        {"question": "How long does an HVAC system last?", "source": "paa", "faq_score": 0.85},
        {"question": "Are heat pumps worth the cost?", "source": "paa", "faq_score": 0.80},
        {"question": "What SEER rating should I choose?", "source": "paa", "faq_score": 0.75},
    ],
    "format_directives": {
        "require_bulleted_lists": True,
        "require_tables": True,
        "min_lists_per_article": 1,
        "min_tables_per_article": 1,
        "answer_first_paragraphs": True,
    },
    "metadata": {"word_budget": 2500, "schema_version": "1.7"},
}

SAMPLE_SIE = {
    "keyword": "best hvac systems 2026",
    "terms": {
        "required": [
            {"term": "energy efficiency", "is_entity": False},
            {"term": "seer rating", "is_entity": True, "entity_category": "concepts"},
            {"term": "heat pump", "is_entity": True, "entity_category": "equipment"},
            {"term": "premium", "is_entity": False},  # Will conflict with brand guide
        ],
        "avoid": [{"term": "cheap"}],
    },
    "usage_recommendations": [
        {"term": "energy efficiency", "usage": {"paragraphs": {"min": 2, "target": 4, "max": 6}}},
        {"term": "seer rating", "usage": {"paragraphs": {"min": 1, "target": 3, "max": 5}}},
        {"term": "heat pump", "usage": {"paragraphs": {"min": 1, "target": 3, "max": 5}}},
        {"term": "premium", "usage": {"paragraphs": {"min": 0, "target": 2, "max": 4}}},
    ],
    "word_count": {"min": 2000, "target": 2400, "max": 2800},
    "word_count_target": 2400,
}

SAMPLE_RESEARCH = {
    "citations": [
        {
            "citation_id": "cit_001",
            "url": "https://www.energy.gov/hvac",
            "title": "HVAC Efficiency Guide",
            "tier": 1,
            "claims": [
                {
                    "claim_text": "modern HVAC systems can be up to 50% more energy efficient",
                    "relevance_score": 0.9,
                    "extraction_method": "verbatim_extraction",
                    "verification_method": "verbatim_match",
                },
            ],
        },
    ],
}


# ---- Mock LLM responses ----

async def fake_claude_json(system, user, **kwargs):
    sl = system.lower()
    ul = user.lower()
    # Title generation
    if "blog post titles" in sl or "title candidates" in sl:
        return {"candidates": [
            "Best HVAC Systems 2026: Energy Efficiency, SEER Ratings, and Heat Pump Guide",
            "HVAC Systems for 2026 — A Buyer's Guide",
            "Best HVAC Systems 2026 Compared",
        ]}
    # H1 enrichment
    if "introduces a blog section" in sl:
        return {"sentence": "This guide compares heat pump and central HVAC system options for energy-conscious homeowners."}
    # Brand-SIE reconciliation (check FIRST — its system prompt also contains
    # "categorization-only" so it must beat the distillation matcher)
    if "reconcile each term" in sl:
        return {
            "required_classifications": [
                {"term": "energy efficiency", "classification": "keep", "brand_guide_reasoning": ""},
                {"term": "seer rating", "classification": "keep", "brand_guide_reasoning": ""},
                {"term": "heat pump", "classification": "keep", "brand_guide_reasoning": ""},
                {"term": "premium", "classification": "exclude_due_to_brand_conflict", "brand_guide_reasoning": "Brand guide explicitly bans 'premium' as marketing language"},
            ],
            "avoid_classifications": [
                {"term": "cheap", "classification": "keep_avoiding", "brand_guide_reasoning": ""},
            ],
        }
    # Brand voice distillation (must come AFTER reconciliation matcher)
    if "brand voice signals" in sl or ("categorization-only" in sl and "brand guide" in ul):
        return {
            "tone_adjectives": ["professional", "approachable", "informative"],
            "voice_directives": ["Avoid hype words", "Lead with value, not promotion"],
            "audience_summary": "Homeowners researching HVAC upgrades",
            "audience_pain_points": ["high energy bills", "system failures"],
            "audience_goals": ["lower utility costs", "comfort"],
            "preferred_terms": ["high-efficiency"],
            "banned_terms": ["premium", "luxury"],
            "discouraged_terms": [],
            "client_services": ["HVAC installation", "AC maintenance"],
            "client_locations": ["Austin, TX"],
            "client_contact_info": {"phone": None, "email": None, "address": None, "hours": None},
        }
    # Section writing
    if "expert blog content writer" in sl:
        # Parse heading order from prompt
        return {
            "sections": [
                {"order": 2, "heading": "Energy Efficiency Ratings", "body": "Modern HVAC systems offer strong energy efficiency for most homes. SEER ratings indicate cooling performance. Modern HVAC systems can be up to 50% more energy efficient.{{cit_001}}\n\n- Higher SEER = more savings\n- Heat pump options have improved\n\n| Brand | SEER |\n|---|---|\n| A | 18 |"},
                {"order": 3, "heading": "Hidden costs of installation", "body": "Installation often includes ductwork upgrades not visible on initial quotes. Homeowners should request itemized bids."},
                {"order": 4, "heading": "Top HVAC Brand Comparisons", "body": "The leading HVAC brands compete on warranty length and reliability. Carrier, Trane, and Lennox dominate the market."},
            ]
        }
    # FAQ writing
    if "write faq answers" in sl:
        return {
            "faqs": [
                {"question": "How long does an HVAC system last?", "answer": "Most HVAC systems last 15 to 20 years with proper maintenance and timely repairs. Heat pumps typically last 10 to 15 years. Regular professional servicing extends the lifespan of any best hvac systems 2026 selection."},
                {"question": "Are heat pumps worth the cost?", "answer": "Heat pumps are worth the cost in most climates because they provide both heating and cooling efficiently. Federal tax credits offset initial expenses. Energy efficiency translates to monthly utility savings."},
                {"question": "What SEER rating should I choose?", "answer": "Most homes benefit from a SEER rating between 14 and 18 for the best balance of upfront cost and operating savings. Higher ratings make sense in hot climates."},
            ]
        }
    # Conclusion writing
    if "blog post conclusion" in sl:
        return {"conclusion": "Choosing the best hvac systems 2026 means weighing energy efficiency, brand reputation, and total cost of ownership. Higher SEER ratings cut utility bills over the system's lifetime, and heat pumps offer dual heating and cooling benefits. When choosing among options, weigh the criteria that matter most to your home and climate."}
    return {}


# ---- Tests ----

@pytest.mark.asyncio
async def test_writer_happy_path_with_client_context():
    from modules.writer.pipeline import run_writer

    req = WriterRequest(
        run_id="test-writer",
        brief_output=SAMPLE_BRIEF,
        sie_output=SAMPLE_SIE,
        research_output=SAMPLE_RESEARCH,
        client_context=ClientContextInput(
            brand_guide_text="Avoid the words 'premium' and 'luxury' — sounds like upselling.",
            icp_text="Homeowners 35-65 researching HVAC upgrades.",
            website_analysis={"services": ["HVAC installation"], "locations": ["Austin, TX"]},
            website_analysis_unavailable=False,
        ),
    )

    with (
        patch("modules.writer.title.claude_json", fake_claude_json),
        patch("modules.writer.distillation.claude_json", fake_claude_json),
        patch("modules.writer.reconciliation.claude_json", fake_claude_json),
        patch("modules.writer.sections.claude_json", fake_claude_json),
        patch("modules.writer.faqs.claude_json", fake_claude_json),
        patch("modules.writer.conclusion.claude_json", fake_claude_json),
    ):
        result = await run_writer(req)

    assert result.metadata.schema_version == "1.6"
    assert result.title  # title generated
    assert result.brand_voice_card_used is not None
    assert "premium" in result.brand_voice_card_used.banned_terms
    # Brand-conflict log should record the 'premium' exclusion
    assert any(e.term == "premium" and e.resolution == "exclude_due_to_brand_conflict" for e in result.brand_conflict_log)
    # Article must contain content sections, FAQ header + 3 questions, and conclusion
    levels = [s.type for s in result.article]
    assert "content" in levels
    assert "faq-header" in levels
    assert sum(1 for t in levels if t == "faq-question") == 3
    assert "conclusion" in levels
    # Citation marker captured in section body
    citation_used = any("cit_001" in (s.body or "") for s in result.article)
    assert citation_used
    assert result.citation_usage.citations_used >= 1


@pytest.mark.asyncio
async def test_writer_no_client_context_falls_back_to_v14():
    from modules.writer.pipeline import run_writer

    req = WriterRequest(
        run_id="t",
        brief_output=SAMPLE_BRIEF,
        sie_output=SAMPLE_SIE,
        research_output=SAMPLE_RESEARCH,
        client_context=None,
    )

    with (
        patch("modules.writer.title.claude_json", fake_claude_json),
        patch("modules.writer.sections.claude_json", fake_claude_json),
        patch("modules.writer.faqs.claude_json", fake_claude_json),
        patch("modules.writer.conclusion.claude_json", fake_claude_json),
    ):
        result = await run_writer(req)

    assert result.metadata.schema_version == "1.6-no-context"
    assert result.brand_voice_card_used is None
    assert result.brand_conflict_log == []


@pytest.mark.asyncio
async def test_writer_aborts_on_keyword_mismatch():
    from modules.writer.pipeline import WriterError, run_writer

    bad_sie = dict(SAMPLE_SIE)
    bad_sie["keyword"] = "different keyword"
    req = WriterRequest(
        run_id="t",
        brief_output=SAMPLE_BRIEF,
        sie_output=bad_sie,
    )
    with pytest.raises(WriterError) as exc_info:
        await run_writer(req)
    assert exc_info.value.code == "keyword_mismatch"


@pytest.mark.asyncio
async def test_writer_aborts_on_faq_count_outside_range():
    from modules.writer.pipeline import WriterError, run_writer

    bad_brief = dict(SAMPLE_BRIEF)
    bad_brief["faqs"] = [{"question": "Only one?", "source": "paa"}]
    req = WriterRequest(run_id="t", brief_output=bad_brief, sie_output=SAMPLE_SIE)
    with pytest.raises(WriterError) as exc_info:
        await run_writer(req)
    assert exc_info.value.code == "faq_count_invalid"


def test_banned_term_regex_construction_and_matching():
    from modules.writer.banned_terms import build_banned_regex, find_banned

    regex = build_banned_regex(["premium", "luxury", "world-class"])
    assert regex is not None
    # Word boundary protects "smart" when banning "art"
    art_regex = build_banned_regex(["art"])
    assert find_banned("a smart approach", art_regex) == []
    assert find_banned("the art of repair", art_regex) == ["art"]
    # Case insensitive
    assert find_banned("This is a PREMIUM choice", regex) == ["premium"]
    # Multi-word phrase
    cutting_regex = build_banned_regex(["cutting edge"])
    assert find_banned("a cutting edge approach", cutting_regex) == ["cutting edge"]
    # Empty list returns None
    assert build_banned_regex([]) is None


@pytest.mark.asyncio
async def test_writer_aborts_on_banned_term_in_heading():
    """If the brief has a heading containing a brand-banned term, the post-hoc
    scan must abort the run with no retry."""
    from modules.writer.banned_terms import BannedTermLeakage
    from modules.writer.pipeline import run_writer

    brief = {
        **SAMPLE_BRIEF,
        "heading_structure": [
            {"level": "H1", "text": "best premium hvac systems 2026", "type": "content", "source": "serp", "order": 1, "heading_priority": 1.0},
            {"level": "H2", "text": "Energy Efficiency Ratings", "type": "content", "source": "serp", "order": 2, "heading_priority": 0.85, "citation_ids": []},
            {"level": "H2", "text": "Frequently Asked Questions", "type": "faq-header", "source": "synthesized", "order": 3},
            {"level": "H3", "text": "How long does an HVAC system last?", "type": "faq-question", "source": "synthesized", "order": 4},
            {"level": "H3", "text": "Are heat pumps worth it?", "type": "faq-question", "source": "synthesized", "order": 5},
            {"level": "H3", "text": "What SEER rating?", "type": "faq-question", "source": "synthesized", "order": 6},
        ],
    }
    req = WriterRequest(
        run_id="t",
        brief_output=brief,
        sie_output=SAMPLE_SIE,
        research_output=SAMPLE_RESEARCH,
        client_context=ClientContextInput(
            brand_guide_text="Banned: premium",
            icp_text="Homeowners",
            website_analysis_unavailable=True,
        ),
    )
    with (
        patch("modules.writer.title.claude_json", fake_claude_json),
        patch("modules.writer.distillation.claude_json", fake_claude_json),
        patch("modules.writer.reconciliation.claude_json", fake_claude_json),
        patch("modules.writer.sections.claude_json", fake_claude_json),
        patch("modules.writer.faqs.claude_json", fake_claude_json),
        patch("modules.writer.conclusion.claude_json", fake_claude_json),
    ):
        with pytest.raises(BannedTermLeakage) as exc_info:
            await run_writer(req)
    assert exc_info.value.term == "premium"


def test_writer_request_validation():
    from pydantic import ValidationError
    # client_context is optional
    WriterRequest(run_id="r", brief_output={"k": 1}, sie_output={})  # OK
    with pytest.raises(ValidationError):
        WriterRequest(run_id="r", brief_output="not a dict", sie_output={})
