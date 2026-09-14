"""Unit tests for the DataForSEO fallback rank + source selection.

No network: only the pure helpers are exercised.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx
import pytest

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


# ---------------------------------------------------------------------------
# transient-error classification
# ---------------------------------------------------------------------------
def _http_status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.dataforseo.com/x")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_is_terminal_task_message():
    # Auth / billing messages abort the whole run.
    assert dataforseo_rank.is_terminal_task_message("Authentication failed") is True
    assert dataforseo_rank.is_terminal_task_message("Unauthorized.") is True
    assert dataforseo_rank.is_terminal_task_message("Access denied") is True
    assert dataforseo_rank.is_terminal_task_message("Payment Required") is True
    assert dataforseo_rank.is_terminal_task_message("Insufficient funds on the account") is True
    # Transient / per-keyword messages must NOT be terminal. The regression that
    # aborted a whole live run after 3 keywords: 40101 "Internal SE Server Error".
    assert dataforseo_rank.is_terminal_task_message("Internal SE Server Error.") is False
    assert dataforseo_rank.is_terminal_task_message("You reached the limit") is False
    assert dataforseo_rank.is_terminal_task_message("Invalid Field") is False
    assert dataforseo_rank.is_terminal_task_message("") is False


def test_is_retryable_exc():
    # A non-terminal task error (e.g. the transient "Internal SE Server Error")
    # is retryable; an auth/billing terminal error is not.
    assert dataforseo_rank.is_retryable_exc(
        dataforseo_rank.DataForSeoTaskError(40101, "Internal SE Server Error.")
    ) is True
    assert dataforseo_rank.is_retryable_exc(dataforseo_rank.DataForSeoTaskError(40202, "limit")) is True
    assert dataforseo_rank.is_retryable_exc(
        dataforseo_rank.DataForSeoTerminalError(40200, "Payment Required")
    ) is False
    assert dataforseo_rank.is_retryable_exc(_http_status_error(503)) is True
    assert dataforseo_rank.is_retryable_exc(_http_status_error(429)) is True
    assert dataforseo_rank.is_retryable_exc(_http_status_error(400)) is False
    assert dataforseo_rank.is_retryable_exc(httpx.ConnectError("dropped")) is True
    assert dataforseo_rank.is_retryable_exc(ValueError("nope")) is False


def test_retry_delay_seconds_backoff_and_cap():
    assert dataforseo_rank.retry_delay_seconds(1, 2.0, 20.0) == 2.0
    assert dataforseo_rank.retry_delay_seconds(2, 2.0, 20.0) == 4.0
    assert dataforseo_rank.retry_delay_seconds(3, 2.0, 20.0) == 8.0
    assert dataforseo_rank.retry_delay_seconds(10, 2.0, 20.0) == 20.0  # clamped to cap
    assert dataforseo_rank.retry_delay_seconds(0, 2.0, 20.0) == 2.0    # non-positive -> attempt 1


# ---------------------------------------------------------------------------
# fetch_serp_rank_with_retry
# ---------------------------------------------------------------------------
def test_fetch_retry_recovers_transient_task_error():
    calls = {"n": 0}
    slept: list[float] = []

    async def flaky(keyword, domain, location_code):
        calls["n"] += 1
        if calls["n"] == 1:
            raise dataforseo_rank.DataForSeoTaskError(40202, "you reached the limit")
        return 7

    async def fake_sleep(delay):
        slept.append(delay)

    rank = asyncio.run(
        dataforseo_rank.fetch_serp_rank_with_retry(
            "kw", "acme.com", 2840, max_retries=2, fetch=flaky, sleep=fake_sleep
        )
    )
    assert rank == 7
    assert calls["n"] == 2       # failed once, succeeded on retry
    assert slept == [2.0]        # one backoff before the retry


def test_fetch_retry_terminal_fails_fast():
    calls = {"n": 0}

    async def terminal(keyword, domain, location_code):
        calls["n"] += 1
        raise dataforseo_rank.DataForSeoTerminalError(40200, "insufficient funds")

    async def fake_sleep(delay):  # pragma: no cover - must never be called
        raise AssertionError("terminal error must not sleep/retry")

    with pytest.raises(dataforseo_rank.DataForSeoTerminalError):
        asyncio.run(
            dataforseo_rank.fetch_serp_rank_with_retry(
                "kw", "acme.com", 2840, max_retries=3, fetch=terminal, sleep=fake_sleep
            )
        )
    assert calls["n"] == 1  # no retries on a terminal error


def test_fetch_retry_exhausts_then_reraises():
    calls = {"n": 0}
    slept: list[float] = []

    async def always_transient(keyword, domain, location_code):
        calls["n"] += 1
        raise dataforseo_rank.DataForSeoTaskError(40202, "limit")

    async def fake_sleep(delay):
        slept.append(delay)

    with pytest.raises(dataforseo_rank.DataForSeoTaskError):
        asyncio.run(
            dataforseo_rank.fetch_serp_rank_with_retry(
                "kw", "acme.com", 2840, max_retries=2, fetch=always_transient, sleep=fake_sleep
            )
        )
    assert calls["n"] == 3       # first try + 2 retries
    assert slept == [2.0, 4.0]   # a backoff before each retry


# ---------------------------------------------------------------------------
# build_failure_summary
# ---------------------------------------------------------------------------
def test_build_failure_summary_counts_and_samples():
    failed = [{"keyword": f"kw{i}", "status_code": 40202, "error": "limit"} for i in range(12)]
    failed.append({"keyword": "weird", "status_code": 40501, "error": "invalid field"})
    summary = dataforseo_rank.build_failure_summary(failed, sample=10)
    assert summary["count"] == 13
    assert summary["status_codes"] == {"40202": 12, "40501": 1}  # dominant code first
    assert len(summary["sample"]) == 10                          # bounded
    assert summary["sample"][0] == {"keyword": "kw0", "status_code": 40202}
