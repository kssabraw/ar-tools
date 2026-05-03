"""Writer-side SIE zone-wiring tests (PRD v2.6 follow-on).

Covers the four wirings that surface SIE per-zone targets into the writer
prompts:
  1. generate_title surfaces title-zone target/max
  2. generate_h1_enrichment surfaces h1-zone target/max
  3. write_faqs derives a FAQ target from the paragraphs zone
  4. optimize_headings excludes is_seed_fragment entities from injection

Plus the underlying plumbing change — ReconciledTerm carries
is_seed_fragment from SIE term metadata.
"""

from __future__ import annotations

import pytest

from modules.writer.faqs import _derive_faq_zone_target, write_faqs
from modules.writer.heading_seo_optimizer import optimize_headings
from modules.writer.reconciliation import (
    FilteredSIETerms,
    ReconciledTerm,
    _entity_metadata_for_term,
    _all_keep,
)
from modules.writer.title import generate_h1_enrichment, generate_title


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capturing_json(response):
    captured = {}

    async def _call(system, user, **kw):
        captured["system"] = system
        captured["user"] = user
        return response

    return _call, captured


# ---------------------------------------------------------------------------
# Plumbing — is_seed_fragment carried through reconciliation
# ---------------------------------------------------------------------------


def test_entity_metadata_extracts_is_seed_fragment():
    rec = {"term": "tiktok shop", "data": {
        "is_entity": False,
        "entity_category": None,
        "is_seed_fragment": True,
    }}
    is_entity, category, is_seed_fragment = _entity_metadata_for_term(rec)
    assert is_entity is False
    assert category is None
    assert is_seed_fragment is True


def test_entity_metadata_defaults_when_field_missing():
    """Pre-v1.3 SIE rows without is_seed_fragment default to False."""
    rec = {"term": "anything", "data": {"is_entity": True, "entity_category": "tools"}}
    is_entity, category, is_seed_fragment = _entity_metadata_for_term(rec)
    assert is_entity is True
    assert category == "tools"
    assert is_seed_fragment is False


def test_all_keep_propagates_is_seed_fragment():
    sie = {
        "terms": {
            "required": [
                {"term": "tiktok shop", "is_seed_fragment": True, "is_entity": False},
                {"term": "checkout flow", "is_seed_fragment": False, "is_entity": True,
                 "entity_category": "concepts"},
            ],
            "avoid": [],
        },
        "usage_recommendations": [],
    }
    required = [{"term": r["term"], "data": r} for r in sie["terms"]["required"]]
    filtered = _all_keep(required, [], [])
    by_term = {t.term: t for t in filtered.required}
    assert by_term["tiktok shop"].is_seed_fragment is True
    assert by_term["checkout flow"].is_seed_fragment is False


# ---------------------------------------------------------------------------
# Title-zone wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_title_includes_title_zone_directive(monkeypatch):
    call, captured = _capturing_json({"candidates": ["A: TikTok Shop ROI Guide"]})
    monkeypatch.setattr("modules.writer.title.claude_json", call)

    title = await generate_title(
        keyword="tiktok shop roi",
        intent_type="how-to",
        required_terms=["roi", "checkout"],
        entities=["TikTok Shop", "Checkout Flow"],
        title_zone_target=2,
        title_zone_max=3,
    )
    assert "tiktok shop roi" in title.lower()
    assert "at least 2" in captured["user"].lower()
    # 3 entity max requested, but only 2 entities listed → clamp to 2.
    assert "do not exceed 2" in captured["user"].lower()


@pytest.mark.asyncio
async def test_generate_title_clamps_directive_to_entity_count(monkeypatch):
    """Title prompt only lists top 5 entities — even if SIE recommends 30,
    the directive count must clamp to len(top_entities)."""
    call, captured = _capturing_json({"candidates": ["TikTok Shop Guide"]})
    monkeypatch.setattr("modules.writer.title.claude_json", call)

    await generate_title(
        keyword="tiktok shop",
        intent_type="how-to",
        required_terms=[],
        entities=["E1", "E2", "E3", "E4", "E5", "E6", "E7"],
        title_zone_target=30,
        title_zone_max=40,
    )
    assert "at least 5" in captured["user"].lower()
    assert "at least 30" not in captured["user"].lower()
    assert "do not exceed 5" in captured["user"].lower()


@pytest.mark.asyncio
async def test_generate_title_omits_directive_when_zero(monkeypatch):
    call, captured = _capturing_json({"candidates": ["TikTok Shop ROI Guide"]})
    monkeypatch.setattr("modules.writer.title.claude_json", call)

    await generate_title(
        keyword="tiktok shop roi",
        intent_type="how-to",
        required_terms=[],
        entities=["TikTok Shop"],
        title_zone_target=0,
        title_zone_max=0,
    )
    assert "at least" not in captured["user"].lower()


# ---------------------------------------------------------------------------
# H1-zone wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_h1_enrichment_includes_h1_zone_directive(monkeypatch):
    call, captured = _capturing_json({"sentence": "lede sentence here"})
    monkeypatch.setattr("modules.writer.title.claude_json", call)

    sentence = await generate_h1_enrichment(
        keyword="tiktok shop roi",
        h1_text="Driving ROI on TikTok Shop",
        high_salience_entities=[
            {"term": "Checkout Flow", "entity_category": "methods"},
            {"term": "Repair Service", "entity_category": "services"},
        ],
        h1_zone_target=2,
        h1_zone_max=2,
    )
    assert sentence == "lede sentence here"
    # Both qualify (services + methods). Directive clamped to available=2.
    assert "include at least 2" in captured["user"].lower()
    assert "no more than 2" in captured["user"].lower()


@pytest.mark.asyncio
async def test_generate_h1_enrichment_clamps_to_lede_ceiling(monkeypatch):
    """A 25-word lede can't carry more than 2 entities readably — even if
    SIE recommends 5, the directive must cap at LEDE_ENTITY_CEILING (2)."""
    call, captured = _capturing_json({"sentence": "x"})
    monkeypatch.setattr("modules.writer.title.claude_json", call)

    await generate_h1_enrichment(
        keyword="kw",
        h1_text="H1",
        high_salience_entities=[
            {"term": "E1", "entity_category": "services"},
            {"term": "E2", "entity_category": "equipment"},
            {"term": "E3", "entity_category": "problems"},
        ],
        h1_zone_target=5,
        h1_zone_max=8,
    )
    # 3 qualifying entities listed, but ceiling caps directive at 2.
    assert "include at least 2" in captured["user"].lower()
    assert "no more than 2" in captured["user"].lower()
    assert "include at least 5" not in captured["user"].lower()


@pytest.mark.asyncio
async def test_generate_h1_enrichment_falls_back_when_zero(monkeypatch):
    call, captured = _capturing_json({"sentence": "lede sentence here"})
    monkeypatch.setattr("modules.writer.title.claude_json", call)

    await generate_h1_enrichment(
        keyword="kw",
        h1_text="H1",
        high_salience_entities=[
            {"term": "Repair Service", "entity_category": "services"},
        ],
        h1_zone_target=0,
        h1_zone_max=0,
    )
    assert "pick 1-2 most natural" in captured["user"].lower()


@pytest.mark.asyncio
async def test_generate_h1_enrichment_skips_when_no_qualifying_entities(monkeypatch):
    """`concepts`/`brands`/etc. don't qualify — empty string short-circuits before LLM."""
    called = False

    async def _call(*a, **kw):
        nonlocal called
        called = True
        return {"sentence": "x"}

    monkeypatch.setattr("modules.writer.title.claude_json", _call)
    out = await generate_h1_enrichment(
        keyword="kw",
        h1_text="H1",
        high_salience_entities=[
            {"term": "X", "entity_category": "brands"},
        ],
        h1_zone_target=2,
        h1_zone_max=3,
    )
    assert out == ""
    assert called is False


# ---------------------------------------------------------------------------
# FAQ-zone derivation
# ---------------------------------------------------------------------------


def test_derive_faq_zone_target_scales_from_paragraphs():
    terms = FilteredSIETerms(
        required=[
            ReconciledTerm(
                term="t1",
                zones={"paragraphs": {"min": 1, "target": 5, "max": 8}},
            ),
            ReconciledTerm(
                term="t2",
                zones={"paragraphs": {"min": 1, "target": 5, "max": 8}},
            ),
        ]
    )
    target, mx = _derive_faq_zone_target(terms)
    # Sum target = 10 → 10 * 0.12 = 1.2 → round to 1
    assert target == 1
    # Sum max = 16 → 16 * 0.12 = 1.92 → round to 2
    assert mx == 2


def test_derive_faq_zone_target_floor_when_paragraphs_present():
    """Even tiny paragraphs targets should produce a FAQ floor of 1."""
    terms = FilteredSIETerms(
        required=[
            ReconciledTerm(
                term="t1",
                zones={"paragraphs": {"min": 0, "target": 1, "max": 1}},
            ),
        ]
    )
    target, mx = _derive_faq_zone_target(terms)
    assert target == 1
    assert mx >= target


def test_derive_faq_zone_target_zero_when_no_paragraphs_data():
    terms = FilteredSIETerms(
        required=[ReconciledTerm(term="t1", zones={})]
    )
    target, mx = _derive_faq_zone_target(terms)
    assert target == 0
    assert mx == 0


@pytest.mark.asyncio
async def test_write_faqs_includes_faq_target_directive(monkeypatch):
    captured = {}

    async def _call(system, user, **kw):
        captured["user"] = user
        return {"faqs": [
            {"question": "Q1?", "answer": "answer one in forty to eighty words placeholder."},
            {"question": "Q2?", "answer": "answer two in forty to eighty words placeholder."},
        ]}

    monkeypatch.setattr("modules.writer.faqs.claude_json", _call)
    filtered = FilteredSIETerms(required=[
        ReconciledTerm(
            term="checkout flow",
            zones={"paragraphs": {"min": 1, "target": 5, "max": 8}},
        ),
        ReconciledTerm(
            term="conversion rate",
            zones={"paragraphs": {"min": 1, "target": 5, "max": 8}},
        ),
    ])

    await write_faqs(
        keyword="kw",
        faq_questions=["Q1?", "Q2?"],
        filtered_terms=filtered,
        brand_voice_card=None,
        banned_regex=None,
    )
    assert "REQUIRED_TERM_USAGE_TARGET" in captured["user"]
    # 2 terms × paragraphs.target=5 → sum 10, ×0.12 → 1; "1 mention" (singular).
    assert "at least 1 distinct REQUIRED_TERM mention" in captured["user"]
    assert "REQUIRED_TERM mentions" not in captured["user"]


@pytest.mark.asyncio
async def test_write_faqs_directive_clamps_to_listed_terms(monkeypatch):
    """If derived target exceeds listed REQUIRED_TERMS (top 8), clamp.

    With paragraphs.target=100 across one term, derived target = 12,
    but only 1 term is listed — the directive must say "at least 1" not
    "at least 12"."""
    captured = {}

    async def _call(system, user, **kw):
        captured["user"] = user
        return {"faqs": [
            {"question": "Q1?", "answer": "answer placeholder text."},
        ]}

    monkeypatch.setattr("modules.writer.faqs.claude_json", _call)
    filtered = FilteredSIETerms(required=[
        ReconciledTerm(
            term="solo term",
            zones={"paragraphs": {"min": 50, "target": 100, "max": 150}},
        ),
    ])
    await write_faqs(
        keyword="kw",
        faq_questions=["Q1?"],
        filtered_terms=filtered,
        brand_voice_card=None,
        banned_regex=None,
    )
    assert "at least 1 distinct REQUIRED_TERM mention" in captured["user"]
    assert "at least 12" not in captured["user"]


@pytest.mark.asyncio
async def test_write_faqs_omits_directive_when_no_paragraphs_data(monkeypatch):
    captured = {}

    async def _call(system, user, **kw):
        captured["user"] = user
        return {"faqs": [
            {"question": "Q1?", "answer": "answer one placeholder text here for tests."},
        ]}

    monkeypatch.setattr("modules.writer.faqs.claude_json", _call)
    filtered = FilteredSIETerms(required=[
        ReconciledTerm(term="x", zones={}),
    ])

    await write_faqs(
        keyword="kw",
        faq_questions=["Q1?"],
        filtered_terms=filtered,
        brand_voice_card=None,
        banned_regex=None,
    )
    assert "REQUIRED_TERM_USAGE_TARGET" not in captured["user"]


# ---------------------------------------------------------------------------
# Heading optimizer — is_seed_fragment exclusion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimize_headings_excludes_seed_fragment_entities():
    """Even if an entity slipped through with is_seed_fragment=True (defensive
    guard against an upstream invariant break), the optimizer must not offer
    it to the LLM as injectable."""
    captured = {}

    async def _call(system, user, **kw):
        captured["user"] = user
        return {"rewrites": []}

    fragment_entity = ReconciledTerm(
        term="tiktok shop",  # A seed fragment that erroneously got is_entity=True
        is_entity=True,
        is_seed_fragment=True,
        zones={
            "title": {"min": 0, "target": 1, "max": 1},
            "h1": {"min": 0, "target": 1, "max": 1},
            "h2": {"min": 0, "target": 1, "max": 2},
            "h3": {"min": 0, "target": 1, "max": 1},
            "paragraphs": {"min": 1, "target": 3, "max": 5},
        },
    )
    legit_entity = ReconciledTerm(
        term="Checkout Flow",
        is_entity=True,
        is_seed_fragment=False,
        entity_category="methods",
        zones={
            "title": {"min": 0, "target": 1, "max": 1},
            "h1": {"min": 0, "target": 1, "max": 1},
            "h2": {"min": 0, "target": 1, "max": 2},
            "h3": {"min": 0, "target": 1, "max": 1},
            "paragraphs": {"min": 1, "target": 3, "max": 5},
        },
    )

    structure = [
        {"level": "H2", "text": "How TikTok Shop Drives ROI", "order": 1,
         "type": "content", "source": "serp"},
    ]
    result = await optimize_headings(
        structure,
        keyword="tiktok shop roi",
        reconciled_terms=[fragment_entity, legit_entity],
        forbidden_terms=[],
        llm_json_fn=_call,
    )
    # Pull the entity payload section out and check it directly. The
    # prompt contains a "Recommended entities" JSON array — split on
    # "Forbidden terms" to isolate that block from the headings JSON.
    entities_block = captured["user"].split("Forbidden terms")[0]
    assert '"term": "Checkout Flow"' in entities_block
    # The fragment entity must NOT have a payload entry.
    assert '"term": "tiktok shop"' not in entities_block
    assert result.llm_called is True
    assert result.skipped_reason is None


@pytest.mark.asyncio
async def test_optimize_headings_short_circuits_when_only_seed_fragments():
    """If every entity is flagged as a seed fragment, the optimizer should
    skip with no_entities_available rather than send an empty payload."""
    fragment = ReconciledTerm(
        term="roi",
        is_entity=True,
        is_seed_fragment=True,
        zones={"h2": {"min": 0, "target": 1, "max": 2}},
    )
    structure = [
        {"level": "H2", "text": "Driving ROI", "order": 1,
         "type": "content", "source": "serp"},
    ]

    async def _call(system, user, **kw):
        raise AssertionError("LLM must not be invoked when entity payload is empty")

    result = await optimize_headings(
        structure,
        keyword="roi tactics",
        reconciled_terms=[fragment],
        forbidden_terms=[],
        llm_json_fn=_call,
    )
    assert result.llm_called is False
    assert result.skipped_reason == "no_entities_available"
