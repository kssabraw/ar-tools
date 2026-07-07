"""Unit tests for services.trend_watch — pure detection + seasonality."""

from __future__ import annotations

from datetime import date

from services import trend_watch as tw


# ---------------------------------------------------------------------------
# algo-update window detection
# ---------------------------------------------------------------------------
def _alerts(spec: dict[str, list[str]]) -> list[dict]:
    """{iso_date: [client_ids]} → alert rows."""
    return [
        {"client_id": cid, "created_at": d}
        for d, cids in spec.items() for cid in cids
    ]


def test_detects_cross_client_window():
    alerts = _alerts({
        "2026-07-01": ["a", "b"],
        "2026-07-02": ["c"],
        "2026-07-05": ["d"],   # a straggler outside the window — not part of the event
    })
    # 6-client book: bar = max(min_clients=3, ceil(0.4×6)=3) = 3.
    out = tw.detect_algo_windows(alerts, total_clients=6, min_clients=3, min_share=0.4, window_days=3)
    assert len(out) == 1
    w = out[0]
    assert w["window_start"] == date(2026, 7, 1)
    assert set(w["client_ids"]) == {"a", "b", "c"}
    assert w["drop_count"] == 3


def test_single_client_noise_never_fires():
    # One client opening many drops is that client's problem, not an update.
    alerts = _alerts({"2026-07-01": ["a", "a", "a"], "2026-07-02": ["a", "a"]})
    assert tw.detect_algo_windows(alerts, 8, 3, 0.4, 3) == []


def test_share_bar_scales_with_portfolio():
    # 3 clients dropping clears min_clients but not 40% of a 20-client book.
    alerts = _alerts({"2026-07-01": ["a", "b", "c"]})
    assert tw.detect_algo_windows(alerts, 20, 3, 0.4, 3) == []
    # …but does clear it for a 6-client book (bar = max(3, ceil(2.4)) = 3).
    assert len(tw.detect_algo_windows(alerts, 6, 3, 0.4, 3)) == 1


def test_overlapping_slides_report_once():
    # A 4-day rolling event must yield one window, not one per slide.
    alerts = _alerts({
        "2026-07-01": ["a", "b", "c"],
        "2026-07-02": ["d", "e"],
        "2026-07-03": ["f"],
        "2026-07-04": ["g", "h", "i"],
    })
    out = tw.detect_algo_windows(alerts, 10, 3, 0.2, 3)
    assert len(out) == 2  # 07-01..03 claimed, next eligible start is 07-04
    assert out[0]["window_start"] == date(2026, 7, 1)
    assert out[1]["window_start"] == date(2026, 7, 4)


def test_algo_note_for_annotates_inside_window_with_grace():
    events = [{"window_start": "2026-07-01", "window_end": "2026-07-03",
               "clients_affected": 4, "clients_total": 8}]
    assert tw.algo_note_for("2026-07-02T10:00:00Z", events) is not None
    assert tw.algo_note_for("2026-07-05", events) is not None       # 3-day grace (rolling)
    assert tw.algo_note_for("2026-07-10", events) is None
    assert tw.algo_note_for(None, events) is None


# ---------------------------------------------------------------------------
# seasonality
# ---------------------------------------------------------------------------
def _history(vol_by_month: dict[int, int], year: int = 2025) -> list[dict]:
    return [{"year": year, "month": m, "search_volume": v} for m, v in vol_by_month.items()]


def test_seasonality_profile_indexes_and_peaks():
    hist = _history({1: 50, 2: 50, 3: 100, 4: 150, 5: 200, 6: 200,
                     7: 150, 8: 100, 9: 50, 10: 50, 11: 50, 12: 50})
    p = tw.seasonality_profile(hist)
    assert p is not None
    assert p["index"][5] > 1.5 and p["index"][1] < 0.7
    assert 5 in p["peak_months"] or 6 in p["peak_months"]
    assert p["low_months"]


def test_seasonality_profile_refuses_thin_or_flat():
    assert tw.seasonality_profile(_history({1: 10, 2: 12})) is None       # <6 months
    assert tw.seasonality_profile(_history({m: 0 for m in range(1, 13)})) is None
    assert tw.seasonality_profile(None) is None


def test_demand_outlook_direction_and_swings():
    rising = tw.seasonality_profile(_history({
        1: 50, 2: 50, 3: 60, 4: 80, 5: 120, 6: 160,
        7: 200, 8: 200, 9: 150, 10: 100, 11: 60, 12: 50}))
    today = date(2026, 4, 15)  # next quarter = May–Jul, well above April
    out = tw.demand_outlook([("roof repair", 1000, rising)], today)
    assert out is not None
    assert out["direction"] == "rising" and out["change_pct_next_quarter"] > 10
    assert out["months_ahead"] == ["May", "Jun", "Jul"]
    assert out["notable_swings"] and out["notable_swings"][0]["keyword"] == "roof repair"
    # no usable profiles → None
    assert tw.demand_outlook([("kw", 1000, None), ("kw2", 0, rising)], today) is None


def test_windows_overlap():
    assert tw.windows_overlap(date(2026, 7, 1), date(2026, 7, 3), date(2026, 7, 3), date(2026, 7, 5))
    assert not tw.windows_overlap(date(2026, 7, 1), date(2026, 7, 3), date(2026, 7, 4), date(2026, 7, 6))
