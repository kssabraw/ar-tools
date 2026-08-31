"""Unit tests for services.campaign_goals — the pure evaluation logic."""

from __future__ import annotations

from datetime import date

from services import campaign_goals as cg


TODAY = date(2026, 7, 7)


def _goal(**kw) -> dict:
    base = {
        "goal_type": "keyword_position",
        "label": "roof repair to top 3",
        "target_value": 3.0,
        "baseline_value": 12.0,
        "baseline_date": "2026-06-01",
        "due_date": None,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# progress_fraction
# ---------------------------------------------------------------------------
def test_progress_fraction_lower_is_better():
    # position 12 → 6 toward target 3: moved 6 of 9 = 2/3
    assert abs(cg.progress_fraction(12, 6, 3, True) - 2 / 3) < 1e-9
    # regression clamps at 0; overshoot clamps at 1
    assert cg.progress_fraction(12, 15, 3, True) == 0.0
    assert cg.progress_fraction(12, 2, 3, True) == 1.0


def test_progress_fraction_higher_is_better_and_degenerate():
    assert cg.progress_fraction(100, 400, 700, False) == 0.5
    # baseline already at/past target → no span to progress through
    assert cg.progress_fraction(3, 2, 3, True) is None
    assert cg.progress_fraction(None, 5, 3, True) is None


# ---------------------------------------------------------------------------
# evaluate_goal
# ---------------------------------------------------------------------------
def test_achieved_when_target_met():
    ev = cg.evaluate_goal(_goal(), 3.0, TODAY)
    assert ev["status"] == "achieved" and ev["progress_pct"] == 100.0
    # higher-is-better type
    ev = cg.evaluate_goal(
        _goal(goal_type="organic_clicks", target_value=800, baseline_value=500), 900, TODAY
    )
    assert ev["status"] == "achieved"


def test_no_data_and_manual():
    assert cg.evaluate_goal(_goal(), None, TODAY)["status"] == "no_data"
    assert cg.evaluate_goal(_goal(goal_type="custom", target_value=None), None, TODAY)["status"] == "manual"


def test_pace_on_track_vs_behind():
    # 36 days into a ~120-day window (elapsed ~30%). Progress 2/3 → on_track.
    g = _goal(baseline_date="2026-06-01", due_date="2026-09-29")
    assert cg.evaluate_goal(g, 6.0, TODAY)["status"] == "on_track"
    # Progress 0 at 30% elapsed (grace 15%) → behind.
    assert cg.evaluate_goal(g, 12.0, TODAY)["status"] == "behind"


def test_pace_projection_not_fooled_by_calendar():
    # The WheelHouse local-pack case: baseline 10.8 → 11.5 toward target 25, only
    # ~5% of the way with ~19% of a long window elapsed. Projected pace is well
    # short of the target, so it must read "behind" — NOT "on track" just because
    # little time has elapsed (the old additive-grace bug).
    g = _goal(goal_type="maps_pack_presence", baseline_value=10.8, target_value=25.0,
              baseline_date="2026-07-07", due_date="2026-12-31")
    ev = cg.evaluate_goal(g, 11.5, date(2026, 8, 10))
    assert ev["status"] == "behind"
    # A goal keeping projected pace (half-way at a fifth of the time) stays on track.
    g2 = _goal(goal_type="keywords_in_top", baseline_value=0, target_value=2.0,
               baseline_date="2026-07-07", due_date="2026-12-31")
    assert cg.evaluate_goal(g2, 1.0, date(2026, 8, 10))["status"] == "on_track"


def test_pace_benefit_of_doubt_very_early():
    # A few days into a 6-month window (elapsed < the min-pace floor): too early to
    # judge the projection, so a barely-moved goal is not alarmed as "behind".
    g = _goal(goal_type="maps_pack_presence", baseline_value=10.0, target_value=25.0,
              baseline_date="2026-07-07", due_date="2026-12-31")
    assert cg.evaluate_goal(g, 10.5, date(2026, 7, 12))["status"] == "on_track"


def test_overdue_past_due_date():
    g = _goal(due_date="2026-07-01")
    ev = cg.evaluate_goal(g, 6.0, TODAY)
    assert ev["status"] == "overdue" and ev["elapsed_pct"] == 100.0
    # …but meeting the target still reads achieved even past due.
    assert cg.evaluate_goal(g, 2.5, TODAY)["status"] == "achieved"


def test_no_due_date_judged_by_movement():
    g = _goal(due_date=None)
    assert cg.evaluate_goal(g, 8.0, TODAY)["status"] == "on_track"
    assert cg.evaluate_goal(g, 13.0, TODAY)["status"] == "behind"


def test_goal_note_carries_numbers_and_status():
    g = _goal(due_date="2026-09-29")
    ev = cg.evaluate_goal(g, 6.0, TODAY)
    note = cg.goal_note(g, ev, 6.0)
    assert "ON_TRACK" in note
    assert "now 6" in note and "target 3" in note and "baseline 12" in note
    assert "due 2026-09-29" in note


def test_measure_goal_dispatch_custom_is_none():
    assert cg.measure_goal(None, "c1", {"goal_type": "custom"}, TODAY) is None


def test_measure_gsc_sum_aggregates_via_rpc():
    """Clicks/impressions goals must sum the per-day RPC totals (server-side
    aggregate), not a raw gsc_query_daily select that PostgREST caps at 1000 rows
    and silently undercounts a busy property."""
    class _Res:
        def __init__(self, data):
            self.data = data

    class _Table:
        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            return _Res([{"id": "prop1"}])  # gsc_properties row

    class _Rpc:
        def execute(self):
            # one row per day (already aggregated); the row dated AFTER `today` must
            # be excluded by the upper-bound filter so a historical measurement is
            # correct — clicks sum to 17 (9 + 8), not 25.
            return _Res([{"date": "2026-07-01", "impressions": 100, "clicks": 9},
                         {"date": "2026-07-05", "impressions": 50, "clicks": 8},
                         {"date": "2026-07-20", "impressions": 999, "clicks": 8}])

    class _SB:
        def table(self, name):
            return _Table()

        def rpc(self, name, params):
            assert name == "gsc_property_daily_traffic"
            assert params["p_property_id"] == "prop1"
            return _Rpc()

    # TODAY = 2026-07-07 → the 2026-07-20 row is in the future and excluded.
    assert cg._measure_gsc_sum(_SB(), "c1", "clicks", TODAY) == 17.0
    assert cg._measure_gsc_sum(_SB(), "c1", "impressions", TODAY) == 150.0


# ---------------------------------------------------------------------------
# effective_target (percent-increase mode)
# ---------------------------------------------------------------------------
def test_effective_target_absolute_and_percent():
    # absolute (default): the stored target is the effective target.
    assert cg.effective_target(_goal(goal_type="gbp_calls", target_value=100.0)) == 100.0
    # percent_increase: baseline * (1 + pct/100).
    g = _goal(goal_type="gbp_calls", target_value=25.0, baseline_value=80.0,
              target_mode="percent_increase")
    assert cg.effective_target(g) == 100.0
    # percent with no baseline can't be computed.
    g2 = _goal(goal_type="gbp_calls", target_value=25.0, baseline_value=None,
               target_mode="percent_increase")
    assert cg.effective_target(g2) is None
    # no target at all → None.
    assert cg.effective_target(_goal(goal_type="custom", target_value=None)) is None
    # a percent increase from a NON-POSITIVE baseline is undefined → None (never 0,
    # which would read as instantly "achieved").
    assert cg.effective_target(_goal(goal_type="gbp_calls", target_value=25.0,
                                     baseline_value=0.0, target_mode="percent_increase")) is None


def test_percent_goal_zero_baseline_is_no_data_not_achieved():
    # The trap: 0 * (1 + 25/100) = 0, and current 0 >= 0 would be "achieved".
    g = _goal(goal_type="gbp_calls", target_value=25.0, baseline_value=0.0,
              target_mode="percent_increase", due_date=None)
    assert cg.evaluate_goal(g, 0.0, TODAY)["status"] == "no_data"
    assert cg.evaluate_goal(g, 5.0, TODAY)["status"] == "no_data"
    # …and a percent goal whose baseline was never captured is also no_data.
    g2 = _goal(goal_type="gbp_impressions", target_value=25.0, baseline_value=None,
               target_mode="percent_increase", due_date=None)
    assert cg.evaluate_goal(g2, 100.0, TODAY)["status"] == "no_data"


def test_evaluate_percent_increase_goal():
    # baseline 80 GBP calls, target +25% ⇒ effective 100. Higher is better.
    g = _goal(goal_type="gbp_impressions", target_value=25.0, baseline_value=80.0,
              target_mode="percent_increase", due_date=None)
    # met the effective target → achieved.
    assert cg.evaluate_goal(g, 100.0, TODAY)["status"] == "achieved"
    # halfway from 80 toward 100 (span 20, moved 10) → 50% progress, on track by movement.
    ev = cg.evaluate_goal(g, 90.0, TODAY)
    assert ev["status"] == "on_track" and ev["progress_pct"] == 50.0
    # no movement → behind (no due date, judged by movement).
    assert cg.evaluate_goal(g, 80.0, TODAY)["status"] == "behind"


def test_goal_note_percent_increase():
    g = _goal(goal_type="gbp_calls", target_value=25.0, baseline_value=80.0,
              target_mode="percent_increase", due_date=None)
    note = cg.goal_note(g, cg.evaluate_goal(g, 90.0, TODAY), 90.0)
    assert "target 100" in note and "+25% over baseline" in note


# ---------------------------------------------------------------------------
# GBP metric measurement dispatch
# ---------------------------------------------------------------------------
def test_measure_gbp_metric_sums_window(monkeypatch):
    """A GBP goal sums the trailing-window gbp_metric_daily values across the
    client's verified locations; the impression fold pulls the four sub-types."""
    from config import settings

    monkeypatch.setattr(settings, "gbp_metrics_enabled", True, raising=False)

    class _Res:
        def __init__(self, data):
            self.data = data

    class _Q:
        def __init__(self, data):
            self._data = data

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def in_(self, *a, **k):
            return self

        def gte(self, *a, **k):
            return self

        def lte(self, *a, **k):
            return self

        def execute(self):
            return _Res(self._data)

    class _SB:
        def table(self, name):
            if name == "gbp_locations":
                return _Q([{"id": "loc1"}, {"id": "loc2"}])
            return _Q([{"value": 3}, {"value": 4}, {"value": 5}])

    assert cg._measure_gbp_metric(_SB(), "c1", "gbp_calls", TODAY) == 12.0
    assert cg._measure_gbp_metric(_SB(), "c1", "gbp_impressions", TODAY) == 12.0
    # dispatch through measure_goal too
    assert cg.measure_goal(_SB(), "c1", {"goal_type": "gbp_website_clicks"}, TODAY) == 12.0


def test_measure_gbp_metric_disabled_or_no_location(monkeypatch):
    from config import settings

    class _Res:
        def __init__(self, data):
            self.data = data

    class _Q:
        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def in_(self, *a, **k):
            return self

        def gte(self, *a, **k):
            return self

        def lte(self, *a, **k):
            return self

        def execute(self):
            return _Res([])

    class _SB:
        def table(self, name):
            return _Q()

    # flag off → None regardless of data
    monkeypatch.setattr(settings, "gbp_metrics_enabled", False, raising=False)
    assert cg._measure_gbp_metric(_SB(), "c1", "gbp_calls", TODAY) is None
    # flag on but no connected location → None
    monkeypatch.setattr(settings, "gbp_metrics_enabled", True, raising=False)
    assert cg._measure_gbp_metric(_SB(), "c1", "gbp_calls", TODAY) is None
