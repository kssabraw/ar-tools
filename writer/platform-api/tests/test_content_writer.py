"""Unit tests for services.content_writer — the pure provider resolver.

The effective content-writer provider is: run/request override ?? client default
?? "anthropic". Pure — no network / no DB.
"""

from __future__ import annotations

from services import content_writer as cw


def test_default_when_nothing_set():
    assert cw.resolve_content_writer_provider(None, None) == "anthropic"
    assert cw.resolve_content_writer_provider(None, {}) == "anthropic"


def test_client_default_used_when_no_override():
    assert cw.resolve_content_writer_provider(None, {"content_writer_provider": "openai"}) == "openai"
    assert cw.resolve_content_writer_provider(None, {"content_writer_provider": "anthropic"}) == "anthropic"


def test_override_wins_over_client_default():
    client = {"content_writer_provider": "anthropic"}
    assert cw.resolve_content_writer_provider("openai", client) == "openai"
    client2 = {"content_writer_provider": "openai"}
    assert cw.resolve_content_writer_provider("anthropic", client2) == "anthropic"


def test_unknown_values_fall_through():
    # An unknown override is ignored -> falls to the client default.
    assert cw.resolve_content_writer_provider("gpt-4", {"content_writer_provider": "openai"}) == "openai"
    # An unknown client default is ignored -> falls to "anthropic".
    assert cw.resolve_content_writer_provider(None, {"content_writer_provider": "bananas"}) == "anthropic"
    # Both unknown -> default.
    assert cw.resolve_content_writer_provider("nope", {"content_writer_provider": "nope"}) == "anthropic"


def test_case_and_whitespace_normalized():
    assert cw.resolve_content_writer_provider("  OpenAI ", None) == "openai"
    assert cw.resolve_content_writer_provider(None, {"content_writer_provider": "ANTHROPIC"}) == "anthropic"


def test_normalize_provider():
    assert cw.normalize_provider("openai") == "openai"
    assert cw.normalize_provider("Anthropic") == "anthropic"
    assert cw.normalize_provider("") is None
    assert cw.normalize_provider(None) is None
    assert cw.normalize_provider("xyz") is None
