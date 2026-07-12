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
