import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import local_dominator  # noqa: E402


# A 3x3 scan (inscribed circle of radius 1.5 keeps all but the 4 corners — 5
# in-circle pins: center + 4 edges). detailsArray indices: 0 = our business,
# 1 = competitor A, 2 = competitor B. Each cell is a rank-ordered list of
# indices (position 0 = ranks 1st at that pin).
def _element():
    return {
        "detailsArray": [
            {"placeId": "US", "name": "Our Biz", "rating": 5.0, "ratingCount": 10,
             "primaryCategory": "Roofer", "websiteURL": "https://us.example"},
            {"placeId": "A", "name": "Comp A", "rating": 4.5, "ratingCount": 100,
             "primaryCategory": "Roofer", "websiteURL": "https://a.example"},
            {"placeId": "B", "name": "Comp B", "rating": 4.0, "ratingCount": 50,
             "primaryCategory": "Roofer", "websiteURL": "https://b.example"},
        ],
        "compressed_grid": [
            [[9, 9, 9], [1, 0, 2], [9, 9, 9]],   # corners ([0][0],[0][2]) are out-of-circle
            [[0, 1, 2], [2, 1, 0], [1, 2, 0]],   # middle row: 3 in-circle pins
            [[9, 9, 9], [0, 2, 1], [9, 9, 9]],
        ],
    }


def test_build_competitor_summary_counts_and_excludes_self():
    out = local_dominator.build_competitor_summary(_element(), our_place_id="US")

    # Our own business is excluded; only A and B remain.
    assert {c["place_id"] for c in out} == {"A", "B"}

    a = next(c for c in out if c["place_id"] == "A")
    # In-circle pins (5): [0][1]=[1,0,2], [1][0]=[0,1,2], [1][1]=[2,1,0],
    # [1][2]=[1,2,0], [2][1]=[0,2,1]. A's positions: 0,1,1,0,2 → ranks 1,2,2,1,3.
    assert a["found_pins"] == 5
    assert a["top3_pins"] == 5      # all ranks <= 3
    assert a["top10_pins"] == 5
    assert a["avg_rank"] == round((1 + 2 + 2 + 1 + 3) / 5, 2)  # 1.8

    b = next(c for c in out if c["place_id"] == "B")
    # B's positions across the 5 pins: 2,2,0,1,1 → ranks 3,3,1,2,2.
    assert b["found_pins"] == 5
    assert b["top3_pins"] == 5
    assert b["avg_rank"] == round((3 + 3 + 1 + 2 + 2) / 5, 2)  # 2.2

    # Ordering: more top-3 first; tie on top3/top10/found → better avg rank wins.
    assert [c["place_id"] for c in out] == ["A", "B"]
    # Carries through business metadata.
    assert a["name"] == "Comp A" and a["reviews"] == 100 and a["primary_category"] == "Roofer"


def test_build_competitor_summary_no_self_id_keeps_all():
    out = local_dominator.build_competitor_summary(_element(), our_place_id=None)
    assert {c["place_id"] for c in out} == {"US", "A", "B"}


def test_build_competitor_summary_respects_top_n_and_bad_indices():
    el = {
        "detailsArray": [{"placeId": "A", "name": "A"}, {"placeId": "B", "name": "B"}],
        # 1x1 grid; out-of-range / non-int indices are ignored, valid ones tallied.
        "compressed_grid": [[[0, 1, 5, None, -1]]],
    }
    out = local_dominator.build_competitor_summary(el, our_place_id=None, top_n=1)
    assert len(out) == 1            # capped to top_n
    assert out[0]["place_id"] == "A"  # rank 1 (position 0) beats B (position 1)


def test_build_competitor_summary_empty():
    assert local_dominator.build_competitor_summary({}, our_place_id="US") == []
