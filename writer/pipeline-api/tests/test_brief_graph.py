"""Unit tests for Brief Generator v2.0 Step 5 — coverage graph + regions.

These tests use deterministic synthetic embeddings (no real OpenAI calls).
The injected embed_fn returns vectors from a lookup table keyed on text,
which lets each test construct precise gate / graph / region scenarios.
"""

from __future__ import annotations

import math
from typing import Awaitable, Callable

import pytest

from modules.brief.graph import (
    Candidate,
    GateResult,
    RegionInfo,
    apply_region_outcomes,
    build_coverage_graph,
    detect_regions,
    embed_with_gates,
    score_regions,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


def _make_embed_fn(table: dict[str, list[float]]):
    """Return an async embed_fn that looks up vectors by exact text match."""
    async def _embed(texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            if t not in table:
                raise KeyError(f"test embed_fn missing vector for: {t!r}")
            out.append(_normalize(list(table[t])))
        return out
    return _embed


def _make_candidate(text: str, source: str = "serp", **kw) -> Candidate:
    return Candidate(text=text, source=source, **kw)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# embed_with_gates — Step 5.1 + 5.2
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embed_with_gates_partitions_by_relevance():
    # Title points along axis 0; candidates project varying amounts onto it.
    table = {
        "seed": [1.0, 0.0, 0.0, 0.0],
        "title": [1.0, 0.0, 0.0, 0.0],
        "scope": [0.9, 0.1, 0.0, 0.0],
        # Above ceiling: ~0.99 cosine to title
        "near_paraphrase": [0.99, 0.14, 0.0, 0.0],
        # Eligible: ~0.71
        "useful": [0.71, 0.71, 0.0, 0.0],
        # Below floor: ~0
        "off_topic": [0.0, 0.0, 1.0, 0.0],
        # Just above floor: ~0.55
        "borderline": [0.55, 0.83, 0.0, 0.0],
    }
    cands = [
        _make_candidate("near_paraphrase", source="serp"),
        _make_candidate("useful", source="paa"),
        _make_candidate("off_topic", source="reddit"),
        _make_candidate("borderline", source="autocomplete"),
    ]
    res = await embed_with_gates(
        seed="seed",
        title="title",
        scope_statement="scope",
        candidates=cands,
        relevance_floor=0.55,
        restatement_ceiling=0.78,
        embed_fn=_make_embed_fn(table),
    )

    assert isinstance(res, GateResult)
    eligible_texts = {c.text for c in res.eligible}
    assert eligible_texts == {"useful", "borderline"}
    discarded_by_reason = {c.text: c.discard_reason for c in res.discarded}
    assert discarded_by_reason["near_paraphrase"] == "above_restatement_ceiling"
    assert discarded_by_reason["off_topic"] == "below_relevance_floor"

    # Each candidate gets its embedding + title_relevance written in place
    for c in cands:
        assert c.embedding, f"{c.text} missing embedding"
        assert 0.0 <= c.title_relevance <= 1.0


@pytest.mark.asyncio
async def test_embed_with_gates_handles_empty_candidates():
    table = {
        "seed": [1.0, 0.0],
        "title": [1.0, 0.0],
        "scope": [1.0, 0.0],
    }
    res = await embed_with_gates(
        seed="seed",
        title="title",
        scope_statement="scope",
        candidates=[],
        relevance_floor=0.55,
        restatement_ceiling=0.78,
        embed_fn=_make_embed_fn(table),
    )
    assert res.eligible == []
    assert res.discarded == []
    assert len(res.title_embedding) == 2


@pytest.mark.asyncio
async def test_embed_with_gates_rejects_invalid_thresholds():
    with pytest.raises(ValueError):
        await embed_with_gates(
            seed="x",
            title="x",
            scope_statement="x",
            candidates=[],
            relevance_floor=0.80,
            restatement_ceiling=0.78,
            embed_fn=_make_embed_fn({"x": [1.0]}),
        )


@pytest.mark.asyncio
async def test_embed_with_gates_validates_vector_count():
    async def bad_embed(texts):
        return [[1.0]]  # Returns 1 vector regardless of input length
    with pytest.raises(RuntimeError):
        await embed_with_gates(
            seed="s",
            title="t",
            scope_statement="sc",
            candidates=[_make_candidate("c1")],
            relevance_floor=0.55,
            restatement_ceiling=0.78,
            embed_fn=bad_embed,
        )


@pytest.mark.asyncio
async def test_embed_with_gates_logs_summary(caplog):
    table = {
        "s": [1.0, 0.0],
        "t": [1.0, 0.0],
        "sc": [1.0, 0.0],
        "good": [0.7, 0.7],
        "bad": [0.0, 1.0],
    }
    with caplog.at_level("INFO", logger="modules.brief.graph"):
        await embed_with_gates(
            seed="s",
            title="t",
            scope_statement="sc",
            candidates=[_make_candidate("good"), _make_candidate("bad")],
            relevance_floor=0.55,
            restatement_ceiling=0.78,
            embed_fn=_make_embed_fn(table),
        )
    events = [r.message for r in caplog.records]
    # Both the per-rejection event and the summary should be emitted
    assert "brief.gate.relevance_floor.discard" in events
    assert "brief.gate.summary" in events


# ----------------------------------------------------------------------
# build_coverage_graph — Step 5.3
# ----------------------------------------------------------------------

def test_build_coverage_graph_creates_edges_above_threshold():
    a = _normalize([0.9, 0.0, 0.0])
    b = _normalize([0.95, 0.05, 0.0])  # cos(a, b) ~ 1.0
    c = _normalize([0.0, 1.0, 0.0])    # cos(a, c) ~ 0
    cands = [
        _make_candidate("a"), _make_candidate("b"), _make_candidate("c"),
    ]
    cands[0].embedding = a
    cands[1].embedding = b
    cands[2].embedding = c
    G = build_coverage_graph(cands, edge_threshold=0.65)
    assert set(G.nodes()) == {0, 1, 2}
    assert G.has_edge(0, 1)
    assert not G.has_edge(0, 2)
    assert not G.has_edge(1, 2)
    # Edge weight is the cosine
    assert G[0][1]["weight"] == pytest.approx(sum(x * y for x, y in zip(a, b)))


def test_build_coverage_graph_skips_missing_embeddings():
    cands = [_make_candidate("a"), _make_candidate("b")]
    cands[0].embedding = _normalize([1.0, 0.0])
    cands[1].embedding = []  # missing
    G = build_coverage_graph(cands, edge_threshold=0.5)
    assert G.number_of_nodes() == 2
    assert G.number_of_edges() == 0


def test_build_coverage_graph_single_node():
    cands = [_make_candidate("a")]
    cands[0].embedding = _normalize([1.0, 0.0])
    G = build_coverage_graph(cands, edge_threshold=0.5)
    assert G.number_of_nodes() == 1
    assert G.number_of_edges() == 0


# ----------------------------------------------------------------------
# detect_regions — Step 5.4
# ----------------------------------------------------------------------

def test_detect_regions_separates_distant_clusters():
    # Two well-separated clusters with no inter-cluster edges
    a1 = _normalize([1.0, 0.0, 0.0, 0.0])
    a2 = _normalize([0.99, 0.14, 0.0, 0.0])
    a3 = _normalize([0.95, 0.31, 0.0, 0.0])
    b1 = _normalize([0.0, 0.0, 1.0, 0.0])
    b2 = _normalize([0.0, 0.0, 0.99, 0.14])
    b3 = _normalize([0.0, 0.0, 0.95, 0.31])
    cands = [_make_candidate(t) for t in ("a1", "a2", "a3", "b1", "b2", "b3")]
    for c, e in zip(cands, [a1, a2, a3, b1, b2, b3]):
        c.embedding = e
    G = build_coverage_graph(cands, edge_threshold=0.65)
    regions = detect_regions(G, resolution=1.0, seed=42)
    assert len(regions) == 2
    cluster_a = {0, 1, 2}
    cluster_b = {3, 4, 5}
    found = [set(r) for r in regions]
    assert cluster_a in found
    assert cluster_b in found


def test_detect_regions_deterministic_with_same_seed():
    a1 = _normalize([1.0, 0.0, 0.0])
    a2 = _normalize([0.99, 0.14, 0.0])
    b1 = _normalize([0.0, 1.0, 0.0])
    b2 = _normalize([0.0, 0.99, 0.14])
    cands = [_make_candidate(t) for t in ("a1", "a2", "b1", "b2")]
    for c, e in zip(cands, [a1, a2, b1, b2]):
        c.embedding = e
    G = build_coverage_graph(cands, edge_threshold=0.65)
    r1 = detect_regions(G, seed=42)
    r2 = detect_regions(G, seed=42)
    assert sorted(sorted(s) for s in r1) == sorted(sorted(s) for s in r2)


def test_detect_regions_empty_graph():
    import networkx as nx
    assert detect_regions(nx.Graph()) == []


# ----------------------------------------------------------------------
# score_regions — Step 5.5
# ----------------------------------------------------------------------

def _make_pair(text_a: str, text_b: str, vec_a, vec_b, source_a="serp", source_b="serp"):
    ca = _make_candidate(text_a, source=source_a)
    cb = _make_candidate(text_b, source=source_b)
    ca.embedding = _normalize(vec_a)
    cb.embedding = _normalize(vec_b)
    return [ca, cb]


def test_score_regions_density_and_diversity():
    title = _normalize([1.0, 0.0, 0.0])
    cands = _make_pair("a", "b", [0.7, 0.7, 0.0], [0.71, 0.7, 0.0],
                       source_a="serp", source_b="paa")
    cands.extend(_make_pair("c", "d", [0.0, 0.0, 1.0], [0.0, 0.05, 0.99],
                            source_a="reddit", source_b="serp"))
    regions = [{0, 1}, {2, 3}]
    scored = score_regions(regions, cands, title,
                           relevance_floor=0.40, restatement_ceiling=0.95)
    by_id = {r.region_id: r for r in scored}
    # region_0 (largest by density-desc tiebreak; both have density 2 — use
    # smallest member index → {0,1} comes first).
    assert by_id["region_0"].member_indices == [0, 1]
    assert by_id["region_0"].density == 2
    assert by_id["region_0"].source_diversity == 2  # serp + paa
    assert by_id["region_1"].source_diversity == 2  # reddit + serp


def test_score_regions_centroid_title_similarity():
    title = _normalize([1.0, 0.0, 0.0])
    cands = _make_pair("a", "b", [0.71, 0.71, 0.0], [0.71, 0.7, 0.0])
    scored = score_regions([{0, 1}], cands, title,
                           relevance_floor=0.40, restatement_ceiling=0.95)
    # Centroid roughly along [0.71, 0.71, 0]; cosine to [1,0,0] ~ 0.71
    assert scored[0].centroid_title_distance == pytest.approx(0.71, abs=0.05)


def test_score_regions_information_gain_signal():
    title = _normalize([1.0, 0.0])
    # Region members: 1 serp + 3 non-serp → info_gain = 0.75
    c0 = _make_candidate("a", source="serp")
    c1 = _make_candidate("b", source="reddit")
    c2 = _make_candidate("c", source="paa")
    c3 = _make_candidate("d", source="persona_gap")
    for c in (c0, c1, c2, c3):
        c.embedding = _normalize([0.7, 0.7])
    scored = score_regions([{0, 1, 2, 3}], [c0, c1, c2, c3], title,
                           relevance_floor=0.40, restatement_ceiling=0.95)
    assert scored[0].information_gain_signal == pytest.approx(0.75)


def test_score_regions_eliminates_off_topic():
    title = _normalize([1.0, 0.0])
    cands = _make_pair("a", "b", [0.0, 1.0], [0.0, 1.0])  # orthogonal to title
    scored = score_regions([{0, 1}], cands, title,
                           relevance_floor=0.55, restatement_ceiling=0.78)
    assert scored[0].eliminated is True
    assert scored[0].elimination_reason == "off_topic"


def test_score_regions_eliminates_restate_title():
    title = _normalize([1.0, 0.0])
    cands = _make_pair("a", "b", [0.99, 0.14], [0.98, 0.2])  # very close to title
    scored = score_regions([{0, 1}], cands, title,
                           relevance_floor=0.55, restatement_ceiling=0.78)
    assert scored[0].eliminated is True
    assert scored[0].elimination_reason == "restates_title"


def test_score_regions_singleton_flag():
    title = _normalize([1.0, 0.0])
    cand = _make_candidate("solo")
    cand.embedding = _normalize([0.7, 0.7])
    scored = score_regions([{0}], [cand], title,
                           relevance_floor=0.40, restatement_ceiling=0.95)
    assert scored[0].is_singleton is True
    assert scored[0].eliminated is False  # singletons stay selectable


def test_score_regions_deterministic_id_assignment():
    """Region IDs follow density-desc, then min-index tiebreak."""
    title = _normalize([1.0, 0.0])
    cands = []
    # Region A: 3 members at indices {2, 3, 4}
    # Region B: 2 members at indices {0, 1}
    # Region C: 3 members at indices {5, 6, 7}
    # Density-desc with smallest-min-index tiebreak:
    #   region_0 = {2,3,4} (density 3, min=2)
    #   region_1 = {5,6,7} (density 3, min=5)
    #   region_2 = {0,1}   (density 2)
    for i in range(8):
        c = _make_candidate(f"c{i}")
        c.embedding = _normalize([0.7, 0.7])
        cands.append(c)
    regions = [{0, 1}, {2, 3, 4}, {5, 6, 7}]
    scored = score_regions(regions, cands, title,
                           relevance_floor=0.40, restatement_ceiling=0.95)
    assert scored[0].region_id == "region_0"
    assert sorted(scored[0].member_indices) == [2, 3, 4]
    assert scored[1].region_id == "region_1"
    assert sorted(scored[1].member_indices) == [5, 6, 7]
    assert scored[2].region_id == "region_2"
    assert sorted(scored[2].member_indices) == [0, 1]


# ----------------------------------------------------------------------
# apply_region_outcomes
# ----------------------------------------------------------------------

def test_apply_region_outcomes_stamps_region_id():
    title = _normalize([1.0, 0.0])
    cands = _make_pair("a", "b", [0.7, 0.7], [0.71, 0.7])
    scored = score_regions([{0, 1}], cands, title,
                           relevance_floor=0.40, restatement_ceiling=0.95)
    kept, eliminated = apply_region_outcomes(scored, cands)
    assert len(kept) == 2
    assert eliminated == []
    assert all(c.region_id == "region_0" for c in cands)


def test_apply_region_outcomes_routes_eliminated_off_topic():
    title = _normalize([1.0, 0.0])
    cands = _make_pair("a", "b", [0.0, 1.0], [0.0, 1.0])
    scored = score_regions([{0, 1}], cands, title,
                           relevance_floor=0.55, restatement_ceiling=0.78)
    kept, eliminated = apply_region_outcomes(scored, cands)
    assert kept == []
    assert len(eliminated) == 2
    assert all(c.discard_reason == "region_off_topic" for c in eliminated)
    # region_id is still recorded so silos / debugging can trace back
    assert all(c.region_id == "region_0" for c in eliminated)


def test_apply_region_outcomes_routes_eliminated_restate_title():
    title = _normalize([1.0, 0.0])
    cands = _make_pair("a", "b", [0.99, 0.14], [0.98, 0.2])
    scored = score_regions([{0, 1}], cands, title,
                           relevance_floor=0.55, restatement_ceiling=0.78)
    kept, eliminated = apply_region_outcomes(scored, cands)
    assert kept == []
    assert all(c.discard_reason == "region_restates_title" for c in eliminated)
