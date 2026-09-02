"""Unit tests for async_jobs queue priority + the bulk/interactive lane fences
(2026-09-02). Supabase is fully mocked — the claim's query chain is recorded so
the ordering and the priority band filters are asserted directly.

Background: bulk flows stamped their per-item jobs 3 minutes apart so a
now-dated interactive job would sort ahead of the rest of a batch. A page
generation takes 10–12 minutes across two lanes, so within ~7 jobs every
remaining bulk timestamp was in the past and clicks queued behind 30+ pages.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

from config import settings
from services import job_priority, job_worker


# ── recording fake ───────────────────────────────────────────────────────────
class _Query:
    def __init__(self, table):
        self._table = table
        self.filters: list[tuple] = []
        self.orders: list[tuple] = []
        self.update_payload = None
        self._negate = False

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self.update_payload = payload
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def _f(self, op, col, val):
        self.filters.append((("not_" if self._negate else "") + op, col, val))
        self._negate = False
        return self

    def eq(self, col, val):
        return self._f("eq", col, val)

    def in_(self, col, vals):
        return self._f("in", col, vals)

    def gte(self, col, val):
        return self._f("gte", col, val)

    def lte(self, col, val):
        return self._f("lte", col, val)

    def order(self, col, desc=False):
        self.orders.append((col, desc))
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        self._table.queries.append(self)
        if self.update_payload is None:
            return type("R", (), {"data": list(self._table.rows)})()
        self._table.updates.append(({col: val for _op, col, val in self.filters}, self.update_payload))
        return type("R", (), {"data": [{"id": "claimed", **self.update_payload}]})()


class _FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.queries: list[_Query] = []
        self.updates: list = []

    def select(self, *a, **k):
        return _Query(self).select(*a, **k)

    def update(self, payload):
        return _Query(self).update(payload)


class _FakeSupabase:
    def __init__(self, rows):
        self.table_ = _FakeTable(rows)

    def table(self, _name):
        return self.table_


def _claim(monkeypatch, rows, **kwargs):
    sb = _FakeSupabase(rows)
    monkeypatch.setattr(job_worker, "get_supabase", lambda: sb)
    job = asyncio.run(job_worker._claim_next_job(**kwargs))
    read = sb.table_.queries[0]
    return job, read, sb


# ── constants ────────────────────────────────────────────────────────────────
def test_priority_constants():
    assert job_priority.INTERACTIVE == 0
    assert job_priority.BACKGROUND < job_priority.INTERACTIVE


# ── claim ordering + fences ──────────────────────────────────────────────────
def test_claim_orders_by_priority_then_scheduled_at(monkeypatch):
    _, read, _ = _claim(monkeypatch, [])
    assert read.orders == [("priority", True), ("scheduled_at", False)]


def test_claim_without_bands_adds_no_priority_filter(monkeypatch):
    _, read, _ = _claim(monkeypatch, [], job_types=["x"], exclude_types=["y"])
    ops = [f[0] for f in read.filters]
    assert "gte" not in ops and "lte" not in ops
    assert ("in", "job_type", ["x"]) in read.filters
    assert ("not_in", "job_type", ["y"]) in read.filters


def test_interactive_band_excludes_background_rows(monkeypatch):
    _, read, _ = _claim(monkeypatch, [], priority_min=job_priority.INTERACTIVE)
    assert ("gte", "priority", 0) in read.filters
    assert not any(f[0] == "lte" for f in read.filters)


def test_bulk_band_claims_only_background_rows(monkeypatch):
    _, read, _ = _claim(monkeypatch, [], priority_max=job_priority.BACKGROUND)
    assert ("lte", "priority", -1) in read.filters
    assert not any(f[0] == "gte" for f in read.filters)


def test_claim_marks_first_claimable_row_running(monkeypatch):
    rows = [{"id": "j1", "job_type": "local_seo_generate", "attempts": 0, "max_attempts": 2}]
    job, _, sb = _claim(monkeypatch, rows)
    assert job["id"] == "claimed" and job["status"] == "running"
    filters, payload = sb.table_.updates[0]
    assert filters == {"id": "j1", "status": "pending"}  # guarded claim


# ── bulk enqueuers stamp BACKGROUND ──────────────────────────────────────────
def test_bulk_enqueue_sites_stamp_background_priority():
    """Every `_bulk_scheduled_at` enqueue row also carries the BACKGROUND
    priority — the stagger alone decays; the priority is what actually yields."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "services"
    sites = 0
    for name in ("local_seo_service.py", "ecommerce_service.py",
                 "wheelhouse_service.py", "local_seo_matrix_store.py"):
        src = (root / name).read_text()
        for m in re.finditer(r'"scheduled_at": _bulk_scheduled_at\(.*?\),\n(\s*)"(\w+)"', src):
            sites += 1
            assert m.group(2) == "priority", f"{name}: scheduled_at not followed by priority"
    assert sites == 6


# ── handler failures route through the retry planner ─────────────────────────
def test_local_seo_generate_transient_failure_requeues(monkeypatch):
    """A 5xx from nlp (provider error) re-queues the job instead of failing it
    terminally — the two 2026-09-02 batch failures at `attempts: 1` never retried."""
    from services import local_seo_service

    writes: list[dict] = []

    class _T:
        def update(self, payload):
            writes.append(payload)
            return self

        def eq(self, *_a):
            return self

        def execute(self):
            return type("R", (), {"data": [{}]})()

    class _SB:
        def table(self, _n):
            return _T()

    async def _boom(**_kw):
        raise HTTPException(status_code=502, detail="local_seo_provider_error")

    monkeypatch.setattr(local_seo_service, "get_supabase", lambda: _SB())
    monkeypatch.setattr(job_worker, "get_supabase", lambda: _SB())
    monkeypatch.setattr(local_seo_service, "generate_page", _boom)
    monkeypatch.setattr(local_seo_service, "_job_progress_writer", lambda _id: None)

    job = {"id": "j", "attempts": 1, "max_attempts": 2,
           "payload": {"client_id": "c", "keyword": "k", "location": "L", "user_id": "u"}}
    asyncio.run(local_seo_service.run_generate_job(job))
    assert writes and writes[-1]["status"] == "pending"
    assert "transient" in writes[-1]["error"]

    # last attempt ⇒ terminal
    writes.clear()
    job["attempts"] = 2
    asyncio.run(local_seo_service.run_generate_job(job))
    assert writes[-1]["status"] == "failed"


def test_bulk_lane_width_setting_default():
    # Owner ruling 2026-09-02: raised 1 → 3 (three bulk pages generate at once;
    # the bulk_lane_max_per_client fairness cap engages at >1). Pair with the
    # Anthropic key pool — see the HANDOFF bulk-throughput tuning recipe.
    assert settings.bulk_lane_workers == 3
