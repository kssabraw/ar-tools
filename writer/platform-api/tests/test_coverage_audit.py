"""Unit tests for the Coverage Audit pure core (Phase 0) — no I/O.

Covers: site-page classification buckets (incl. blog exclusion + multi-word place
names + homepage no-content), the AXES-ONLY report grid (must never carry Matrix
cell-state), the minimum-demand floor on gaps, and empty-state degrade.
"""

from services import coverage_audit as ca
from services.site_page_index import build_location_slug_index, build_page_token_index


# --- classify_site_pages ------------------------------------------------------
def test_classify_buckets_and_blog_exclusion():
    urls = [
        "https://x.com/roof-restoration-melbourne/",   # service + place
        "https://x.com/melbourne/",                    # place only
        "https://x.com/roof-restoration/",             # service only
        "https://x.com/blog/why-roof-restoration/",    # blog → other
        "https://x.com/",                              # homepage → no_content
        "https://x.com/plumbing-san-francisco/",       # service + multi-word place
    ]
    result = ca.classify_site_pages(urls, ["Melbourne", "San Francisco"])

    sl_urls = {e["url"] for e in result[ca.BUCKET_SERVICE_LOCATION]}
    assert sl_urls == {
        "https://x.com/roof-restoration-melbourne/",
        "https://x.com/plumbing-san-francisco/",
    }
    assert {e["url"] for e in result[ca.BUCKET_LOCATION_ONLY]} == {"https://x.com/melbourne/"}
    assert {e["url"] for e in result[ca.BUCKET_SERVICE_ONLY]} == {"https://x.com/roof-restoration/"}

    other = {e["url"]: e["reason"] for e in result[ca.BUCKET_OTHER]}
    assert other == {
        "https://x.com/blog/why-roof-restoration/": "non_page",
        "https://x.com/": "no_content",
    }


def test_classify_multiword_place_splits_tokens():
    result = ca.classify_site_pages(
        ["https://x.com/plumbing-san-francisco/"], ["San Francisco"]
    )
    entry = result[ca.BUCKET_SERVICE_LOCATION][0]
    assert entry["place_tokens"] == ["francisco", "san"]
    assert entry["service_tokens"] == ["plumbing"]


def test_classify_dedupes_urls():
    urls = ["https://x.com/roofing/", "https://x.com/roofing/"]
    result = ca.classify_site_pages(urls, [])
    assert len(result[ca.BUCKET_SERVICE_ONLY]) == 1


def test_classify_empty_inputs_degrade():
    assert ca.classify_site_pages(None, None) == {
        ca.BUCKET_SERVICE_ONLY: [],
        ca.BUCKET_LOCATION_ONLY: [],
        ca.BUCKET_SERVICE_LOCATION: [],
        ca.BUCKET_OTHER: [],
    }
    assert ca.classify_site_pages([], []) == {
        ca.BUCKET_SERVICE_ONLY: [],
        ca.BUCKET_LOCATION_ONLY: [],
        ca.BUCKET_SERVICE_LOCATION: [],
        ca.BUCKET_OTHER: [],
    }


# --- build_coverage_grid ------------------------------------------------------
def _site_index(urls):
    return {
        "token_index": build_page_token_index(urls),
        "location_index": build_location_slug_index(urls),
    }


def test_grid_present_absent_from_site():
    site = _site_index(
        [
            "https://x.com/roof-restoration-melbourne/",
            "https://x.com/gutter-cleaning/",
            "https://x.com/melbourne/",
        ]
    )
    grid = ca.build_coverage_grid(
        ["Roof Restoration", "Gutter Cleaning"], ["Melbourne", "Geelong"], site
    )

    svc = {r["service"]: r for r in grid["services"]}
    # A city-less service page exists for gutter cleaning, but roof-restoration
    # only exists as a "<service> <city>" page (no bare /roof-restoration/).
    assert svc["Gutter Cleaning"]["present"] is True
    assert svc["Gutter Cleaning"]["source"] == "site"
    assert svc["Roof Restoration"]["present"] is False

    loc = {r["location"]: r for r in grid["locations"]}
    assert loc["Melbourne"]["present"] is True          # /melbourne/ hub exists
    assert loc["Geelong"]["present"] is False

    cells = {r["keyword"]: r for r in grid["cells"]}
    assert cells["Roof Restoration Melbourne"]["present"] is True
    assert cells["Roof Restoration Geelong"]["present"] is False
    assert cells["Gutter Cleaning Melbourne"]["present"] is False
    assert cells["Gutter Cleaning Geelong"]["present"] is False

    assert grid["counts"]["cells_total"] == 4
    assert grid["counts"]["cells_present"] == 1
    assert grid["counts"]["cells_absent"] == 3


def test_grid_in_tool_index_marks_present():
    site = _site_index(["https://x.com/roof-restoration-melbourne/"])
    in_tool = _site_index(["https://x.com/gutter-cleaning-geelong/"])
    grid = ca.build_coverage_grid(
        ["Gutter Cleaning"], ["Geelong"], site, in_tool
    )
    cell = grid["cells"][0]
    assert cell["keyword"] == "Gutter Cleaning Geelong"
    assert cell["present"] is True
    assert cell["source"] == "in_tool"


def test_grid_never_emits_matrix_cell_state():
    """AXES-ONLY contract (plan §8 Major #1): the report grid must never carry any
    Matrix per-cell coverage-state key — the Matrix owns that via mark_coverage."""
    site = _site_index(["https://x.com/roof-restoration-melbourne/"])
    grid = ca.build_coverage_grid(
        ["Roof Restoration", "Gutters"], ["Melbourne", "Geelong"], site
    )
    for section in ("services", "locations", "cells"):
        for row in grid[section]:
            offending = set(row.keys()) & ca.MATRIX_CELL_STATE_KEYS
            assert not offending, f"grid {section} row leaked matrix state: {offending}"
            # Presence is a plain boolean, not a matrix cell-state string.
            assert isinstance(row["present"], bool)


def test_grid_empty_index_all_absent():
    grid = ca.build_coverage_grid(["Roofing"], ["Melbourne"], None)
    assert grid["services"][0]["present"] is False
    assert grid["locations"][0]["present"] is False
    assert grid["cells"][0]["present"] is False


def test_grid_empty_axes_degrade():
    grid = ca.build_coverage_grid([], [], None)
    assert grid["services"] == []
    assert grid["locations"] == []
    assert grid["cells"] == []
    assert grid["counts"]["cells_total"] == 0


def test_grid_accepts_dict_axis_entries():
    site = _site_index([])
    grid = ca.build_coverage_grid(
        [{"label": "Roofing"}], [{"name": "Melbourne"}], site
    )
    assert grid["services"][0]["service"] == "Roofing"
    assert grid["locations"][0]["location"] == "Melbourne"


# --- diff_coverage ------------------------------------------------------------
def test_diff_extracts_absent():
    grid = {
        "services": [
            {"service": "Roofing", "keyword": "Roofing", "present": True},
            {"service": "Gutters", "keyword": "Gutters", "present": False},
        ],
        "locations": [
            {"location": "Melbourne", "keyword": "Melbourne", "present": False},
        ],
        "cells": [
            {"service": "Roofing", "location": "Melbourne",
             "keyword": "Roofing Melbourne", "present": True},
            {"service": "Gutters", "location": "Melbourne",
             "keyword": "Gutters Melbourne", "present": False},
        ],
    }
    diff = ca.diff_coverage(grid)
    assert diff["missing_services"] == [{"service": "Gutters", "keyword": "Gutters"}]
    assert diff["missing_locations"] == [{"location": "Melbourne", "keyword": "Melbourne"}]
    assert diff["missing_cells"] == [
        {"service": "Gutters", "location": "Melbourne", "keyword": "Gutters Melbourne"}
    ]


def test_diff_empty_degrade():
    empty = {"missing_services": [], "missing_locations": [], "missing_cells": []}
    assert ca.diff_coverage(None) == empty
    assert ca.diff_coverage({}) == empty


# --- rank_gaps ----------------------------------------------------------------
def _cell_gaps():
    return [
        {"service": "Roof Restoration", "location": "Geelong",
         "keyword": "Roof Restoration Geelong"},
        {"service": "Gutter Cleaning", "location": "Melbourne",
         "keyword": "Gutter Cleaning Melbourne"},
        {"service": "Gutter Cleaning", "location": "Geelong",
         "keyword": "Gutter Cleaning Geelong"},
    ]


def _market():
    return {
        "roof restoration geelong": {"search_volume": 100, "cpc": 5.0, "competition": "MEDIUM"},
        "gutter cleaning melbourne": {"search_volume": 5, "cpc": 2.0, "competition": "LOW"},
        "gutter cleaning geelong": {"search_volume": None, "cpc": None, "competition": None},
    }


def test_rank_gaps_floor_drops_subfloor_and_unknown():
    ranked = ca.rank_gaps(_cell_gaps(), _market(), min_volume=10)
    # Only the 100-volume cell clears the floor; the 5-volume cell and the
    # unknown-volume (None → 0) cell are DROPPED, not merely ranked last.
    assert len(ranked) == 1
    row = ranked[0]
    assert row["keyword"] == "Roof Restoration Geelong"
    assert row["volume"] == 100
    assert row["est_value"] is not None and row["est_value"] > 0
    assert row["opportunity_score"] > 0


def test_rank_gaps_floor_zero_keeps_all_and_orders_by_score():
    ranked = ca.rank_gaps(_cell_gaps(), _market(), min_volume=0)
    assert [r["keyword"] for r in ranked] == [
        "Roof Restoration Geelong",   # highest opportunity score
        "Gutter Cleaning Melbourne",
        "Gutter Cleaning Geelong",    # unknown volume → score 0, last
    ]
    scores = [r["opportunity_score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)


def test_rank_gaps_missing_market_data_scores_zero():
    ranked = ca.rank_gaps(
        [{"keyword": "no data keyword"}], {}, min_volume=0
    )
    assert ranked[0]["volume"] is None
    assert ranked[0]["opportunity_score"] == 0
    assert ranked[0]["est_value"] is None


def test_rank_gaps_empty_degrade():
    assert ca.rank_gaps([], {}, min_volume=10) == []
    assert ca.rank_gaps(None, None) == []


# --- competition → difficulty proxy -------------------------------------------
def test_competition_to_difficulty_bands():
    assert ca._competition_to_difficulty("LOW") == 20.0
    assert ca._competition_to_difficulty("medium") == 50.0
    assert ca._competition_to_difficulty("High") == 80.0
    assert ca._competition_to_difficulty(None) is None
    assert ca._competition_to_difficulty(0.4) == 40.0   # 0-1 fraction scaled
    assert ca._competition_to_difficulty(65) == 65.0    # already an index
