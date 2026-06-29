"""Unit tests for the Maps geo-grid analyzer + alerting (pure logic + reconcile)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import maps_analyzer as ma  # noqa: E402

TODAY = date(2026, 6, 29)


def _types(signals):
    return {s.alert_type for s in signals}


# ---------------------------------------------------------------------------
# Individual detectors
# ---------------------------------------------------------------------------
def test_grid_rank_drop_fires_and_respects_threshold():
    sig = ma.detect_grid_rank_drop("kw", {"average_rank": 8.0}, {"average_rank": 5.0})
    assert len(sig) == 1 and sig[0].alert_type == "grid_rank_drop"
    assert sig[0].from_value == 5.0 and sig[0].to_value == 8.0 and sig[0].delta == 3.0
    # Below threshold (default 1.5) → no signal; improvement → no signal.
    assert ma.detect_grid_rank_drop("kw", {"average_rank": 5.5}, {"average_rank": 5.0}) == []
    assert ma.detect_grid_rank_drop("kw", {"average_rank": 3.0}, {"average_rank": 5.0}) == []
    # Missing data → no signal.
    assert ma.detect_grid_rank_drop("kw", {"average_rank": None}, {"average_rank": 5.0}) == []


def test_coverage_drop_picks_largest_qualifying_metric():
    curr = {"top3_pins": 6, "top10_pins": 9, "total_pins": 10}
    prev = {"top3_pins": 8, "top10_pins": 10, "total_pins": 10}
    sig = ma.detect_coverage_drop("kw", curr, prev)  # Top-3: 80→60 (-20); Top-10: 100→90 (-10)
    assert len(sig) == 1 and sig[0].delta == 20.0
    assert sig[0].details["metric"] == "Top-3"
    # No qualifying drop (defaults 15pts).
    assert ma.detect_coverage_drop("kw", {"top3_pins": 7, "top10_pins": 9, "total_pins": 10}, prev) == []


def test_lost_pack_core_ring():
    curr_an = {"ring_summaries": [{"ranked": 0, "cells": 9}]}
    prev_an = {"ring_summaries": [{"ranked": 9, "cells": 9}]}
    sig = ma.detect_lost_pack("kw", {}, {}, curr_an, prev_an)
    assert len(sig) == 1 and sig[0].alert_type == "lost_pack"
    assert sig[0].details["reason"] == "core_ring"


def test_lost_pack_found_collapse():
    sig = ma.detect_lost_pack(
        "kw", {"found_pins": 2, "total_pins": 9}, {"found_pins": 9, "total_pins": 9}, {}, {}
    )
    assert len(sig) == 1 and sig[0].details["reason"] == "found_collapse"
    # A modest dip stays quiet.
    assert ma.detect_lost_pack(
        "kw", {"found_pins": 8, "total_pins": 9}, {"found_pins": 9, "total_pins": 9}, {}, {}
    ) == []


def test_area_decline_per_octant():
    curr_an = {"sectors_overall": [
        {"sector": "N", "cells": 4, "coverage_pct_top3": 20.0, "avg_rank": 9.0},
        {"sector": "S", "cells": 4, "coverage_pct_top3": 75.0, "avg_rank": 3.0},
        {"sector": "E", "cells": 1, "coverage_pct_top3": 0.0, "avg_rank": None},  # too thin
    ]}
    prev_an = {"sectors_overall": [
        {"sector": "N", "cells": 4, "coverage_pct_top3": 75.0, "avg_rank": 3.0},  # -55 pts
        {"sector": "S", "cells": 4, "coverage_pct_top3": 80.0, "avg_rank": 2.0},  # -5 pts (quiet)
        {"sector": "E", "cells": 1, "coverage_pct_top3": 75.0, "avg_rank": 3.0},
    ]}
    sig = ma.detect_area_decline("kw", curr_an, prev_an)
    # Only N qualifies (S below threshold, E too thin to trust).
    assert [s.sector for s in sig] == ["N"]
    assert sig[0].alert_type == "area_decline"


def _above(grid, directory=None):
    return {"directory": directory or {"A": {"name": "Comp A"}}, "grid": grid}


def test_competitor_surge_fires_for_biggest_gainer():
    curr = {"competitors_above": _above([[[["A", 1]], [["A", 1]], [["A", 2]], [["A", 1]], [["A", 1]], [["A", 1]]]])}
    prev = {"competitors_above": _above([[[["A", 1]]]])}  # A was on 1 pin, now 6 → gain 5
    sig = ma.detect_competitor_surge("kw", curr, prev)
    assert len(sig) == 1 and sig[0].alert_type == "competitor_surge"
    assert sig[0].to_value == 6.0 and sig[0].delta == 5.0
    assert sig[0].details["name"] == "Comp A"
    # No competitor data on one side → skip (no false surge).
    assert ma.detect_competitor_surge("kw", {"competitors_above": None}, prev) == []


# ---------------------------------------------------------------------------
# analyze_keyword + build_maps_changes
# ---------------------------------------------------------------------------
def test_analyze_keyword_first_scan_no_signals():
    assert ma.analyze_keyword("kw", {"average_rank": 12.0}, None) == []


def test_analyze_keyword_combines_signals():
    curr = {"average_rank": 9.0, "top3_pins": 2, "top10_pins": 4, "total_pins": 10,
            "found_pins": 4, "rank_grid": None, "competitors_above": None}
    prev = {"average_rank": 4.0, "top3_pins": 8, "top10_pins": 9, "total_pins": 10,
            "found_pins": 9, "rank_grid": None, "competitors_above": None}
    types = _types(ma.analyze_keyword("kw", curr, prev))
    assert "grid_rank_drop" in types and "coverage_drop" in types and "lost_pack" in types


def test_build_maps_changes_first_scan():
    out = ma.build_maps_changes({"id": "s1"}, None, [{"keyword": "kw", "average_rank": 5.0, "total_pins": 10, "found_pins": 8, "top3_pins": 5, "top10_pins": 8}], [])
    assert out["has_previous"] is False
    assert out["keywords"][0]["average_rank_prev"] is None
    assert out["keywords"][0]["average_rank_now"] == 5.0


def test_build_maps_changes_deltas():
    curr = [{"keyword": "kw", "average_rank": 8.0, "total_pins": 10, "found_pins": 4, "top3_pins": 2, "top10_pins": 4, "rank_grid": None}]
    prev = [{"keyword": "kw", "average_rank": 5.0, "total_pins": 10, "found_pins": 9, "top3_pins": 8, "top10_pins": 9, "rank_grid": None}]
    out = ma.build_maps_changes({"id": "s2"}, {"id": "s1"}, curr, prev)
    assert out["has_previous"] is True
    row = out["keywords"][0]
    assert row["average_rank_delta"] == 3.0
    assert row["top3_pct_now"] == 20.0 and row["top3_pct_prev"] == 80.0
    assert "grid_rank_drop" in row["alert_types"]


# ---------------------------------------------------------------------------
# build_maps_periods (7/30/90/since-start)
# ---------------------------------------------------------------------------
def _periods_fixture():
    scans = [
        {"id": "n", "completed_at": "2026-06-29T00:00:00Z"},     # today
        {"id": "d8", "completed_at": "2026-06-21T00:00:00Z"},    # 7d baseline
        {"id": "d31", "completed_at": "2026-05-29T00:00:00Z"},   # 30d baseline
        {"id": "d95", "completed_at": "2026-03-26T00:00:00Z"},   # 90d baseline
        {"id": "first", "completed_at": "2026-01-01T00:00:00Z"}, # since-start baseline
    ]
    spec = {"first": (2, 8), "d95": (3, 7), "d31": (4, 6), "d8": (5, 5), "n": (8, 2)}
    results = [
        {"scan_id": sid, "keyword": "kw", "average_rank": ar,
         "top3_pins": t3, "top10_pins": t3, "total_pins": 10, "found_pins": t3}
        for sid, (ar, t3) in spec.items()
    ]
    return scans, results


def test_build_maps_periods_window_baselines():
    scans, results = _periods_fixture()
    out = ma.build_maps_periods(scans, results, TODAY)
    assert out["scan_count"] == 5 and out["as_of"] == "2026-06-29"
    kw = out["keywords"][0]
    rank = next(m for m in kw["metrics"] if m["metric"] == "average_rank")
    assert rank["now"] == 8
    assert rank["windows"]["7d"]["from_value"] == 5 and rank["windows"]["7d"]["delta"] == 3
    assert rank["windows"]["30d"]["delta"] == 4
    assert rank["windows"]["90d"]["delta"] == 5
    assert rank["windows"]["start"]["delta"] == 6 and rank["windows"]["start"]["baseline_at"] == "2026-01-01"
    t3 = next(m for m in kw["metrics"] if m["metric"] == "top3_pct")
    assert t3["now"] == 20.0
    assert t3["windows"]["7d"]["delta"] == -30.0 and t3["windows"]["start"]["delta"] == -60.0


def test_build_maps_periods_single_scan_has_no_windows():
    scans = [{"id": "n", "completed_at": "2026-06-29T00:00:00Z"}]
    results = [{"scan_id": "n", "keyword": "kw", "average_rank": 5,
                "top3_pins": 5, "top10_pins": 5, "total_pins": 10, "found_pins": 5}]
    out = ma.build_maps_periods(scans, results, TODAY)
    rank = next(m for m in out["keywords"][0]["metrics"] if m["metric"] == "average_rank")
    assert rank["now"] == 5
    assert all(rank["windows"][w]["delta"] is None for w in ("7d", "30d", "90d", "start"))


def test_build_maps_periods_overall_is_pin_weighted():
    scans = [{"id": "n", "completed_at": "2026-06-29T00:00:00Z"},
             {"id": "p", "completed_at": "2026-06-21T00:00:00Z"}]
    results = [
        {"scan_id": "n", "keyword": "A", "average_rank": 8, "top3_pins": 2, "top10_pins": 2, "total_pins": 10, "found_pins": 2},
        {"scan_id": "n", "keyword": "B", "average_rank": 4, "top3_pins": 4, "top10_pins": 4, "total_pins": 10, "found_pins": 4},
        {"scan_id": "p", "keyword": "A", "average_rank": 6, "top3_pins": 3, "top10_pins": 3, "total_pins": 10, "found_pins": 3},
        {"scan_id": "p", "keyword": "B", "average_rank": 2, "top3_pins": 5, "top10_pins": 5, "total_pins": 10, "found_pins": 5},
    ]
    out = ma.build_maps_periods(scans, results, TODAY)
    ov = out["overall"]
    rank = next(m for m in ov["metrics"] if m["metric"] == "average_rank")
    assert rank["now"] == 6  # mean(8, 4)
    t3 = next(m for m in ov["metrics"] if m["metric"] == "top3_pct")
    assert t3["now"] == 30.0  # (2+4)/(10+10)
    assert t3["windows"]["7d"]["delta"] == -10.0  # 30 now vs (3+5)/20=40 a week ago


# ---------------------------------------------------------------------------
# build_area_periods (per-octant trends + narrative)
# ---------------------------------------------------------------------------
# 3×3 grid: each non-centre cell is its own compass octant (centre = None).
_OCT_POS = {"NW": (0, 0), "N": (0, 1), "NE": (0, 2), "W": (1, 0),
            "E": (1, 2), "SW": (2, 0), "S": (2, 1), "SE": (2, 2)}


def _grid3(cells: dict):
    g = [[None, None, None], [None, None, None], [None, None, None]]
    for oct_name, (r, c) in _OCT_POS.items():
        if oct_name in cells:
            g[r][c] = cells[oct_name]
    return g


def test_build_area_periods_octant_drop_and_narrative():
    scans = [{"id": "now", "completed_at": "2026-06-29T00:00:00Z"},
             {"id": "first", "completed_at": "2026-01-01T00:00:00Z"}]
    results = [
        {"scan_id": "first", "keyword": "kw", "rank_grid": _grid3({"SW": 2, "N": 2})},
        {"scan_id": "now", "keyword": "kw", "rank_grid": _grid3({"N": 2})},  # SW fell out
    ]
    out = ma.build_area_periods(scans, results, TODAY, {"SW": "Newtown"})
    assert out["scan_count"] == 2
    sw = next(a for a in out["areas"] if a["sector"] == "SW")
    assert sw["now_top3_pct"] == 0.0 and sw["city"] == "Newtown" and sw["sector_full"] == "Southwest"
    assert sw["windows"]["start"]["from_value"] == 100.0 and sw["windows"]["start"]["delta"] == -100.0
    # N held at 100% and sorts to the end (strongest); SW (0%) is in the weak head.
    assert out["areas"][-1]["sector"] == "N"
    assert any("Southwest" in l and "Newtown" in l and "fell 100 pts" in l for l in out["narrative"])


def test_build_area_periods_pin_weighted_across_keywords():
    scans = [{"id": "n", "completed_at": "2026-06-29T00:00:00Z"}]
    results = [
        {"scan_id": "n", "keyword": "A", "rank_grid": _grid3({"N": 2})},  # N ranked
        {"scan_id": "n", "keyword": "B", "rank_grid": _grid3({})},        # N unranked
    ]
    out = ma.build_area_periods(scans, results, TODAY)
    n = next(a for a in out["areas"] if a["sector"] == "N")
    assert n["now_top3_pct"] == 50.0  # 1 of 2 pins in Top-3
    assert n["windows"]["start"]["delta"] is None  # single scan → no comparison
    assert out["narrative"] == []


def test_build_area_periods_positive_fallback_when_stable():
    scans = [{"id": "now", "completed_at": "2026-06-29T00:00:00Z"},
             {"id": "first", "completed_at": "2026-01-01T00:00:00Z"}]
    results = [
        {"scan_id": "first", "keyword": "kw", "rank_grid": _grid3({"N": 2, "S": 2})},
        {"scan_id": "now", "keyword": "kw", "rank_grid": _grid3({"N": 2, "S": 2})},
    ]
    out = ma.build_area_periods(scans, results, TODAY)
    assert out["narrative"] == ["Coverage has held or improved across all directions over the tracked windows."]


# ---------------------------------------------------------------------------
# reconcile (mocked supabase)
# ---------------------------------------------------------------------------
class _FakeQuery:
    def __init__(self, table, store):
        self.table, self.store, self._op, self._payload = table, store, None, None

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def insert(self, rows):
        self._op, self._payload = "insert", rows
        return self

    def update(self, patch):
        self._op, self._payload = "update", patch
        return self

    def execute(self):
        if self._op == "insert":
            self.store.setdefault("inserts", []).extend(self._payload)
            return type("R", (), {"data": self._payload})
        if self._op == "update":
            self.store.setdefault("updates", []).append(self._payload)
            return type("R", (), {"data": []})
        return type("R", (), {"data": self.store.get("open_rows", [])})


class _FakeSupabase:
    def __init__(self, open_rows):
        self.store = {"open_rows": open_rows}

    def table(self, name):
        return _FakeQuery(name, self.store)


def test_reconcile_opens_new_resolves_cleared_dedupes_open():
    # One alert already open for (kw1, grid_rank_drop); kw1 also newly trips
    # area_decline (N). kw2's previously-open coverage_drop has cleared.
    open_rows = [
        {"id": "a1", "keyword": "kw1", "alert_type": "grid_rank_drop", "sector": None},
        {"id": "a2", "keyword": "kw2", "alert_type": "coverage_drop", "sector": None},
    ]
    supa = _FakeSupabase(open_rows)
    per_keyword = [
        ("kw1", [
            ma.MapsAlertSignal(alert_type="grid_rank_drop", message="still dropping"),  # already open
            ma.MapsAlertSignal(alert_type="area_decline", sector="N", message="N weak"),  # new
        ]),
        ("kw2", []),  # coverage_drop cleared → resolve a2
    ]
    out = ma.reconcile_alerts(supa, "client-1", "scan-2", "scan-1", per_keyword, TODAY)
    assert out["opened"] == 1 and out["resolved"] == 1
    inserts = supa.store["inserts"]
    assert len(inserts) == 1 and inserts[0]["alert_type"] == "area_decline" and inserts[0]["sector"] == "N"
    assert out["opened_alerts"][0]["keyword"] == "kw1"


# ---------------------------------------------------------------------------
# summarize digest
# ---------------------------------------------------------------------------
def test_summarize_maps_alerts_critical_and_warning():
    crit = ma.summarize_maps_alerts([
        {"keyword": "a", "alert_type": "lost_pack", "message": "a lost pack."},
        {"keyword": "b", "alert_type": "coverage_drop", "message": "b coverage."},
    ])
    assert crit["severity"] == "critical" and crit["title"] == "2 local-pack alerts detected"
    warn = ma.summarize_maps_alerts([{"keyword": "a", "alert_type": "coverage_drop", "message": "m"}])
    assert warn["severity"] == "warning" and warn["title"] == "1 local-pack alert detected"
