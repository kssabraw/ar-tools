"""Unit tests for the GSC ingest + scheduler (Organic Rank Tracker M2).

GSC API and Supabase are fully mocked — nothing hits the network or a DB.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services import gsc_ingest, gsc_scheduler


# ---------------------------------------------------------------------------
# compute_window
# ---------------------------------------------------------------------------
def test_compute_window_three_days_inclusive():
    start, end = gsc_ingest.compute_window(date(2026, 6, 22), 3)
    assert start == "2026-06-20"
    assert end == "2026-06-22"


def test_compute_window_single_day_floor():
    start, end = gsc_ingest.compute_window(date(2026, 6, 22), 0)
    assert start == "2026-06-22"
    assert end == "2026-06-22"


# ---------------------------------------------------------------------------
# parse_query_daily_rows
# ---------------------------------------------------------------------------
def test_parse_rows_maps_keys_and_metrics():
    rows = [
        {"keys": ["best hvac", "2026-06-20"], "clicks": 5, "impressions": 100, "ctr": 0.05, "position": 8.3},
    ]
    parsed = gsc_ingest.parse_query_daily_rows("prop-1", rows)
    assert parsed == [
        {
            "property_id": "prop-1",
            "query": "best hvac",
            "date": "2026-06-20",
            "clicks": 5,
            "impressions": 100,
            "ctr": 0.05,
            "position": 8.3,
        }
    ]


def test_parse_rows_skips_malformed_and_defaults_missing():
    rows = [
        {"keys": ["only-one-key"]},                 # too few keys → skipped
        {"keys": ["q", "2026-06-21"]},              # missing metrics → defaulted
    ]
    parsed = gsc_ingest.parse_query_daily_rows("p", rows)
    assert len(parsed) == 1
    assert parsed[0]["clicks"] == 0
    assert parsed[0]["impressions"] == 0
    assert parsed[0]["position"] is None


# ---------------------------------------------------------------------------
# ingest_property
# ---------------------------------------------------------------------------
def _property_row(**over):
    row = {
        "id": "prop-1",
        "site_url": "https://acmehvac.com/",
        "property_type": "url_prefix",
        "access_status": "ok",
    }
    row.update(over)
    return row


class _FakeSupabase:
    """Minimal supabase-py table chain stub capturing upserts/inserts/updates."""

    def __init__(self, property_row):
        self._property_row = property_row
        self.upserted: list[dict] = []
        self.sync_runs: list[dict] = []
        self.property_updates: list[dict] = []

    def table(self, name):
        return _FakeTable(self, name)


class _FakeTable:
    def __init__(self, parent, name):
        self.parent = parent
        self.name = name
        self._payload = None

    # terminal-ish builders just return self
    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def upsert(self, payload, **_k):
        self.parent.upserted.extend(payload)
        return self

    def insert(self, payload):
        if self.name == "sync_runs":
            self.parent.sync_runs.append(payload)
        return self

    def update(self, payload):
        if self.name == "gsc_properties":
            self.parent.property_updates.append(payload)
        return self

    def execute(self):
        if self.name == "gsc_properties" and self._select_mode():
            return SimpleNamespace(data=[self.parent._property_row])
        return SimpleNamespace(data=[])

    def _select_mode(self):
        return True


def test_ingest_happy_path(monkeypatch):
    fake = _FakeSupabase(_property_row())
    monkeypatch.setattr(gsc_ingest, "get_supabase", lambda: fake)
    monkeypatch.setattr(
        gsc_ingest.gsc_service,
        "fetch_search_analytics",
        lambda *a, **k: [
            {"keys": ["hvac repair", "2026-06-21"], "clicks": 3, "impressions": 40, "ctr": 0.075, "position": 6.1},
            {"keys": ["ac install", "2026-06-21"], "clicks": 0, "impressions": 12, "ctr": 0.0, "position": 14.0},
        ],
    )

    result = gsc_ingest.ingest_property("prop-1", "2026-06-21", "2026-06-21")

    assert result.status == "ok"
    assert result.rows == 2
    assert len(fake.upserted) == 2
    assert fake.sync_runs and fake.sync_runs[0]["status"] == "ok"
    assert fake.sync_runs[0]["rows"] == 2


def test_ingest_403_marks_property_no_access(monkeypatch):
    fake = _FakeSupabase(_property_row())
    monkeypatch.setattr(gsc_ingest, "get_supabase", lambda: fake)

    def boom(*_a, **_k):
        exc = Exception("forbidden")
        exc.resp = MagicMock(status=403)  # type: ignore[attr-defined]
        raise exc

    monkeypatch.setattr(gsc_ingest.gsc_service, "fetch_search_analytics", boom)

    result = gsc_ingest.ingest_property("prop-1", "2026-06-21", "2026-06-21")

    assert result.status == "failed"
    assert fake.property_updates and fake.property_updates[0]["access_status"] == "no_access"
    assert fake.sync_runs and fake.sync_runs[0]["status"] == "failed"


def test_ingest_property_not_found(monkeypatch):
    fake = _FakeSupabase(None)
    # property select returns empty
    monkeypatch.setattr(gsc_ingest, "get_supabase", lambda: fake)

    class _Empty(_FakeTable):
        def execute(self):
            return SimpleNamespace(data=[])

    monkeypatch.setattr(fake, "table", lambda name: _Empty(fake, name))
    result = gsc_ingest.ingest_property("missing")
    assert result.status == "failed"
    assert result.error == "property_not_found"


def test_ingest_no_rows_still_records_ok(monkeypatch):
    fake = _FakeSupabase(_property_row())
    monkeypatch.setattr(gsc_ingest, "get_supabase", lambda: fake)
    monkeypatch.setattr(gsc_ingest.gsc_service, "fetch_search_analytics", lambda *a, **k: [])

    result = gsc_ingest.ingest_property("prop-1", "2026-06-21", "2026-06-21")

    assert result.status == "ok"
    assert result.rows == 0
    assert fake.upserted == []
    assert fake.sync_runs[0]["status"] == "ok"


# ---------------------------------------------------------------------------
# scheduler should_run
# ---------------------------------------------------------------------------
def _utc(y, m, d, h):
    return datetime(y, m, d, h, 0, tzinfo=timezone.utc)


def test_should_run_after_hour_and_not_run_today():
    assert gsc_scheduler.should_run(_utc(2026, 6, 22, 9), None, 8) is True


def test_should_not_run_before_hour():
    assert gsc_scheduler.should_run(_utc(2026, 6, 22, 7), None, 8) is False


def test_should_not_run_twice_same_day():
    now = _utc(2026, 6, 22, 9)
    assert gsc_scheduler.should_run(now, date(2026, 6, 22), 8) is False


def test_should_run_next_day():
    now = _utc(2026, 6, 23, 9)
    assert gsc_scheduler.should_run(now, date(2026, 6, 22), 8) is True


# ---------------------------------------------------------------------------
# scheduler enqueue
# ---------------------------------------------------------------------------
def test_enqueue_due_ingests_skips_pending(monkeypatch):
    inserts: list[dict] = []

    class _Sched:
        def table(self, name):
            return _SchedTable(name, inserts)

    monkeypatch.setattr(gsc_scheduler, "get_supabase", lambda: _Sched())
    # prop-a has a pending job, prop-b does not
    monkeypatch.setattr(
        gsc_scheduler, "_has_pending_ingest", lambda sb, pid: pid == "prop-a"
    )

    count = gsc_scheduler.enqueue_due_ingests()
    assert count == 1
    assert inserts == [{"job_type": "gsc_ingest", "entity_id": "prop-b", "payload": {"property_id": "prop-b"}}]


class _SchedTable:
    def __init__(self, name, inserts):
        self.name = name
        self.inserts = inserts

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.inserts.append(payload)
        return self

    def execute(self):
        if self.name == "gsc_properties":
            return SimpleNamespace(data=[{"id": "prop-a"}, {"id": "prop-b"}])
        return SimpleNamespace(data=[])
