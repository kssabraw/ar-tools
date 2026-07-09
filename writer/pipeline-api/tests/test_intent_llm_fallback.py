"""Step 3.3 - LLM arbitration for the no-signal intent case.

Only fires when BOTH deterministic passes (keyword pattern precheck +
SERP-signal rules) come up empty; replaces the silent informational/0.55
default. Degrades back to that default on any failure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from models.brief import IntentSignals
from modules.brief import intent as intent_mod
from modules.brief.intent import classify_intent

# A keyword no deterministic pattern matches (not best/top-prefixed, no
# leading count, no how-to/what-is/vs token), paired with empty signals.
_NO_SIGNAL_KEYWORD = "freight audit companies ranked and compared"


@pytest.mark.asyncio
async def test_llm_fallback_classifies_when_nothing_matched():
    mock = AsyncMock(return_value={"intent": "listicle"})
    with patch.object(intent_mod, "claude_json", mock):
        intent, confidence, review = await classify_intent(
            keyword=_NO_SIGNAL_KEYWORD,
            signals=IntentSignals(),
            titles=["Best Freight Audit Companies", "Top Freight Audit Firms"],
            top_3_domains=[],
        )
    assert intent == "listicle"
    assert confidence == 0.75
    assert review is False
    mock.assert_awaited_once()
    # The arbitration call must use the configured cheap-tier model.
    assert mock.await_args.kwargs["model"] == intent_mod.settings.intent_llm_fallback_model


@pytest.mark.asyncio
async def test_llm_fallback_error_degrades_to_informational_default():
    mock = AsyncMock(side_effect=RuntimeError("api down"))
    with patch.object(intent_mod, "claude_json", mock):
        intent, confidence, review = await classify_intent(
            keyword=_NO_SIGNAL_KEYWORD,
            signals=IntentSignals(),
            titles=[],
            top_3_domains=[],
        )
    assert (intent, confidence, review) == ("informational", 0.55, True)


@pytest.mark.asyncio
async def test_llm_fallback_invalid_label_degrades_to_default():
    mock = AsyncMock(return_value={"intent": "buying-guide"})  # not in taxonomy
    with patch.object(intent_mod, "claude_json", mock):
        intent, confidence, review = await classify_intent(
            keyword=_NO_SIGNAL_KEYWORD,
            signals=IntentSignals(),
            titles=[],
            top_3_domains=[],
        )
    assert (intent, confidence, review) == ("informational", 0.55, True)


@pytest.mark.asyncio
async def test_llm_fallback_not_called_when_rules_matched():
    """A SERP signal match (news_box) means the deterministic classifier is
    authoritative - the LLM must not be consulted."""
    mock = AsyncMock(return_value={"intent": "listicle"})
    with patch.object(intent_mod, "claude_json", mock):
        intent, _, _ = await classify_intent(
            keyword=_NO_SIGNAL_KEYWORD,
            signals=IntentSignals(news_box=True),
            titles=[],
            top_3_domains=[],
        )
    assert intent == "news"
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_fallback_not_called_on_precheck_match():
    mock = AsyncMock(return_value={"intent": "informational"})
    with patch.object(intent_mod, "claude_json", mock):
        intent, _, _ = await classify_intent(
            keyword="10 best freight audit companies 2026",
            signals=IntentSignals(),
            titles=[],
            top_3_domains=[],
        )
    assert intent == "listicle"  # precheck short-circuits
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_fallback_respects_disabled_setting(monkeypatch):
    monkeypatch.setattr(intent_mod.settings, "intent_llm_fallback_enabled", False)
    mock = AsyncMock(return_value={"intent": "listicle"})
    with patch.object(intent_mod, "claude_json", mock):
        intent, confidence, review = await classify_intent(
            keyword=_NO_SIGNAL_KEYWORD,
            signals=IntentSignals(),
            titles=[],
            top_3_domains=[],
        )
    assert (intent, confidence, review) == ("informational", 0.55, True)
    mock.assert_not_awaited()
