import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers.maps import build_maps_trends  # noqa: E402

S1 = "11111111-1111-1111-1111-111111111111"
S2 = "22222222-2222-2222-2222-222222222222"


def test_build_maps_trends_groups_orders_and_computes_pct():
    # Two completed scans (returned newest-first, as the query orders them) and
    # per-keyword results that should regroup by keyword, oldest → newest.
    scans = [
        {"id": S2, "completed_at": "2026-06-20T00:00:00Z", "trigger": "manual"},
        {"id": S1, "completed_at": "2026-06-13T00:00:00Z", "trigger": "scheduled"},
    ]
    results = [
        {"scan_id": S1, "keyword": "plumber", "average_rank": 5.0,
         "found_pins": 50, "total_pins": 100, "top3_pins": 10, "top10_pins": 25},
        {"scan_id": S2, "keyword": "plumber", "average_rank": 4.0,
         "found_pins": 60, "total_pins": 100, "top3_pins": 20, "top10_pins": 40},
        {"scan_id": S2, "keyword": "emergency plumber", "average_rank": None,
         "found_pins": 0, "total_pins": 100, "top3_pins": 0, "top10_pins": 0},
    ]

    resp = build_maps_trends(scans, results)

    # Keywords sorted alphabetically.
    assert [k.keyword for k in resp.keywords] == ["emergency plumber", "plumber"]

    plumber = next(k for k in resp.keywords if k.keyword == "plumber")
    # Points ordered oldest → newest by completed_at (s1 then s2).
    assert [str(p.scan_id) for p in plumber.points] == [S1, S2]
    p1, p2 = plumber.points
    assert (p1.top3_pct, p1.top10_pct, p1.found_pct) == (10.0, 25.0, 50.0)
    assert (p2.top3_pct, p2.top10_pct, p2.found_pct) == (20.0, 40.0, 60.0)
    assert p2.trigger == "manual"

    # A keyword found on no pins → 0% coverage, null average rank.
    emergency = resp.keywords[0]
    assert emergency.points[0].top3_pct == 0.0
    assert emergency.points[0].average_rank is None


def test_build_maps_trends_handles_zero_pins_and_orphan_results():
    scans = [{"id": S1, "completed_at": "2026-06-13T00:00:00Z", "trigger": "scheduled"}]
    results = [
        {"scan_id": S1, "keyword": "kw", "average_rank": None,
         "found_pins": 0, "total_pins": 0, "top3_pins": 0, "top10_pins": 0},
        # Orphan result for a scan not in the list → ignored.
        {"scan_id": S2, "keyword": "kw", "found_pins": 1, "total_pins": 1,
         "top3_pins": 1, "top10_pins": 1},
    ]

    resp = build_maps_trends(scans, results)

    assert len(resp.keywords) == 1
    pt = resp.keywords[0].points[0]
    # No pins → percentages are None rather than a divide-by-zero.
    assert pt.top3_pct is None and pt.top10_pct is None and pt.found_pct is None
    # Orphan result excluded → exactly one point.
    assert len(resp.keywords[0].points) == 1


def test_build_maps_trends_empty():
    assert build_maps_trends([], []).keywords == []
