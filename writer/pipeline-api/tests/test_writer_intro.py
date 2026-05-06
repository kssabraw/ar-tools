"""Tests for the Agree / Promise / Preview intro generator (three-block format)."""

from __future__ import annotations

from typing import Any

import pytest

from modules.writer.banned_terms import build_banned_regex
from modules.writer.intro import (
    INTRO_MAX_WORDS,
    INTRO_MAX_WORDS_PER_BLOCK,
    INTRO_MIN_WORDS,
    _validate_intro_blocks,
    write_intro,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _blocks(agree_n: int = 30, promise_n: int = 27, preview_n: int = 25) -> tuple[str, str, str]:
    """Return (agree, promise, preview) with the specified word counts."""
    return (
        " ".join(["word"] * agree_n),
        " ".join(["word"] * promise_n),
        " ".join(["word"] * preview_n),
    )


def _fake(*responses: Any):
    """Return an async function that yields each response in turn."""
    iterator = iter(responses)

    async def _call(system, user, **kwargs):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    return _call


def _valid_payload(agree_n: int = 30, promise_n: int = 27, preview_n: int = 25) -> dict:
    agree, promise, preview = _blocks(agree_n, promise_n, preview_n)
    return {
        "agree_style_selected": "direct_thesis",
        "agree": agree,
        "promise": promise,
        "preview": preview,
    }


# ---------------------------------------------------------------------------
# Pure validator (sync, no LLM)
# ---------------------------------------------------------------------------

def test_validate_intro_blocks_accepts_valid_blocks():
    agree, promise, preview = _blocks()
    ok, _ = _validate_intro_blocks(agree, promise, preview)
    assert ok is True


def test_validate_intro_blocks_rejects_total_too_short():
    # 10 + 10 + 10 = 30 words - below INTRO_MIN_WORDS (80)
    agree, promise, preview = _blocks(agree_n=10, promise_n=10, preview_n=10)
    ok, msg = _validate_intro_blocks(agree, promise, preview)
    assert ok is False
    assert "too short" in msg


def test_validate_intro_blocks_rejects_total_too_long():
    # 45 + 45 + 45 = 135 words - above INTRO_MAX_WORDS (120); each block ≤ 50
    agree, promise, preview = _blocks(agree_n=45, promise_n=45, preview_n=45)
    ok, msg = _validate_intro_blocks(agree, promise, preview)
    assert ok is False
    assert "too long" in msg


def test_validate_intro_blocks_rejects_block_over_50_words():
    agree = " ".join(["word"] * (INTRO_MAX_WORDS_PER_BLOCK + 5))
    promise = " ".join(["word"] * 25)
    preview = " ".join(["word"] * 25)
    ok, msg = _validate_intro_blocks(agree, promise, preview)
    assert ok is False
    assert "'agree' block" in msg


def test_validate_intro_blocks_rejects_empty_agree():
    _, promise, preview = _blocks()
    ok, msg = _validate_intro_blocks("", promise, preview)
    assert ok is False
    assert "agree" in msg


def test_validate_intro_blocks_rejects_empty_promise():
    agree, _, preview = _blocks()
    ok, msg = _validate_intro_blocks(agree, "", preview)
    assert ok is False
    assert "promise" in msg


def test_validate_intro_blocks_rejects_empty_preview():
    agree, promise, _ = _blocks()
    ok, msg = _validate_intro_blocks(agree, promise, "")
    assert ok is False
    assert "preview" in msg


def test_validate_intro_blocks_rejects_heading_marker():
    agree = "# Heading inside agree " + " ".join(["word"] * 29)
    _, promise, preview = _blocks()
    ok, msg = _validate_intro_blocks(agree, promise, preview)
    assert ok is False
    assert "heading marker" in msg


def test_validate_intro_blocks_rejects_bullet_list():
    agree = "- bullet item\n" + " ".join(["word"] * 29)
    _, promise, preview = _blocks()
    ok, msg = _validate_intro_blocks(agree, promise, preview)
    assert ok is False
    assert "list marker" in msg


def test_validate_intro_blocks_rejects_numbered_list():
    agree = "1. numbered item\n" + " ".join(["word"] * 29)
    _, promise, preview = _blocks()
    ok, msg = _validate_intro_blocks(agree, promise, preview)
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
    assert "\n\n" in section.body  # three blocks separated by blank lines
    assert INTRO_MIN_WORDS <= section.word_count <= INTRO_MAX_WORDS


@pytest.mark.asyncio
async def test_write_intro_body_joins_three_blocks(monkeypatch):
    agree = " ".join(["word"] * 30)
    promise = " ".join(["word"] * 27)
    preview = " ".join(["word"] * 25)
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake({
            "agree_style_selected": "failure_mode",
            "agree": agree,
            "promise": promise,
            "preview": preview,
        }),
    )

    section = await write_intro(
        keyword="kw", title="t", scope_statement="",
        intent_type="how-to", h2_list=[],
        brand_voice_card=None, banned_regex=build_banned_regex([]),
        intro_order=1,
    )
    assert section.body == f"{agree}\n\n{promise}\n\n{preview}"


@pytest.mark.asyncio
async def test_write_intro_retries_on_word_count_then_succeeds(monkeypatch):
    # First attempt: total only 30 words - too short
    short_payload = {
        "agree_style_selected": "direct_thesis",
        "agree": " ".join(["word"] * 10),
        "promise": " ".join(["word"] * 10),
        "preview": " ".join(["word"] * 10),
    }
    monkeypatch.setattr(
        "modules.writer.intro.claude_json",
        _fake(short_payload, _valid_payload()),
    )

    section = await write_intro(
        keyword="kw", title="t", scope_statement="", intent_type="how-to",
        h2_list=["A", "B"], brand_voice_card=None,
        banned_regex=build_banned_regex([]), intro_order=2,
    )
    assert INTRO_MIN_WORDS <= section.word_count <= INTRO_MAX_WORDS


@pytest.mark.asyncio
async def test_write_intro_accepts_with_warning_after_two_failures(monkeypatch):
    # Both attempts produce too-short blocks - module accepts with warning
    bad_payload = {
        "agree_style_selected": "direct_thesis",
        "agree": "tiny agree",
        "promise": "tiny promise",
        "preview": "tiny preview",
    }
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
    assert "tiny agree" in section.body


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
    labelled to NOT be enumerated in the Preview."""
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
