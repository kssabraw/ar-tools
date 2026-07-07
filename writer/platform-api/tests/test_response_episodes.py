"""Unit tests for services.response_episodes — the pure verify-loop logic
(2-week rechecks, 6-week escalation) from the Rank Drop Mitigation SOPs.

No network / no DB: evaluate_episode + episode_note are pure; run_episode_sync's
reads/writes are covered by integration testing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services import response_episodes as ep

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)


def _episode(opened_days_ago: int, baseline_pos: float | None = 8.0, **extra) -> dict:
    return {
        "id": "e-1",
        "client_id": "c-1",
        "channel": "organic",
        "keyword": "emergency plumber",
        "opened_at": (NOW - timedelta(days=opened_days_ago)).isoformat(),
        "baseline": {"position": baseline_pos},
        "checks": [],
        "status": "open",
        **extra,
    }


# ---------------------------------------------------------------------------
# evaluate_episode
# ---------------------------------------------------------------------------
def test_resolved_alert_recovers_regardless_of_age():
    r = ep.evaluate_episode(_episode(50), alert_resolved=True, current_position=30.0, now=NOW)
    assert r["verdict"] == "recovered"


def test_improving_episode_is_never_escalated():
    # 50 days old, but position gained 8 → 4 (≥ IMPROVE_MIN_POSITIONS)
    r = ep.evaluate_episode(_episode(50), alert_resolved=False, current_position=4.0, now=NOW)
    assert r["verdict"] == "improving"
    assert r["improved"] is True


def test_stalled_episode_escalates_at_six_weeks():
    r = ep.evaluate_episode(_episode(42), alert_resolved=False, current_position=8.5, now=NOW)
    assert r["verdict"] == "escalate"


def test_stalled_episode_before_six_weeks_keeps_checking():
    r = ep.evaluate_episode(_episode(20), alert_resolved=False, current_position=8.5, now=NOW)
    assert r["verdict"] == "no_improvement"


def test_missing_position_data_counts_as_not_improved():
    # No current read → can't claim improvement; at 6 weeks that escalates.
    r = ep.evaluate_episode(_episode(45, baseline_pos=None), alert_resolved=False,
                            current_position=None, now=NOW)
    assert r["verdict"] == "escalate"
    r2 = ep.evaluate_episode(_episode(10, baseline_pos=None), alert_resolved=False,
                             current_position=None, now=NOW)
    assert r2["verdict"] == "no_improvement"


def test_small_gain_is_not_improvement():
    # 8.0 → 7.0 is under the 2-position bar
    r = ep.evaluate_episode(_episode(42), alert_resolved=False, current_position=7.0, now=NOW)
    assert r["verdict"] == "escalate"


# ---------------------------------------------------------------------------
# episode_note — the Action Plan's verify-loop line
# ---------------------------------------------------------------------------
def test_note_fresh_episode():
    note = ep.episode_note(_episode(3), NOW)
    assert "first recheck" in note


def test_note_no_improvement_recommends_link_round():
    e = _episode(21, checks=[{"at": "x", "verdict": "no_improvement", "position": 8.4}])
    note = ep.episode_note(e, NOW)
    assert "3 weeks" in note
    assert "Recipe Engine" in note


def test_note_improving():
    e = _episode(15, checks=[{"at": "x", "verdict": "improving", "position": 5.0}])
    assert "improving" in ep.episode_note(e, NOW)


def test_note_escalated():
    e = _episode(45, status="escalated")
    note = ep.episode_note(e, NOW)
    assert "6-week rule" in note


def test_note_handles_missing_opened_at():
    assert ep.episode_note({"opened_at": None}, NOW) is None
