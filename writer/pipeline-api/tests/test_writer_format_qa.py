"""End-of-run format QA - the "is this the right KIND of article?" check.

One Haiku call after final assembly judging keyword vs delivered H2
outline. Warn-and-accept + best-effort: verdicts flag metadata, failures
return unknown (all-None), nothing aborts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from models.writer import ArticleSection
from modules.writer import format_qa as fq
from modules.writer.format_qa import check_format_qa, check_notes_landed


def _article(h2s: list[str]) -> list[ArticleSection]:
    return [
        ArticleSection(order=i + 1, level="H2", type="content", heading=h, body="w")
        for i, h in enumerate(h2s)
    ]


_KW = "10 best freight audit companies 2026"
_OUTLINE = ["What Freight Audit Companies Do", "How Freight Audits Work"]


@pytest.mark.asyncio
async def test_mismatch_flags_metadata_fields():
    mock = AsyncMock(return_value={
        "matches": False,
        "expected_archetype": "listicle",
        "note": "Keyword calls for a ranked list; outline is explanatory prose.",
    })
    with patch.object(fq, "claude_json", mock):
        result = await check_format_qa(
            keyword=_KW, intent_type="informational",
            title="Freight Audit Companies Guide", article=_article(_OUTLINE),
        )
    assert result.matches_intent is False
    assert result.expected_archetype == "listicle"
    assert result.note
    assert mock.await_args.kwargs["model"] == fq.settings.writer_format_qa_model
    # The prompt carries the keyword, the planned intent, and the outline.
    user = mock.await_args.args[1]
    assert _KW in user and "informational" in user and _OUTLINE[0] in user


@pytest.mark.asyncio
async def test_match_verdict_passes_through():
    mock = AsyncMock(return_value={
        "matches": True, "expected_archetype": "listicle", "note": "ok",
    })
    with patch.object(fq, "claude_json", mock):
        result = await check_format_qa(
            keyword=_KW, intent_type="listicle",
            title="10 Best Freight Audit Companies",
            article=_article(["1. Company A", "2. Company B"]),
        )
    assert result.matches_intent is True


@pytest.mark.asyncio
async def test_api_error_returns_unknown():
    mock = AsyncMock(side_effect=RuntimeError("api down"))
    with patch.object(fq, "claude_json", mock):
        result = await check_format_qa(
            keyword=_KW, intent_type="informational",
            title="t", article=_article(_OUTLINE),
        )
    assert (result.matches_intent, result.expected_archetype, result.note) == (None, None, None)


@pytest.mark.asyncio
async def test_malformed_verdict_returns_unknown():
    mock = AsyncMock(return_value={"matches": "yes", "expected_archetype": "listicle"})
    with patch.object(fq, "claude_json", mock):
        result = await check_format_qa(
            keyword=_KW, intent_type="informational",
            title="t", article=_article(_OUTLINE),
        )
    assert result.matches_intent is None


@pytest.mark.asyncio
async def test_invalid_archetype_label_dropped_but_verdict_kept():
    mock = AsyncMock(return_value={
        "matches": False, "expected_archetype": "buying-guide", "note": "n",
    })
    with patch.object(fq, "claude_json", mock):
        result = await check_format_qa(
            keyword=_KW, intent_type="informational",
            title="t", article=_article(_OUTLINE),
        )
    assert result.matches_intent is False
    assert result.expected_archetype is None


@pytest.mark.asyncio
async def test_disabled_setting_skips_call(monkeypatch):
    monkeypatch.setattr(fq.settings, "writer_format_qa_enabled", False)
    mock = AsyncMock()
    with patch.object(fq, "claude_json", mock):
        result = await check_format_qa(
            keyword=_KW, intent_type="informational",
            title="t", article=_article(_OUTLINE),
        )
    assert result.matches_intent is None
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_outline_skips_call():
    mock = AsyncMock()
    with patch.object(fq, "claude_json", mock):
        result = await check_format_qa(
            keyword=_KW, intent_type="informational", title="t", article=[],
        )
    assert result.matches_intent is None
    mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Notes-landed judge
# ---------------------------------------------------------------------------

_NOTES = "Mention Zero Down Supply Chain Services as one of the top 10 best."


@pytest.mark.asyncio
async def test_notes_judge_landed_verdicts_pass_through():
    mock = AsyncMock(return_value={"directives": [
        {"note": "Mention ZDSCS in the top 10", "landed": True,
         "evidence": "Zero Down Supply Chain Services rounds out our top picks"},
    ]})
    with patch.object(fq, "claude_json", mock):
        result = await check_notes_landed(user_notes=_NOTES, article=_article(_OUTLINE))
    assert result.landed_all is True
    assert len(result.verdicts) == 1 and result.verdicts[0]["landed"] is True
    # Prompt carries the notes and the article text (headings + bodies).
    user = mock.await_args.args[1]
    assert _NOTES in user and _OUTLINE[0] in user
    assert mock.await_args.kwargs["model"] == fq.settings.writer_format_qa_model


@pytest.mark.asyncio
async def test_notes_judge_flags_missed_directive():
    mock = AsyncMock(return_value={"directives": [
        {"note": "Mention ZDSCS", "landed": False, "evidence": "Company never appears"},
        {"note": "Lead with 2026 trends", "landed": True, "evidence": "2026 trends open the intro"},
    ]})
    with patch.object(fq, "claude_json", mock):
        result = await check_notes_landed(user_notes=_NOTES, article=_article(_OUTLINE))
    assert result.landed_all is False
    assert [v["landed"] for v in result.verdicts] == [False, True]


@pytest.mark.asyncio
async def test_notes_judge_skips_when_no_notes():
    mock = AsyncMock()
    with patch.object(fq, "claude_json", mock):
        result = await check_notes_landed(user_notes=None, article=_article(_OUTLINE))
        blank = await check_notes_landed(user_notes="   ", article=_article(_OUTLINE))
    assert result.landed_all is None and result.verdicts == []
    assert blank.landed_all is None
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_notes_judge_error_returns_unknown():
    mock = AsyncMock(side_effect=RuntimeError("api down"))
    with patch.object(fq, "claude_json", mock):
        result = await check_notes_landed(user_notes=_NOTES, article=_article(_OUTLINE))
    assert result.landed_all is None and result.verdicts == []


@pytest.mark.asyncio
async def test_notes_judge_malformed_verdicts_return_unknown():
    mock = AsyncMock(return_value={"directives": [{"note": "x", "landed": "yes"}]})
    with patch.object(fq, "claude_json", mock):
        result = await check_notes_landed(user_notes=_NOTES, article=_article(_OUTLINE))
    assert result.landed_all is None and result.verdicts == []


@pytest.mark.asyncio
async def test_notes_judge_respects_disabled_setting(monkeypatch):
    monkeypatch.setattr(fq.settings, "writer_notes_qa_enabled", False)
    mock = AsyncMock()
    with patch.object(fq, "claude_json", mock):
        result = await check_notes_landed(user_notes=_NOTES, article=_article(_OUTLINE))
    assert result.landed_all is None
    mock.assert_not_awaited()
