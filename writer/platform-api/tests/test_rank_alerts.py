"""Unit tests for rank-drop alert detection (pure logic only, no I/O)."""

from __future__ import annotations

from datetime import date, timedelta

from services import rank_alerts

TODAY = date(2026, 6, 22)


def _gsc(spec):
    """Rows from [(day_offset, gsc_position), ...]; offset 0 = today."""
    return [
        {"date": (TODAY - timedelta(days=o)).isoformat(), "gsc_position": p, "tracked_rank": None}
        for o, p in spec
    ]


def _df(spec):
    """Rows from [(day_offset, tracked_rank), ...]."""
    return [
        {"date": (TODAY - timedelta(days=o)).isoformat(), "gsc_position": None, "tracked_rank": p}
        for o, p in spec
    ]


def _types(signals):
    return {s.alert_type for s in signals}


# ---------------------------------------------------------------------------
# weekly_drop + page_one_exit (GSC)
# ---------------------------------------------------------------------------
def test_weekly_drop_and_page_one_exit_gsc():
    # Prior week (offsets 7–13) at position 8; last week (0–6) at 16.
    rows = _gsc([(o, 8) for o in range(7, 14)] + [(o, 16) for o in range(0, 7)])
    signals = rank_alerts.detect_alerts("emergency plumber", rows, "gsc", "stable", TODAY)
    assert _types(signals) == {"weekly_drop", "page_one_exit"}
    wk = next(s for s in signals if s.alert_type == "weekly_drop")
    assert wk.from_position == 8 and wk.to_position == 16 and wk.delta == 8
    assert wk.source == "gsc"


def test_no_weekly_drop_when_baseline_too_deep():
    # Baseline 18 (>15) → no weekly_drop; 18 is already off page 1 → no exit.
    rows = _gsc([(o, 18) for o in range(7, 14)] + [(o, 25) for o in range(0, 7)])
    signals = rank_alerts.detect_alerts("kw", rows, "gsc", "stable", TODAY)
    assert "weekly_drop" not in _types(signals)
    assert "page_one_exit" not in _types(signals)


def test_page_one_exit_only_when_drop_under_threshold():
    # 6 → 11: only a 5-spot slide (no weekly_drop) but crosses off page 1.
    rows = _gsc([(o, 6) for o in range(7, 14)] + [(o, 11) for o in range(0, 7)])
    signals = rank_alerts.detect_alerts("kw", rows, "gsc", "stable", TODAY)
    assert _types(signals) == {"page_one_exit"}


# ---------------------------------------------------------------------------
# thirty_day_drop (GSC) + top-20 floor
# ---------------------------------------------------------------------------
def test_thirty_day_drop_gsc():
    # Month-ago window (30–36) at 12; current week (0–6) at 20. No prior-week
    # data, so the weekly rules stay silent and only the 30-day rule fires.
    rows = _gsc([(o, 12) for o in range(30, 37)] + [(o, 20) for o in range(0, 7)])
    signals = rank_alerts.detect_alerts("kw", rows, "gsc", "stable", TODAY)
    assert _types(signals) == {"thirty_day_drop"}
    s = signals[0]
    assert s.from_position == 12 and s.to_position == 20 and s.delta == 8


def test_thirty_day_drop_floor_excludes_deep_keywords():
    # Was 25 (outside top 20) → 33: a real 8-spot drop, but below the floor.
    rows = _gsc([(o, 25) for o in range(30, 37)] + [(o, 33) for o in range(0, 7)])
    signals = rank_alerts.detect_alerts("kw", rows, "gsc", "stable", TODAY)
    assert "thirty_day_drop" not in _types(signals)


# ---------------------------------------------------------------------------
# deindexed (from the existing status signal)
# ---------------------------------------------------------------------------
def test_deindexed_from_status():
    rows = _gsc([(o, 4) for o in range(20, 27)])  # established then gone
    signals = rank_alerts.detect_alerts("kw", rows, "gsc", "deindex_risk", TODAY)
    assert "deindexed" in _types(signals)
    d = next(s for s in signals if s.alert_type == "deindexed")
    assert d.source == "gsc"


# ---------------------------------------------------------------------------
# DataForSEO weekly path
# ---------------------------------------------------------------------------
def test_dataforseo_weekly_drop():
    # Weekly points: today=18, a week ago=5, two weeks ago=4.
    rows = _df([(0, 18), (7, 5), (14, 4)])
    signals = rank_alerts.detect_alerts("kw", rows, "dataforseo", "stable", TODAY)
    assert _types(signals) == {"weekly_drop", "page_one_exit"}
    wk = next(s for s in signals if s.alert_type == "weekly_drop")
    assert wk.from_position == 5 and wk.to_position == 18 and wk.source == "dataforseo"


# ---------------------------------------------------------------------------
# negative / no-data cases
# ---------------------------------------------------------------------------
def test_no_alerts_when_stable_gsc():
    rows = _gsc([(o, 5) for o in range(0, 40)])
    signals = rank_alerts.detect_alerts("kw", rows, "gsc", "stable", TODAY)
    assert signals == []


def test_no_alerts_when_no_data():
    rows = _gsc([(o, None) for o in range(0, 10)])
    signals = rank_alerts.detect_alerts("kw", rows, "none", "no_data", TODAY)
    assert signals == []
