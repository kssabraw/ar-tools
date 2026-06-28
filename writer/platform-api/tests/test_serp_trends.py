"""Unit tests for the SERP Landscape Trends pure helpers (no network)."""

from __future__ import annotations

from datetime import date

from services import serp_trends


def _snap(d: str, signals=None, aio=False, local=False, rank=None, dr=None):
    return {
        "captured_at": f"{d}T00:00:00+00:00",
        "intent_signals": signals or [],
        "aio_present": aio,
        "local_intent": local,
        "client_rank": rank,
        "client_dr": dr,
    }


# ---------------------------------------------------------------------------
# signal_set
# ---------------------------------------------------------------------------
def test_signal_set_unions_flags():
    s = serp_trends.signal_set(_snap("2026-06-01", ["forums", "video"], aio=True, local=True))
    assert s == {"forums", "video", "aio", "local"}


def test_signal_set_empty():
    assert serp_trends.signal_set({"intent_signals": None}) == set()


# ---------------------------------------------------------------------------
# compute_timeline_deltas
# ---------------------------------------------------------------------------
def test_timeline_deltas_added_removed_and_rank():
    snaps = [
        _snap("2026-06-01", ["forums"], rank=8, dr=100),
        _snap("2026-06-08", ["forums", "video"], aio=True, rank=5, dr=120),
    ]
    out = serp_trends.compute_timeline_deltas(snaps)
    assert out[0]["signals_added"] == [] and out[0]["client_rank_delta"] is None
    # 'aio' is ordered before 'video' per TRACKED_SIGNALS.
    assert out[1]["signals_added"] == ["aio", "video"]
    assert out[1]["signals_removed"] == []
    assert out[1]["client_rank_delta"] == -3   # 5 - 8, improved
    assert out[1]["client_dr_delta"] == 20


def test_timeline_deltas_removal_and_none_rank():
    snaps = [
        _snap("2026-06-01", ["forums", "shopping"], local=True, rank=3),
        _snap("2026-06-08", ["forums"], rank=None),
    ]
    out = serp_trends.compute_timeline_deltas(snaps)
    assert out[1]["signals_removed"] == ["local", "shopping"]
    assert out[1]["client_rank_delta"] is None  # missing current rank


# ---------------------------------------------------------------------------
# build_week_ends
# ---------------------------------------------------------------------------
def test_build_week_ends_oldest_first_ends_today():
    ends = serp_trends.build_week_ends(date(2026, 6, 28), 3)
    assert ends == [date(2026, 6, 14), date(2026, 6, 21), date(2026, 6, 28)]


# ---------------------------------------------------------------------------
# weekly_prevalence (as-of) + prevalence_series
# ---------------------------------------------------------------------------
def test_weekly_prevalence_as_of_carries_latest_snapshot_forward():
    # kw A captured wk1 (forums), re-captured wk3 (forums+aio). kw B only wk2 (aio).
    by_kw = {
        "A": [_snap("2026-06-14", ["forums"]), _snap("2026-06-28", ["forums"], aio=True)],
        "B": [_snap("2026-06-21", [], aio=True)],
    }
    week_ends = [date(2026, 6, 14), date(2026, 6, 21), date(2026, 6, 28)]
    weeks = serp_trends.weekly_prevalence(by_kw, week_ends)

    # wk1: only A has data → 1 keyword, forums=1, aio=0
    assert weeks[0]["keyword_count"] == 1
    assert weeks[0]["counts"]["forums"] == 1 and weeks[0]["counts"]["aio"] == 0
    # wk2: A (still wk1 snapshot, forums) + B (aio) → 2 keywords
    assert weeks[1]["keyword_count"] == 2
    assert weeks[1]["counts"]["forums"] == 1 and weeks[1]["counts"]["aio"] == 1
    # wk3: A now forums+aio, B aio → forums=1, aio=2
    assert weeks[2]["counts"]["forums"] == 1 and weeks[2]["counts"]["aio"] == 2

    series = serp_trends.prevalence_series(weeks)
    aio = next(s for s in series if s["signal"] == "aio")
    assert aio["counts"] == [0, 1, 2]
    assert aio["pct"] == [0.0, 0.5, 1.0]
    # A signal never seen is omitted entirely.
    assert all(s["signal"] != "shopping" for s in series)


def test_prevalence_series_pct_none_when_no_data():
    weeks = [{"date": "2026-06-14", "keyword_count": 0, "counts": {s: 0 for s in serp_trends.TRACKED_SIGNALS}}]
    # forums never appears → omitted; with no data the row set is empty.
    assert serp_trends.prevalence_series(weeks) == []


# ---------------------------------------------------------------------------
# compute_change_digest
# ---------------------------------------------------------------------------
def test_change_digest_reports_added_removed_sorted():
    by_kw = {
        "A": [_snap("2026-06-01", ["forums"]), _snap("2026-06-08", ["forums", "video"], aio=True)],
        "B": [_snap("2026-06-01", ["shopping"]), _snap("2026-06-08", ["shopping"])],  # no change
        "C": [_snap("2026-06-08", ["news"])],  # single snapshot — skipped
    }
    names = {"A": "kw a", "B": "kw b", "C": "kw c"}
    out = serp_trends.compute_change_digest(by_kw, names)
    assert len(out) == 1
    assert out[0]["keyword_id"] == "A"
    assert out[0]["added"] == ["aio", "video"]
    assert out[0]["removed"] == []
