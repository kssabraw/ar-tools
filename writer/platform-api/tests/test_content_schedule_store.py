"""Unit tests for services.content_schedule_store — the pure planning helpers
(normalize / plan / estimate) behind the suite Content Scheduler.

No network / no DB: normalize_items, plan_item_datetimes, and estimate_batch are
pure; the DB helpers are covered by integration testing.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from services import content_schedule_store as store
from services.content_schedule_store import BatchItemInput
from fanout.writer.schedule_planner import ScheduleError

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


# ── normalize_items ──────────────────────────────────────────────────────────


def test_normalize_trims_drops_blank_and_caps():
    raw = [
        {"keyword": "  plumber newtown "},
        {"keyword": ""},
        {"keyword": "   "},
        {"keyword": "roof repair bondi"},
        {"keyword": "x" * 201},                 # over length
    ]
    items, skipped = store.normalize_items(raw, max_items=10)
    assert [i.keyword for i in items] == ["plumber newtown", "roof repair bondi"]
    assert skipped == 3


def test_normalize_dedupes_on_keyword_and_location():
    raw = [
        {"keyword": "Plumber", "location": "Newtown"},
        {"keyword": "plumber", "location": "newtown"},   # dupe (case-insensitive)
        {"keyword": "plumber", "location": "Bondi"},      # distinct place -> kept
        {"keyword": "plumber"},                           # distinct (no location) -> kept
    ]
    items, skipped = store.normalize_items(raw, max_items=10)
    assert len(items) == 3
    assert skipped == 1


def test_normalize_cap_truncates_but_not_counted_as_skipped():
    raw = [{"keyword": f"kw {i}"} for i in range(5)]
    items, skipped = store.normalize_items(raw, max_items=3)
    assert len(items) == 3
    assert skipped == 0                          # the over-cap remainder isn't "skipped"


def test_normalize_cleans_services_per_row():
    items, _ = store.normalize_items(
        [{"keyword": "plumber austin",
          "services": [" drains ", "Drains", "", "hot water"]}],
        max_items=5,
    )
    assert items[0].services == ["drains", "hot water"]


def test_normalize_accepts_dataclass_inputs():
    items, skipped = store.normalize_items(
        [BatchItemInput(keyword="  hvac  ", services=["repair"])], max_items=5
    )
    assert items[0].keyword == "hvac"
    assert items[0].services == ["repair"]
    assert skipped == 0


# ── plan_item_datetimes ──────────────────────────────────────────────────────


def test_plan_now_releases_everything_immediately():
    dts = store.plan_item_datetimes(3, mode="now", now_utc=NOW)
    assert dts == [NOW, NOW, NOW]


def test_plan_all_at_once_is_now():
    dts = store.plan_item_datetimes(2, mode="all_at_once", now_utc=NOW)
    assert dts == [NOW, NOW]


def test_plan_drip_buckets_by_per_day():
    # 5 items, 2/day -> days 0,0,1,1,2 from the start date at 09:00 UTC.
    dts = store.plan_item_datetimes(
        5, mode="drip", per_day=2, start_date=date(2026, 7, 11),
        time_of_day=time(9, 0), tz_name="UTC", now_utc=NOW,
    )
    days = [d.date() for d in dts]
    assert days == [date(2026, 7, 11), date(2026, 7, 11),
                    date(2026, 7, 12), date(2026, 7, 12), date(2026, 7, 13)]
    assert all(d.timetz() == time(9, 0, tzinfo=timezone.utc) for d in dts)


def test_plan_weekly_multi_day_orders_chronologically():
    # Tue(1)+Thu(3), 1/slot, starting Mon 2026-07-13 -> Tue 14, Thu 16, Tue 21...
    dts = store.plan_item_datetimes(
        3, mode="weekly", per_day=1, weekdays=[1, 3],
        start_date=date(2026, 7, 13), tz_name="UTC", now_utc=NOW,
    )
    assert [d.date() for d in dts] == [date(2026, 7, 14), date(2026, 7, 16),
                                       date(2026, 7, 21)]


def test_plan_empty_is_empty():
    assert store.plan_item_datetimes(0, mode="drip", per_day=1) == []


def test_plan_bad_cadence_raises():
    with pytest.raises(ScheduleError):
        store.plan_item_datetimes(3, mode="drip", per_day=0, now_utc=NOW)


# ── estimate_batch ───────────────────────────────────────────────────────────


def test_estimate_uses_per_content_type_cost():
    blog = store.estimate_batch(10, "blog_post", "now", now_utc=NOW)
    local = store.estimate_batch(10, "local_seo_page", "now", now_utc=NOW)
    assert blog["cost_estimate_usd"] == round(10 * store.DEFAULT_COST_PER_TYPE["blog_post"], 2)
    assert local["cost_estimate_usd"] == round(10 * store.DEFAULT_COST_PER_TYPE["local_seo_page"], 2)
    assert local["cost_estimate_usd"] != blog["cost_estimate_usd"]


def test_estimate_custom_cost_map():
    est = store.estimate_batch(4, "service_page", "now",
                               cost_per_type={"service_page": 1.25}, now_utc=NOW)
    assert est["cost_estimate_usd"] == 5.0


def test_estimate_reports_finish_date_for_scheduled():
    est = store.estimate_batch(
        4, "blog_post", "drip", per_day=1, start_date=date(2026, 7, 11),
        tz_name="UTC", now_utc=NOW,
    )
    assert est["finish_date"] == "2026-07-14"    # 4 items, 1/day -> days 11..14


def test_estimate_now_has_no_finish_date():
    est = store.estimate_batch(4, "blog_post", "now", now_utc=NOW)
    assert "finish_date" not in est
