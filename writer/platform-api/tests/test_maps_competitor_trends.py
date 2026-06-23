import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers.maps import build_competitor_trends  # noqa: E402

S1 = "11111111-1111-1111-1111-111111111111"  # older scan
S2 = "22222222-2222-2222-2222-222222222222"  # newer scan
SOLD = "33333333-3333-3333-3333-333333333333"  # pre-capture scan (no competitors_above)


def _above(grid):
    return {"directory": {"A": {"name": "Comp A"}, "B": {"name": "Comp B"}}, "grid": grid}


def test_competitor_trends_tracks_gain_and_orders_by_latest():
    # 2 scans, each 4 in-circle pins (total_pins=4). A beats us on 1 pin in S1,
    # 3 pins in S2 (gaining); B beats us on 2 pins then 1 (declining).
    scans = [
        {"id": S2, "completed_at": "2026-06-20T00:00:00Z"},
        {"id": S1, "completed_at": "2026-06-13T00:00:00Z"},
    ]
    results = [
        {"scan_id": S1, "total_pins": 4, "competitors_above": _above(
            [[[["A", 1]], [["B", 1], ["B", 2]]]])},  # A:1 pin, B:2 pins
        {"scan_id": S2, "total_pins": 4, "competitors_above": _above(
            [[[["A", 1]], [["A", 1]], [["A", 2]], [["B", 1]]]])},  # A:3 pins, B:1 pin
    ]

    resp = build_competitor_trends(scans, results)
    assert resp.scan_count == 2

    a = next(c for c in resp.competitors if c.place_id == "A")
    b = next(c for c in resp.competitors if c.place_id == "B")
    # Points are oldest → newest. A: 1/4=25% → 3/4=75% (gaining +50).
    assert [p.beats_pct for p in a.points] == [25.0, 75.0]
    assert a.latest_pct == 75.0 and a.delta_pct == 50.0
    # B: 2/4=50% → 1/4=25% (declining -25).
    assert [p.beats_pct for p in b.points] == [50.0, 25.0]
    assert b.delta_pct == -25.0
    # Ordered by latest pressure: A (75%) before B (25%).
    assert [c.place_id for c in resp.competitors] == ["A", "B"]
    assert a.name == "Comp A"


def test_competitor_trends_skips_scans_without_competitor_data():
    scans = [
        {"id": S2, "completed_at": "2026-06-20T00:00:00Z"},
        {"id": SOLD, "completed_at": "2026-06-01T00:00:00Z"},  # pre-capture
    ]
    results = [
        {"scan_id": SOLD, "total_pins": 4, "competitors_above": None},  # not captured
        {"scan_id": S2, "total_pins": 4, "competitors_above": _above([[[["A", 1]]]])},
    ]
    resp = build_competitor_trends(scans, results)
    # Only the one scan with data is counted; the pre-capture scan is skipped so
    # it doesn't read as a false 0%.
    assert resp.scan_count == 1
    a = next(c for c in resp.competitors if c.place_id == "A")
    assert len(a.points) == 1 and a.points[0].beats_pct == 25.0
    assert a.delta_pct is None  # only one data point → no delta


def test_competitor_trends_empty():
    assert build_competitor_trends([], []).competitors == []
