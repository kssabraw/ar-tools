"""Unit tests for services.citation_check + routers.citations pure helpers —
fetch classification (fail-open on bot-blocks), the two-strike death rule, and
URL-paste normalization. No network / no DB.
"""

from __future__ import annotations

from routers.citations import normalize_citation_urls
from services import citation_check as cc


# ---------------------------------------------------------------------------
# classify_fetch — only hard failures can kill a citation
# ---------------------------------------------------------------------------
def test_2xx_3xx_is_ok():
    assert cc.classify_fetch(200, False) == "ok"
    assert cc.classify_fetch(301, False) == "ok"


def test_hard_404_410_and_network_errors_fail():
    assert cc.classify_fetch(404, False) == "hard_fail"
    assert cc.classify_fetch(410, False) == "hard_fail"
    assert cc.classify_fetch(None, True) == "hard_fail"


def test_bot_blocks_and_server_trouble_are_fail_open():
    for code in (401, 403, 429, 500, 502, 503):
        assert cc.classify_fetch(code, False) == "blocked", code


# ---------------------------------------------------------------------------
# next_status — two consecutive hard failures before dead
# ---------------------------------------------------------------------------
def test_first_hard_failure_is_unknown_not_dead():
    assert cc.next_status("hard_fail", 0) == ("unknown", 1)


def test_second_hard_failure_is_dead():
    assert cc.next_status("hard_fail", 1) == ("dead", 2)


def test_ok_resets_the_counter():
    assert cc.next_status("ok", 5) == ("live", 0)


def test_blocked_neither_kills_nor_heals():
    assert cc.next_status("blocked", 1) == ("blocked", 1)


# ---------------------------------------------------------------------------
# normalize_citation_urls — the paste parser
# ---------------------------------------------------------------------------
def test_paste_parsing_dedupes_and_schemes():
    raw = """
    https://yelp.com/biz/acme, yellowpages.com/acme
    https://yelp.com/biz/acme/
    not a url
    """
    urls = normalize_citation_urls(raw)
    assert urls == ["https://yelp.com/biz/acme", "https://yellowpages.com/acme"]


def test_paste_parsing_caps():
    raw = "\n".join(f"https://dir{i}.com/acme" for i in range(600))
    assert len(normalize_citation_urls(raw)) == 500
