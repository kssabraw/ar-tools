"""Tests for Step 12 refinements (PRD v2.0.2): 12.1 discard-reason
filtering, 12.3 search-demand validation, 12.4 viability check."""

from __future__ import annotations

import math

import pytest

from modules.brief.graph import Candidate, RegionInfo
from modules.brief.silos import (
    MIN_SEARCH_DEMAND_SCORE,
    SiloIdentificationResult,
    SiloViabilityResult,
    _is_member_eligible,
    _search_demand_score,
    identify_silos,
    verify_silo_viability,
)
from models.brief import SiloCandidate, SiloSourceHeading


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


def _cand(text, embedding, *, source="serp", discard_reason=None,
          serp_frequency=15, llm_fanout_consensus=3,
          title_relevance=0.6, heading_priority=0.5) -> Candidate:
    c = Candidate(text=text, source=source)  # type: ignore[arg-type]
    c.embedding = _normalize(embedding)
    c.title_relevance = title_relevance
    c.heading_priority = heading_priority
    c.discard_reason = discard_reason
    c.serp_frequency = serp_frequency
    c.llm_fanout_consensus = llm_fanout_consensus
    return c


def _region(rid, members, eliminated=False, elimination_reason=None):
    return RegionInfo(
        region_id=rid,
        member_indices=members,
        centroid=[],
        density=len(members),
        source_diversity=1,
        centroid_title_distance=0.65,
        information_gain_signal=0.5,
        eliminated=eliminated,
        elimination_reason=elimination_reason,
        is_singleton=len(members) < 2,
    )


# ----------------------------------------------------------------------
# Step 12.1 — discard-reason filtering
# ----------------------------------------------------------------------

@pytest.mark.parametrize("reason,expected", [
    ("scope_verification_out_of_scope", True),
    ("global_cap_exceeded", True),
    (None, True),                           # untagged eligible
    ("above_restatement_ceiling", False),
    ("below_relevance_floor", False),
    ("region_off_topic", False),
    ("region_restates_title", False),
    ("low_cluster_coherence", False),
    ("duplicate", False),
    ("displaced_by_authority_gap_h3", False),
    ("h3_below_parent_relevance_floor", False),
    ("h3_above_parent_restatement_ceiling", False),
])
def test_member_eligibility_table_yes_and_no(reason, expected):
    c = _cand("x", [0.9, 0.0], discard_reason=reason)
    assert _is_member_eligible(c, region_contributed=False) is expected


def test_below_priority_threshold_eligible_when_region_did_not_contribute():
    c = _cand("x", [0.9, 0.0], discard_reason="below_priority_threshold")
    assert _is_member_eligible(c, region_contributed=False) is True


def test_below_priority_threshold_excluded_when_region_contributed():
    c = _cand("x", [0.9, 0.0], discard_reason="below_priority_threshold")
    assert _is_member_eligible(c, region_contributed=True) is False


def test_silo_filters_out_ineligible_members():
    """A region whose members all have ineligible discard_reasons → no silo."""
    pool = [
        _cand("a", [0.9, 0.0, 0.0], discard_reason="above_restatement_ceiling"),
        _cand("b", [0.95, 0.05, 0.0], discard_reason="region_off_topic"),
    ]
    regions = [_region("region_3", [0, 1])]
    res = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert res.candidates == []
    assert res.rejected_by_discard_reason_count == 2


# ----------------------------------------------------------------------
# Step 12.3 — search-demand score
# ----------------------------------------------------------------------

def test_search_demand_score_max_signals():
    """All five signals at max → score 1.0."""
    cands = [
        _cand("a", [1.0, 0], source="paa", serp_frequency=20, llm_fanout_consensus=4),
        _cand("b", [1.0, 0], source="reddit"),
        _cand("c", [1.0, 0], source="autocomplete"),
    ]
    score = _search_demand_score(cands)
    assert score == pytest.approx(1.0)


def test_search_demand_score_no_signals():
    cands = [
        _cand("a", [1.0, 0], source="serp",
              serp_frequency=0, llm_fanout_consensus=0),
    ]
    assert _search_demand_score(cands) == 0.0


def test_search_demand_score_partial():
    """SERP source with frequency=10 + consensus=2; no other signals.
    Expected: 0.30 * 0.5 + 0.25 * 0.5 = 0.275 — below 0.30 floor."""
    cands = [
        _cand("a", [1.0, 0], source="serp",
              serp_frequency=10, llm_fanout_consensus=2),
    ]
    assert _search_demand_score(cands) == pytest.approx(0.275)


def test_silo_dropped_when_search_demand_below_threshold():
    """A coherent cluster with weak demand signals is dropped."""
    pool = [
        _cand("a", [0.9, 0.0, 0.0], serp_frequency=2, llm_fanout_consensus=0),
        _cand("b", [0.95, 0.05, 0.0], serp_frequency=2, llm_fanout_consensus=0),
    ]
    regions = [_region("region_3", [0, 1])]
    res = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert res.candidates == []
    assert res.rejected_by_search_demand_count == 1


def test_silo_carries_search_demand_score_in_output():
    pool = [
        _cand("a", [0.9, 0.0, 0.0], source="paa"),
        _cand("b", [0.95, 0.05, 0.0], source="reddit"),
    ]
    regions = [_region("region_3", [0, 1])]
    res = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert len(res.candidates) == 1
    assert res.candidates[0].search_demand_score >= MIN_SEARCH_DEMAND_SCORE


def test_silo_carries_discard_reason_breakdown():
    pool = [
        _cand("a", [0.9, 0.0, 0.0], discard_reason="below_priority_threshold"),
        _cand("b", [0.95, 0.05, 0.0], discard_reason="below_priority_threshold"),
        _cand("c", [0.9, 0.1, 0.0], discard_reason="global_cap_exceeded"),
    ]
    regions = [_region("region_3", [0, 1, 2])]
    res = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert len(res.candidates) == 1
    breakdown = res.candidates[0].discard_reason_breakdown
    assert breakdown["below_priority_threshold"] == 2
    assert breakdown["global_cap_exceeded"] == 1


def test_singleton_scope_reject_dropped_when_demand_below_threshold():
    """A scope-verification reject with no demand signals is filtered."""
    rejected = _cand(
        "Niche tactics nobody searches for", [0.7, 0.7],
        source="serp",
        discard_reason="scope_verification_out_of_scope",
        serp_frequency=0,
        llm_fanout_consensus=0,
    )
    res = identify_silos(
        regions=[], candidate_pool=[],
        contributing_region_ids=set(), scope_rejects=[rejected],
    )
    assert res.candidates == []
    assert res.rejected_by_search_demand_count == 1


# ----------------------------------------------------------------------
# Step 12.4 — viability check
# ----------------------------------------------------------------------

def _silo(keyword: str, recommended_intent="informational") -> SiloCandidate:
    return SiloCandidate(
        suggested_keyword=keyword,
        cluster_coherence_score=0.7,
        review_recommended=False,
        recommended_intent=recommended_intent,
        routed_from="non_selected_region",
        source_headings=[
            SiloSourceHeading(text=keyword, source="serp",
                              title_relevance=0.6, heading_priority=0.5),
        ],
        search_demand_score=0.5,
        estimated_intent=recommended_intent,
    )


def _llm_mock(*responses):
    """Deterministic LLM mock — returns each response in turn."""
    iterator = iter(responses)

    async def _mock(system, user, **kw):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    return _mock


@pytest.mark.asyncio
async def test_viability_keeps_viable_candidates():
    silo = _silo("How to optimize TikTok Shop ads")
    payload = {
        "candidate_keyword": "How to optimize TikTok Shop ads",
        "viable_as_standalone_article": True,
        "reasoning": "Distinct intent vs definitional parent",
        "estimated_intent": "how-to",
    }
    res = await verify_silo_viability(
        [silo], title="What TikTok Shop Is", scope_statement="x",
        llm_json_fn=_llm_mock(payload),
    )
    assert res.candidates == [silo]
    assert silo.viable_as_standalone_article is True
    assert silo.viability_reasoning.startswith("Distinct intent")
    assert silo.estimated_intent == "how-to"
    assert res.fallback_applied is False


@pytest.mark.asyncio
async def test_viability_excludes_non_viable_candidates():
    silo = _silo("What TikTok Shop Is (paraphrase)")
    payload = {
        "candidate_keyword": "What TikTok Shop Is (paraphrase)",
        "viable_as_standalone_article": False,
        "reasoning": "Restates the parent's intent",
        "estimated_intent": "informational",
    }
    res = await verify_silo_viability(
        [silo], title="What TikTok Shop Is", scope_statement="x",
        llm_json_fn=_llm_mock(payload),
    )
    assert res.candidates == []
    assert res.rejected_count == 1
    assert silo.viable_as_standalone_article is False


@pytest.mark.asyncio
async def test_viability_runs_in_parallel_for_multiple_candidates():
    """With 3 candidates, all 3 are checked and routed individually."""
    s1 = _silo("Keyword 1")
    s2 = _silo("Keyword 2")
    s3 = _silo("Keyword 3")

    async def per_kw(system, user, **kw):
        # Identify which keyword is being checked from the user prompt
        for kw_text in ("Keyword 1", "Keyword 2", "Keyword 3"):
            if kw_text in user:
                return {
                    "candidate_keyword": kw_text,
                    "viable_as_standalone_article": kw_text != "Keyword 2",
                    "reasoning": "ok",
                    "estimated_intent": "informational",
                }
        return {}

    res = await verify_silo_viability(
        [s1, s2, s3], title="t", scope_statement="x",
        llm_json_fn=per_kw,
    )
    viable_kws = {c.suggested_keyword for c in res.candidates}
    assert viable_kws == {"Keyword 1", "Keyword 3"}
    assert res.rejected_count == 1


@pytest.mark.asyncio
async def test_viability_double_failure_falls_back_to_viable_true():
    silo = _silo("Whatever")
    res = await verify_silo_viability(
        [silo], title="t", scope_statement="x",
        llm_json_fn=_llm_mock("garbage1", "garbage2"),
    )
    assert res.candidates == [silo]
    assert silo.viable_as_standalone_article is True
    assert "fallback_after_llm_failure" in silo.viability_reasoning
    assert res.fallback_applied is True


@pytest.mark.asyncio
async def test_viability_double_llm_exception_falls_back():
    silo = _silo("Whatever")
    res = await verify_silo_viability(
        [silo], title="t", scope_statement="x",
        llm_json_fn=_llm_mock(RuntimeError("a"), RuntimeError("b")),
    )
    assert silo in res.candidates
    assert res.fallback_applied is True


@pytest.mark.asyncio
async def test_viability_retry_on_invalid_payload_then_success():
    silo = _silo("Keyword X")
    bad = {"viable_as_standalone_article": "not-a-bool"}
    good = {
        "candidate_keyword": "Keyword X",
        "viable_as_standalone_article": True,
        "reasoning": "Distinct article angle",
        "estimated_intent": "informational",
    }
    res = await verify_silo_viability(
        [silo], title="t", scope_statement="x",
        llm_json_fn=_llm_mock(bad, good),
    )
    assert silo in res.candidates
    assert res.fallback_applied is False


@pytest.mark.asyncio
async def test_viability_retry_on_invalid_estimated_intent():
    silo = _silo("Keyword X")
    bad = {
        "candidate_keyword": "Keyword X",
        "viable_as_standalone_article": True,
        "reasoning": "x",
        "estimated_intent": "not-a-real-intent",
    }
    good = {
        "candidate_keyword": "Keyword X",
        "viable_as_standalone_article": True,
        "reasoning": "ok",
        "estimated_intent": "how-to",
    }
    res = await verify_silo_viability(
        [silo], title="t", scope_statement="x",
        llm_json_fn=_llm_mock(bad, good),
    )
    assert silo.estimated_intent == "how-to"


@pytest.mark.asyncio
async def test_viability_empty_input_returns_empty_no_llm_call():
    called = False

    async def boom(*a, **k):
        nonlocal called
        called = True
        raise AssertionError("must not call LLM with empty input")

    res = await verify_silo_viability(
        [], title="t", scope_statement="x", llm_json_fn=boom,
    )
    assert res.candidates == []
    assert res.rejected_count == 0
    assert res.fallback_applied is False
    assert called is False


@pytest.mark.asyncio
async def test_viability_truncates_long_reasoning():
    silo = _silo("Keyword X")
    payload = {
        "candidate_keyword": "Keyword X",
        "viable_as_standalone_article": True,
        "reasoning": "x" * 500,
        "estimated_intent": "informational",
    }
    await verify_silo_viability(
        [silo], title="t", scope_statement="x",
        llm_json_fn=_llm_mock(payload),
    )
    assert len(silo.viability_reasoning) <= 150


@pytest.mark.asyncio
async def test_viability_logs_complete(caplog):
    silo = _silo("Keyword X")
    payload = {
        "candidate_keyword": "Keyword X",
        "viable_as_standalone_article": True,
        "reasoning": "ok",
        "estimated_intent": "informational",
    }
    with caplog.at_level("INFO", logger="modules.brief.silos"):
        await verify_silo_viability(
            [silo], title="t", scope_statement="x",
            llm_json_fn=_llm_mock(payload),
        )
    assert any(r.message == "brief.silo.viability_complete" for r in caplog.records)
