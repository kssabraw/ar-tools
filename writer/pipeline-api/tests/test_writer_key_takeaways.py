"""Tests for the Key Takeaways generator (content-quality PRD §R4)."""

from __future__ import annotations

from typing import Any

import pytest

from models.writer import BrandVoiceCard
from modules.writer.banned_terms import build_banned_regex
from modules.writer.key_takeaways import (
    KEY_TAKEAWAYS_MAX_BULLETS,
    KEY_TAKEAWAYS_MAX_WORDS_PER_BULLET,
    KEY_TAKEAWAYS_MIN_BULLETS,
    _validate_bullets,
    write_key_takeaways,
)


def _bullets(count: int = 4, words_per: int = 15) -> list[str]:
    return [
        " ".join(["word"] * words_per) + f" item {i}"
        for i in range(count)
    ]


def _fake(*responses: Any):
    iterator = iter(responses)

    async def _call(system, user, **kwargs):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        _call.last_user = user  # type: ignore[attr-defined]
        return item

    _call.last_user = ""  # type: ignore[attr-defined]
    return _call


def _valid_payload(count: int = 4, words_per: int = 15) -> dict:
    return {"key_takeaways": _bullets(count=count, words_per=words_per)}


# ---------------------------------------------------------------------------
# Pure validator
# ---------------------------------------------------------------------------

def test_validate_bullets_accepts_valid_set():
    ok, _ = _validate_bullets(_bullets(count=4, words_per=15))
    assert ok is True


def test_validate_bullets_rejects_too_few():
    ok, msg = _validate_bullets(_bullets(count=2, words_per=15))
    assert ok is False
    assert "at least" in msg


def test_validate_bullets_rejects_too_many():
    ok, msg = _validate_bullets(_bullets(count=KEY_TAKEAWAYS_MAX_BULLETS + 1, words_per=15))
    assert ok is False
    assert "at most" in msg


def test_validate_bullets_rejects_long_bullet():
    bullets = _bullets(count=4, words_per=KEY_TAKEAWAYS_MAX_WORDS_PER_BULLET + 5)
    ok, msg = _validate_bullets(bullets)
    assert ok is False
    assert "words" in msg


def test_validate_bullets_rejects_empty_bullet():
    bullets = _bullets(count=4)
    bullets[2] = "   "
    ok, msg = _validate_bullets(bullets)
    assert ok is False
    assert "empty" in msg


def test_validate_bullets_rejects_heading_marker():
    bullets = _bullets(count=4)
    bullets[0] = "# Heading inside bullet text here"
    ok, msg = _validate_bullets(bullets)
    assert ok is False
    assert "heading marker" in msg


def test_validate_bullets_rejects_duplicate():
    bullets = _bullets(count=4)
    bullets[2] = bullets[1]
    ok, msg = _validate_bullets(bullets)
    assert ok is False
    assert "distinct" in msg


def test_validate_bullets_min_count_boundary_ok():
    ok, _ = _validate_bullets(_bullets(count=KEY_TAKEAWAYS_MIN_BULLETS, words_per=10))
    assert ok is True


def test_validate_bullets_max_count_boundary_ok():
    ok, _ = _validate_bullets(_bullets(count=KEY_TAKEAWAYS_MAX_BULLETS, words_per=10))
    assert ok is True


# ---------------------------------------------------------------------------
# write_key_takeaways flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_key_takeaways_happy_path(monkeypatch):
    monkeypatch.setattr(
        "modules.writer.key_takeaways.claude_json",
        _fake(_valid_payload()),
    )
    section = await write_key_takeaways(
        keyword="how to open a tiktok shop",
        intent_type="how-to",
        article_body="Body paragraph one.\n\nBody paragraph two.",
        brand_voice_card=None,
        banned_regex=build_banned_regex([]),
        key_takeaways_order=2,
    )
    assert section.type == "key-takeaways"
    assert section.heading == "Key Takeaways"
    assert section.level == "none"
    assert section.body.startswith("- ")
    assert section.body.count("\n- ") == 3  # 4 bullets total


@pytest.mark.asyncio
async def test_write_key_takeaways_retries_on_too_few(monkeypatch):
    short = {"key_takeaways": _bullets(count=2, words_per=10)}
    monkeypatch.setattr(
        "modules.writer.key_takeaways.claude_json",
        _fake(short, _valid_payload()),
    )
    section = await write_key_takeaways(
        keyword="kw", intent_type="how-to",
        article_body="Body.", brand_voice_card=None,
        banned_regex=build_banned_regex([]), key_takeaways_order=2,
    )
    assert section.body.count("\n- ") == 3  # 4 bullets after retry


@pytest.mark.asyncio
async def test_write_key_takeaways_accepts_with_warning_after_two_failures(monkeypatch):
    bad = {"key_takeaways": _bullets(count=2, words_per=10)}
    monkeypatch.setattr(
        "modules.writer.key_takeaways.claude_json",
        _fake(bad, bad),
    )
    section = await write_key_takeaways(
        keyword="kw", intent_type="how-to",
        article_body="Body.", brand_voice_card=None,
        banned_regex=build_banned_regex([]), key_takeaways_order=2,
    )
    # Body still contains the bullets even though count was below min
    assert section.type == "key-takeaways"
    assert section.body.startswith("- ")


@pytest.mark.asyncio
async def test_write_key_takeaways_falls_back_on_llm_exception(monkeypatch):
    monkeypatch.setattr(
        "modules.writer.key_takeaways.claude_json",
        _fake(RuntimeError("network down")),
    )
    section = await write_key_takeaways(
        keyword="kw", intent_type="how-to",
        article_body="Body.", brand_voice_card=None,
        banned_regex=build_banned_regex([]), key_takeaways_order=2,
    )
    assert section.type == "key-takeaways"
    assert "GENERATION FAILED" in section.body
    assert section.word_count == 0


@pytest.mark.asyncio
async def test_write_key_takeaways_article_body_in_prompt(monkeypatch):
    captured: dict = {}

    async def _capture(system, user, **kw):
        captured["user"] = user
        return _valid_payload()

    monkeypatch.setattr("modules.writer.key_takeaways.claude_json", _capture)
    await write_key_takeaways(
        keyword="kw", intent_type="how-to",
        article_body="UNIQUE_MARKER body content",
        brand_voice_card=None,
        banned_regex=build_banned_regex([]), key_takeaways_order=2,
    )
    assert "UNIQUE_MARKER" in captured["user"]
    assert "ARTICLE_BODY" in captured["user"]


@pytest.mark.asyncio
async def test_write_key_takeaways_brand_voice_in_prompt(monkeypatch):
    captured: dict = {}

    async def _capture(system, user, **kw):
        captured["user"] = user
        return _valid_payload()

    monkeypatch.setattr("modules.writer.key_takeaways.claude_json", _capture)
    card = BrandVoiceCard(
        tone_adjectives=["Confident", "Direct"],
        preferred_terms=["creators", "ROI"],
        discouraged_terms=["magic"],
    )
    await write_key_takeaways(
        keyword="kw", intent_type="how-to",
        article_body="Body.", brand_voice_card=card,
        banned_regex=build_banned_regex([]), key_takeaways_order=2,
    )
    assert "Confident" in captured["user"]
    assert "creators" in captured["user"]
    assert "magic" in captured["user"]


@pytest.mark.asyncio
async def test_write_key_takeaways_banned_term_retries(monkeypatch):
    leak = {"key_takeaways": ["This bullet uses the badterm here in valid words"] + _bullets(count=3, words_per=10)}
    clean = _valid_payload()
    monkeypatch.setattr(
        "modules.writer.key_takeaways.claude_json",
        _fake(leak, clean),
    )
    section = await write_key_takeaways(
        keyword="kw", intent_type="how-to",
        article_body="Body.", brand_voice_card=None,
        banned_regex=build_banned_regex(["badterm"]), key_takeaways_order=2,
    )
    assert "badterm" not in section.body.lower()
