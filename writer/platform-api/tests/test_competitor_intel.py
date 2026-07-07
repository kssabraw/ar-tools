"""Unit tests for services.competitor_intel — pure discovery/normalization."""

from __future__ import annotations

from datetime import date

from services import competitor_intel as ci


# ---------------------------------------------------------------------------
# normalize_domain
# ---------------------------------------------------------------------------
def test_normalize_domain_strips_scheme_www_path_port():
    assert ci.normalize_domain("https://www.BobsRoofing.com/services/") == "bobsroofing.com"
    assert ci.normalize_domain("bobsroofing.com") == "bobsroofing.com"
    assert ci.normalize_domain("http://sub.example.co.uk:8080/x") == "sub.example.co.uk"
    assert ci.normalize_domain(None) is None
    assert ci.normalize_domain("  ") is None


# ---------------------------------------------------------------------------
# discover_from_maps
# ---------------------------------------------------------------------------
def test_discover_from_maps_ranks_by_pack_presence_and_dedups():
    rows = [
        {"place_id": "a", "name": "Alpha Roofing", "website": "https://alpha.com", "top3_pins": 3, "found_pins": 10},
        {"place_id": "a", "name": "Alpha Roofing", "website": "https://alpha.com", "top3_pins": 8, "found_pins": 12},
        {"place_id": "b", "name": "Beta Roofing", "website": None, "top3_pins": 5, "found_pins": 20},
        {"place_id": None, "name": "No Place", "top3_pins": 9},   # no place_id → skipped
        {"place_id": "c", "name": None, "top3_pins": 9},          # no name → skipped
    ]
    out = ci.discover_from_maps(rows, limit=5)
    assert [c["name"] for c in out] == ["Alpha Roofing", "Beta Roofing"]
    assert out[0]["domain"] == "alpha.com"      # website normalized
    assert out[1]["domain"] is None             # maps-only competitor
    assert all(c["source"] == "maps" for c in out)


# ---------------------------------------------------------------------------
# discover_from_serp
# ---------------------------------------------------------------------------
def test_discover_from_serp_requires_recurrence_and_skips_client():
    rows = [
        {"keyword": "roof repair", "domain": "www.rival.com", "position": 2, "is_client": False},
        {"keyword": "roof replacement", "domain": "rival.com", "position": 5, "is_client": False},
        {"keyword": "roof repair", "domain": "oneoff.com", "position": 3, "is_client": False},
        {"keyword": "roof repair", "domain": "client.com", "position": 1, "is_client": True},
        {"keyword": "roof repair", "domain": "clientsite.com", "position": 4, "is_client": False},
        {"keyword": "roof replacement", "domain": "clientsite.com", "position": 6, "is_client": False},
        {"keyword": "roof repair", "domain": "deep.com", "position": 40, "is_client": False},  # >10 → out
    ]
    out = ci.discover_from_serp(rows, client_domain="https://www.clientsite.com")
    names = [c["domain"] for c in out]
    assert "rival.com" in names           # 2 keywords, www-variant merged
    assert "oneoff.com" not in names      # only 1 keyword
    assert "clientsite.com" not in names  # the client's own domain
    assert "client.com" not in names      # is_client rows never qualify
    assert all(c["source"] == "organic" for c in out)


def test_discover_from_serp_orders_by_breadth_then_best_position():
    rows = []
    for kw in ("a", "b", "c"):
        rows.append({"keyword": kw, "domain": "broad.com", "position": 8, "is_client": False})
    for kw in ("a", "b"):
        rows.append({"keyword": kw, "domain": "strong.com", "position": 1, "is_client": False})
    out = ci.discover_from_serp(rows, client_domain=None)
    assert [c["domain"] for c in out] == ["broad.com", "strong.com"]


# ---------------------------------------------------------------------------
# review_velocity
# ---------------------------------------------------------------------------
def test_review_velocity_trailing_window():
    today = date(2026, 7, 7)
    dates = ["2026-07-01", "2026-06-15", "2026-05-20", "2026-01-01", None, "junk"]
    # 3 reviews in 90 days → 1.0/mo
    assert ci.review_velocity(dates, today) == 1.0
    assert ci.review_velocity([], today) == 0.0
