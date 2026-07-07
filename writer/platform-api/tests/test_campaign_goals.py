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
