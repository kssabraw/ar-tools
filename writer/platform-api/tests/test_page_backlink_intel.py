"""Unit tests for services.page_backlink_intel — money-page selection + the
RD-imbalance rule (Link Building SOP entity-balance health check). Pure only.
"""

from __future__ import annotations

from services import page_backlink_intel as pb


# ---------------------------------------------------------------------------
# money_page_urls
# ---------------------------------------------------------------------------
def test_money_pages_exclude_homepage_offsite_and_dupes():
    urls = pb.money_page_urls(
        "https://acme.com/",
        [
            "https://acme.com/",                     # homepage → excluded
            "https://acme.com/anaheim/plumbing/",
            "https://acme.com/anaheim/plumbing/",    # dupe
            "https://ACME.com/anaheim/plumbing",     # dupe (case/slash)
            "https://competitor.com/page",           # off-domain → excluded
            "https://www.acme.com/drain-cleaning/",  # www variant of own domain → kept
            None,
        ],
    )
    assert urls == [
        "https://acme.com/anaheim/plumbing/",
        "https://www.acme.com/drain-cleaning/",
    ]


def test_money_pages_cap():
    urls = pb.money_page_urls(
        "https://acme.com",
        [f"https://acme.com/p{i}/" for i in range(10)],
        cap=3,
    )
    assert len(urls) == 3


# ---------------------------------------------------------------------------
# detect_imbalance — ratio + noise floor
# ---------------------------------------------------------------------------
def test_imbalance_detected_past_ratio():
    offenders = pb.detect_imbalance(
        40, [{"url": "https://acme.com/p", "referring_domains": 100}]
    )
    assert len(offenders) == 1
    assert offenders[0]["homepage_rd"] == 40


def test_no_imbalance_within_ratio():
    assert pb.detect_imbalance(40, [{"url": "u", "referring_domains": 55}]) == []


def test_noise_floor_blocks_tiny_pages():
    # 15 RD > 5 × 1.5 but under the 20-RD floor → not an offender
    assert pb.detect_imbalance(5, [{"url": "u", "referring_domains": 15}]) == []


def test_missing_homepage_read_detects_nothing():
    assert pb.detect_imbalance(None, [{"url": "u", "referring_domains": 500}]) == []


# ---------------------------------------------------------------------------
# build_page_view — latest-capture pages + per-URL history shaping
# ---------------------------------------------------------------------------
def test_build_page_view_empty():
    assert pb.build_page_view([]) == {"latest_captured_at": None, "pages": [], "history": {}}


def test_build_page_view_latest_ordering_and_history():
    rows = [
        # older capture
        {"url": "https://a.com/", "is_homepage": True, "referring_domains": 100, "backlinks": 200, "url_rating": 30, "captured_at": "2026-06-01T00:00:00+00:00"},
        {"url": "https://a.com/svc", "is_homepage": False, "referring_domains": 10, "backlinks": 12, "url_rating": 8, "captured_at": "2026-06-01T00:00:00+00:00"},
        # latest capture — inner page out-ranks homepage on RD
        {"url": "https://a.com/", "is_homepage": True, "referring_domains": 110, "backlinks": 210, "url_rating": 31, "captured_at": "2026-07-01T00:00:00+00:00"},
        {"url": "https://a.com/svc", "is_homepage": False, "referring_domains": 40, "backlinks": 44, "url_rating": 15, "captured_at": "2026-07-01T00:00:00+00:00"},
        {"url": "https://a.com/loc", "is_homepage": False, "referring_domains": 200, "backlinks": 260, "url_rating": 22, "captured_at": "2026-07-01T00:00:00+00:00"},
    ]
    view = pb.build_page_view(rows)
    assert view["latest_captured_at"] == "2026-07-01T00:00:00+00:00"
    # latest capture only, homepage first then RD desc
    assert [p["url"] for p in view["pages"]] == ["https://a.com/", "https://a.com/loc", "https://a.com/svc"]
    # per-URL history is ascending and spans both captures for the recurring page
    svc_hist = view["history"]["https://a.com/svc"]
    assert [h["referring_domains"] for h in svc_hist] == [10, 40]
    # a page seen only in the latest capture has a single-point history
    assert len(view["history"]["https://a.com/loc"]) == 1


def test_build_page_view_ignores_rows_without_capture_ts():
    view = pb.build_page_view([{"url": "u", "referring_domains": 5, "captured_at": None}])
    assert view == {"latest_captured_at": None, "pages": [], "history": {}}
