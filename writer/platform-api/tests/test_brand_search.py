"""Unit tests for brand-search pure helpers (no network)."""

from __future__ import annotations

from services import brand_search


def test_derive_brand_terms_keeps_distinctive_drops_generic():
    terms = brand_search.derive_brand_terms("Ace Plumbing Co", "Ace Plumbing")
    assert "ace plumbing co" in terms          # full phrase
    assert "ace" in terms                       # distinctive token
    assert "plumbing" not in terms              # generic trade word dropped
    assert "co" not in terms                    # generic suffix dropped


def test_resolve_brand_terms_prefers_manual_override():
    client = {"name": "Ace Plumbing", "brand_terms": ["AceCo", "Ace Plumbing"]}
    assert brand_search.resolve_brand_terms(client) == ["aceco", "ace plumbing"]


def test_resolve_brand_terms_derives_from_name_and_gbp():
    client = {"name": "Redback Roofing", "gbp": {"business_name": "Redback Roofing Pty"}}
    terms = brand_search.resolve_brand_terms(client)
    assert "redback" in terms
    assert "roofing" not in terms


def test_classify_query_phrase_and_token_and_negative():
    terms = ["ace plumbing", "ace"]
    assert brand_search.classify_query("ace plumbing reviews", terms) is True   # phrase
    assert brand_search.classify_query("call ace today", terms) is True         # token (word)
    assert brand_search.classify_query("emergency plumber sydney", terms) is False
    assert brand_search.classify_query("spacex launch", ["ace"]) is False       # not a substring match


def test_build_brand_search_buckets_by_week_and_shares():
    terms = ["ace"]
    rows = [
        {"query": "ace plumbing", "date": "2026-06-01", "impressions": 100, "clicks": 10},   # Mon
        {"query": "plumber near me", "date": "2026-06-03", "impressions": 300, "clicks": 5},
        {"query": "ace reviews", "date": "2026-06-08", "impressions": 50, "clicks": 8},       # next Mon
    ]
    out = brand_search.build_brand_search(rows, terms)
    assert [w["week"] for w in out["series"]] == ["2026-06-01", "2026-06-08"]
    wk1 = out["series"][0]
    assert wk1["branded_impressions"] == 100 and wk1["nonbranded_impressions"] == 300
    assert wk1["branded_share_pct"] == 25.0
    assert out["totals"]["branded_impressions"] == 150
    assert out["totals"]["branded_share_pct"] == 33.3   # 150 / 450


def test_detect_brand_decline_fires_and_respects_threshold():
    # 8 weeks: prior 4 sum 400, recent 4 sum 200 → 50% decline.
    series = [{"branded_impressions": v} for v in [100, 100, 100, 100, 50, 50, 50, 50]]
    drop = brand_search.detect_brand_decline(series, min_drop_pct=25.0, window=4)
    assert drop is not None and drop["delta_pct"] == 50.0
    assert brand_search.detect_brand_decline(series, min_drop_pct=60.0, window=4) is None


def test_detect_brand_decline_needs_two_full_windows():
    series = [{"branded_impressions": 100} for _ in range(6)]
    assert brand_search.detect_brand_decline(series, 10.0, window=4) is None
