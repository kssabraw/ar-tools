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


# ── per-job-type timeout overrides (ops fix 2026-07-12) ───────────────────────
def test_stale_timeout_for_prefers_override(monkeypatch):
    monkeypatch.setattr(settings, "job_stale_timeout_minutes", 30, raising=False)
    monkeypatch.setattr(
        settings, "job_stale_timeout_overrides", {"gsc_page_ingest": 60}, raising=False
    )
    assert job_worker.stale_timeout_for("gsc_page_ingest") == 60
    assert job_worker.stale_timeout_for("maps_scan") == 30
    assert job_worker.stale_timeout_for(None) == 30


def test_past_timeout_parsing():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    old = (now - timedelta(minutes=61)).isoformat()
    recent = (now - timedelta(minutes=45)).isoformat()
    assert job_worker._past_timeout(old, now, 60) is True
    assert job_worker._past_timeout(recent, now, 60) is False
    # Missing/garbage started_at counts as past (historical reaper behavior).
    assert job_worker._past_timeout(None, now, 60) is True
    assert job_worker._past_timeout("garbage", now, 60) is True


def test_reap_honors_long_job_override(monkeypatch):
    """A job type with a 60-min override, 45 min into its run, survives the
    30-min sweep; the same-age default-type job is reaped."""
    from datetime import datetime, timedelta, timezone

    started_45m = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    rows = [
        {"id": "long", "job_type": "gsc_page_ingest", "attempts": 1, "max_attempts": 2,
         "started_at": started_45m},
        {"id": "norm", "job_type": "maps_scan", "attempts": 1, "max_attempts": 2,
         "started_at": started_45m},
    ]
    sb = _FakeSupabase(rows)
    _patch(monkeypatch, sb)
    monkeypatch.setattr(
        settings, "job_stale_timeout_overrides", {"gsc_page_ingest": 60}, raising=False
    )
    _run(job_worker._reap_stale_jobs())
    # Only the default-timeout job was touched.
    assert len(sb._table.updates) == 1
    reaped_ids = [q.filters.get("id") for q in sb._table.queries if q.update_payload]
    assert reaped_ids == ["norm"]


def test_reap_override_past_its_own_timeout(monkeypatch):
    """Past even the 60-min override → reaped like anything else."""
    from datetime import datetime, timedelta, timezone

    started_90m = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
    rows = [{"id": "long", "job_type": "gsc_page_ingest", "attempts": 1,
             "max_attempts": 2, "started_at": started_90m}]
    sb = _FakeSupabase(rows)
    _patch(monkeypatch, sb)
    monkeypatch.setattr(
        settings, "job_stale_timeout_overrides", {"gsc_page_ingest": 60}, raising=False
    )
    _run(job_worker._reap_stale_jobs())
    assert len(sb._table.updates) == 1


# ── interactive-lane claim filter ─────────────────────────────────────────────
class _ClaimQuery(_Query):
    def in_(self, col, vals):
        self.filters[(col, "in")] = list(vals)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self


class _ClaimTable(_FakeTable):
    def _q(self):
        q = _ClaimQuery(self, self._rows)
        self.queries.append(q)
        return q


def test_claim_filters_to_interactive_types(monkeypatch):
    t = _ClaimTable([])  # no pending jobs — we only inspect the filter
    sb = _FakeSupabase([])
    sb._table = t
    monkeypatch.setattr(job_worker, "get_supabase", lambda: sb)
    _run(job_worker._claim_next_job(["icp_scan", "website_scrape"]))
    q = t.queries[0]
    assert q.filters[("job_type", "in")] == ["icp_scan", "website_scrape"]
    assert q.filters["status"] == "pending"
    # No filter → no job_type restriction.
    _run(job_worker._claim_next_job())
    assert ("job_type", "in") not in t.queries[1].filters
