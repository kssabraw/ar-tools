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
