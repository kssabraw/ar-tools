"""Unit tests for the Anthropic prompt-caching helper (services/prompt_cache.py).

The helper is pure formatting — it turns a string into the block list that
carries a ``cache_control`` breakpoint — so the tests pin the shape, the kill
switch, and the total/idempotent guards that let it be applied unconditionally.
"""

from config import settings
from services import prompt_cache


def test_cache_text_wraps_a_string_with_an_ephemeral_breakpoint():
    out = prompt_cache.cache_text("a big invariant system prompt", enabled=True)
    assert out == [{
        "type": "text",
        "text": "a big invariant system prompt",
        "cache_control": {"type": "ephemeral"},
    }]


def test_cache_text_disabled_returns_the_plain_string_unchanged():
    # Kill switch ⇒ exact prior request shape (a bare string).
    assert prompt_cache.cache_text("hello", enabled=False) == "hello"


def test_cache_text_is_a_no_op_on_empty_and_non_strings():
    assert prompt_cache.cache_text("", enabled=True) == ""
    assert prompt_cache.cache_text(None, enabled=True) is None
    already = [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}]
    # Applying twice is a no-op: a block list is not a bare string.
    assert prompt_cache.cache_text(already, enabled=True) is already


def test_cache_text_reads_the_config_flag_when_no_override(monkeypatch):
    monkeypatch.setattr(settings, "prompt_cache_enabled", True)
    assert isinstance(prompt_cache.cache_text("ctx"), list)
    monkeypatch.setattr(settings, "prompt_cache_enabled", False)
    assert prompt_cache.cache_text("ctx") == "ctx"
