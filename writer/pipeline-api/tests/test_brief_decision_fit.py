"""Tests for the brief decision-fit stage (schema v2.8) + fan-out trim."""

from __future__ import annotations

import pytest

from models.brief import DecisionFitDirective
from modules.brief.decision_fit import (
    build_decision_fit_directive,
    decision_fit_qualifies,
    detect_partner_factor,
)


# ---- A1: qualification gate ----

def test_decision_fit_qualifies_happy():
    detection = {
        "is_multi_answer": True,
        "conditions": ["if you need speed", "if you need price"],
        "confidence": 0.8,
    }
    assert decision_fit_qualifies(detection) is True


def test_decision_fit_qualifies_rejects():
    # Not multi-answer.
    assert not decision_fit_qualifies(
        {"is_multi_answer": False, "conditions": ["a", "b"], "confidence": 0.9}
    )
    # Below tau.
    assert not decision_fit_qualifies(
        {"is_multi_answer": True, "conditions": ["a", "b"], "confidence": 0.5}
    )
    # Fewer than 2 distinct conditions (case-insensitive dedupe).
    assert not decision_fit_qualifies(
        {"is_multi_answer": True, "conditions": ["Same", "same"], "confidence": 0.9}
    )
    assert not decision_fit_qualifies({})


# ---- A4: partner-factor detection (pure) ----

def test_detect_partner_factor_comparative():
    assert detect_partner_factor("comparison", []) == "comparative_depth"
    assert detect_partner_factor(
        "informational", [{"text": "Tabs vs Spaces", "source": "serp"}]
    ) == "comparative_depth"


def test_detect_partner_factor_edge_case_from_authority():
    assert detect_partner_factor(
        "how-to", [{"text": "Setup", "source": "authority_gap_sme"}]
    ) == "edge_case_detail"


def test_detect_partner_factor_definitions_and_none():
    assert detect_partner_factor("informational", [{"text": "Overview", "source": "serp"}]) == "direct_definitions"
    assert detect_partner_factor(
        "how-to", [{"text": "Step one", "source": "serp"}]
    ) is None


# ---- A3/A5: directive build ----

async def test_build_decision_fit_directive_happy():
    async def fake_llm(system, user, **kwargs):
        return {
            "branches": [
                {"condition": "you need it fast", "option": "pick the express tier", "source": "paa"},
                {"condition": "you are price-sensitive", "option": "pick the basic tier", "source": "llm"},
                {"condition": "you need it fast", "option": "dup dropped", "source": "llm"},
            ],
            "default_statement": "When unsure, start with the basic tier.",
        }

    detection = {"is_multi_answer": True, "conditions": ["fast", "cheap"], "confidence": 0.9}
    directive = await build_decision_fit_directive(
        detection, anchor_h2_text="Which Tier Is Right for You",
        persona_gaps=["q1"], paa=["q2"], reddit=["t1"],
        partner_factor="comparative_depth", llm_json_fn=fake_llm,
    )
    assert isinstance(directive, DecisionFitDirective)
    assert directive.anchor_h2_text == "Which Tier Is Right for You"
    assert directive.partner_factor == "comparative_depth"
    assert len(directive.branches) == 2  # duplicate condition dropped
    assert directive.branches[0].source == "paa"
    assert directive.default_statement.startswith("When unsure")


async def test_build_decision_fit_directive_no_partner_factor():
    async def fake_llm(system, user, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("LLM must not be called without a partner factor")

    out = await build_decision_fit_directive(
        {"conditions": ["a", "b"]}, anchor_h2_text="A",
        persona_gaps=[], paa=[], reddit=[], partner_factor=None, llm_json_fn=fake_llm,
    )
    assert out is None


async def test_build_decision_fit_directive_too_few_branches():
    async def fake_llm(system, user, **kwargs):
        return {"branches": [{"condition": "only one", "option": "x"}], "default_statement": "d"}

    out = await build_decision_fit_directive(
        {"conditions": ["a", "b"]}, anchor_h2_text="A",
        persona_gaps=[], paa=[], reddit=[], partner_factor="direct_definitions", llm_json_fn=fake_llm,
    )
    assert out is None


async def test_build_decision_fit_directive_degrades_on_failure():
    async def boom(system, user, **kwargs):
        raise RuntimeError("sonnet down")

    out = await build_decision_fit_directive(
        {"conditions": ["a", "b"]}, anchor_h2_text="A",
        persona_gaps=[], paa=[], reddit=[], partner_factor="comparative_depth", llm_json_fn=boom,
    )
    assert out is None


# ---- Change 1: fan-out source trim ----

def test_fanout_sources_trimmed_to_chatgpt_and_gemini():
    from modules.brief.pipeline import FANOUT_LLMS
    from modules.brief.scoring import LLM_FANOUT_SOURCES, LLM_RESPONSE_SOURCES

    ids = {llm_id for llm_id, _model, _force in FANOUT_LLMS}
    assert ids == {"chatgpt", "gemini"}
    assert LLM_FANOUT_SOURCES == {"llm_fanout_chatgpt", "llm_fanout_gemini"}
    assert all("claude" not in s and "perplexity" not in s for s in LLM_RESPONSE_SOURCES)


# ---- Fix #4: lead-H2 injection keeps the global cap a hard ceiling ----

def test_enforce_heading_cap_trims_last_content_group():
    from models.brief import HeadingItem
    from modules.brief.pipeline import _enforce_heading_cap

    def _h(level, text, type="content"):
        return HeadingItem(level=level, text=text, type=type, source="serp")

    # H1 (exempt) + 3 content H2 groups (4 capped items) + FAQ block (exempt).
    hs = [
        _h("H1", "Title"),
        _h("H2", "Lead"),            # injected lead
        _h("H2", "Body A"),
        _h("H3", "Body A sub"),      # belongs to Body A
        _h("H2", "Body B"),
        _h("H2", "Frequently Asked Questions", type="faq-header"),
        _h("H3", "A question?", type="faq-question"),
    ]
    # 4 capped content items (Lead, Body A, Body A sub, Body B); cap at 3.
    _enforce_heading_cap(hs, cap=3)

    texts = [h.text for h in hs]
    # The last content H2 group (Body B) is dropped; the lead + earlier groups stay.
    assert "Body B" not in texts
    assert "Lead" in texts and "Body A" in texts and "Body A sub" in texts
    # H1 and the FAQ block are never trimmed (exempt from the cap).
    assert "Title" in texts and "Frequently Asked Questions" in texts and "A question?" in texts
    capped = sum(1 for h in hs if h.level in ("H2", "H3") and h.type == "content")
    assert capped == 3


def test_enforce_heading_cap_noop_when_within_cap():
    from models.brief import HeadingItem
    from modules.brief.pipeline import _enforce_heading_cap

    hs = [
        HeadingItem(level="H1", text="T", type="content", source="serp"),
        HeadingItem(level="H2", text="A", type="content", source="serp"),
        HeadingItem(level="H2", text="B", type="content", source="serp"),
    ]
    before = list(hs)
    _enforce_heading_cap(hs, cap=15)
    assert hs == before


def test_consensus_normalized_by_live_source_count():
    from modules.brief.scoring import HeadingCandidate, LLM_FANOUT_SOURCES, compute_priority

    c = HeadingCandidate(text="x", source="llm_fanout_chatgpt", semantic_score=0.0)
    c.llm_fanout_consensus = len(LLM_FANOUT_SOURCES)  # full agreement
    compute_priority([c])
    # Full consensus contributes the entire 0.2 weight (norm == 1.0), not /4.
    assert c.heading_priority == pytest.approx(0.2, abs=1e-6)
