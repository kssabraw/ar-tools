"""Step 7.5 - Anchor-slot reservation (Brief Generator PRD v2.1)."""

from __future__ import annotations

import math

import pytest

from modules.brief.graph import Candidate
from modules.brief.intent_template import get_template
from modules.brief.skeleton_slots import (
    MIN_ANCHOR_COSINE,
    embed_anchor_slots,
    reserve_anchor_slots,
)


def _unit(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def _candidate(
    text: str,
    *,
    embedding: list[float],
    region_id: str,
    priority: float = 0.5,
) -> Candidate:
    return Candidate(
        text=text,
        source="serp",
        embedding=_unit(embedding),
        title_relevance=0.7,
        region_id=region_id,
        heading_priority=priority,
    )


# ---- embed_anchor_slots ----


@pytest.mark.asyncio
async def test_embed_anchor_slots_returns_empty_when_no_anchors():
    template = get_template("listicle")
    assert template.anchor_slots == []
    embeddings = await embed_anchor_slots(template)
    assert embeddings == []


@pytest.mark.asyncio
async def test_embed_anchor_slots_calls_embed_fn_with_anchors():
    template = get_template("how-to")
    captured: list[list[str]] = []

    async def fake_embed(texts: list[str]) -> list[list[float]]:
        captured.append(list(texts))
        return [[1.0, 0.0]] * len(texts)

    embeddings = await embed_anchor_slots(template, embed_fn=fake_embed)
    assert captured == [list(template.anchor_slots)]
    assert len(embeddings) == len(template.anchor_slots)


@pytest.mark.asyncio
async def test_embed_anchor_slots_swallows_failures():
    """Anchor embedding failures must NOT abort the pipeline; reservation
    falls through to plain MMR via empty return."""
    template = get_template("how-to")

    async def boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding outage")

    embeddings = await embed_anchor_slots(template, embed_fn=boom)
    assert embeddings == []


# ---- reserve_anchor_slots ----


def test_reserve_returns_empty_when_no_anchors():
    cands = [_candidate("X", embedding=[1, 0], region_id="r1")]
    template = get_template("listicle")  # no anchors
    result = reserve_anchor_slots(cands, template, anchor_embeddings=[])
    assert result.reserved == []
    assert result.unmatched_slot_indices == []


def test_reserve_picks_highest_cosine_per_slot():
    """Two anchors, four candidates - each anchor should reserve the
    candidate most aligned with it, not the highest-priority one."""
    template = get_template("how-to").model_copy(deep=True)
    template.anchor_slots = ["plan", "launch"]

    plan_anchor = _unit([1.0, 0.0])
    launch_anchor = _unit([0.0, 1.0])

    # cand_a aligns strongly with the plan anchor; cand_b aligns with launch.
    cand_a = _candidate("A - Plan and prepare", embedding=[0.95, 0.1], region_id="r1", priority=0.5)
    cand_b = _candidate("B - Launch and ship", embedding=[0.1, 0.95], region_id="r2", priority=0.5)
    # cand_c is high-priority but topically off both anchors → must NOT
    # be reserved; goes to MMR pool.
    cand_c = _candidate("C - Random topic", embedding=[0.6, 0.6], region_id="r3", priority=0.99)

    result = reserve_anchor_slots(
        [cand_a, cand_b, cand_c],
        template,
        anchor_embeddings=[plan_anchor, launch_anchor],
    )
    assert [c.text for c in result.reserved] == [
        "A - Plan and prepare", "B - Launch and ship",
    ]
    assert result.unmatched_slot_indices == []


def test_reserve_respects_region_uniqueness():
    """Two anchors aligned with the same region should still produce at
    most one reservation per region - the second slot should be marked
    unmatched."""
    template = get_template("how-to").model_copy(deep=True)
    template.anchor_slots = ["plan", "configure"]

    a1 = _unit([1.0, 0.0])
    a2 = _unit([1.0, 0.0])

    # Both candidates live in r1 and both align with both anchors. The
    # first slot wins; the second slot must skip the second candidate
    # (region already used) and find no fit → unmatched.
    c1 = _candidate("C1", embedding=[1.0, 0.0], region_id="r1", priority=0.7)
    c2 = _candidate("C2", embedding=[0.99, 0.05], region_id="r1", priority=0.6)

    result = reserve_anchor_slots(
        [c1, c2], template, anchor_embeddings=[a1, a2],
    )
    assert len(result.reserved) == 1
    assert result.reserved[0].region_id == "r1"
    assert 1 in result.unmatched_slot_indices


def test_reserve_skips_candidates_below_min_anchor_cosine():
    """If no candidate exceeds the floor, the slot is left empty rather
    than force-fitting an off-anchor candidate."""
    template = get_template("how-to").model_copy(deep=True)
    template.anchor_slots = ["plan"]
    plan_anchor = _unit([1.0, 0.0])
    # Candidate is orthogonal to the anchor - cosine = 0, well below 0.55.
    weak = _candidate("Weak", embedding=[0.0, 1.0], region_id="r1")
    result = reserve_anchor_slots([weak], template, anchor_embeddings=[plan_anchor])
    assert result.reserved == []
    assert result.unmatched_slot_indices == [0]


def test_reserve_enforces_inter_heading_threshold():
    """A candidate already too similar to a previously reserved one must
    not be reserved by a subsequent slot."""
    template = get_template("how-to").model_copy(deep=True)
    template.anchor_slots = ["plan", "configure"]

    a1 = _unit([1.0, 0.0])
    a2 = _unit([0.99, 0.05])  # very similar to a1

    # c1 reserves slot 0; c2 is 0.99 cosine to c1 (different region) -
    # inter-heading threshold should reject it.
    c1 = _candidate("C1", embedding=[1.0, 0.0], region_id="r1", priority=0.5)
    c2 = _candidate("C2", embedding=[0.99, 0.05], region_id="r2", priority=0.5)

    result = reserve_anchor_slots(
        [c1, c2], template, anchor_embeddings=[a1, a2],
        inter_heading_threshold=0.75,
    )
    assert [c.text for c in result.reserved] == ["C1"]
    assert 1 in result.unmatched_slot_indices


def test_reserve_does_not_mutate_input_candidates():
    template = get_template("how-to").model_copy(deep=True)
    template.anchor_slots = ["plan"]
    a = _unit([1.0, 0.0])
    cand = _candidate("X", embedding=[1.0, 0.0], region_id="r1")
    snapshot = (cand.text, cand.discard_reason, list(cand.embedding))
    reserve_anchor_slots([cand], template, anchor_embeddings=[a])
    assert cand.text == snapshot[0]
    assert cand.discard_reason == snapshot[1]
    assert list(cand.embedding) == snapshot[2]


def test_reserve_returns_in_anchor_order_for_strict_sequential():
    """Strict-sequential (how-to) anchors must produce reserved
    candidates in narrative order."""
    template = get_template("how-to").model_copy(deep=True)
    # Three anchors in narrative order
    template.anchor_slots = ["plan", "build", "ship"]

    a_plan = _unit([1.0, 0.0, 0.0])
    a_build = _unit([0.0, 1.0, 0.0])
    a_ship = _unit([0.0, 0.0, 1.0])

    # Add candidates in arbitrary order
    cands = [
        _candidate("Ship", embedding=[0.0, 0.0, 1.0], region_id="r3"),
        _candidate("Plan", embedding=[1.0, 0.0, 0.0], region_id="r1"),
        _candidate("Build", embedding=[0.0, 1.0, 0.0], region_id="r2"),
    ]
    result = reserve_anchor_slots(
        cands, template, anchor_embeddings=[a_plan, a_build, a_ship],
    )
    assert [c.text for c in result.reserved] == ["Plan", "Build", "Ship"]


def test_reserve_handles_mismatched_embedding_count():
    """Defensive: if embed_fn returned fewer embeddings than anchors,
    reservation should bail rather than misalign."""
    template = get_template("how-to").model_copy(deep=True)
    template.anchor_slots = ["plan", "build"]
    # Only one embedding for two anchors
    result = reserve_anchor_slots([], template, anchor_embeddings=[[1.0, 0.0]])
    assert result.reserved == []
    assert result.unmatched_slot_indices == []  # bailed before iterating


def test_reserve_min_anchor_cosine_default():
    """Sanity check: the documented floor matches the constant."""
    assert MIN_ANCHOR_COSINE == 0.55
