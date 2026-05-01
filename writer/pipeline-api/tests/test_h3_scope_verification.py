"""Step 8.5b — Authority Gap H3 scope verification (PRD v2.0.3)."""

from __future__ import annotations

import pytest

from modules.brief.graph import Candidate
from modules.brief.scope_verification import (
    H3ScopeVerificationResult,
    verify_h3_scope,
)


def _make_h3(text: str) -> Candidate:
    c = Candidate(text=text, source="authority_gap_sme")  # type: ignore[arg-type]
    c.exempt = True
    return c


def _llm_mock(*responses):
    iterator = iter(responses)

    async def _mock(system, user, **kw):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    return _mock


def _payload(*pairs):
    """pairs: (h3_text, classification) → strict-schema response."""
    return {
        "verified_h3s": [
            {"h3_text": text, "scope_classification": cls,
             "reasoning": f"reason for {text}"}
            for text, cls in pairs
        ]
    }


_TITLE = "How to Open a TikTok Shop"
_SCOPE = (
    "Covers eligibility, signup, document verification, and first-product "
    "listing. Does not cover post-launch operations, marketing, or "
    "creator program enrollment."
)


# ----------------------------------------------------------------------
# Routing — in_scope / borderline / out_of_scope
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_in_scope_h3_kept_with_classification_stamped():
    h3 = _make_h3("Documents to prepare before signup")
    res = await verify_h3_scope(
        title=_TITLE, scope_statement=_SCOPE,
        h3s=[h3],
        llm_json_fn=_llm_mock(_payload(("Documents to prepare before signup", "in_scope"))),
    )
    assert res.kept == [h3]
    assert res.rejected == []
    assert h3.scope_classification == "in_scope"
    assert h3.discard_reason is None


@pytest.mark.asyncio
async def test_borderline_h3_kept_and_counted():
    h3 = _make_h3("How long the verification queue takes")
    res = await verify_h3_scope(
        title=_TITLE, scope_statement=_SCOPE,
        h3s=[h3],
        llm_json_fn=_llm_mock(_payload(("How long the verification queue takes", "borderline"))),
    )
    assert h3 in res.kept
    assert res.borderline_count == 1
    assert h3.scope_classification == "borderline"


@pytest.mark.asyncio
async def test_out_of_scope_h3_routed_with_discard_reason():
    h3 = _make_h3("Why sellers abandon their TikTok Shop within 60 days")
    res = await verify_h3_scope(
        title=_TITLE, scope_statement=_SCOPE,
        h3s=[h3],
        llm_json_fn=_llm_mock(_payload(("Why sellers abandon their TikTok Shop within 60 days", "out_of_scope"))),
    )
    assert res.kept == []
    assert h3 in res.rejected
    assert res.rejected_count == 1
    assert h3.discard_reason == "scope_verification_out_of_scope"
    # scope_classification stays None so downstream silo routing
    # recognizes this as scope-rejected, not borderline-kept.
    assert h3.scope_classification is None


@pytest.mark.asyncio
async def test_mixed_classifications_route_correctly():
    in_h3 = _make_h3("In-scope thing")
    border_h3 = _make_h3("Borderline thing")
    out_h3 = _make_h3("Way out of scope thing")
    res = await verify_h3_scope(
        title=_TITLE, scope_statement=_SCOPE,
        h3s=[in_h3, border_h3, out_h3],
        llm_json_fn=_llm_mock(_payload(
            ("In-scope thing", "in_scope"),
            ("Borderline thing", "borderline"),
            ("Way out of scope thing", "out_of_scope"),
        )),
    )
    assert in_h3 in res.kept
    assert border_h3 in res.kept
    assert out_h3 in res.rejected
    assert res.borderline_count == 1
    assert res.rejected_count == 1


# ----------------------------------------------------------------------
# Empty / fallback paths
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_h3_input_short_circuits_no_llm_call():
    called = False

    async def boom(*a, **k):
        nonlocal called
        called = True
        raise AssertionError("must not call LLM with empty input")

    res = await verify_h3_scope(
        title=_TITLE, scope_statement=_SCOPE,
        h3s=[], llm_json_fn=boom,
    )
    assert res.kept == []
    assert res.rejected == []
    assert res.fallback_applied is False
    assert called is False


@pytest.mark.asyncio
async def test_double_failure_falls_back_to_in_scope():
    h3_a = _make_h3("A")
    h3_b = _make_h3("B")
    res = await verify_h3_scope(
        title=_TITLE, scope_statement=_SCOPE,
        h3s=[h3_a, h3_b],
        llm_json_fn=_llm_mock("garbage1", "garbage2"),
    )
    assert h3_a in res.kept
    assert h3_b in res.kept
    assert res.fallback_applied is True
    assert h3_a.scope_classification == "in_scope"


@pytest.mark.asyncio
async def test_double_llm_exception_falls_back():
    h3 = _make_h3("X")
    res = await verify_h3_scope(
        title=_TITLE, scope_statement=_SCOPE,
        h3s=[h3],
        llm_json_fn=_llm_mock(RuntimeError("a"), RuntimeError("b")),
    )
    assert h3 in res.kept
    assert res.fallback_applied is True


@pytest.mark.asyncio
async def test_retry_on_invalid_payload_then_success():
    h3 = _make_h3("X")
    bad = {"verified_h3s": [{"h3_text": "X", "scope_classification": "maybe"}]}
    good = _payload(("X", "in_scope"))
    res = await verify_h3_scope(
        title=_TITLE, scope_statement=_SCOPE,
        h3s=[h3], llm_json_fn=_llm_mock(bad, good),
    )
    assert h3 in res.kept
    assert res.fallback_applied is False


@pytest.mark.asyncio
async def test_missing_h3_in_response_defaults_to_in_scope():
    """LLM only classified one of two — the other defaults to in_scope."""
    h3_a = _make_h3("A")
    h3_b = _make_h3("B")
    res = await verify_h3_scope(
        title=_TITLE, scope_statement=_SCOPE,
        h3s=[h3_a, h3_b],
        llm_json_fn=_llm_mock(_payload(("A", "out_of_scope"))),  # only A
    )
    assert h3_a in res.rejected
    assert h3_b in res.kept
    assert h3_b.scope_classification == "in_scope"


@pytest.mark.asyncio
async def test_rogue_classification_dropped(caplog):
    h3 = _make_h3("Real H3")
    payload = _payload(
        ("Real H3", "in_scope"),
        ("Hallucinated H3", "out_of_scope"),
    )
    with caplog.at_level("WARNING", logger="modules.brief.scope_verification"):
        res = await verify_h3_scope(
            title=_TITLE, scope_statement=_SCOPE,
            h3s=[h3], llm_json_fn=_llm_mock(payload),
        )
    assert h3 in res.kept
    assert any(
        r.message == "brief.scope_h3.rogue_classification"
        for r in caplog.records
    )


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logs_complete_summary(caplog):
    h3 = _make_h3("X")
    with caplog.at_level("INFO", logger="modules.brief.scope_verification"):
        await verify_h3_scope(
            title=_TITLE, scope_statement=_SCOPE,
            h3s=[h3], llm_json_fn=_llm_mock(_payload(("X", "in_scope"))),
        )
    assert any(r.message == "brief.scope_h3.complete" for r in caplog.records)
    assert any(r.message == "brief.scope_h3.verified" for r in caplog.records)
