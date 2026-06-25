"""Unit tests for the GSC Research analysis helpers (pure, no I/O)."""

from __future__ import annotations

from services import gsc_research


# ---------------------------------------------------------------------------
# aggregate_query_pages
# ---------------------------------------------------------------------------
def test_aggregate_sums_and_impression_weights_position():
    rows = [
        {"query": "ac repair", "page": "/a", "clicks": 1, "impressions": 100, "position": 10.0},
        {"query": "ac repair", "page": "/a", "clicks": 2, "impressions": 100, "position": 14.0},  # avg 12
        {"query": "ac repair", "page": "/b", "clicks": 0, "impressions": 50, "position": 8.0},
    ]
    out = {(r["query"], r["page"]): r for r in gsc_research.aggregate_query_pages(rows)}
    a = out[("ac repair", "/a")]
    assert a["clicks"] == 3
    assert a["impressions"] == 200
    assert a["position"] == 12.0
    assert out[("ac repair", "/b")]["position"] == 8.0


def test_parse_live_page_rows_maps_keys_and_skips_incomplete():
    raw = [
        {"keys": ["ac repair", "/a"], "clicks": 3, "impressions": 100, "position": 7.2},
        {"keys": ["only-query"], "clicks": 1, "impressions": 5, "position": 9.0},  # no page → skip
        {"keys": ["", "/b"], "clicks": 1, "impressions": 5, "position": 9.0},       # blank query → skip
    ]
    out = gsc_research.parse_live_page_rows(raw)
    assert out == [{"query": "ac repair", "page": "/a", "clicks": 3, "impressions": 100, "position": 7.2}]


def test_aggregate_skips_blank_query_or_page():
    rows = [
        {"query": "", "page": "/a", "clicks": 1, "impressions": 10, "position": 5.0},
        {"query": "x", "page": "", "clicks": 1, "impressions": 10, "position": 5.0},
    ]
    assert gsc_research.aggregate_query_pages(rows) == []


# ---------------------------------------------------------------------------
# find_cannibalization
# ---------------------------------------------------------------------------
def test_cannibalization_flags_clustered_impressions_all_ranking_high():
    aggregated = [
        {"query": "lawyer", "page": "/x", "clicks": 5, "impressions": 100, "position": 4.0},
        {"query": "lawyer", "page": "/y", "clicks": 3, "impressions": 80, "position": 9.0},  # within 50%
    ]
    out = gsc_research.find_cannibalization(aggregated)
    assert len(out) == 1
    row = out[0]
    assert row["query"] == "lawyer"
    assert row["page_count"] == 2
    assert row["total_impressions"] == 180
    # pages ordered by impressions desc
    assert [p["page"] for p in row["pages"]] == ["/x", "/y"]


def test_cannibalization_excludes_single_page():
    aggregated = [{"query": "solo", "page": "/x", "clicks": 1, "impressions": 100, "position": 3.0}]
    assert gsc_research.find_cannibalization(aggregated) == []


def test_cannibalization_excludes_when_a_page_ranks_low():
    aggregated = [
        {"query": "q", "page": "/x", "clicks": 1, "impressions": 100, "position": 5.0},
        {"query": "q", "page": "/y", "clicks": 1, "impressions": 90, "position": 40.0},  # > 30
    ]
    assert gsc_research.find_cannibalization(aggregated) == []


def test_cannibalization_excludes_when_impressions_far_apart():
    aggregated = [
        {"query": "q", "page": "/x", "clicks": 1, "impressions": 1000, "position": 5.0},
        {"query": "q", "page": "/y", "clicks": 1, "impressions": 100, "position": 9.0},  # >50% apart
    ]
    assert gsc_research.find_cannibalization(aggregated) == []


# ---------------------------------------------------------------------------
# find_quick_wins / find_hidden_wins
# ---------------------------------------------------------------------------
def test_quick_wins_band_and_sort():
    aggregated = [
        {"query": "a", "page": "/a", "clicks": 1, "impressions": 50, "position": 6.0},   # in band
        {"query": "b", "page": "/b", "clicks": 1, "impressions": 200, "position": 10.0}, # in band, more impr
        {"query": "c", "page": "/c", "clicks": 1, "impressions": 10, "position": 5.0},   # boundary excl
        {"query": "d", "page": "/d", "clicks": 1, "impressions": 10, "position": 11.0},  # out of band
    ]
    out = gsc_research.find_quick_wins(aggregated)
    assert [r["keyword"] for r in out] == ["b", "a"]
    assert all(k in out[0] for k in ("search_volume", "cpc", "competition"))


def test_hidden_wins_band_and_min_impressions():
    aggregated = [
        {"query": "a", "page": "/a", "clicks": 1, "impressions": 5, "position": 12.0},   # in band
        {"query": "b", "page": "/b", "clicks": 1, "impressions": 4, "position": 20.0},   # too few impr
        {"query": "c", "page": "/c", "clicks": 1, "impressions": 100, "position": 30.0}, # boundary incl
        {"query": "d", "page": "/d", "clicks": 1, "impressions": 100, "position": 31.0}, # out of band
    ]
    out = gsc_research.find_hidden_wins(aggregated)
    assert sorted(r["keyword"] for r in out) == ["a", "c"]


# ---------------------------------------------------------------------------
# enrich_with_market
# ---------------------------------------------------------------------------
def test_enrich_with_market_matches_case_insensitively():
    rows = [{"keyword": "AC Repair", "page": "/a", "position": 6.0, "impressions": 1, "clicks": 0,
             "search_volume": None, "cpc": None, "competition": None}]
    market = {"ac repair": {"search_volume": 1000, "cpc": 4.5, "competition": "HIGH"}}
    gsc_research.enrich_with_market(rows, market)
    assert rows[0]["search_volume"] == 1000
    assert rows[0]["cpc"] == 4.5
    assert rows[0]["competition"] == "HIGH"
