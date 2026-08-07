"""Tests for the scheduler's durable run markers (ops fix 2026-07-12).

The in-memory "already ran today" markers re-fired every daily block on each
deploy (freeze_check ran up to 17×/client/day). Markers now persist to the
`scheduler_state` table — these tests cover the pure parsers and the
best-effort load/save wrappers (mocked Supabase, no DB).
"""

from __future__ import annotations

from datetime import date

from services import gsc_scheduler as S


# ── pure parsers ──────────────────────────────────────────────────────────────
def test_parse_marker_date():
    assert S.parse_marker_date("2026-07-12") == date(2026, 7, 12)
    assert S.parse_marker_date(None) is None
    assert S.parse_marker_date("") is None
    assert S.parse_marker_date("not-a-date") is None
    assert S.parse_marker_date("2026-13-99") is None  # invalid parts → None


def test_parse_marker_month():
    assert S.parse_marker_month("2026-07") == (2026, 7)
    # A full date still parses to its month (prefix split).
    assert S.parse_marker_month("2026-07-12") == (2026, 7)
    assert S.parse_marker_month(None) is None
    assert S.parse_marker_month("garbage") is None


# ── best-effort load/save (mocked Supabase) ───────────────────────────────────
class _Table:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail
        self.upserts = []

    def select(self, *_a, **_k):
        return self

    def upsert(self, payload, **_k):
        self.upserts.append(payload)
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("db down")
        return type("R", (), {"data": self.rows})()


class _SB:
    def __init__(self, table):
        self._t = table

    def table(self, _name):
        return self._t


def test_load_scheduler_state_maps_rows(monkeypatch):
    t = _Table(rows=[{"key": "daily", "value": "2026-07-12"}, {"key": "", "value": "x"}])
    monkeypatch.setattr(S, "get_supabase", lambda: _SB(t))
    state = S.load_scheduler_state()
    assert state == {"daily": "2026-07-12"}  # empty keys dropped


def test_load_scheduler_state_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(S, "get_supabase", lambda: _SB(_Table(fail=True)))
    assert S.load_scheduler_state() == {}  # never raises


def test_save_marker_upserts_and_swallows_errors(monkeypatch):
    t = _Table()
    monkeypatch.setattr(S, "get_supabase", lambda: _SB(t))
    S.save_marker("daily", "2026-07-12")
    assert t.upserts and t.upserts[0]["key"] == "daily"
    assert t.upserts[0]["value"] == "2026-07-12"
    # A failing save is logged, never raised (the loop must survive).
    monkeypatch.setattr(S, "get_supabase", lambda: _SB(_Table(fail=True)))
    S.save_marker("daily", "2026-07-13")  # no exception


def test_marker_roundtrip_prevents_rerun():
    """The restored marker satisfies should_run's 'already ran today' check —
    the actual deploy-refire scenario."""
    from datetime import datetime, timezone

    now = datetime(2026, 7, 12, 9, 0, tzinfo=timezone.utc)
    restored = S.parse_marker_date(now.date().isoformat())
    assert S.should_run(now, restored, hour_utc=6) is False  # no re-fire
    # Next day it runs again.
    tomorrow = datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc)
    assert S.should_run(tomorrow, restored, hour_utc=6) is True


# ── weekly_due: the missed-window catch-up ────────────────────────────────────
# A weekly block can only fire between `hour_utc` and midnight UTC on ONE
# weekday. A scheduler not alive across that window used to drop the whole week
# silently and wait another seven days (the Maps geo-grid lost its Tuesday
# grids that way). `weekly_due` keeps the normal path identical and adds a
# self-healing catch-up once a full week has elapsed.
from datetime import datetime, timezone  # noqa: E402

TUE = 1


def _now(y, m, d, hour):
    return datetime(y, m, d, hour, tzinfo=timezone.utc)


def test_weekly_due_fires_on_target_weekday_after_hour():
    # Tue 2026-08-04 at 08:00, last run the previous Tuesday.
    assert S.weekly_due(_now(2026, 8, 4, 8), date(2026, 7, 28), TUE, 8) is True


def test_weekly_due_waits_until_the_target_hour():
    assert S.weekly_due(_now(2026, 8, 4, 7), date(2026, 7, 28), TUE, 8) is False


def test_weekly_due_only_once_per_day():
    # Already ran today — a later tick the same day must not re-fire.
    assert S.weekly_due(_now(2026, 8, 4, 20), date(2026, 8, 4), TUE, 8) is False


def test_weekly_due_quiet_on_a_non_target_weekday():
    # Wed, ran yesterday (Tue) — not due, and not yet overdue.
    assert S.weekly_due(_now(2026, 8, 5, 9), date(2026, 8, 4), TUE, 8) is False


def test_weekly_due_catches_up_after_a_missed_window():
    """The regression: the scheduler was down all Tuesday, so the run never
    happened. By Wednesday a full week has elapsed and it must fire rather than
    silently wait for the next Tuesday."""
    # Last run Tue 2026-07-28; the Tue 2026-08-04 window was missed entirely.
    assert S.weekly_due(_now(2026, 8, 5, 9), date(2026, 7, 28), TUE, 8) is True


def test_weekly_due_catch_up_still_respects_the_hour():
    assert S.weekly_due(_now(2026, 8, 5, 3), date(2026, 7, 28), TUE, 8) is False


def test_weekly_due_no_marker_waits_for_the_target_weekday():
    """A fresh install / unreadable marker must not fire on an arbitrary day —
    the catch-up is for a gap we can measure, not an unknown one."""
    assert S.weekly_due(_now(2026, 8, 5, 9), None, TUE, 8) is False      # Wed
    assert S.weekly_due(_now(2026, 8, 4, 9), None, TUE, 8) is True       # Tue
