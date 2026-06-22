"""Unit tests for striking-distance + deindex confirmation helpers (M4)."""

from __future__ import annotations

from datetime import date

from services import gsc_service, rank_materialize, rank_status


# ---------------------------------------------------------------------------
# striking distance
# ---------------------------------------------------------------------------
def test_striking_distance_band_and_exclusions():
    rows = [
        {"query": "ac repair", "clicks": 2, "impressions": 100, "position": 12.0},   # in band
        {"query": "hvac", "clicks": 50, "impressions": 900, "position": 2.0},        # too high (pos 2)
        {"query": "furnace", "clicks": 1, "impressions": 40, "position": 35.0},      # too low
        {"query": "tracked one", "clicks": 1, "impressions": 500, "position": 11.0}, # already tracked
    ]
    out = rank_status.aggregate_striking_distance(rows, {"tracked one"}, 8.0, 20.0)
    assert [r["query"] for r in out] == ["ac repair"]
    assert out[0]["avg_position"] == 12.0


def test_striking_distance_impression_weighted_and_sorted():
    rows = [
        {"query": "a", "clicks": 1, "impressions": 100, "position": 10.0},
        {"query": "a", "clicks": 1, "impressions": 100, "position": 14.0},  # avg 12
        {"query": "b", "clicks": 1, "impressions": 500, "position": 9.0},
    ]
    out = rank_status.aggregate_striking_distance(rows, set(), 8.0, 20.0)
    # b has more impressions → first.
    assert [r["query"] for r in out] == ["b", "a"]
    a = next(r for r in out if r["query"] == "a")
    assert a["avg_position"] == 12.0


# ---------------------------------------------------------------------------
# index status classification
# ---------------------------------------------------------------------------
def test_classify_index_status():
    assert gsc_service.classify_index_status("PASS") == "indexed"
    assert gsc_service.classify_index_status("FAIL") == "not_indexed"
    assert gsc_service.classify_index_status("NEUTRAL") == "not_indexed"
    assert gsc_service.classify_index_status(None) == "unknown"


# ---------------------------------------------------------------------------
# needs_index_check
# ---------------------------------------------------------------------------
def test_needs_index_check_only_for_flagged_with_url():
    today = date(2026, 6, 22)
    assert rank_materialize.needs_index_check("deindex_risk", "/p", None, today, 3) is True
    assert rank_materialize.needs_index_check("dropping", "/p", None, today, 3) is False
    assert rank_materialize.needs_index_check("deindex_risk", None, None, today, 3) is False


def test_needs_index_check_respects_recheck_window():
    today = date(2026, 6, 22)
    # checked yesterday, recheck window 3 days → skip
    assert rank_materialize.needs_index_check("deindex_risk", "/p", "2026-06-21", today, 3) is False
    # checked 5 days ago → due
    assert rank_materialize.needs_index_check("deindex_risk", "/p", "2026-06-17", today, 3) is True
