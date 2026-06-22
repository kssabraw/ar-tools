"""Unit tests for the DataForSEO fallback rank + source selection.

No network: only the pure helpers are exercised.
"""

from __future__ import annotations

from datetime import date, timedelta

from services import dataforseo_rank, rank_materialize, rank_status


# ---------------------------------------------------------------------------
# extract_domain
# ---------------------------------------------------------------------------
def test_extract_domain_strips_scheme_and_www():
    assert dataforseo_rank.extract_domain("https://www.acmehvac.com/services") == "acmehvac.com"
    assert dataforseo_rank.extract_domain("acmehvac.com") == "acmehvac.com"
    assert dataforseo_rank.extract_domain("") == ""


# ---------------------------------------------------------------------------
# find_rank_in_items
# ---------------------------------------------------------------------------
def test_find_rank_matches_domain_and_www():
    items = [
        {"type": "organic", "domain": "competitor.com", "rank_absolute": 1},
        {"type": "paid", "domain": "acmehvac.com", "rank_absolute": 2},  # not organic
        {"type": "organic", "domain": "www.acmehvac.com", "rank_absolute": 4},
    ]
    assert dataforseo_rank.find_rank_in_items(items, "acmehvac.com") == 4


def test_find_rank_returns_none_when_absent():
    items = [{"type": "organic", "domain": "competitor.com", "rank_absolute": 1}]
    assert dataforseo_rank.find_rank_in_items(items, "acmehvac.com") is None
    assert dataforseo_rank.find_rank_in_items(items, "") is None


def test_location_code_for_uses_cctld():
    assert dataforseo_rank.location_code_for({"website_url": "https://acme.com.au"}) == 2036  # AU
    assert dataforseo_rank.location_code_for({"website_url": "https://acme.com"}) == 2840    # default US


# ---------------------------------------------------------------------------
# is_gsc_covered
# ---------------------------------------------------------------------------
def test_is_gsc_covered_true_when_recent_position():
    today = date(2026, 6, 22)
    rows = [{"date": (today - timedelta(days=2)).isoformat(), "gsc_position": 8.0}]
    assert dataforseo_rank.is_gsc_covered(rows, today, 14) is True


def test_is_gsc_covered_false_when_old_or_null():
    today = date(2026, 6, 22)
    rows = [
        {"date": (today - timedelta(days=40)).isoformat(), "gsc_position": 8.0},  # too old
        {"date": today.isoformat(), "gsc_position": None},                        # null
    ]
    assert dataforseo_rank.is_gsc_covered(rows, today, 14) is False


# ---------------------------------------------------------------------------
# source classification
# ---------------------------------------------------------------------------
def test_classify_source_variants():
    assert rank_materialize.classify_source([{"gsc_position": 5, "tracked_rank": 3}]) == "both"
    assert rank_materialize.classify_source([{"gsc_position": 5, "tracked_rank": None}]) == "gsc"
    assert rank_materialize.classify_source([{"gsc_position": None, "tracked_rank": 3}]) == "dataforseo"
    assert rank_materialize.classify_source([{"gsc_position": None, "tracked_rank": None}]) == "gsc"


def test_determine_primary_source_prefers_recent_gsc():
    today = date(2026, 6, 22)
    rows = [{"date": today.isoformat(), "gsc_position": 9.0, "tracked_rank": 4}]
    assert rank_status.determine_primary_source(rows, today, 14) == "gsc"


def test_determine_primary_source_falls_back_to_dataforseo():
    today = date(2026, 6, 22)
    # No recent GSC, but a DataForSEO rank exists → dataforseo.
    rows = [{"date": (today - timedelta(days=30)).isoformat(), "gsc_position": None, "tracked_rank": 12}]
    assert rank_status.determine_primary_source(rows, today, 14) == "dataforseo"


def test_determine_primary_source_none_when_no_data():
    today = date(2026, 6, 22)
    rows = [{"date": today.isoformat(), "gsc_position": None, "tracked_rank": None}]
    assert rank_status.determine_primary_source(rows, today, 14) == "none"


# ---------------------------------------------------------------------------
# source-aware summary
# ---------------------------------------------------------------------------
def test_summary_dataforseo_mode_drops_gsc_metrics():
    today = date(2026, 6, 22)
    # Weekly DataForSEO points, no GSC — should expose today_rank + sparkline,
    # and leave the GSC columns (avg_*, clicks/impr) empty.
    rows = [
        {"date": (today - timedelta(days=14)).isoformat(), "gsc_position": None, "tracked_rank": 18, "clicks": 0, "impressions": 0, "ctr": 0},
        {"date": (today - timedelta(days=7)).isoformat(), "gsc_position": None, "tracked_rank": 12, "clicks": 0, "impressions": 0, "ctr": 0},
        {"date": today.isoformat(), "gsc_position": None, "tracked_rank": 9, "clicks": 0, "impressions": 0, "ctr": 0},
    ]
    s = rank_status.compute_keyword_summary(rows, today, 14)
    assert s["primary_source"] == "dataforseo"
    assert s["today_rank"] == 9
    assert s["avg_30"] is None and s["clicks_30d"] == 0
    assert s["sparkline"] == [18, 12, 9]
    assert s["direction"] == "up"  # 18 → 9 = improving


def test_summary_gsc_mode_keeps_metrics():
    today = date(2026, 6, 22)
    rows = [
        {"date": (today - timedelta(days=i)).isoformat(), "gsc_position": 8.0, "tracked_rank": None,
         "clicks": 1, "impressions": 20, "ctr": 0.05}
        for i in range(10)
    ]
    s = rank_status.compute_keyword_summary(rows, today, 14)
    assert s["primary_source"] == "gsc"
    assert s["avg_7"] == 8.0
    assert s["clicks_30d"] == 10 and s["impressions_30d"] == 200
