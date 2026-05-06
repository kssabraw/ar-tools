"""Step 8.7 - H3 Parent-Fit Verification (PRD v2.2 / Phase 2)."""

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
# wrong_parent - re-attachment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_parent_reattaches_to_same_region_h2():
    """PRD v2.2 / Phase 2 fix #2: re-attachment requires same region as
    the H3. If the LLM marks an H3 wrong_parent and a different H2 in
    the SAME region has capacity + clears the parent_relevance floor,
    re-attach there. Cross-region re-attachment is forbidden - that
    would silently re-introduce the v2.2 same-region drift fix."""
    # All three live in region r1. h3 is currently misplaced under
    # h2_a but cosine to h2_b is high. Both H2s in r1 → re-attach allowed.
    h2_a = _h2("Cart Abandonment", "r1", [1, 0, 0])
    h2_b = _h2("Affiliate Strategy", "r1", [0, 1, 0])
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
async def test_wrong_parent_does_not_reattach_cross_region():
    """PRD v2.2 / Phase 2 fix #2: even when a different-region H2 has
    capacity + high cosine to the H3, re-attachment is BLOCKED - the
    H3 routes to silos instead. This is the explicit guard against
    Step 8.7 silently undoing Step 8.6's same-region tightening."""
    h2_a = _h2("Cart Abandonment", "r1", [1, 0, 0])
    # h2_b lives in r2 - different region from the H3.
    h2_b = _h2("Affiliate Strategy", "r2", [0, 1, 0])
    h3 = _h3("Vetting affiliates", "r1",
             [0, 0.95, 0.1], parent_h2_text="Cart Abandonment")
    attachments = {0: [h3], 1: []}
    result = await verify_h3_parent_fit(
        selected_h2s=[h2_a, h2_b],
        h2_attachments=attachments,
        llm_json_fn=_classifier({"h2_0.h3_0": "wrong_parent"}),
    )
    # No same-region alternative → silo route.
    assert attachments[0] == []
    assert attachments[1] == []
    assert h3 in result.routed_to_silos
    assert h3.discard_reason == "h3_wrong_parent"
    assert len(result.reattached) == 0


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
    # H2 B already has 2 H3s - full.
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


# ---------------------------------------------------------------------------
# Phase 2 review fix #1 - list-mutation iteration regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_h3s_under_one_h2_with_mixed_routing():
    """Phase 2 review fix #1 - if an H2 has multiple H3s and the LLM
    routes them to different verdicts, every H3 must receive its OWN
    verdict, not the verdict of a sibling.

    Pre-fix: positional iteration with `attached.remove(h3)` shifted
    indices, causing later H3s to be processed under earlier H3s'
    verdicts (or skipped entirely)."""
    h2 = _h2("Parent H2", "r1", [1, 0, 0])
    a = _h3("A - promote me", "r1", [0.7, 0.3, 0],
            parent_h2_text="Parent H2")
    b = _h3("B - wrong parent", "r1", [0.7, 0.3, 0.1],
            parent_h2_text="Parent H2")
    c = _h3("C - leave alone", "r1", [0.75, 0.25, 0],
            parent_h2_text="Parent H2")
    attachments = {0: [a, b, c]}

    # Add a same-region alternative parent so b can re-attach (fix #2
    # requirement). Place it in r1 with high cosine to b.
    other_parent = _h2("Other H2", "r1", [0.7, 0.3, 0.1])
    attachments[1] = []

    result = await verify_h3_parent_fit(
        selected_h2s=[h2, other_parent],
        h2_attachments=attachments,
        llm_json_fn=_classifier({
            "h2_0.h3_0": "promote_to_h2",
            "h2_0.h3_1": "wrong_parent",
            "h2_0.h3_2": "good",
        }),
    )

    # A was promoted → silo
    assert a in result.routed_to_silos
    assert a.discard_reason == "h3_promoted_to_h2_candidate"
    # B was re-attached to other_parent (same region, has capacity)
    assert b in attachments[1]
    assert b not in attachments[0]
    assert b.parent_h2_text == "Other H2"
    # C was left alone - must still be under the original H2
    assert c in attachments[0]
    assert c.parent_fit_classification is None
    assert c.discard_reason is None
    # Counts add up
    assert result.promoted_count == 1
    assert result.wrong_parent_count == 1


@pytest.mark.asyncio
async def test_two_promote_to_h2_under_same_h2_does_not_skip_second():
    """Phase 2 review fix #1 - when two consecutive H3s under the same
    H2 are both promoted, the SECOND must not be silently skipped due
    to index shift after the first removal."""
    h2 = _h2("Parent", "r1", [1, 0, 0])
    a = _h3("A", "r1", [0.7, 0.3, 0], parent_h2_text="Parent")
    b = _h3("B", "r1", [0.75, 0.25, 0], parent_h2_text="Parent")
    attachments = {0: [a, b]}

    result = await verify_h3_parent_fit(
        selected_h2s=[h2],
        h2_attachments=attachments,
        llm_json_fn=_classifier({
            "h2_0.h3_0": "promote_to_h2",
            "h2_0.h3_1": "promote_to_h2",
        }),
    )

    # BOTH H3s must be removed and silo'd, not just A.
    assert attachments[0] == []
    assert a in result.routed_to_silos
    assert b in result.routed_to_silos
    assert result.promoted_count == 2
