import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import local_dominator  # noqa: E402


# 3x3 scan; inscribed circle keeps center + 4 edges (5 pins), drops 4 corners.
# detailsArray: 0 = our business (US), 1 = A, 2 = B.
def _element():
    return {
        "detailsArray": [
            {"placeId": "US", "name": "Our Biz", "location": {"latitude": -37.8, "longitude": 144.9}},
            {"placeId": "A", "name": "Comp A", "rating": 4.5, "ratingCount": 100,
             "primaryCategory": "Roofer", "websiteURL": "https://a.example",
             "location": {"latitude": -37.81, "longitude": 144.91}},
            {"placeId": "B", "name": "Comp B", "rating": 4.0, "ratingCount": 50,
             "primaryCategory": "Roofer", "websiteURL": "https://b.example",
             "location": {"latitude": -37.82, "longitude": 144.92}},
        ],
        "compressed_grid": [
            [[9], [1, 0, 2], [9]],     # corners out-of-circle; top edge: A above US, B below
            [[0, 1, 2], [2, 1, 0], [1, 2, 0]],
            [[9], [2, 1, 0], [9]],     # bottom edge: B,A above US
        ],
    }


def test_above_keeps_only_higher_ranked_and_shapes_grid():
    res = local_dominator.build_competitors_above(_element(), our_place_id="US")
    grid = res["grid"]

    # 3x3: every pin falls inside the inscribed circle (corner dist^2 = 2 <=
    # radius^2 = 2.25). The corner cells hold junk indices → filtered to [].
    assert grid[0][0] == [] and grid[0][2] == []
    assert grid[2][0] == [] and grid[2][2] == []

    # Top edge [1,0,2]: US at position 1 → only A (rank 1) is above; B discarded.
    assert grid[0][1] == [["A", 1]]
    # Center [0,1,2]: US ranks 1st → nobody above.
    assert grid[1][1 - 1] == []   # grid[1][0]
    # Middle-right [1,2,0]: US at position 2 → A(rank1) and B(rank2) above.
    assert grid[1][2] == [["A", 1], ["B", 2]]
    # Bottom edge [2,1,0]: US at position 2 → B(rank1), A(rank2) above.
    assert grid[2][1] == [["B", 1], ["A", 2]]

    # Directory holds de-duplicated details for everyone who outranks us.
    assert set(res["directory"]) == {"A", "B"}
    assert res["directory"]["A"]["name"] == "Comp A"
    assert res["directory"]["A"]["reviews"] == 100
    assert res["directory"]["A"]["lat"] == -37.81


def test_above_when_client_absent_keeps_whole_pack():
    # US not in detailsArray for this keyword → every business outranks us.
    el = {
        "detailsArray": [{"placeId": "A", "name": "A"}, {"placeId": "B", "name": "B"}],
        "compressed_grid": [[[0, 1]]],  # 1x1 grid (single in-circle pin)
    }
    res = local_dominator.build_competitors_above(el, our_place_id="US")
    assert res["grid"][0][0] == [["A", 1], ["B", 2]]
    assert set(res["directory"]) == {"A", "B"}


def test_above_ignores_bad_indices_and_excludes_self():
    el = {
        "detailsArray": [{"placeId": "US"}, {"placeId": "A", "name": "A"}],
        "compressed_grid": [[[1, 5, None, 0]]],  # A, junk, junk, US → A is above US
    }
    res = local_dominator.build_competitors_above(el, our_place_id="US")
    assert res["grid"][0][0] == [["A", 1]]
    assert "US" not in res["directory"]


def test_above_marks_out_of_circle_pins_null():
    # 5x5: corners fall outside the inscribed circle (dist^2 = 8 > radius^2 =
    # 6.25) → null; the center is in-circle.
    el = {
        "detailsArray": [{"placeId": "A", "name": "A"}, {"placeId": "US"}],
        "compressed_grid": [[[0] for _ in range(5)] for _ in range(5)],  # every cell = [A]
    }
    g = local_dominator.build_competitors_above(el, our_place_id="US")["grid"]
    assert g[0][0] is None and g[0][4] is None and g[4][0] is None and g[4][4] is None
    assert g[2][2] == [["A", 1]]  # center: A outranks the (absent) client


def test_above_empty_element():
    assert local_dominator.build_competitors_above({}, our_place_id="US") == {"directory": {}, "grid": []}
