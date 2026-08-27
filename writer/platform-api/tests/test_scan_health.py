"""Unit tests for services.scan_health — pure failure-streak detection, the
alert gate, dedupe-episode keying, and digest copy. No network / no DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services import scan_health as sh


def _run(status: str, days_ago: float, now: datetime) -> sh.JobRun:
    return sh.JobRun(status=status, created_at=now - timedelta(days=days_ago))


NOW = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# failure_streak
# ---------------------------------------------------------------------------
def test_streak_counts_leading_failures_until_last_success():
    runs = [
        _run("failed", 0, NOW),
        _run("failed", 1, NOW),
        _run("failed", 2, NOW),
        _run("complete", 3, NOW),  # anchor
        _run("failed", 4, NOW),    # before the last success — not counted
    ]
    info = sh.failure_streak(runs)
    assert info.streak == 3
    assert info.last_success_at == NOW - timedelta(days=3)
    assert info.oldest_failure_at == NOW - timedelta(days=2)


def test_streak_zero_when_latest_is_success():
    info = sh.failure_streak([_run("complete", 0, NOW), _run("failed", 1, NOW)])
    assert info.streak == 0
    assert info.last_success_at == NOW


def test_streak_never_succeeded_has_no_anchor():
    runs = [_run("failed", 0, NOW), _run("failed", 5, NOW), _run("failed", 10, NOW)]
    info = sh.failure_streak(runs)
    assert info.streak == 3
    assert info.last_success_at is None
    assert info.oldest_failure_at == NOW - timedelta(days=10)


def test_streak_ignores_nonterminal_and_unsorted_input():
    runs = [
        _run("pending", 0, NOW),   # ignored
        _run("running", 0.5, NOW),  # ignored
        _run("failed", 2, NOW),
        _run("failed", 1, NOW),     # out of order on purpose
    ]
    info = sh.failure_streak(runs)
    assert info.streak == 2


# ---------------------------------------------------------------------------
# should_alert — long enough AND old enough
# ---------------------------------------------------------------------------
def test_alerts_when_streak_and_age_clear_bars():
    info = sh.StreakInfo(streak=3, last_success_at=NOW - timedelta(days=5), oldest_failure_at=NOW)
    assert sh.should_alert(info, NOW, min_streak=3, min_days=3) is True


def test_no_alert_below_min_streak():
    info = sh.StreakInfo(streak=2, last_success_at=NOW - timedelta(days=9), oldest_failure_at=NOW)
    assert sh.should_alert(info, NOW, min_streak=3, min_days=3) is False


def test_no_alert_when_streak_too_young():
    # three failures but all today — same-day retries shouldn't fire.
    info = sh.StreakInfo(
        streak=3,
        last_success_at=NOW - timedelta(hours=6),
        oldest_failure_at=NOW - timedelta(hours=5),
    )
    assert sh.should_alert(info, NOW, min_streak=3, min_days=3) is False


def test_age_measured_from_oldest_failure_when_never_succeeded():
    info = sh.StreakInfo(streak=4, last_success_at=None, oldest_failure_at=NOW - timedelta(days=10))
    assert sh.should_alert(info, NOW, min_streak=3, min_days=3) is True


def test_no_alert_when_no_anchor_at_all():
    info = sh.StreakInfo(streak=5, last_success_at=None, oldest_failure_at=None)
    assert sh.should_alert(info, NOW, min_streak=3, min_days=3) is False


# ---------------------------------------------------------------------------
# episode_key — one key per episode, re-nudges weekly, resets on recovery
# ---------------------------------------------------------------------------
def test_episode_key_stable_within_same_week_and_anchor():
    info = sh.StreakInfo(streak=4, last_success_at=NOW - timedelta(days=6), oldest_failure_at=NOW)
    later_same_week = NOW + timedelta(days=1)  # still ISO week 35 of 2026
    assert sh.episode_key("geogrid", "c1", info, NOW) == sh.episode_key(
        "geogrid", "c1", info, later_same_week
    )


def test_episode_key_changes_next_week():
    info = sh.StreakInfo(streak=4, last_success_at=NOW - timedelta(days=6), oldest_failure_at=NOW)
    next_week = NOW + timedelta(days=7)
    assert sh.episode_key("geogrid", "c1", info, NOW) != sh.episode_key(
        "geogrid", "c1", info, next_week
    )


def test_episode_key_changes_when_anchor_moves_after_recovery():
    a = sh.StreakInfo(streak=3, last_success_at=NOW - timedelta(days=10), oldest_failure_at=NOW)
    b = sh.StreakInfo(streak=3, last_success_at=NOW - timedelta(days=2), oldest_failure_at=NOW)
    assert sh.episode_key("organic", "c1", a, NOW) != sh.episode_key("organic", "c1", b, NOW)


def test_episode_key_never_anchor_is_distinct():
    info = sh.StreakInfo(streak=3, last_success_at=None, oldest_failure_at=NOW - timedelta(days=9))
    assert "never" in sh.episode_key("geogrid", "c1", info, NOW)


# ---------------------------------------------------------------------------
# build_digest
# ---------------------------------------------------------------------------
def test_digest_names_client_pipeline_and_error():
    info = sh.StreakInfo(streak=17, last_success_at=NOW - timedelta(days=23), oldest_failure_at=NOW)
    d = sh.build_digest("EML Calibration", "geogrid", info, "local_dominator_create_failed: 500", NOW)
    assert d["severity"] == "warning"
    assert "EML Calibration" in d["title"]
    assert "Maps geo-grid" in d["title"]
    assert "17 consecutive" in d["summary"]
    assert "23 days ago" in d["summary"]
    assert "local_dominator_create_failed" in d["summary"]


def test_digest_without_last_success_reports_staleness():
    info = sh.StreakInfo(streak=4, last_success_at=None, oldest_failure_at=NOW - timedelta(days=8))
    d = sh.build_digest("Acme", "organic", info, None, NOW)
    assert "no success in the last 8 days" in d["summary"]
    assert "Organic rank" in d["title"]
