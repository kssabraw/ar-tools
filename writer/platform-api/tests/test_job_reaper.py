"""Unit tests for the stale-job reaper in the async job worker.

In-process jobs (asyncio.to_thread) aren't resumable, so a redeploy/crash mid-run
leaves them stuck status='running' forever. The reaper sweeps those: re-queue
while retry attempts remain, else fail. Supabase is fully mocked — no DB.
"""

from __future__ import annotations

import asyncio

from config import settings
from services import job_worker


# ── _plan_reap (pure decision) ────────────────────────────────────────────────
def test_plan_reap_requeues_while_attempts_remain():
    update, outcome = job_worker._plan_reap(attempts=1, max_attempts=2)
    assert outcome == "requeued"
    assert update == {"status": "pending", "started_at": None}


def test_plan_reap_fails_when_attempts_exhausted():
    update, outcome = job_worker._plan_reap(attempts=2, max_attempts=2)
    assert outcome == "failed"
    assert update["status"] == "failed"
    assert "stale_timeout" in update["error"]
    assert update["completed_at"] == "now()"


# ── _reap_stale_jobs (orchestration, mocked Supabase) ─────────────────────────
class _Query:
    """Records the chained filters + the update payload for one table().update/select."""

    def __init__(self, table, rows):
        self._table = table
        self._rows = rows
        self.update_payload = None
        self.filters = {}

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self.update_payload = payload
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def lt(self, col, val):
        self.filters[(col, "lt")] = val
        return self

    def execute(self):
        # Read path returns the seeded rows; update path echoes a non-empty result
        # (a row was changed) unless the table chose to report a no-op.
        if self.update_payload is None:
            return type("R", (), {"data": self._rows})()
        self._table.updates.append(self.update_payload)
        return type("R", (), {"data": [{"id": "x"}] if self._table.update_hits else []})()


class _FakeTable:
    def __init__(self, rows, update_hits=True):
        self._rows = rows
        self.updates = []
        self.update_hits = update_hits
        self.queries = []

    def _q(self):
        q = _Query(self, self._rows)
        self.queries.append(q)
        return q

    def select(self, *a, **k):
        return self._q().select(*a, **k)

    def update(self, payload):
        return self._q().update(payload)


class _FakeSupabase:
    def __init__(self, rows, update_hits=True):
        self._table = _FakeTable(rows, update_hits)

    def table(self, _name):
        return self._table


def _run(coro):
    return asyncio.run(coro)


def _patch(monkeypatch, supabase, timeout=30):
    monkeypatch.setattr(settings, "job_stale_timeout_minutes", timeout, raising=False)
    monkeypatch.setattr(job_worker, "get_supabase", lambda: supabase)


def test_reap_requeues_and_fails_by_attempts(monkeypatch):
    rows = [
        {"id": "a", "job_type": "local_seo_silo", "attempts": 1, "max_attempts": 2},
        {"id": "b", "job_type": "maps_scan", "attempts": 2, "max_attempts": 2},
    ]
    sb = _FakeSupabase(rows)
    _patch(monkeypatch, sb)
    _run(job_worker._reap_stale_jobs())
    updates = sb._table.updates
    assert {"status": "pending", "started_at": None} in updates
    assert any(u["status"] == "failed" for u in updates)


def test_reap_noop_when_nothing_stale(monkeypatch):
    sb = _FakeSupabase([])
    _patch(monkeypatch, sb)
    _run(job_worker._reap_stale_jobs())
    assert sb._table.updates == []


def test_reap_disabled_when_timeout_zero(monkeypatch):
    sb = _FakeSupabase([{"id": "a", "attempts": 0, "max_attempts": 2}])
    _patch(monkeypatch, sb, timeout=0)
    _run(job_worker._reap_stale_jobs())
    # Disabled → it never even queries, so no updates are attempted.
    assert sb._table.updates == []
    assert sb._table.queries == []
