"""Unit tests for the content-writer prose provider router.

Covers the pure provider selection: normalization, the per-request contextvar,
and the missing-key degrade (openai selected but OPENAI_API_KEY unset ⇒ Claude).
No network / no LLM call is made.
"""

from __future__ import annotations

from modules.writer import prose_llm


def test_normalize_provider():
    assert prose_llm.normalize_provider("openai") == "openai"
    assert prose_llm.normalize_provider("OpenAI") == "openai"
    assert prose_llm.normalize_provider(" openai ") == "openai"
    assert prose_llm.normalize_provider("anthropic") == "anthropic"
    assert prose_llm.normalize_provider("") == "anthropic"
    assert prose_llm.normalize_provider(None) == "anthropic"
    assert prose_llm.normalize_provider("gpt-4") == "anthropic"  # unknown ⇒ default


def test_default_provider_is_anthropic():
    # A fresh contextvar (no set) reads anthropic.
    assert prose_llm.normalize_provider(prose_llm._provider_var.get()) == "anthropic"


def test_set_provider_routes_openai_when_keyed(monkeypatch):
    monkeypatch.setattr(prose_llm.settings, "openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(
        prose_llm.settings, "content_writer_openai_model", "gpt-5.6-luna", raising=False
    )
    token = prose_llm.set_prose_provider("openai")
    try:
        assert prose_llm.current_prose_provider() == "openai"
        assert prose_llm.effective_prose_model() == "gpt-5.6-luna"
    finally:
        prose_llm.reset_prose_provider(token)


def test_openai_degrades_to_anthropic_without_key(monkeypatch):
    monkeypatch.setattr(prose_llm.settings, "openai_api_key", "", raising=False)
    token = prose_llm.set_prose_provider("openai")
    try:
        # Selected openai but no key ⇒ effective provider is anthropic, no model.
        assert prose_llm.current_prose_provider() == "anthropic"
        assert prose_llm.effective_prose_model() is None
    finally:
        prose_llm.reset_prose_provider(token)


def test_anthropic_selection(monkeypatch):
    monkeypatch.setattr(prose_llm.settings, "openai_api_key", "sk-test", raising=False)
    token = prose_llm.set_prose_provider("anthropic")
    try:
        assert prose_llm.current_prose_provider() == "anthropic"
        assert prose_llm.effective_prose_model() is None
    finally:
        prose_llm.reset_prose_provider(token)
