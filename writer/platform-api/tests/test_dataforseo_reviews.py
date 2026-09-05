"""Tests for the corrected DataForSEO review instrument (outreach ISSUES I-059).

The parsing tests matter, but the ERROR tests are the point of the module. The bug being fixed
was not a parser that read the wrong field — it was a failure path that returned `[]`, which every
caller then read as the sentence "this business has no reviews". So the assertions that carry the
most weight here are the ones proving a failure can no longer be mistaken for data.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import dataforseo_reviews as dfr  # noqa: E402
from services.dataforseo_reviews import ReviewFetchError  # noqa: E402


def _envelope(result, status_code=20000):
    return {"tasks": [{"id": "task-1", "status_code": status_code, "result": result}]}


# --- the failure semantics --------------------------------------------------
def test_task_level_error_raises_instead_of_returning_no_reviews():
    """A 200 carrying a failed task must not become an empty review list.

    DataForSEO reports per-task status inside a 200, so `raise_for_status()` alone never sees
    this. Returning [] here is the exact shape of the original defect.
    """
    body = _envelope(None, status_code=40501)
    with pytest.raises(ReviewFetchError) as exc:
        dfr.parse_reviews(body)
    assert "40501" in str(exc.value)


def test_missing_result_block_raises_and_is_not_zero_reviews():
    with pytest.raises(ReviewFetchError):
        dfr.parse_reviews(_envelope([]))


def test_no_tasks_raises():
    with pytest.raises(ReviewFetchError):
        dfr.parse_reviews({"tasks": []})


def test_http_404_raises_and_names_the_status():
    """The 404 that started all this. It used to be swallowed into 'no reviews'."""
    request = httpx.Request("POST", dfr.REVIEWS_TASK_POST_ENDPOINT)
    response = httpx.Response(404, request=request)
    client = MagicMock()
    client.post = AsyncMock(side_effect=httpx.HTTPStatusError("404", request=request, response=response))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(dfr, "credentials_present", return_value=True), patch.object(
        dfr.httpx, "AsyncClient", return_value=client
    ):
        with pytest.raises(ReviewFetchError) as exc:
            asyncio.run(dfr.fetch_reviews("place-1", depth=10))
    assert "404" in str(exc.value)


def test_transport_error_raises():
    request = httpx.Request("POST", dfr.REVIEWS_TASK_POST_ENDPOINT)
    client = MagicMock()
    client.post = AsyncMock(side_effect=httpx.ConnectError("boom", request=request))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(dfr, "credentials_present", return_value=True), patch.object(
        dfr.httpx, "AsyncClient", return_value=client
    ):
        with pytest.raises(ReviewFetchError):
            asyncio.run(dfr.fetch_reviews("place-1", depth=10))


def test_missing_credentials_raises_rather_than_reporting_no_reviews():
    with patch.object(dfr, "credentials_present", return_value=False):
        with pytest.raises(ReviewFetchError):
            asyncio.run(dfr.fetch_reviews("place-1", depth=10))
        with pytest.raises(ReviewFetchError):
            asyncio.run(dfr.fetch_business_rating("place-1"))


def test_dead_endpoint_is_not_used_by_any_live_path():
    """Named for the record, never posted to."""
    assert dfr.REVIEWS_LIVE_ENDPOINT_DOES_NOT_EXIST.endswith("/reviews/live")
    assert dfr.REVIEWS_TASK_POST_ENDPOINT.endswith("/reviews/task_post")
    assert dfr.REVIEWS_LIVE_ENDPOINT_DOES_NOT_EXIST != dfr.REVIEWS_TASK_POST_ENDPOINT


# --- an genuinely empty answer is still allowed through ---------------------
def test_provider_asserting_an_empty_item_list_returns_empty():
    """The provider IS allowed to say 'no reviews' — only failures may not say it for it."""
    assert dfr.parse_reviews(_envelope([{"items": []}])) == []


# --- parsing ----------------------------------------------------------------
def test_parse_reviews_maps_shape_and_keeps_all_ratings():
    body = _envelope(
        [
            {
                "items": [
                    {
                        "profile_name": "Ann",
                        "review_text": "great",
                        "review_rating": {"value": 5},
                        "timestamp": "2026-01-02T10:00:00+00:00",
                    },
                    {
                        "author_title": "Bob",
                        "review_text": "awful",
                        "review_rating": {"value": 1},
                        "review_datetime_utc": "2026-01-03 11:00:00",
                    },
                ]
            }
        ]
    )
    reviews = dfr.parse_reviews(body)
    assert [r["rating"] for r in reviews] == [5.0, 1.0]
    assert [r["date"] for r in reviews] == ["2026-01-02", "2026-01-03"]
    assert [r["reviewer"] for r in reviews] == ["Ann", "Bob"]


def test_parse_reviews_does_not_filter_low_ratings():
    """Filtering is caller policy. A fetch layer that dropped 1★ reviews would make the
    distribution and negative counts silently WRONG rather than empty — harder to notice."""
    body = _envelope([{"items": [{"review_text": "bad", "review_rating": {"value": 1}}]}])
    assert len(dfr.parse_reviews(body)) == 1


def test_parse_business_rating_keeps_zero_and_missing_apart():
    zero = _envelope([{"items": [{"rating": {"value": 0, "votes_count": 0}}]}])
    assert dfr.parse_business_rating(zero) == (0.0, 0)

    missing = _envelope([{"items": [{"rating": {"value": 4.5}}]}])
    rating, count = dfr.parse_business_rating(missing)
    assert rating == 4.5
    assert count is None, "an absent count must not be reported as zero"


def test_parse_business_rating_reads_flat_spellings():
    body = _envelope([{"items": [{"reviews_count": 12}]}])
    assert dfr.parse_business_rating(body) == (None, 12)


def test_task_is_ready_distinguishes_in_progress_from_empty():
    assert dfr.task_is_ready(_envelope([{"items": []}])) is True
    assert dfr.task_is_ready(_envelope(None, status_code=20100)) is False
    assert dfr.task_is_ready({"tasks": []}) is False


def test_parse_task_id():
    assert dfr.parse_task_id(_envelope(None, status_code=20100)) == "task-1"
    with pytest.raises(ReviewFetchError):
        dfr.parse_task_id({"tasks": [{"status_code": 20100}]})


def test_parse_reviews_reads_the_live_rating_dict_shape():
    # The live task_get envelope carries the per-review rating under `rating`
    # as {"rating_type": "Max5", "value": 5, ...} (not `review_rating`).
    from services import dataforseo_reviews as dr
    body = _envelope([{"items": [
        {"review_text": "great", "rating": {"rating_type": "Max5", "value": 5, "rating_max": 5}, "timestamp": "2026-07-12 00:00:00 +00:00"},
        {"review_text": "ok", "rating": 4, "review_datetime_utc": "2026-01-01 10:00:00"},
        {"review_text": "meh", "rating": {"value": None}},
        {"review_text": "old", "review_rating": {"value": 3}},
    ]}])
    reviews = dr.parse_reviews(body)
    assert [r["rating"] for r in reviews] == [5.0, 4.0, None, 3.0]
    assert reviews[0]["date"] == "2026-07-12" and reviews[1]["date"] == "2026-01-01"
