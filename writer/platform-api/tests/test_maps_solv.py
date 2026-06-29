"""Unit tests for Share of Local Voice pure helpers (no network)."""

from __future__ import annotations

from services import maps_solv


def _result(keyword, total, top3, top10=None, competitors=None):
    return {
        "keyword": keyword,
        "total_pins": total,
        "top3_pins": top3,
        "top10_pins": top10 if top10 is not None else top3,
        "competitors": competitors or [],
    }


def test_overall_coverage_client_and_competitor_shares():
    results = [
        _result("plumber", 100, 40, 60, [
            {"place_id": "a", "name": "Ace", "top3_pins": 30},
            {"place_id": "b", "name": "Bob", "top3_pins": 10},
        ]),
        _result("drain", 100, 20, 40, [
            {"place_id": "a", "name": "Ace", "top3_pins": 50},
        ]),
    ]
    ov = maps_solv.overall_coverage(results)
    assert ov["total_pins"] == 200
    assert ov["client_top3_pins"] == 60
    assert ov["client_coverage_pct"] == 30.0          # 60/200
    assert ov["client_coverage_top10_pct"] == 50.0    # 100/200
    # Ace aggregates across keywords (30+50=80 → 40%), sorted first.
    assert ov["competitor_shares"][0]["place_id"] == "a"
    assert ov["competitor_shares"][0]["top3_pins"] == 80
    assert ov["competitor_shares"][0]["share_pct"] == 40.0
    assert ov["competitor_shares"][1]["place_id"] == "b"


def test_overall_coverage_handles_zero_pins():
    ov = maps_solv.overall_coverage([_result("x", 0, 0)])
    assert ov["client_coverage_pct"] is None
    assert ov["competitor_shares"] == []


def test_build_solv_series_sorted_and_latest_breakdown():
    scans = [
        {"id": "s1", "completed_at": "2026-06-01T00:00:00Z", "trigger": "scheduled"},
        {"id": "s2", "completed_at": "2026-06-08T00:00:00Z", "trigger": "scheduled"},
    ]
    results = [
        _result("plumber", 100, 20, 40, [{"place_id": "a", "name": "Ace", "top3_pins": 60}]) | {"scan_id": "s1"},
        _result("plumber", 100, 35, 55, [{"place_id": "a", "name": "Ace", "top3_pins": 45}]) | {"scan_id": "s2"},
    ]
    out = maps_solv.build_solv(scans, results)
    assert [p["scan_id"] for p in out["series"]] == ["s1", "s2"]   # oldest → newest
    assert out["series"][-1]["client_coverage_pct"] == 35.0
    # Latest-scan competitor + keyword breakdowns come from s2.
    assert out["competitors"][0]["place_id"] == "a"
    assert out["keywords"][0]["keyword"] == "plumber"
    assert out["keywords"][0]["client_coverage_pct"] == 35.0


def test_detect_solv_drop_fires_on_decline_with_gainer():
    latest = [_result("k", 100, 20, 40, [{"place_id": "a", "name": "Ace", "top3_pins": 70}])]
    previous = [_result("k", 100, 40, 60, [{"place_id": "a", "name": "Ace", "top3_pins": 40}])]
    drop = maps_solv.detect_solv_drop(latest, previous, min_drop_pct=10.0)
    assert drop is not None
    assert drop["from_pct"] == 40.0
    assert drop["to_pct"] == 20.0
    assert drop["delta_pct"] == 20.0
    assert drop["top_gainer"] == "Ace"


def test_detect_solv_drop_none_below_threshold():
    latest = [_result("k", 100, 38, 60)]
    previous = [_result("k", 100, 40, 60)]
    assert maps_solv.detect_solv_drop(latest, previous, min_drop_pct=10.0) is None


def test_detect_solv_drop_none_without_two_scans():
    assert maps_solv.detect_solv_drop([], [_result("k", 100, 40)], 10.0) is None
    assert maps_solv.detect_solv_drop([_result("k", 100, 20)], [], 10.0) is None
