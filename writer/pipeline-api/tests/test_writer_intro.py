"""Tests for the free-form brand-voice intro generator."""

from __future__ import annotations

from typing import Any

import pytest

from modules.writer.banned_terms import build_banned_regex
from modules.writer.intro import (
    INTRO_MAX_WORDS,
    INTRO_MIN_WORDS,
    _validate_intro,
    write_intro,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _intro_text(n_words: int = 90) -> str:
    return " ".join(["word"] * n_words)


def _fake(*responses: Any):
    """Return an async function that yields each response in turn."""
    iterator = iter(responses)

    async def _call(system, user, **kwargs):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    return _call


def _valid_payload(n_words: int = 90) -> dict:
    return {"intro": _intro_text(n_words)}


# ---------------------------------------------------------------------------
# Pure validator (sync, no LLM)
# ---------------------------------------------------------------------------

def test_validate_intro_accepts_valid_intro():
    ok, _ = _validate_intro(_intro_text(90))
    assert ok is True


def test_validate_intro_rejects_empty():
    ok, msg = _validate_intro("")
    assert ok is False
    assert "empty" in msg


def test_validate_intro_rejects_total_too_short():
    ok, msg = _validate_intro(_intro_text(30))
    assert ok is False
    assert "too short" in msg


def test_validate_intro_rejects_total_too_long():
    ok, msg = _validate_intro(_intro_text(150))
    assert ok is False
    assert "too long" in msg


def test_validate_intro_rejects_heading_marker():
    body = "# Heading inside intro\n" + _intro_text(89)
    ok, msg = _validate_intro(body)
    assert ok is False
    assert "heading marker" in msg


def test_validate_intro_rejects_bullet_list():
    body = "- bullet item\n" + _intro_text(89)
    ok, msg = _validate_intro(body)
    assert ok is False
    assert "list marker" in msg


def test_validate_intro_rejects_numbered_list():
    body = "1. numbered item\n" + _intro_text(89)
    ok, msg = _validate_intro(body)
    assert ok is False
    assert "list marker" in msg


# ---------------------------------------------------------------------------
# Full write_intro flow with a fake claude_json
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_intro_happy_path(monkeypatch):
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake(_valid_payload()),
    )

    section = await write_intro(
        keyword="how to open a tiktok shop",
        title="How to Open a TikTok Shop",
        scope_statement="Covers signup through first listing.",
        intent_type="how-to",
        h2_list=["Sign up", "Set up your shop", "List your first product"],
        brand_voice_card=None,
        banned_regex=build_banned_regex([]),
        intro_order=2,
    )
    assert section.type == "intro"
    assert section.level == "none"
    assert section.heading is None
    assert INTRO_MIN_WORDS <= section.word_count <= INTRO_MAX_WORDS


@pytest.mark.asyncio
async def test_write_intro_uses_intro_field_verbatim(monkeypatch):
    text = _intro_text(90)
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake({"intro": text}),
    )

    section = await write_intro(
        keyword="kw", title="t", scope_statement="",
        intent_type="how-to", h2_list=[],
        brand_voice_card=None, banned_regex=build_banned_regex([]),
        intro_order=1,
    )
    assert section.body == text


@pytest.mark.asyncio
async def test_write_intro_retries_on_word_count_then_succeeds(monkeypatch):
    # First attempt too short, second valid.
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake({"intro": _intro_text(30)}, _valid_payload()),
    )

    section = await write_intro(
        keyword="kw", title="t", scope_statement="", intent_type="how-to",
        h2_list=["A", "B"], brand_voice_card=None,
        banned_regex=build_banned_regex([]), intro_order=2,
    )
    assert INTRO_MIN_WORDS <= section.word_count <= INTRO_MAX_WORDS


@pytest.mark.asyncio
async def test_write_intro_accepts_with_warning_after_two_failures(monkeypatch):
    # Both attempts produce too-short text - module accepts with warning.
    bad_payload = {"intro": "tiny intro"}
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake(bad_payload, bad_payload),
    )

    section = await write_intro(
        keyword="kw", title="t", scope_statement="", intent_type="how-to",
        h2_list=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]), intro_order=2,
    )
    assert section.type == "intro"
    assert "tiny intro" in section.body


@pytest.mark.asyncio
async def test_write_intro_falls_back_to_placeholder_on_llm_exception(monkeypatch):
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake(RuntimeError("network down")),
    )

    section = await write_intro(
        keyword="kw", title="t", scope_statement="", intent_type="how-to",
        h2_list=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]), intro_order=2,
    )
    assert section.type == "intro"
    assert "INTRO GENERATION FAILED" in section.body
    assert section.word_count == 0


@pytest.mark.asyncio
async def test_write_intro_supporting_data_appears_in_prompt(monkeypatch):
    captured: dict = {}

    async def _capture(system, user, **kw):
        captured["user"] = user
        return _valid_payload()

    monkeypatch.setattr("modules.writer.intro.claude_json", _capture)

    await write_intro(
        keyword="kw", title="t", scope_statement="",
        intent_type="informational", h2_list=["A"],
        brand_voice_card=None, banned_regex=build_banned_regex([]),
        intro_order=1,
        supporting_data="73% of top-performing brands use this tactic.",
    )
    assert "SUPPORTING_DATA" in captured["user"]
    assert "73%" in captured["user"]


@pytest.mark.asyncio
async def test_write_intro_h2_list_passed_as_context_not_roadmap(monkeypatch):
    """H2 titles should appear in the prompt as topic context, clearly
    labelled to NOT be enumerated in the intro."""
    captured: dict = {}

    async def _capture(system, user, **kw):
        captured["user"] = user
        return _valid_payload()

    monkeypatch.setattr("modules.writer.intro.claude_json", _capture)

    await write_intro(
        keyword="kw", title="t", scope_statement="",
        intent_type="how-to",
        h2_list=["Step one", "Step two", "Step three"],
        brand_voice_card=None, banned_regex=build_banned_regex([]),
        intro_order=1,
    )
    assert "ARTICLE_TOPICS" in captured["user"]
    assert "context only" in captured["user"]
    assert "do NOT enumerate" in captured["user"]
    assert "Step one" in captured["user"]
