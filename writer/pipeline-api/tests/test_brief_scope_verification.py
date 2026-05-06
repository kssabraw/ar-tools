"""Unit tests for Brief Generator v2.0 Step 8.5 - scope verification.

Mocks the LLM via injected llm_json_fn; no real Claude calls.
"""

from __future__ import annotations

import pytest

from modules.brief.graph import Candidate
from modules.brief.scope_verification import (
    ScopeVerificationResult,
    verify_scope,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _make_llm_mock(*responses):
    iterator = iter(responses)

    async def _mock(system, user, **kw):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    return _mock


def _make_h2(text: str) -> Candidate:
    c = Candidate(text=text, source="serp")  # type: ignore[arg-type]
    c.region_id = "region_0"
    return c


def _build_payload(*pairs):
    """pairs: (h2_text, classification) tuples → strict-schema payload."""
    return {
        "verified_h2s": [
            {
                "h2_text": text,
                "scope_classification": cls,
                "reasoning": f"reason for {text}",
            }
            for text, cls in pairs
        ]
    }


_TITLE = "What TikTok Shop Is and How It Works in 2026"
_SCOPE = (
    "Defines TikTok Shop and explains how it works for sellers and "
    "buyers. Does not cover advanced seller tactics, algorithm "
    "optimization, or inventory management decisions."
)


# ----------------------------------------------------------------------
# Routing - in_scope / borderline / out_of_scope
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_routes_in_scope_kept():
    h2 = _make_h2("How TikTok Shop Works")
    payload = _build_payload(("How TikTok Shop Works", "in_scope"))
    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[h2], llm_json_fn=_make_llm_mock(payload),
    )
    assert res.kept == [h2]
    assert res.rejected == []
    assert h2.scope_classification == "in_scope"
    assert h2.discard_reason is None


@pytest.mark.asyncio
async def test_routes_borderline_kept_and_counted():
    h2 = _make_h2("Who Should Use TikTok Shop")
    payload = _build_payload(("Who Should Use TikTok Shop", "borderline"))
    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[h2], llm_json_fn=_make_llm_mock(payload),
    )
    assert h2 in res.kept
    assert res.borderline_count == 1
    assert h2.scope_classification == "borderline"


@pytest.mark.asyncio
async def test_routes_out_of_scope_rejected():
    h2 = _make_h2("How to Optimize for TikTok Shop Algorithm")
    payload = _build_payload(
        ("How to Optimize for TikTok Shop Algorithm", "out_of_scope")
    )
    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[h2], llm_json_fn=_make_llm_mock(payload),
    )
    assert res.kept == []
    assert h2 in res.rejected
    assert res.rejected_count == 1
    assert h2.discard_reason == "scope_verification_out_of_scope"
    # scope_classification stays None so downstream silo routing
    # recognizes this as a rejection
    assert h2.scope_classification is None


@pytest.mark.asyncio
async def test_mixed_classification_routes_correctly():
    in_h2 = _make_h2("How TikTok Shop Works")
    border_h2 = _make_h2("Who Can Sell on TikTok Shop")
    out_h2 = _make_h2("How to Run TikTok Shop Ads")
    payload = _build_payload(
        ("How TikTok Shop Works", "in_scope"),
        ("Who Can Sell on TikTok Shop", "borderline"),
        ("How to Run TikTok Shop Ads", "out_of_scope"),
    )
    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[in_h2, border_h2, out_h2],
        llm_json_fn=_make_llm_mock(payload),
    )
    assert in_h2 in res.kept
    assert border_h2 in res.kept
    assert out_h2 in res.rejected
    assert res.borderline_count == 1
    assert res.rejected_count == 1
    assert in_h2.scope_classification == "in_scope"
    assert border_h2.scope_classification == "borderline"
    assert out_h2.discard_reason == "scope_verification_out_of_scope"


# ----------------------------------------------------------------------
# Empty input - no LLM call
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_input_returns_empty_result_no_llm_call():
    called = False

    async def boom(*a, **k):
        nonlocal called
        called = True
        raise AssertionError("LLM should not be called with empty input")

    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[], llm_json_fn=boom,
    )
    assert res.kept == []
    assert res.rejected == []
    assert res.fallback_applied is False
    assert called is False


# ----------------------------------------------------------------------
# Default in_scope when LLM omits an H2
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_h2_in_response_defaults_to_in_scope():
    """LLM only classified one of three - the other two default to in_scope.

    PRD: 'no classification' is treated as a pass (we keep it).
    """
    h2_a = _make_h2("A")
    h2_b = _make_h2("B")
    h2_c = _make_h2("C")
    payload = _build_payload(("A", "out_of_scope"))  # only A returned
    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[h2_a, h2_b, h2_c],
        llm_json_fn=_make_llm_mock(payload),
    )
    assert h2_a in res.rejected
    assert h2_b in res.kept
    assert h2_c in res.kept
    assert h2_b.scope_classification == "in_scope"
    assert h2_c.scope_classification == "in_scope"


# ----------------------------------------------------------------------
# Rogue classification (LLM hallucinates an H2 not in the input)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rogue_classification_dropped(caplog):
    h2 = _make_h2("Real H2")
    payload = _build_payload(
        ("Real H2", "in_scope"),
        ("Hallucinated H2 LLM Made Up", "out_of_scope"),
    )
    with caplog.at_level("WARNING", logger="modules.brief.scope_verification"):
        res = await verify_scope(
            title=_TITLE, scope_statement=_SCOPE,
            selected_h2s=[h2], llm_json_fn=_make_llm_mock(payload),
        )
    # Real H2 is processed correctly
    assert h2 in res.kept
    # Rogue classification logged but discarded
    assert any(
        r.message == "brief.scope.rogue_classification"
        for r in caplog.records
    )


# ----------------------------------------------------------------------
# Validation failures → retry → success
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_on_non_dict_payload():
    h2 = _make_h2("X")
    good = _build_payload(("X", "in_scope"))
    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[h2],
        llm_json_fn=_make_llm_mock("not a dict", good),
    )
    assert h2 in res.kept
    assert res.fallback_applied is False


@pytest.mark.asyncio
async def test_retry_on_invalid_classification_value():
    h2 = _make_h2("X")
    bad = {"verified_h2s": [
        {"h2_text": "X", "scope_classification": "maybe", "reasoning": ""}
    ]}
    good = _build_payload(("X", "in_scope"))
    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[h2], llm_json_fn=_make_llm_mock(bad, good),
    )
    assert h2 in res.kept
    assert res.fallback_applied is False


@pytest.mark.asyncio
async def test_retry_on_llm_exception():
    h2 = _make_h2("X")
    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[h2],
        llm_json_fn=_make_llm_mock(
            RuntimeError("boom"),
            _build_payload(("X", "in_scope")),
        ),
    )
    assert h2 in res.kept
    assert res.fallback_applied is False


# ----------------------------------------------------------------------
# Double failure → fallback (accept all as in_scope)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_double_failure_fallback_accepts_all():
    h2_a = _make_h2("A")
    h2_b = _make_h2("B")
    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[h2_a, h2_b],
        llm_json_fn=_make_llm_mock("garbage1", "garbage2"),
    )
    # PRD: do not abort, accept everything as in_scope
    assert h2_a in res.kept
    assert h2_b in res.kept
    assert res.rejected == []
    assert res.fallback_applied is True
    assert h2_a.scope_classification == "in_scope"
    assert h2_b.scope_classification == "in_scope"


@pytest.mark.asyncio
async def test_double_llm_exception_fallback_accepts_all():
    h2 = _make_h2("X")
    res = await verify_scope(
        title=_TITLE, scope_statement=_SCOPE,
        selected_h2s=[h2],
        llm_json_fn=_make_llm_mock(
            RuntimeError("a"), RuntimeError("b"),
        ),
    )
    assert h2 in res.kept
    assert res.fallback_applied is True
    assert h2.scope_classification == "in_scope"


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logs_complete_summary(caplog):
    h2 = _make_h2("X")
    payload = _build_payload(("X", "in_scope"))
    with caplog.at_level("INFO", logger="modules.brief.scope_verification"):
        await verify_scope(
            title=_TITLE, scope_statement=_SCOPE,
            selected_h2s=[h2], llm_json_fn=_make_llm_mock(payload),
        )
    assert any(r.message == "brief.scope.complete" for r in caplog.records)
    assert any(r.message == "brief.scope.verified" for r in caplog.records)


@pytest.mark.asyncio
async def test_logs_fallback_warning(caplog):
    h2 = _make_h2("X")
    with caplog.at_level("WARNING", logger="modules.brief.scope_verification"):
        await verify_scope(
            title=_TITLE, scope_statement=_SCOPE,
            selected_h2s=[h2],
            llm_json_fn=_make_llm_mock("bad1", "bad2"),
        )
    assert any(r.message == "brief.scope.fallback" for r in caplog.records)
