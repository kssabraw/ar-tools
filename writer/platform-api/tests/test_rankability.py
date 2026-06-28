"""Unit tests for the rankability pure scorer (no network)."""

from __future__ import annotations

from services import rankability


def _inp(**over):
    base = {
        "top_ur": [50, 60, 55],
        "top_rd": [40, 50, 45],
        "competitor_dr": [120, 140, 130],
        "targeted_count": 8,
        "top_count": 10,
        "client_ur": 50,
        "client_rd": 40,
        "client_dr": 120,
        "aio_present": False,
        "signals": [],
        "client_rank": None,
    }
    base.update(over)
    return base


def test_weak_serp_scores_high_and_easy():
    # Very low incumbent authority + many loose matches → highly winnable.
    out = rankability.score_keyword(_inp(
        top_ur=[10, 5, 8], top_rd=[2, 1, 3], competitor_dr=[20, 10, 15],
        targeted_count=2, top_count=10, client_ur=80, client_rd=120, client_dr=300,
    ))
    assert out["score"] >= 70
    assert out["band"] == "Easy"


def test_strong_serp_scores_low_and_hard():
    # High-authority, tightly-targeted incumbents + weak client → not winnable.
    out = rankability.score_keyword(_inp(
        top_ur=[700, 800, 750], top_rd=[400, 500, 450], competitor_dr=[800, 850, 820],
        targeted_count=10, top_count=10, client_ur=None, client_rd=None, client_dr=50,
    ))
    assert out["score"] <= 35
    assert out["band"] in ("Hard", "Very hard")


def test_loose_matches_increase_score():
    strong_targeting = rankability.score_keyword(_inp(targeted_count=10, top_count=10))
    weak_targeting = rankability.score_keyword(_inp(targeted_count=2, top_count=10))
    assert weak_targeting["score"] > strong_targeting["score"]


def test_aio_penalty_lowers_score():
    no_aio = rankability.score_keyword(_inp(aio_present=False))
    aio = rankability.score_keyword(_inp(aio_present=True))
    assert aio["score"] < no_aio["score"]
    assert any("AI Overview" in f["text"] for f in aio["factors"])


def test_rank_momentum_surfaces_as_factor():
    out = rankability.score_keyword(_inp(client_rank=6))
    assert any("rank #6" in f["text"] for f in out["factors"])


def test_factors_capped_at_three_with_directions():
    out = rankability.score_keyword(_inp())
    assert len(out["factors"]) <= 3
    assert all(f["direction"] in ("up", "down") for f in out["factors"])


def test_band_thresholds():
    assert rankability.score_keyword(_inp(
        top_ur=[0, 0], top_rd=[0, 0], competitor_dr=[0, 0],
        targeted_count=0, top_count=10, client_ur=200, client_rd=200, client_dr=500,
    ))["band"] == "Easy"


def test_median_robust_to_single_outlier():
    # One giant brand shouldn't tank an otherwise-weak SERP (median, not mean).
    out = rankability.score_keyword(_inp(
        top_ur=[10, 12, 900], top_rd=[5, 6, 800], competitor_dr=[10, 15, 900],
        targeted_count=3, top_count=10, client_ur=40, client_rd=30, client_dr=150,
    ))
    assert out["score"] >= 60  # median stays low despite the outlier
