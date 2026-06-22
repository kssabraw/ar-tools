"""Unit tests for query×page parsing, canonical resolution, Pages pivot (M4)."""

from __future__ import annotations

from services import gsc_ingest, rank_materialize, rank_status


def test_parse_query_page_rows():
    rows = [
        {"keys": ["hvac repair", "https://x.com/hvac", "2026-06-21"],
         "clicks": 3, "impressions": 50, "ctr": 0.06, "position": 7.1},
        {"keys": ["too", "few"]},  # < 3 keys → skipped
    ]
    parsed = gsc_ingest.parse_query_page_rows("prop-1", rows)
    assert len(parsed) == 1
    assert parsed[0]["page"] == "https://x.com/hvac"
    assert parsed[0]["query"] == "hvac repair"
    assert parsed[0]["date"] == "2026-06-21"


def test_resolve_canonical_prefers_most_clicks():
    rows = [
        {"query": "HVAC Repair", "page": "/a", "clicks": 2, "impressions": 100},
        {"query": "HVAC Repair", "page": "/b", "clicks": 5, "impressions": 10},
        {"query": "HVAC Repair", "page": "/a", "clicks": 1, "impressions": 100},
    ]
    # /a totals 3 clicks, /b totals 5 → /b wins on clicks.
    assert rank_materialize.resolve_canonical_pages(rows) == {"hvac repair": "/b"}


def test_resolve_canonical_tiebreak_on_impressions():
    rows = [
        {"query": "q", "page": "/a", "clicks": 1, "impressions": 10},
        {"query": "q", "page": "/b", "clicks": 1, "impressions": 80},
    ]
    assert rank_materialize.resolve_canonical_pages(rows) == {"q": "/b"}


def test_aggregate_pages_sums_and_weights():
    rows = [
        {"query": "q1", "page": "/a", "clicks": 5, "impressions": 100, "position": 4.0},
        {"query": "q2", "page": "/a", "clicks": 1, "impressions": 100, "position": 8.0},
        {"query": "q3", "page": "/b", "clicks": 9, "impressions": 50, "position": 2.0},
    ]
    pages = rank_status.aggregate_pages(rows)
    # /b has more clicks → first.
    assert pages[0]["page"] == "/b"
    a = next(p for p in pages if p["page"] == "/a")
    assert a["clicks"] == 6 and a["keywords"] == 2
    # impression-weighted position: (4*100 + 8*100)/200 = 6.0
    assert a["avg_position"] == 6.0
