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


class _Usage:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_usage_cache_fields_reads_the_two_counters():
    u = _Usage(input_tokens=100, cache_read_input_tokens=900, cache_creation_input_tokens=50)
    assert prompt_cache.usage_cache_fields(u) == {
        "cache_read_input_tokens": 900,
        "cache_creation_input_tokens": 50,
    }


def test_usage_cache_fields_zero_fills_absent_or_none():
    # A None usage, or one missing the counters (e.g. caching off), reads as zeros.
    assert prompt_cache.usage_cache_fields(None) == {
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
    }
    assert prompt_cache.usage_cache_fields(_Usage(input_tokens=10)) == {
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
    }


def test_add_cache_usage_accumulates_in_place_across_rounds():
    acc = {"input_tokens": 0, "output_tokens": 0}
    prompt_cache.add_cache_usage(acc, _Usage(cache_read_input_tokens=0, cache_creation_input_tokens=200))
    prompt_cache.add_cache_usage(acc, _Usage(cache_read_input_tokens=1800, cache_creation_input_tokens=0))
    prompt_cache.add_cache_usage(acc, None)  # tolerant of a missing usage
    assert acc["cache_read_input_tokens"] == 1800
    assert acc["cache_creation_input_tokens"] == 200
    # the pre-existing keys are left intact
    assert acc["input_tokens"] == 0 and acc["output_tokens"] == 0
