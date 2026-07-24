"""Unit tests for rank status + summary computation (Organic Rank Tracker M3)."""

from __future__ import annotations

from datetime import date, timedelta

from services import rank_materialize, rank_status
from routers.rank import _split_keywords


def _series(positions, end=date(2026, 6, 22)):
    """Build (date, position) points ending at `end`, one per day ascending."""
    n = len(positions)
    return [(end - timedelta(days=n - 1 - i), positions[i]) for i in range(n)]


# ---------------------------------------------------------------------------
# compute_status
# ---------------------------------------------------------------------------
def test_status_no_data_when_all_null():
    assert rank_status.compute_status(_series([None] * 20)) == "no_data"


def test_status_deindex_risk_sustained_null_after_baseline():
    # 20 days of solid presence, then 8 consecutive null days.
    series = _series([10] * 20 + [None] * 8)
    assert rank_status.compute_status(series) == "deindex_risk"


def test_status_not_deindex_when_gap_too_short():
    series = _series([10] * 20 + [None] * 3)
    assert rank_status.compute_status(series) != "deindex_risk"


def test_status_not_deindex_without_baseline():
    # Only 2 non-null days of presence then a long gap = anonymization flicker.
    series = _series([12, 12] + [None] * 10)
    assert rank_status.compute_status(series) == "no_data" or rank_status.compute_status(series) == "stable"


def test_status_climbing():
    # Positions improving from ~20 down to ~5 (lower is better).
    series = _series([20, 19, 18, 16, 14, 12, 10, 8, 6, 5])
    assert rank_status.compute_status(series) == "climbing"


def test_status_dropping():
    series = _series([5, 6, 8, 10, 12, 14, 16, 18, 20, 22])
    assert rank_status.compute_status(series) == "dropping"


def test_status_stable():
    series = _series([10, 11, 10, 9, 10, 11, 10, 10, 9, 10])
    assert rank_status.compute_status(series) == "stable"


def test_status_volatile_swing_and_return():
    # Big swing (3 → 20 → 4) that lands back near the baseline.
    series = _series([4, 4, 5, 18, 20, 19, 6, 5, 4, 4])
    assert rank_status.compute_status(series) == "volatile"


def test_status_trend_called_on_two_checks():
    # Only two ranked checks, but a real 24-position climb — must not default to
    # "stable" just for lack of history (the DataForSEO sparse-data case).
    assert rank_status.compute_status(_series([53, 29])) == "climbing"
    assert rank_status.compute_status(_series([29, 53])) == "dropping"


def test_status_small_move_within_threshold_is_stable():
    # Net move within ±TREND_THRESHOLD stays stable even though the arrow shows
    # a (small) direction — the ±3 band is the label's source of truth.
    assert rank_status.compute_status(_series([41, 40])) == "stable"   # +1
    assert rank_status.compute_status(_series([40, 43])) == "stable"   # -3 (boundary)


def test_status_single_check_is_stable():
    assert rank_status.compute_status(_series([12])) == "stable"


# ---------------------------------------------------------------------------
# compute_trend — the single source of truth shared by the arrow + the status
# band. It windows to 90 days and is source-aware, so arrow and label agree.
# ---------------------------------------------------------------------------
from datetime import date, timedelta  # noqa: E402

_TODAY = date(2026, 7, 24)


def _df_rows(points):
    """DataForSEO metric rows: points = [(days_ago, tracked_rank)]."""
    return [
        {"date": (_TODAY - timedelta(days=da)).isoformat(),
         "gsc_position": None, "tracked_rank": rk}
        for da, rk in points
    ]


def test_compute_trend_dataforseo_climb():
    direction, improvement, band = rank_status.compute_trend(
        _df_rows([(40, 35), (5, 29)]), _TODAY, 14
    )
    assert (direction, band) == ("up", "climbing")
    assert improvement == 6


def test_compute_trend_small_move_is_stable_but_arrow_tilts():
    # +1 net: label stays Stable (within ±3) but the arrow still reads "up".
    direction, _, band = rank_status.compute_trend(_df_rows([(40, 30), (5, 29)]), _TODAY, 14)
    assert direction == "up"
    assert band == "stable"


def test_compute_trend_ignores_points_older_than_window():
    # A check 100 days ago must NOT count — only one ranked point sits inside the
    # 90-day window, so there's no movement to measure (regression: the old
    # 120-day materialize window said "climbing" while the 90-day arrow was flat).
    direction, improvement, band = rank_status.compute_trend(
        _df_rows([(100, 53), (5, 29)]), _TODAY, 14
    )
    assert direction is None
    assert improvement is None
    assert band == "stable"


def test_compute_trend_matches_summary_direction():
    # The arrow (summary["direction"]) is derived from compute_trend, so they
    # must never disagree.
    rows = _df_rows([(40, 20), (5, 30)])  # dropped 10
    direction, _, band = rank_status.compute_trend(rows, _TODAY, 14)
    summary = rank_status.compute_keyword_summary(rows, _TODAY, 14)
    assert summary["direction"] == direction == "down"
    assert band == "dropping"


# ---------------------------------------------------------------------------
# rolling_average / compute_keyword_summary
# ---------------------------------------------------------------------------
def test_rolling_average_ignores_nulls_and_old():
    today = date(2026, 6, 22)
    series = _series([None, 10.0, 20.0], end=today)  # last 3 days
    assert rank_status.rolling_average(series, 7, today) == 15.0


def test_rolling_average_none_when_no_data():
    today = date(2026, 6, 22)
    assert rank_status.rolling_average(_series([None, None]), 30, today) is None


def test_compute_keyword_summary_shape_and_direction():
    today = date(2026, 6, 22)
    rows = []
    # 30 days: positions improving from 12 to 4, steady clicks/impressions.
    for i in range(30):
        rows.append(
            {
                "date": (today - timedelta(days=29 - i)).isoformat(),
                "clicks": 2,
                "impressions": 40,
                "ctr": 0.05,
                "gsc_position": 12 - (i * 8 / 29),
                "tracked_rank": None,
            }
        )
    summary = rank_status.compute_keyword_summary(rows, today)
    assert summary["clicks_30d"] == 60
    assert summary["impressions_30d"] == 1200
    assert summary["ctr_30d"] == 0.05
    assert len(summary["sparkline"]) == 30
    # Recent (7d) better than the 90d average → improving → "up".
    assert summary["direction"] == "up"
    assert summary["today_rank"] is None


def test_summary_today_rank_picks_latest_non_null():
    today = date(2026, 6, 22)
    rows = [
        {"date": "2026-06-20", "gsc_position": 5, "tracked_rank": 7, "clicks": 0, "impressions": 0, "ctr": 0},
        {"date": "2026-06-21", "gsc_position": 5, "tracked_rank": 4, "clicks": 0, "impressions": 0, "ctr": 0},
    ]
    assert rank_status.compute_keyword_summary(rows, today)["today_rank"] == 4


# ---------------------------------------------------------------------------
# aggregate_hero
# ---------------------------------------------------------------------------
def test_aggregate_hero_means_and_sums_per_day():
    today = date(2026, 6, 22)
    rows = [
        {"date": "2026-06-21", "gsc_position": 10, "clicks": 1, "impressions": 10},
        {"date": "2026-06-21", "gsc_position": 20, "clicks": 2, "impressions": 20},
        {"date": "2026-06-22", "gsc_position": None, "clicks": 0, "impressions": 5},
    ]
    hero = rank_status.aggregate_hero(rows, today, 90)
    assert hero[0] == {"date": "2026-06-21", "avg_position": 15.0, "clicks": 3, "impressions": 30}
    # All-null day still appears, with avg_position None.
    assert hero[1]["avg_position"] is None
    assert hero[1]["impressions"] == 5


# ---------------------------------------------------------------------------
# materialize axis building (pure)
# ---------------------------------------------------------------------------
def test_date_range_inclusive():
    days = rank_materialize.date_range(date(2026, 6, 20), date(2026, 6, 22))
    assert days == [date(2026, 6, 20), date(2026, 6, 21), date(2026, 6, 22)]


def test_build_keyword_axis_fills_gaps_with_null_position():
    dates = rank_materialize.date_range(date(2026, 6, 20), date(2026, 6, 22))
    index = rank_materialize.index_gsc_rows(
        [{"query": "Best HVAC", "date": "2026-06-21", "clicks": 3, "impressions": 50, "ctr": 0.06, "position": 7.2}]
    )
    rows = rank_materialize.build_keyword_axis("kw-1", "best hvac", dates, index)
    assert len(rows) == 3
    # Day with data (case-insensitive match)
    assert rows[1]["gsc_position"] == 7.2 and rows[1]["clicks"] == 3
    # Absent days → NULL position, zero metrics (stored gap)
    assert rows[0]["gsc_position"] is None and rows[0]["impressions"] == 0
    assert rows[2]["gsc_position"] is None


# ---------------------------------------------------------------------------
# keyword splitting
# ---------------------------------------------------------------------------
def test_split_keywords_handles_newlines_commas_dupes_blanks():
    raw = ["hvac repair\nac install, hvac repair", "  ", "furnace tune-up"]
    assert _split_keywords(raw) == ["hvac repair", "ac install", "furnace tune-up"]
