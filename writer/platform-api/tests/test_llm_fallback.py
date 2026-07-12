"""Unit tests for the cross-provider LLM fallback layer (services/report_llm.py).

The chain is exercised by monkeypatching the per-provider runners + settings, so
no real provider is ever hit. Backoff is neutralized by setting the per-provider
retry budget to 0 (a transient error then advances immediately, no sleeps)."""

import httpx
import pytest

from services import report_llm as rl


def _transient() -> Exception:
    """A 429 shaped like the Gemini REST path raises — classified transient."""
    return httpx.HTTPStatusError(
        "rate limited",
        request=httpx.Request("POST", "http://x"),
        response=httpx.Response(429),
    )


@pytest.fixture(autouse=True)
def _fast_chain(monkeypatch):
    """All three provider keys present; no per-provider retry backoff."""
    monkeypatch.setattr(rl.settings, "anthropic_api_key", "a", raising=False)
    monkeypatch.setattr(rl.settings, "openai_api_key", "o", raising=False)
    monkeypatch.setattr(rl.settings, "gemini_api_key", "g", raising=False)
    monkeypatch.setattr(rl.settings, "llm_fallback_enabled", True, raising=False)
    monkeypatch.setattr(rl.settings, "llm_fallback_providers", "openai,gemini", raising=False)
    monkeypatch.setattr(rl.settings, "llm_fallback_max_retries_per_provider", 0, raising=False)


# ── pure helpers ─────────────────────────────────────────────────────────────
def test_provider_chain_dedup_and_order():
    assert rl._provider_chain("anthropic") == ["anthropic", "openai", "gemini"]
    # primary already in the fallback list → not duplicated, stays first
    assert rl._provider_chain("openai") == ["openai", "gemini"]


def test_provider_chain_disabled_returns_primary_only(monkeypatch):
    monkeypatch.setattr(rl.settings, "llm_fallback_enabled", False, raising=False)
    assert rl._provider_chain("anthropic") == ["anthropic"]


def test_model_for_resolution(monkeypatch):
    monkeypatch.setattr(rl.settings, "llm_fallback_openai_model", "gpt-x", raising=False)
    monkeypatch.setattr(rl.settings, "llm_fallback_gemini_model", "gem-x", raising=False)
    # primary keeps the caller's model
    assert rl._model_for("anthropic", "anthropic", "claude-1", None) == "claude-1"
    # fallback provider uses its config default
    assert rl._model_for("openai", "anthropic", "claude-1", None) == "gpt-x"
    assert rl._model_for("gemini", "anthropic", "claude-1", None) == "gem-x"
    # explicit override wins
    assert rl._model_for("openai", "anthropic", "claude-1", {"openai": "over"}) == "over"


def test_is_transient_classifies_httpx():
    assert rl.is_transient_llm_error(_transient())
    assert rl.is_transient_llm_error(
        httpx.HTTPStatusError("boom", request=httpx.Request("POST", "http://x"),
                              response=httpx.Response(503))
    )
    assert not rl.is_transient_llm_error(
        httpx.HTTPStatusError("bad", request=httpx.Request("POST", "http://x"),
                              response=httpx.Response(400))
    )
    assert rl.is_transient_llm_error(httpx.ConnectError("down"))
    assert not rl.is_transient_llm_error(ValueError("nope"))


def test_to_gemini_schema_transforms_types_and_drops_keys():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "$schema": "http://json-schema.org/draft-07/schema#",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": ["integer", "null"], "description": "n"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name"],
    }
    out = rl._to_gemini_schema(schema)
    assert out["type"] == "OBJECT"
    assert "additionalProperties" not in out and "$schema" not in out
    assert out["properties"]["name"]["type"] == "STRING"
    assert out["properties"]["count"]["type"] == "INTEGER"  # list → non-null
    assert out["properties"]["count"]["description"] == "n"
    assert out["properties"]["tags"]["items"]["type"] == "STRING"
    assert out["required"] == ["name"]


def test_gemini_parsers():
    data = {"candidates": [{"content": {"parts": [
        {"text": "hello "}, {"text": "world"},
    ]}, "finishReason": "STOP"}]}
    assert rl._gemini_text(data) == "hello world"
    assert rl._gemini_finish(data) == "STOP"

    fc = {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "emit", "args": {"a": 1}}},
    ]}}]}
    assert rl._gemini_function_args(fc, "emit") == {"a": 1}
    assert rl._gemini_function_args(fc, "other") is None
    assert rl._gemini_function_args({"candidates": []}, "emit") is None


# ── forced-tool chain (async) ────────────────────────────────────────────────
_FT_KW = dict(
    model="claude-x", system="sys", user="usr", tool_name="emit",
    tool_description="d", input_schema={"type": "object"}, max_tokens=100,
)


async def test_forced_tool_falls_back_to_openai_on_transient(monkeypatch):
    calls = []

    async def anthro(**kw):
        calls.append("anthropic")
        raise _transient()

    async def openai(**kw):
        calls.append("openai")
        return {"ok": True}, "tool_use"

    monkeypatch.setattr(rl, "_run_anthropic", anthro)
    monkeypatch.setattr(rl, "_run_openai", openai)
    out = await rl.run_forced_tool(provider="anthropic", **_FT_KW)
    assert out == {"ok": True}
    assert calls == ["anthropic", "openai"]


async def test_forced_tool_chains_to_gemini_when_openai_also_fails(monkeypatch):
    async def fail(**kw):
        raise _transient()

    async def gemini(**kw):
        return {"g": 1}, "STOP"

    monkeypatch.setattr(rl, "_run_anthropic", fail)
    monkeypatch.setattr(rl, "_run_openai", fail)
    monkeypatch.setattr(rl, "_run_gemini", gemini)
    out = await rl.run_forced_tool(provider="anthropic", **_FT_KW)
    assert out == {"g": 1}


async def test_forced_tool_non_transient_raises_without_fallback(monkeypatch):
    calls = []

    async def anthro(**kw):
        calls.append("anthropic")
        raise ValueError("bad request")

    async def openai(**kw):  # pragma: no cover - must not run
        calls.append("openai")
        return {"ok": True}, "tool_use"

    monkeypatch.setattr(rl, "_run_anthropic", anthro)
    monkeypatch.setattr(rl, "_run_openai", openai)
    with pytest.raises(ValueError):
        await rl.run_forced_tool(provider="anthropic", **_FT_KW)
    assert calls == ["anthropic"]  # no fallback on a non-transient error


async def test_forced_tool_skips_provider_missing_key(monkeypatch):
    calls = []

    async def openai(**kw):
        calls.append("openai")
        return {"ok": True}, "tool_use"

    monkeypatch.setattr(rl.settings, "anthropic_api_key", "", raising=False)  # unconfigured
    monkeypatch.setattr(rl, "_run_openai", openai)
    out = await rl.run_forced_tool(provider="anthropic", **_FT_KW)
    assert out == {"ok": True}
    assert calls == ["openai"]  # anthropic skipped, went straight to openai


async def test_forced_tool_empty_result_advances(monkeypatch):
    async def anthro(**kw):
        return None, "end_turn"  # model didn't emit the tool

    async def openai(**kw):
        return {"ok": True}, "tool_use"

    monkeypatch.setattr(rl, "_run_anthropic", anthro)
    monkeypatch.setattr(rl, "_run_openai", openai)
    out = await rl.run_forced_tool(provider="anthropic", **_FT_KW)
    assert out == {"ok": True}


async def test_forced_tool_all_fail_raises_transient(monkeypatch):
    async def fail(**kw):
        raise _transient()

    monkeypatch.setattr(rl, "_run_anthropic", fail)
    monkeypatch.setattr(rl, "_run_openai", fail)
    monkeypatch.setattr(rl, "_run_gemini", fail)
    with pytest.raises(httpx.HTTPStatusError):
        await rl.run_forced_tool(provider="anthropic", **_FT_KW)


# ── text chain (async + sync) ────────────────────────────────────────────────
async def test_generate_text_falls_back(monkeypatch):
    async def anthro(**kw):
        raise _transient()

    async def openai(**kw):
        return "fallback text"

    monkeypatch.setattr(rl, "_run_anthropic_text", anthro)
    monkeypatch.setattr(rl, "_run_openai_text", openai)
    out = await rl.generate_text(user="hi", max_tokens=50, model="claude-x")
    assert out == "fallback text"


async def test_generate_text_empty_advances(monkeypatch):
    async def anthro(**kw):
        return "   "  # whitespace-only → treated as empty, advance

    async def openai(**kw):
        return "real"

    monkeypatch.setattr(rl, "_run_anthropic_text", anthro)
    monkeypatch.setattr(rl, "_run_openai_text", openai)
    assert await rl.generate_text(user="hi", max_tokens=50) == "real"


def test_generate_text_sync_falls_back(monkeypatch):
    def anthro(**kw):
        raise _transient()

    def openai(**kw):
        return "sync fallback"

    monkeypatch.setattr(rl, "_run_anthropic_text_sync", anthro)
    monkeypatch.setattr(rl, "_run_openai_text_sync", openai)
    assert rl.generate_text_sync(user="hi", max_tokens=50) == "sync fallback"


def test_run_forced_tool_sync_falls_back(monkeypatch):
    def anthro(**kw):
        raise _transient()

    def openai(**kw):
        return {"ok": 1}, "tool_use"

    monkeypatch.setattr(rl, "_run_anthropic_sync", anthro)
    monkeypatch.setattr(rl, "_run_openai_sync", openai)
    assert rl.run_forced_tool_sync(provider="anthropic", **_FT_KW) == {"ok": 1}
