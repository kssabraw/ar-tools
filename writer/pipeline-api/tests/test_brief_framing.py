"""Step 11 - H2 Framing Validator (Brief Generator PRD v2.1)."""

from __future__ import annotations

import pytest

from modules.brief.framing import (
    passes_framing,
    validate_and_rewrite_framing,
)
from modules.brief.graph import Candidate
from modules.brief.intent_template import get_template


def _candidate(text: str) -> Candidate:
    return Candidate(text=text, source="serp")


# ---------------------------------------------------------------------------
# passes_framing - regex-only predicates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "Plan your TikTok Shop launch",
    "Set Up your seller account",
    "Step 1: Configure your storefront",
    "Optimize product listings for discovery",
    "Validate your fulfillment workflow",
    "Iterate on what's working",
])
def test_verb_leading_passes_for_action_verbs(text):
    assert passes_framing(text, "verb_leading_action")


@pytest.mark.parametrize("text", [
    "What is TikTok Shop",
    "How does TikTok Shop work",
    "The Best TikTok Shop Tips",
    "Your TikTok Shop dashboard",
])
def test_verb_leading_rejects_questions_and_articles(text):
    assert not passes_framing(text, "verb_leading_action")


@pytest.mark.parametrize("text", [
    "1. Pick a niche",
    "1) Pick a niche",
    "#3 Optimize listings",
    "Top 5 monetization tactics",
    "Number 2: Validate demand",
])
def test_ordinal_passes(text):
    assert passes_framing(text, "ordinal_then_noun_phrase")


@pytest.mark.parametrize("text", [
    "Pick a niche",                 # missing ordinal
    "First, pick a niche",          # word, not numeral
    "What to consider first",       # question form
])
def test_ordinal_rejects_non_ordinal(text):
    assert not passes_framing(text, "ordinal_then_noun_phrase")


# ---------------------------------------------------------------------------
# Bug-fix regression cases (Phase 1 review fixes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "Where Should You Sell?",
    "When to Launch Your Shop",
    "Which TikTok Shop Plan Fits",
    "Should You Sell on TikTok",
    "Could TikTok Shop Work for You",
    "Are TikTok Shops Profitable",
    "Will TikTok Shop Survive a Ban",
    "Has TikTok Shop Changed Recently",
])
def test_verb_leading_rejects_extended_question_words(text):
    """Fix #1 - pre-Phase-1 the verb-stem heuristic falsely passed
    `Where`, `When`, `Should`, `Are`, etc. because each ends in a
    stem letter on the alternation list. After the fix, every common
    question/auxiliary leader is rejected by `_NON_VERB_LEADERS`."""
    assert not passes_framing(text, "verb_leading_action")


@pytest.mark.parametrize("text", [
    "Configuring your storefront",   # ends in 'g'; old regex rejected
    "Consider audience overlap",     # ends in 'r'; old regex rejected
    "Handle returns gracefully",     # already has 'handle' in whitelist
    "Increase your conversion rate", # 'increase' in whitelist
    "Maximize engagement velocity",  # 'maximize' in whitelist
    "Pick a profitable niche",       # 'pick' in whitelist
    "Ship your first batch",         # 'ship' in whitelist
    "Scale operations carefully",    # not in whitelist; default-accept
    "Streamline your fulfillment",   # not in whitelist; default-accept
])
def test_verb_leading_accepts_common_imperatives(text):
    """Fix #2 - the old verb-stem heuristic falsely rejected many valid
    imperative verbs (Configuring, Consider, Handle, …). After the fix,
    the predicate's default-accept policy plus the broader whitelist
    let these pass on first try."""
    assert passes_framing(text, "verb_leading_action")


@pytest.mark.parametrize("text", [
    "1. Pick a niche",
    "2) Set up your store",
    "#3 Optimize listings",
])
def test_verb_leading_accepts_ordinal_prefix(text):
    """Action H2s with an ordinal prefix should pass - `1. Pick a niche`
    is still action-leading even though the first lexical token is '1.'."""
    assert passes_framing(text, "verb_leading_action")


@pytest.mark.parametrize("text", [
    "The best storefront layout",   # 'the'
    "Your TikTok Shop dashboard",   # 'your'
    "Top 5 monetization tactics",   # 'top'
    "Best practices for sellers",   # 'best'
    "Ultimate Guide to TikTok Shop",  # 'ultimate'
    "This year's TikTok trends",    # 'this'
])
def test_verb_leading_rejects_articles_determiners_and_superlatives(text):
    """Articles, possessive determiners, and superlative AI-tells are all
    rejected - these are noun-phrase / commercial leaders, not action."""
    assert not passes_framing(text, "verb_leading_action")


@pytest.mark.parametrize("text", [
    "Pricing",
    "Feature Set",
    "Customer Support",
    "Pricing and Plans",
])
def test_axis_passes_short_noun_phrases(text):
    assert passes_framing(text, "axis_noun_phrase")


@pytest.mark.parametrize("text", [
    "What is the best pricing plan",  # question
    "How do they handle support",     # question
])
def test_axis_rejects_questions(text):
    assert not passes_framing(text, "axis_noun_phrase")


def test_question_or_topic_accepts_anything_non_empty():
    assert passes_framing("What is X", "question_or_topic_phrase")
    assert passes_framing("Some random topic", "question_or_topic_phrase")
    assert not passes_framing("", "question_or_topic_phrase")
    assert not passes_framing("   ", "question_or_topic_phrase")


def test_no_constraint_always_passes():
    assert passes_framing("anything", "no_constraint")
    assert passes_framing("?", "no_constraint")


# ---------------------------------------------------------------------------
# validate_and_rewrite_framing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_constraint_template_is_noop():
    template = get_template("news")
    cands = [_candidate("Anything goes here"), _candidate("Even questions?")]
    called = False

    async def llm_fn(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    result = await validate_and_rewrite_framing(cands, template, llm_json_fn=llm_fn)
    assert called is False
    assert result.rewritten_indices == []
    assert result.accepted_with_violation_indices == []


@pytest.mark.asyncio
async def test_all_passing_skips_llm_call():
    """If every H2 already passes the regex, the LLM rewrite call must
    not fire (cost optimization + reduces flake surface)."""
    template = get_template("how-to")
    cands = [
        _candidate("Plan your launch"),
        _candidate("Set Up your store"),
        _candidate("Launch and iterate"),
    ]
    calls: list[tuple] = []

    async def llm_fn(system, user, **kwargs):
        calls.append((system, user))
        return {"rewrites": []}

    result = await validate_and_rewrite_framing(cands, template, llm_json_fn=llm_fn)
    assert calls == []
    assert result.llm_called is False
    assert result.rewritten_indices == []


@pytest.mark.asyncio
async def test_failing_h2s_are_rewritten_when_llm_returns_passing_text():
    template = get_template("how-to")
    cands = [
        _candidate("What is a TikTok Shop"),     # fails verb-leading
        _candidate("Set Up your store"),         # already passes
        _candidate("The Best Storefront Layout"),  # fails verb-leading
    ]

    async def llm_fn(system, user, **kwargs):
        # Fake an LLM that rewrites both failing H2s into action form.
        return {
            "rewrites": [
                {"index": 0, "text": "Set Up Your TikTok Shop"},
                {"index": 2, "text": "Design Your Storefront Layout"},
            ]
        }

    result = await validate_and_rewrite_framing(cands, template, llm_json_fn=llm_fn)
    assert sorted(result.rewritten_indices) == [0, 2]
    assert result.accepted_with_violation_indices == []
    assert cands[0].text == "Set Up Your TikTok Shop"
    assert cands[1].text == "Set Up your store"  # untouched
    assert cands[2].text == "Design Your Storefront Layout"


@pytest.mark.asyncio
async def test_rewrite_that_still_fails_regex_is_accepted_with_violation():
    """The LLM-rewritten text is re-checked against the regex; if it
    STILL fails, we accept the original and stamp accepted_with_violation."""
    template = get_template("how-to")
    cand = _candidate("What is a TikTok Shop")

    async def llm_fn(*args, **kwargs):
        # Returns another non-verb-leading heading
        return {"rewrites": [{"index": 0, "text": "The TikTok Shop Concept"}]}

    result = await validate_and_rewrite_framing([cand], template, llm_json_fn=llm_fn)
    assert result.rewritten_indices == []
    assert result.accepted_with_violation_indices == [0]
    # Original text preserved (we don't apply the failing rewrite)
    assert cand.text == "What is a TikTok Shop"


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_accept_with_violation():
    """LLM exception → log + accept all originals + flag llm_failed."""
    template = get_template("how-to")
    cand = _candidate("What is a TikTok Shop")

    async def boom(*args, **kwargs):
        raise RuntimeError("LLM outage")

    result = await validate_and_rewrite_framing([cand], template, llm_json_fn=boom)
    assert result.llm_called is True
    assert result.llm_failed is True
    assert result.accepted_with_violation_indices == [0]
    assert cand.text == "What is a TikTok Shop"


@pytest.mark.asyncio
async def test_partial_rewrite_response_handles_missing_indices():
    """If the LLM returns rewrites for only some failing H2s, the rest
    fall through to accept_with_violation."""
    template = get_template("how-to")
    cands = [
        _candidate("What is a Shop"),
        _candidate("How does it work"),
    ]

    async def llm_fn(*args, **kwargs):
        return {"rewrites": [{"index": 0, "text": "Set Up Your Shop"}]}

    result = await validate_and_rewrite_framing(cands, template, llm_json_fn=llm_fn)
    assert result.rewritten_indices == [0]
    assert result.accepted_with_violation_indices == [1]


@pytest.mark.asyncio
async def test_empty_candidate_list_is_noop():
    template = get_template("how-to")

    async def llm_fn(*args, **kwargs):
        raise AssertionError("Should not be called")

    result = await validate_and_rewrite_framing([], template, llm_json_fn=llm_fn)
    assert result.rewritten_indices == []
    assert result.accepted_with_violation_indices == []


@pytest.mark.asyncio
async def test_listicle_failures_get_ordinal_rewrites():
    """Listicle template: heading missing an ordinal should fail the
    regex and route to LLM rewrite."""
    template = get_template("listicle")
    cand = _candidate("Optimize your product photos")

    async def llm_fn(*args, **kwargs):
        return {"rewrites": [{"index": 0, "text": "1. Optimize your product photos"}]}

    result = await validate_and_rewrite_framing([cand], template, llm_json_fn=llm_fn)
    assert result.rewritten_indices == [0]
    assert cand.text == "1. Optimize your product photos"
