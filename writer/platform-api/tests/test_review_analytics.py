"""Unit tests for review analytics pure helpers (no network)."""

from __future__ import annotations

from datetime import date

from services import review_analytics

TODAY = date(2026, 6, 29)


def _rev(rating, d):
    return {"rating": rating, "date": d}


def test_analyze_reviews_distribution_velocity_negatives():
    reviews = [
        _rev(5, "2026-06-01"), _rev(5, "2026-05-01"), _rev(4, "2026-04-01"),
        _rev(1, "2026-06-15"),                         # recent negative (<=2, within 90d)
        _rev(2, "2024-01-01"),                         # old negative — not "recent", not in velocity year
    ]
    a = review_analytics.analyze_reviews(reviews, TODAY)
    assert a["count"] == 5
    assert a["rating_distribution"]["5"] == 2 and a["rating_distribution"]["1"] == 1
    assert a["recent_negatives"] == 1                  # only the 2026-06-15 one-star
    assert a["velocity_per_month"] == round(4 / 12, 1)  # 4 reviews within the last year
    assert a["last_review_date"] == "2026-06-15"
    assert a["avg_rating"] == round((5 + 5 + 4 + 1 + 2) / 5, 2)


def test_analyze_reviews_empty():
    a = review_analytics.analyze_reviews([], TODAY)
    assert a["count"] == 0 and a["avg_rating"] is None and a["velocity_per_month"] == 0


def test_compare_velocity_behind_median():
    client = {"velocity_per_month": 1.0, "avg_rating": 4.5}
    competitors = [
        {"velocity_per_month": 3.0, "avg_rating": 4.6},
        {"velocity_per_month": 5.0, "avg_rating": 4.8},
        {"velocity_per_month": 4.0, "avg_rating": 4.7},
    ]
    cmp = review_analytics.compare(client, competitors)
    assert cmp["competitor_median_velocity"] == 4.0
    assert cmp["velocity_behind"] == 3.0       # 4.0 − 1.0


def test_compare_not_behind_when_client_leads():
    client = {"velocity_per_month": 9.0, "avg_rating": 4.9}
    competitors = [{"velocity_per_month": 3.0, "avg_rating": 4.5}]
    cmp = review_analytics.compare(client, competitors)
    assert cmp["velocity_behind"] is None


def test_detect_review_gap_on_velocity_or_negatives():
    cmp = {"competitor_median_velocity": 4.0, "velocity_behind": 3.0}
    client = {"velocity_per_month": 1.0, "recent_negatives": 0}
    gap = review_analytics.detect_review_gap(cmp, client, min_behind=2.0)
    assert gap is not None and gap["behind"] == 3.0

    # Below the velocity threshold AND no negatives → no signal.
    cmp2 = {"competitor_median_velocity": 2.0, "velocity_behind": 1.0}
    assert review_analytics.detect_review_gap(cmp2, {"recent_negatives": 0}, 2.0) is None

    # Recent negatives alone trigger it even if velocity is fine.
    assert review_analytics.detect_review_gap(
        {"velocity_behind": None}, {"velocity_per_month": 8, "recent_negatives": 2}, 2.0
    ) is not None


# --- fail fast before the provider contract is proved ---------------------------------------
#
# The task_post/task_get envelope has never been confirmed against a live paid task (I-059): the
# probe established the lifecycle exists, not what it returns. DataForSEO bills on task
# acceptance, so a wrong envelope must cost ONE task, not one per place — every place would fail
# identically and each would be billed. Owner ruling 2026-08-03: run the first real job small and
# fail loud, rather than building a synthetic test that can only confirm the shape we assumed.

import asyncio as _asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock as _AsyncMock, patch as _patch  # noqa: E402

from services import review_analytics as _ra  # noqa: E402
from services.dataforseo_reviews import ReviewFetchError as _ReviewFetchError  # noqa: E402


class _FakeSupabase:
    def __init__(self, place):
        self._place = place

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return SimpleNamespace(data=[{"gbp_place_id": self._place}])


def _run_fetch_and_store(fetch_side_effect, competitors):
    with _patch.object(_ra, "get_supabase", return_value=_FakeSupabase("client-place")), _patch.object(
        _ra.competitor_gbp, "latest_profiles", return_value=competitors
    ), _patch.object(
        _ra, "fetch_reviews_full", _AsyncMock(side_effect=fetch_side_effect)
    ) as fetch, _patch.object(_ra, "_store", lambda *a, **k: len(a[3])):
        result = _asyncio.run(_ra.fetch_and_store("client-1"))
    return result, fetch


def test_a_failure_before_any_success_aborts_the_run():
    """One billed task, not nine. The first failure is almost certainly systemic."""
    competitors = [{"place_id": f"c{i}"} for i in range(8)]
    result, fetch = _run_fetch_and_store(_ReviewFetchError("HTTP 404 from task_get"), competitors)

    assert fetch.await_count == 1, "must stop after the first failure, not try every place"
    assert result["aborted"] is not None
    assert "404" in result["aborted"]
    assert result["failed"] == 1


def test_a_failure_AFTER_a_success_is_skipped_not_aborted():
    """Once one lookup works the contract is proved, so later failures are per-place problems
    (a delisted listing, a transient timeout) and must not stop the run."""
    competitors = [{"place_id": f"c{i}"} for i in range(3)]
    side_effect = [
        [{"rating": 5.0, "date": "2026-01-01", "text": "x", "reviewer": "a"}],  # client: succeeds
        _ReviewFetchError("transient"),                                        # c0: fails
        [{"rating": 4.0, "date": "2026-01-02", "text": "y", "reviewer": "b"}],  # c1: succeeds
        [{"rating": 3.0, "date": "2026-01-03", "text": "z", "reviewer": "c"}],  # c2: succeeds
    ]
    result, fetch = _run_fetch_and_store(side_effect, competitors)

    assert fetch.await_count == 4, "must continue past a failure once the shape is proved"
    assert result["aborted"] is None
    assert result["failed"] == 1


def test_a_clean_run_reports_no_failures():
    competitors = [{"place_id": "c0"}]
    reviews = [{"rating": 5.0, "date": "2026-01-01", "text": "x", "reviewer": "a"}]
    result, fetch = _run_fetch_and_store([reviews, reviews], competitors)

    assert fetch.await_count == 2
    assert result["aborted"] is None
    assert result["failed"] == 0
    assert result["failures"] == []
