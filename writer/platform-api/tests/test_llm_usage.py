"""Unit tests for the LLM usage ledger pricing + recorder helpers.

No network: pricing math, the SDK-usage extractors, the ambient context merge,
and that record() is best-effort (no source → no-op; a broken DB insert is
swallowed, never raised).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# llm_usage imports db.supabase_client at load — stub it (tests never touch a DB).
if "db.supabase_client" not in sys.modules:
    sys.modules.setdefault("db", types.ModuleType("db"))
    _fake_db = types.ModuleType("db.supabase_client")
    _fake_db.get_supabase = lambda: None  # type: ignore[attr-defined]
    sys.modules["db.supabase_client"] = _fake_db

from services import llm_pricing  # noqa: E402
from services import llm_usage  # noqa: E402


# ── pricing ──────────────────────────────────────────────────────────────────

def test_price_for_known_and_unknown():
    assert llm_pricing.price_for("claude-sonnet-4-6") == (3.00, 15.00)
    assert llm_pricing.price_for("claude-sonnet-5") == (2.00, 10.00)
    assert llm_pricing.price_for("claude-haiku-4-5-20251001") == (1.00, 5.00)
    assert llm_pricing.price_for("claude-opus-5") == (5.00, 25.00)
    assert llm_pricing.price_for("gpt-5.6-luna") == (0.20, 1.20)
    # unknown → None (captured as tokens, unpriced)
    assert llm_pricing.price_for("gpt-5.4-mini") is None
    assert llm_pricing.price_for("sonar") is None
    assert llm_pricing.price_for(None) is None


def test_sonnet_versions_resolve_before_bare_sonnet():
    # sonnet-4-6 and sonnet-5 must not be shadowed by the bare "sonnet" default.
    assert llm_pricing.price_for("claude-sonnet-4-6") == (3.00, 15.00)
    assert llm_pricing.price_for("claude-sonnet-5") == (2.00, 10.00)
    # an unversioned sonnet still resolves to the default tier
    assert llm_pricing.price_for("some-sonnet-model") == (3.00, 15.00)


def test_compute_cost():
    # 1M in @ $3 + 0.5M out @ $15 = 3 + 7.5 = 10.5
    cost, priced = llm_pricing.compute_cost("claude-sonnet-4-6", 1_000_000, 500_000)
    assert priced is True and cost == 10.5
    # unknown model → tokens captured, cost 0, priced False
    cost, priced = llm_pricing.compute_cost("mystery-model", 1000, 1000)
    assert cost == 0.0 and priced is False


def test_register_prices_overrides():
    llm_pricing.register_prices({"gpt-5.4-mini": (0.10, 0.40)})
    try:
        assert llm_pricing.price_for("gpt-5.4-mini") == (0.10, 0.40)
        cost, priced = llm_pricing.compute_cost("gpt-5.4-mini", 1_000_000, 1_000_000)
        assert priced is True and cost == 0.5
    finally:
        llm_pricing._OTHER.clear()  # keep the module table clean for other tests


# ── usage extractors ─────────────────────────────────────────────────────────

class _Usage:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, usage):
        self.usage = usage


def test_anthropic_usage():
    assert llm_usage.anthropic_usage(_Resp(_Usage(input_tokens=120, output_tokens=45))) == (120, 45)
    assert llm_usage.anthropic_usage(_Resp(None)) == (0, 0)


def test_openai_usage_both_shapes():
    # Chat Completions shape
    assert llm_usage.openai_usage(_Resp(_Usage(prompt_tokens=90, completion_tokens=10))) == (90, 10)
    # Responses API shape
    assert llm_usage.openai_usage(_Resp(_Usage(input_tokens=200, output_tokens=30))) == (200, 30)


def test_dict_and_gemini_extractors():
    assert llm_usage.openai_usage_dict({"usage": {"prompt_tokens": 5, "completion_tokens": 6}}) == (5, 6)
    assert llm_usage.openai_usage_dict({"usage": {"input_tokens": 7, "output_tokens": 8}}) == (7, 8)
    assert llm_usage.gemini_usage({"usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 4}}) == (11, 4)
    assert llm_usage.gemini_usage({}) == (0, 0)
    assert llm_usage.openai_usage_dict(None) == (0, 0)


# ── record() best-effort behaviour ───────────────────────────────────────────

def test_record_noop_without_source():
    # No source (no ambient context, none passed) → records nothing, never raises.
    llm_usage.record(provider="openai", model="gpt-5.4", input_tokens=100, output_tokens=10)


def test_record_swallows_db_error():
    # get_supabase() is stubbed to None → .table() raises → record must swallow it.
    llm_usage.record(provider="anthropic", model="claude-sonnet-4-6", source="ai_visibility_scan",
                     input_tokens=100, output_tokens=50)  # must not raise


def test_record_skips_empty_usage():
    # source present but zero tokens and zero cost → nothing to record (returns early
    # before ever touching the DB, so the None stub is never hit).
    llm_usage.record(provider="openai", model="gpt-5.4", source="ai_visibility_scan",
                     input_tokens=0, output_tokens=0)


def test_usage_context_merges_and_resets():
    assert llm_usage._ctx.get() is None
    with llm_usage.usage_context(source="ai_visibility_scan", client_id="c1", metadata={"batch": "b1"}):
        ctx = llm_usage._ctx.get()
        assert ctx["source"] == "ai_visibility_scan"
        assert ctx["client_id"] == "c1"
        assert ctx["metadata"]["batch"] == "b1"
        with llm_usage.usage_context(actor_id="u1", metadata={"extra": "x"}):
            inner = llm_usage._ctx.get()
            assert inner["source"] == "ai_visibility_scan"  # inherited
            assert inner["actor_id"] == "u1"
            assert inner["metadata"] == {"batch": "b1", "extra": "x"}  # merged
        # inner reset — the outer context never had actor_id
        assert "actor_id" not in llm_usage._ctx.get()
    assert llm_usage._ctx.get() is None  # fully reset
