"""Step 8.7 — H3 Parent-Fit Verification (PRD v2.2 / Phase 2)."""

from __future__ import annotations

import math

import pytest

from modules.brief.graph import Candidate
from modules.brief.h3_parent_fit import (
    FitVerificationResult,
    verify_h3_parent_fit,
)


def _unit(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def _h2(text: str, region: str, embedding: list[float]) -> Candidate:
    c = Candidate(text=text, source="serp")
    c.region_id = region
    c.embedding = _unit(embedding)
    return c


def _h3(
    text: str,
    region: str,
    embedding: list[float],
    *,
    source: str = "serp",
    parent_h2_text: str = "",
    parent_relevance: float = 0.7,
) -> Candidate:
    c = Candidate(text=text, source=source)  # type: ignore[arg-type]
    c.region_id = region
    c.embedding = _unit(embedding)
    c.parent_h2_text = parent_h2_text
    c.parent_relevance = parent_relevance
    return c


def _classifier(by_id: dict[str, str]):
    """Return a fake claude_json that emits the given classifications.

    Maps `h3_id` → classification. Missing ids default to `good`.
    """
    async def fake(system, user, **kwargs):
        # Find all h3_ids in the user payload
        import re as _re
        ids = _re.findall(r'"h3_id":\s*"([^"]+)"', user)
        verifications = [
            {
                "h3_id": i,
                "classification": by_id.get(i, "good"),
                "reasoning": "test",
            }
            for i in ids
        ]
        return {"verifications": verifications}
    return fake


# ---------------------------------------------------------------------------
# No-op + edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_attachments_returns_noop():
    result = await verify_h3_parent_fit(
        selected_h2s=[_h2("H2", "r1", [1, 0, 0])],
        h2_attachments={},
        llm_json_fn=_classifier({}),
    )
    assert result.marginal_count == 0
    assert result.wrong_parent_count == 0
    assert result.promoted_count == 0
    assert not result.llm_called


@pytest.mark.asyncio
async def test_all_good_classification_noop():
    h2 = _h2("H2", "r1", [1, 0, 0])
    h3 = _h3("Sub-topic", "r1", [0.9, 0.1, 0], parent_h2_text="H2")
    attachments = {0: [h3]}
    result = await verify_h3_parent_fit(
        selected_h2s=[h2],
        h2_attachments=attachments,
        llm_json_fn=_classifier({}),  # all default to good
    )
    assert result.llm_called is True
    assert attachments[0] == [h3]
    assert h3.parent_fit_classification is None
    assert h3.discard_reason is None


# ---------------------------------------------------------------------------
# Marginal classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_marginal_stamps_classification_and_keeps_h3():
    h2 = _h2("H2", "r1", [1, 0, 0])
    h3 = _h3("Edge case", "r1", [0.85, 0.2, 0], parent_h2_text="H2")
    attachments = {0: [h3]}
    result = await verify_h3_parent_fit(
        selected_h2s=[h2],
        h2_attachments=attachments,
        llm_json_fn=_classifier({"h2_0.h3_0": "marginal"}),
    )
    assert h3 in attachments[0]
    assert h3.parent_fit_classification == "marginal"
    assert result.marginal_count == 1
    assert h3.discard_reason is None


# ---------------------------------------------------------------------------
# wrong_parent — re-attachment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_parent_reattaches_to_better_h2():
    """If the LLM marks an H3 as wrong_parent and a different H2 has
    capacity + clears the parent_relevance floor, re-attach there."""
    h2_a = _h2("Cart Abandonment", "r1", [1, 0, 0])
    h2_b = _h2("Affiliate Strategy", "r2", [0, 1, 0])
    # H3 originally under h2_a but cosine to h2_b is high.
    h3 = _h3("Vetting affiliates", "r1",
            [0, 0.95, 0.1], parent_h2_text="Cart Abandonment")
    attachments = {0: [h3], 1: []}
    result = await verify_h3_parent_fit(
        selected_h2s=[h2_a, h2_b],
        h2_attachments=attachments,
        llm_json_fn=_classifier({"h2_0.h3_0": "wrong_parent"}),
    )
    assert attachments[0] == []
    assert h3 in attachments[1]
    assert h3.parent_h2_text == "Affiliate Strategy"
    assert h3.parent_relevance > 0.65
    assert result.wrong_parent_count == 1
    assert len(result.reattached) == 1
    assert h3 not in result.routed_to_silos
    assert h3.discard_reason is None  # not a silo reject


@pytest.mark.asyncio
async def test_wrong_parent_routes_to_silo_when_no_better_parent():
    """If no other H2 fits (all below floor or no capacity), the H3
    is removed and routed to silos with discard_reason='h3_wrong_parent'."""
    h2_a = _h2("H2 A", "r1", [1, 0, 0])
    h2_b = _h2("H2 B", "r2", [-1, 0, 0])  # opposite direction
    h3 = _h3("Misfit topic", "r1",
            [0.9, 0.1, 0], parent_h2_text="H2 A")
    attachments = {0: [h3], 1: []}
    result = await verify_h3_parent_fit(
        selected_h2s=[h2_a, h2_b],
        h2_attachments=attachments,
        llm_json_fn=_classifier({"h2_0.h3_0": "wrong_parent"}),
    )
    assert attachments[0] == []
    assert attachments[1] == []
    assert h3 in result.routed_to_silos
    assert h3.discard_reason == "h3_wrong_parent"
    assert result.wrong_parent_count == 1
    assert len(result.reattached) == 0


@pytest.mark.asyncio
async def test_wrong_parent_skips_full_h2():
    """A candidate parent already at max_h3_per_h2 should NOT be
    selected as the re-attachment target."""
    h2_a = _h2("H2 A", "r1", [1, 0, 0])
    h2_b = _h2("H2 B", "r2", [0, 1, 0])
    # H2 B already has 2 H3s — full.
    full_a = _h3("F1", "r2", [0, 0.9, 0], parent_h2_text="H2 B")
    full_b = _h3("F2", "r2", [0, 0.95, 0], parent_h2_text="H2 B")
    misfit = _h3("Misfit", "r1", [0, 0.93, 0], parent_h2_text="H2 A")
    attachments = {0: [misfit], 1: [full_a, full_b]}
    result = await verify_h3_parent_fit(
        selected_h2s=[h2_a, h2_b],
        h2_attachments=attachments,
        llm_json_fn=_classifier({"h2_0.h3_0": "wrong_parent"}),
    )
    # H2 B is full → misfit routes to silos, not re-attached
    assert misfit in result.routed_to_silos
    assert misfit.discard_reason == "h3_wrong_parent"


# ---------------------------------------------------------------------------
# promote_to_h2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_to_h2_routes_to_silo():
    h2 = _h2("Cart Abandonment", "r1", [1, 0, 0])
    h3 = _h3("How algorithm signals weight new sellers", "r1",
            [0.7, 0.3, 0.4], parent_h2_text="Cart Abandonment")
    attachments = {0: [h3]}
    result = await verify_h3_parent_fit(
        selected_h2s=[h2],
        h2_attachments=attachments,
        llm_json_fn=_classifier({"h2_0.h3_0": "promote_to_h2"}),
    )
    assert attachments[0] == []
    assert h3 in result.routed_to_silos
    assert h3.discard_reason == "h3_promoted_to_h2_candidate"
    assert result.promoted_count == 1


# ---------------------------------------------------------------------------
# Authority-gap exemption
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authority_gap_promote_downgrades_to_marginal():
    """Authority-gap H3s are never discarded (PRD §5 Step 9). When the
    LLM says `promote_to_h2`, downgrade to `marginal` so the H3 stays
    under its current parent with the flag set."""
    h2 = _h2("H2", "r1", [1, 0, 0])
    h3 = _h3("Authority topic", "r1", [0.7, 0.3, 0],
            source="authority_gap_sme", parent_h2_text="H2")
    attachments = {0: [h3]}
    result = await verify_h3_parent_fit(
        selected_h2s=[h2],
        h2_attachments=attachments,
        llm_json_fn=_classifier({"h2_0.h3_0": "promote_to_h2"}),
    )
    assert h3 in attachments[0]
    assert h3.parent_fit_classification == "marginal"
    assert h3.discard_reason is None
    assert result.marginal_count == 1
    assert result.promoted_count == 0


@pytest.mark.asyncio
async def test_authority_gap_wrong_parent_with_no_fitting_parent_downgrades():
    """Authority-gap H3 with `wrong_parent` and no fitting alternative
    parent → downgrade to marginal under current parent (don't discard)."""
    h2_a = _h2("H2 A", "r1", [1, 0, 0])
    h2_b = _h2("H2 B", "r2", [-1, 0, 0])
    h3 = _h3("Auth misfit", "r1", [0.9, 0.1, 0],
            source="authority_gap_sme", parent_h2_text="H2 A")
    attachments = {0: [h3], 1: []}
    result = await verify_h3_parent_fit(
        selected_h2s=[h2_a, h2_b],
        h2_attachments=attachments,
        llm_json_fn=_classifier({"h2_0.h3_0": "wrong_parent"}),
    )
    assert h3 in attachments[0]
    assert h3.parent_fit_classification == "marginal"
    assert h3.discard_reason is None
    assert result.marginal_count == 1


# ---------------------------------------------------------------------------
# Fallback paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_accept_all():
    """LLM exception on both attempts → accept all as `good`."""
    h2 = _h2("H2", "r1", [1, 0, 0])
    h3 = _h3("Sub", "r1", [0.9, 0.1, 0], parent_h2_text="H2")
    attachments = {0: [h3]}

    async def boom(*args, **kwargs):
        raise RuntimeError("LLM outage")

    result = await verify_h3_parent_fit(
        selected_h2s=[h2],
        h2_attachments=attachments,
        llm_json_fn=boom,
    )
    assert result.fallback_applied is True
    # H3 stays under original parent, no flag stamped, no discard
    assert h3 in attachments[0]
    assert h3.parent_fit_classification is None
    assert h3.discard_reason is None


@pytest.mark.asyncio
async def test_malformed_json_then_recovery():
    """First attempt returns garbage; second attempt succeeds → use
    second-attempt classifications."""
    h2 = _h2("H2", "r1", [1, 0, 0])
    h3 = _h3("Sub", "r1", [0.9, 0.1, 0], parent_h2_text="H2")
    attachments = {0: [h3]}

    call_count = {"n": 0}

    async def two_attempt(system, user, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "not a dict"
        return {"verifications": [
            {"h3_id": "h2_0.h3_0", "classification": "marginal", "reasoning": "edge"},
        ]}

    result = await verify_h3_parent_fit(
        selected_h2s=[h2],
        h2_attachments=attachments,
        llm_json_fn=two_attempt,
    )
    assert call_count["n"] == 2
    assert result.fallback_applied is False
    assert h3.parent_fit_classification == "marginal"
    assert result.marginal_count == 1


@pytest.mark.asyncio
async def test_rogue_h3_id_silently_dropped():
    """LLM returns a classification for an h3_id we didn't send.
    Drop the rogue entry; the legit H3 still gets its real
    classification (or the default)."""
    h2 = _h2("H2", "r1", [1, 0, 0])
    h3 = _h3("Sub", "r1", [0.9, 0.1, 0], parent_h2_text="H2")
    attachments = {0: [h3]}

    async def with_rogue(*args, **kwargs):
        return {"verifications": [
            {"h3_id": "h2_0.h3_0", "classification": "good", "reasoning": ""},
            {"h3_id": "h2_99.h3_99", "classification": "wrong_parent", "reasoning": "ghost"},
        ]}

    result = await verify_h3_parent_fit(
        selected_h2s=[h2],
        h2_attachments=attachments,
        llm_json_fn=with_rogue,
    )
    assert result.fallback_applied is False
    assert h3 in attachments[0]
    assert h3.parent_fit_classification is None
