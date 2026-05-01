"""Tests for the v1.6 Agree/Promise/Preview intro generator."""

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


# -----------------------------------------------------------------------
# Pure validator (sync, no LLM)
# -----------------------------------------------------------------------

def test_validate_intro_accepts_well_formed_paragraph():
    body = " ".join(["word"] * 100)
    ok, _ = _validate_intro(body)
    assert ok is True


def test_validate_intro_rejects_too_short():
    ok, msg = _validate_intro("a b c d e")
    assert ok is False
    assert "too short" in msg


def test_validate_intro_rejects_too_long():
    ok, msg = _validate_intro(" ".join(["word"] * (INTRO_MAX_WORDS + 5)))
    assert ok is False
    assert "too long" in msg


def test_validate_intro_rejects_paragraph_break():
    body = ("word " * 70).strip() + "\n\n" + ("more " * 30).strip()
    ok, msg = _validate_intro(body)
    assert ok is False
    assert "paragraph break" in msg


def test_validate_intro_rejects_heading_marker():
    body = "# Heading inside intro " + ("word " * 70).strip()
    ok, msg = _validate_intro(body)
    assert ok is False
    assert "heading marker" in msg


def test_validate_intro_rejects_bullet_list():
    body = "- bullet\n" + ("word " * 70).strip()
    ok, msg = _validate_intro(body)
    assert ok is False
    assert "list marker" in msg


def test_validate_intro_rejects_numbered_list():
    body = "1. numbered\n" + ("word " * 70).strip()
    ok, msg = _validate_intro(body)
    assert ok is False
    assert "list marker" in msg


def test_validate_intro_rejects_empty():
    ok, _ = _validate_intro("")
    assert ok is False


# -----------------------------------------------------------------------
# Full write_intro flow with a fake claude_json
# -----------------------------------------------------------------------

def _fake(*responses: Any):
    """Return an async function that yields each response in turn."""
    iterator = iter(responses)

    async def _call(system, user, **kwargs):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    return _call


@pytest.mark.asyncio
async def test_write_intro_happy_path(monkeypatch):
    body = "Many readers asking about TikTok Shop want a concrete picture of how it differs from a search-driven storefront. " + " ".join(["word"] * 60)
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake({"intro": body}),
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
    assert section.body == body
    assert INTRO_MIN_WORDS <= section.word_count <= INTRO_MAX_WORDS


@pytest.mark.asyncio
async def test_write_intro_retries_on_word_count_then_succeeds(monkeypatch):
    short_body = " ".join(["word"] * 20)  # too short
    good_body = " ".join(["word"] * 100)
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake({"intro": short_body}, {"intro": good_body}),
    )

    section = await write_intro(
        keyword="kw", title="t", scope_statement="s", intent_type="how-to",
        h2_list=["A", "B"], brand_voice_card=None,
        banned_regex=build_banned_regex([]), intro_order=2,
    )
    assert section.body == good_body


@pytest.mark.asyncio
async def test_write_intro_accepts_with_warning_after_retry_failure(monkeypatch):
    # Both attempts fail validation (too short with paragraph break) — module
    # should normalize and accept rather than abort.
    bad1 = "tiny"
    bad2 = "still tiny"
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake({"intro": bad1}, {"intro": bad2}),
    )

    section = await write_intro(
        keyword="kw", title="t", scope_statement="", intent_type="how-to",
        h2_list=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]), intro_order=2,
    )
    # Accept-with-warning path: the body is the (normalized) second attempt.
    assert section.type == "intro"
    assert section.body == bad2


@pytest.mark.asyncio
async def test_write_intro_normalizes_paragraph_break_after_retry(monkeypatch):
    # First: paragraph break. Second: still has break. Should normalize.
    body_with_break = ("word " * 50).strip() + "\n\n" + ("word " * 50).strip()
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake({"intro": body_with_break}, {"intro": body_with_break}),
    )

    section = await write_intro(
        keyword="kw", title="t", scope_statement="", intent_type="how-to",
        h2_list=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]), intro_order=2,
    )
    assert "\n\n" not in section.body  # normalized


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
