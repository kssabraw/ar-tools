"""Unit tests for services.citation_audit — presence evaluation (pure)."""

from __future__ import annotations

from services import citation_audit as ca


def test_host_matches_directory_handles_subdomains_and_www():
    assert ca.host_matches_directory("https://www.yelp.com/biz/acme", "yelp.com")
    assert ca.host_matches_directory("https://business.facebook.com/acme", "facebook.com")
    assert not ca.host_matches_directory("https://notyelp.com/acme", "yelp.com")
    assert not ca.host_matches_directory(None, "yelp.com")


def test_evaluate_listing_found_and_missing():
    found = ca.evaluate_listing("yelp.com", ["https://google.com/x", "https://www.yelp.com/biz/acme"])
    assert found == {"directory": "yelp.com", "listed": True, "url": "https://www.yelp.com/biz/acme"}

    missing = ca.evaluate_listing("bbb.org", ["https://google.com/x"])
    assert missing == {"directory": "bbb.org", "listed": False, "url": None}


def test_build_result_separates_listed_from_missing():
    checks = [
        {"directory": "yelp.com", "listed": True, "url": "u"},
        {"directory": "bbb.org", "listed": False, "url": None},
        {"directory": "angi.com", "listed": False, "url": None},
    ]
    r = ca.build_result(checks)
    assert r["directories_checked"] == 3
    assert r["listed_count"] == 1
    assert r["missing_count"] == 2
    assert r["missing"] == ["bbb.org", "angi.com"]
