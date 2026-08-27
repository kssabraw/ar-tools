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


# ---------------------------------------------------------------------------
# task_producers.on_scan_health — the PACE wiring (opens/closes board tasks)
# ---------------------------------------------------------------------------
class _FakeQuery:
    """Minimal chainable Supabase table stub returning a fixed row set."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeSupabase:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        return _FakeQuery(self._rows)


def _wire(monkeypatch, live_rows):
    """Patch task_producers so on_scan_health runs without a real DB, capturing
    created/closed calls. Returns (created, closed) lists."""
    from services import task_producers as tp

    created: list[dict] = []
    closed: list[str] = []
    monkeypatch.setattr(tp.settings, "native_tasks_enabled", True, raising=False)
    monkeypatch.setattr(tp.settings, "task_producer_scan_health_enabled", True, raising=False)
    monkeypatch.setattr(
        tp, "_create",
        lambda cid, name, *, source, source_ref, description: created.append(
            {"client_id": cid, "name": name, "source": source, "source_ref": source_ref}
        ),
    )
    monkeypatch.setattr(tp, "get_supabase", lambda: _FakeSupabase(live_rows))
    monkeypatch.setattr(tp.task_service, "close_task_by_source",
                        lambda source, ref: closed.append(ref) or True)
    return tp, created, closed


def test_producer_opens_task_per_failing_group(monkeypatch):
    tp, created, closed = _wire(monkeypatch, live_rows=[])
    tp.on_scan_health([
        {"client_id": "c1", "pipeline_key": "geogrid", "label": "Maps geo-grid",
         "streak": 17, "summary": "17 consecutive ... failed"},
    ])
    assert len(created) == 1
    assert created[0]["source"] == "scan_health"
    assert created[0]["source_ref"] == "c1:geogrid"
    assert "Maps geo-grid" in created[0]["name"]
    assert closed == []


def test_producer_closes_recovered_group(monkeypatch):
    # c1:geogrid is still failing; c2:organic recovered (open task, not alerting).
    live = [
        {"id": "t1", "source_ref": "c1:geogrid", "completed": False},
        {"id": "t2", "source_ref": "c2:organic", "completed": False},
    ]
    tp, created, closed = _wire(monkeypatch, live_rows=live)
    tp.on_scan_health([
        {"client_id": "c1", "pipeline_key": "geogrid", "label": "Maps geo-grid",
         "streak": 5, "summary": "still failing"},
    ])
    # c1 already live → not recreated is not asserted here (_create is idempotent
    # in prod); the recovery close is the contract under test.
    assert closed == ["c2:organic"]


def test_producer_empty_list_closes_all_open(monkeypatch):
    live = [{"id": "t1", "source_ref": "c1:geogrid", "completed": False}]
    tp, created, closed = _wire(monkeypatch, live_rows=live)
    tp.on_scan_health([])  # nothing failing now → recovery
    assert created == []
    assert closed == ["c1:geogrid"]


def test_producer_noop_when_disabled(monkeypatch):
    tp, created, closed = _wire(monkeypatch, live_rows=[])
    monkeypatch.setattr(tp.settings, "task_producer_scan_health_enabled", False, raising=False)
    tp.on_scan_health([
        {"client_id": "c1", "pipeline_key": "geogrid", "label": "Maps geo-grid",
         "streak": 9, "summary": "x"},
    ])
    assert created == [] and closed == []
