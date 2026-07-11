"""Unit tests for the pure parse helpers in services/backlinks_api.py and the
target-normalization helper in services/backlink_explorer.py — no network."""

from datetime import datetime, timezone

import pytest

from services import backlinks_api
from services import backlink_explorer


# ---------------------------------------------------------------------------
# parse_summary
# ---------------------------------------------------------------------------
def test_parse_summary_derives_dofollow_and_dr():
    body = {"tasks": [{"status_code": 20000, "result": [{
        "target": "example.com", "referring_domains": 120, "referring_main_domains": 110,
        "backlinks": 900, "backlinks_nofollow": 300, "broken_backlinks": 12,
        "referring_ips": 80, "referring_subnets": 70, "rank": 456,
        "first_seen": "2020-01-01", "lost_date": None,
    }]}]}
    out = backlinks_api.parse_summary(body)
    assert out["referring_domains"] == 120
    assert out["dofollow"] == 600            # 900 - 300
    assert out["nofollow"] == 300
    assert out["domain_rating"] == 45.6      # 456 / 10
    assert out["broken_backlinks"] == 12


def test_parse_summary_handles_missing_nofollow():
    body = {"tasks": [{"status_code": 20000, "result": [{"backlinks": 10}]}]}
    out = backlinks_api.parse_summary(body)
    assert out["dofollow"] is None           # can't derive without nofollow
    assert out["domain_rating"] is None      # no rank


def test_parse_summary_raises_on_error():
    body = {"tasks": [{"status_code": 40400, "status_message": "bad", "result": None}]}
    with pytest.raises(RuntimeError, match="dataforseo_backlinks_summary_error"):
        backlinks_api.parse_summary(body)


# ---------------------------------------------------------------------------
# parse_referring_domains
# ---------------------------------------------------------------------------
def test_parse_referring_domains_maps_rank_and_lost():
    body = {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"domain": "a.com", "rank": 300, "backlinks": 20, "backlinks_nofollow": 5,
         "first_seen": "2021-01-01", "lost_date": None, "is_new": True},
        {"domain": "b.com", "rank": 100, "backlinks": 4, "backlinks_nofollow": 4,
         "first_seen": "2020-01-01", "lost_date": "2023-06-01"},
    ]}]}]}
    out = backlinks_api.parse_referring_domains(body)
    assert out[0] == {"domain": "a.com", "domain_rating": 30.0, "backlinks": 20,
                      "dofollow": 15, "first_seen": "2021-01-01", "last_seen": None,
                      "is_lost": False, "is_new": True}
    assert out[1]["is_lost"] is True
    assert out[1]["last_seen"] == "2023-06-01"
    assert out[1]["dofollow"] == 0


def test_parse_referring_domains_empty():
    body = {"tasks": [{"status_code": 20000, "result": [{"items": []}]}]}
    assert backlinks_api.parse_referring_domains(body) == []


# ---------------------------------------------------------------------------
# parse_anchors / parse_history
# ---------------------------------------------------------------------------
def test_parse_anchors():
    body = {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"anchor": "click here", "backlinks": 50, "backlinks_nofollow": 10,
         "referring_domains": 12, "first_seen": "2019-01-01"},
    ]}]}]}
    out = backlinks_api.parse_anchors(body)
    assert out == [{"anchor": "click here", "backlinks": 50, "referring_domains": 12,
                    "dofollow": 40, "first_seen": "2019-01-01"}]


def test_parse_history_series():
    body = {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"date": "2024-01-01", "referring_domains": 100, "backlinks": 800, "rank": 400,
         "new_referring_domains": 5, "lost_referring_domains": 2,
         "new_backlinks": 30, "lost_backlinks": 10},
    ]}]}]}
    out = backlinks_api.parse_history(body)
    assert out[0]["referring_domains"] == 100
    assert out[0]["domain_rating"] == 40.0
    assert out[0]["new_referring_domains"] == 5


# ---------------------------------------------------------------------------
# parse_backlinks (link list) — flags + pagination total
# ---------------------------------------------------------------------------
def test_parse_backlinks_flags_and_total():
    body = {"tasks": [{"status_code": 20000, "result": [{"total_count": 5321, "items": [
        {"url_from": "https://a.com/x", "domain_from": "a.com", "url_to": "https://t.com/",
         "anchor": "great tool", "dofollow": True, "domain_from_rank": 500, "page_from_rank": 350,
         "first_seen": "2022-01-01", "last_seen": "2024-01-01",
         "is_new": False, "is_lost": False, "is_broken": True},
    ]}]}]}
    out = backlinks_api.parse_backlinks(body)
    assert out["total_count"] == 5321
    link = out["links"][0]
    assert link["domain_rating"] == 50.0
    assert link["page_rating"] == 35.0
    assert link["is_broken"] is True
    assert link["dofollow"] is True


# ---------------------------------------------------------------------------
# fetch_backlinks mode guard (pure branch, no network) — invalid mode coerced
# ---------------------------------------------------------------------------
def test_link_modes_constant():
    assert "one_per_domain" in backlinks_api.LINK_MODES
    assert "one_per_subdomain" not in backlinks_api.LINK_MODES


# ---------------------------------------------------------------------------
# normalize_target
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("example.com", ("example.com", "domain")),
    ("https://example.com", ("example.com", "domain")),
    ("https://www.example.com/", ("example.com", "domain")),
    ("http://www.example.com", ("example.com", "domain")),
    ("blog.example.com", ("blog.example.com", "subdomain")),
    ("https://shop.example.co.uk", ("shop.example.co.uk", "subdomain")),
    ("example.com/blog/post-1", ("example.com/blog/post-1", "url")),
    ("https://example.com/pricing", ("example.com/pricing", "url")),
    ("https://example.com/pricing/", ("example.com/pricing", "url")),   # trailing slash stripped
    ("example.com/a/b/", ("example.com/a/b", "url")),                    # deep path trailing slash stripped
])
def test_normalize_target(raw, expected):
    assert backlink_explorer.normalize_target(raw) == expected


def test_normalize_target_rejects_empty():
    with pytest.raises(ValueError):
        backlink_explorer.normalize_target("   ")


# ---------------------------------------------------------------------------
# link filter map
# ---------------------------------------------------------------------------
def test_link_filter_map_covers_tabs():
    for key in ("all", "dofollow", "nofollow", "new", "lost", "broken"):
        assert key in backlink_explorer._LINK_FILTERS
    assert backlink_explorer._LINK_FILTERS["broken"] == [["is_broken", "=", True]]
    assert backlink_explorer._LINK_FILTERS["all"] is None


# ---------------------------------------------------------------------------
# diff_domains (new/lost referring-domain diffing)
# ---------------------------------------------------------------------------
def test_diff_domains_new_and_lost():
    out = backlink_explorer.diff_domains({"a.com", "b.com"}, ["b.com", "c.com", "d.com"])
    assert out == {"new": ["c.com", "d.com"], "lost": ["a.com"]}


def test_diff_domains_no_change():
    out = backlink_explorer.diff_domains({"a.com", "b.com"}, ["a.com", "b.com"])
    assert out == {"new": [], "lost": []}


def test_diff_domains_ignores_empty():
    out = backlink_explorer.diff_domains({"a.com"}, ["a.com", None, ""])
    assert out == {"new": [], "lost": []}


# ---------------------------------------------------------------------------
# _diff_for_snapshot — baseline + API-failure guard (no false total-loss)
# ---------------------------------------------------------------------------
def test_diff_for_snapshot_baseline_is_empty():
    # No previous snapshot → baseline, never "all new".
    assert backlink_explorer._diff_for_snapshot(None, True, set(), ["a.com", "b.com"]) == {"new": [], "lost": []}


def test_diff_for_snapshot_suppressed_when_fetch_failed():
    # RD fetch failed (rd_ok False) with an empty current list — must NOT report
    # every previous domain as lost (that would be a false outage-driven alert).
    assert backlink_explorer._diff_for_snapshot("s1", False, {"a.com", "b.com"}, []) == {"new": [], "lost": []}


def test_diff_for_snapshot_genuine_total_loss_still_reported():
    # A SUCCESSFUL empty fetch is a genuine total loss — still diffed.
    out = backlink_explorer._diff_for_snapshot("s1", True, {"a.com", "b.com"}, [])
    assert out == {"new": [], "lost": ["a.com", "b.com"]}


def test_diff_for_snapshot_normal():
    out = backlink_explorer._diff_for_snapshot("s1", True, {"a.com"}, ["a.com", "c.com"])
    assert out == {"new": ["c.com"], "lost": []}


# ---------------------------------------------------------------------------
# should_alert (threshold gate — defaults 10 new / 10 lost)
# ---------------------------------------------------------------------------
def test_should_alert_below_threshold():
    assert backlink_explorer.should_alert(3, 4) is False


def test_should_alert_on_new():
    assert backlink_explorer.should_alert(10, 0) is True


def test_should_alert_on_lost():
    assert backlink_explorer.should_alert(0, 12) is True


# ---------------------------------------------------------------------------
# match_own_domain_target (agent-layer own-domain lookup)
# ---------------------------------------------------------------------------
def test_match_own_domain_target_finds_bare_domain():
    targets = [
        {"target": "sub.example.com", "target_type": "subdomain"},
        {"target": "example.com", "target_type": "domain"},
    ]
    assert backlink_explorer.match_own_domain_target(targets, "example.com")["target_type"] == "domain"


def test_match_own_domain_target_case_insensitive():
    targets = [{"target": "Example.com", "target_type": "domain"}]
    assert backlink_explorer.match_own_domain_target(targets, "example.com") is not None


def test_match_own_domain_target_none_when_only_url_tracked():
    targets = [{"target": "example.com/pricing", "target_type": "url"}]
    assert backlink_explorer.match_own_domain_target(targets, "example.com") is None


def test_match_own_domain_target_none_without_domain():
    assert backlink_explorer.match_own_domain_target([{"target": "x.com", "target_type": "domain"}], None) is None


# ---------------------------------------------------------------------------
# net_rd_change
# ---------------------------------------------------------------------------
def test_net_rd_change():
    assert backlink_explorer.net_rd_change(100, 85) == -15
    assert backlink_explorer.net_rd_change(50, 50) == 0
    assert backlink_explorer.net_rd_change(None, 5) is None
    assert backlink_explorer.net_rd_change(5, None) is None


# ---------------------------------------------------------------------------
# should_alert_gated — churn suppressed unless net total RD corroborates
# ---------------------------------------------------------------------------
def test_gated_suppresses_window_churn():
    # 12 in + 12 out but the true total is flat → window churn, no alert.
    assert backlink_explorer.should_alert_gated(12, 12, 0) is False


def test_gated_real_loss_alerts():
    assert backlink_explorer.should_alert_gated(0, 15, -15) is True


def test_gated_real_gain_alerts():
    assert backlink_explorer.should_alert_gated(15, 0, 5) is True


def test_gated_loss_with_positive_net_suppressed():
    # 12 lost from the window but the total went UP → not a real loss.
    assert backlink_explorer.should_alert_gated(0, 12, 5) is False


def test_gated_falls_back_when_no_prior_total():
    assert backlink_explorer.should_alert_gated(0, 12, None) is True


def test_gated_below_threshold_never_alerts():
    assert backlink_explorer.should_alert_gated(3, 4, -50) is False


# ---------------------------------------------------------------------------
# is_recent (with explicit now for determinism)
# ---------------------------------------------------------------------------
def test_is_recent_fresh():
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    assert backlink_explorer.is_recent("2026-07-05T00:00:00Z", 21, now=now) is True


def test_is_recent_stale():
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    assert backlink_explorer.is_recent("2026-01-01T00:00:00Z", 21, now=now) is False


def test_is_recent_missing_or_bad():
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    assert backlink_explorer.is_recent(None, 21, now=now) is False
    assert backlink_explorer.is_recent("not-a-date", 21, now=now) is False


# ---------------------------------------------------------------------------
# ensure_client_domain_tracked — guard short-circuits (no DB I/O reached)
# ---------------------------------------------------------------------------
def test_ensure_autotrack_disabled_returns_false(monkeypatch):
    monkeypatch.setattr(backlink_explorer.settings, "backlink_auto_track_client_domain", False)
    assert backlink_explorer.ensure_client_domain_tracked("c1", "https://example.com") is False


def test_ensure_autotrack_no_website_returns_false(monkeypatch):
    monkeypatch.setattr(backlink_explorer.settings, "backlink_auto_track_client_domain", True)
    assert backlink_explorer.ensure_client_domain_tracked("c1", "") is False
    assert backlink_explorer.ensure_client_domain_tracked("c1", None) is False
