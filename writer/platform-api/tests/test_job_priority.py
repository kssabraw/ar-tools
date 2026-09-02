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
_STAGGERED_ENQUEUE_FILES = (
    "local_seo_service.py", "ecommerce_service.py", "wheelhouse_service.py",
    "local_seo_matrix_store.py", "syndication_service.py", "content_batch.py",
    "website_generate.py",
)


def test_staggered_enqueue_sites_stamp_background_priority():
    """Every staggered (batch) enqueue row also carries the BACKGROUND priority —
    the stagger alone decays; the priority is what actually yields to a click.
    Asserts the property on each site rather than an exact site count, so adding
    a correctly stamped batch enqueuer doesn't break this test."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "services"
    sites = 0
    for name in _STAGGERED_ENQUEUE_FILES:
        src = (root / name).read_text()
        for m in re.finditer(r'"scheduled_at": _\w+\(.*?\),\n(\s*)"(\w+)"', src):
            sites += 1
            assert m.group(2) == "priority", f"{name}: staggered enqueue not followed by priority"
    assert sites >= 9  # the 9 known sites; a regex that stops matching would read 0


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


# ── requeue resets the stale progress (review fix) ───────────────────────────
def test_plan_job_retry_resets_progress_and_names_the_wait():
    update, outcome = job_worker.plan_job_retry(
        attempts=1, max_attempts=2, transient=True, error="local_seo_provider_error",
    )
    assert outcome == "requeued"
    assert update["progress"] is None
    assert update["progress_message"] == "Temporary provider error — retrying in 5 min"
    terminal, _ = job_worker.plan_job_retry(attempts=2, max_attempts=2, transient=True, error="x")
    assert "progress_message" not in terminal


# ── idempotent resume: a retried job reuses the page it already persisted ────
class _ResumeSB:
    """Fake Supabase: `local_seo_pages` returns the seeded page for the job;
    `async_jobs` records updates."""

    def __init__(self, page):
        self.page = page
        self.writes: list[dict] = []
        self.page_queries = 0

    def table(self, name):
        sb = self

        class _T:
            def __init__(self):
                self._payload = None

            def select(self, *_a, **_k):
                sb.page_queries += 1 if name == "local_seo_pages" else 0
                return self

            def update(self, payload):
                self._payload = payload
                return self

            def eq(self, *_a): return self
            def is_(self, *_a): return self
            def order(self, *_a, **_k): return self
            def limit(self, *_a): return self

            def execute(self):
                if self._payload is not None:
                    sb.writes.append(self._payload)
                    return type("R", (), {"data": [{}]})()
                rows = [sb.page] if (name == "local_seo_pages" and sb.page) else []
                return type("R", (), {"data": rows})()

        return _T()


def test_generate_job_resumes_the_page_a_prior_attempt_persisted(monkeypatch):
    from services import local_seo_service

    sb = _ResumeSB({"id": "page-1", "composite_score": 81.0, "keyword": "k"})
    monkeypatch.setattr(local_seo_service, "get_supabase", lambda: sb)

    async def _must_not_run(**_kw):
        raise AssertionError("generate_page must not run when the job already has a page")

    monkeypatch.setattr(local_seo_service, "generate_page", _must_not_run)
    job = {"id": "j", "attempts": 2, "max_attempts": 2,
           "payload": {"client_id": "c", "keyword": "k", "location": "L", "user_id": "u"}}
    asyncio.run(local_seo_service.run_generate_job(job))
    assert sb.page_queries == 1
    assert sb.writes[-1]["status"] == "complete"
    assert sb.writes[-1]["result"] == {"page_id": "page-1"}


def test_generate_job_generates_when_no_page_exists_and_stamps_the_job(monkeypatch):
    from services import local_seo_service

    sb = _ResumeSB(None)
    monkeypatch.setattr(local_seo_service, "get_supabase", lambda: sb)
    seen = {}

    async def _gen(**kw):
        seen.update(kw)
        return {"id": "page-2"}

    monkeypatch.setattr(local_seo_service, "generate_page", _gen)
    monkeypatch.setattr(local_seo_service, "_job_progress_writer", lambda _id: None)
    job = {"id": "j2", "attempts": 1, "max_attempts": 2,
           "payload": {"client_id": "c", "keyword": "k", "location": "L", "user_id": "u"}}
    asyncio.run(local_seo_service.run_generate_job(job))
    assert seen["job_id"] == "j2"                 # the page will be stamped with the job
    assert sb.writes[-1]["result"] == {"page_id": "page-2"}


def test_reoptimize_url_job_resumes_without_rewriting(monkeypatch):
    from services import local_seo_service

    sb = _ResumeSB({"id": "page-3", "composite_score": 77.5, "keyword": "k"})
    monkeypatch.setattr(local_seo_service, "get_supabase", lambda: sb)

    async def _must_not_run(**_kw):
        raise AssertionError("reoptimize_url must not run when the job already has a page")

    monkeypatch.setattr(local_seo_service, "reoptimize_url", _must_not_run)
    job = {"id": "j3", "attempts": 2, "max_attempts": 2,
           "payload": {"client_id": "c", "keyword": "k", "location": "L",
                       "page_url": "https://x.test/p", "user_id": "u"}}
    asyncio.run(local_seo_service.run_reoptimize_url_job(job))
    result = sb.writes[-1]["result"]
    assert sb.writes[-1]["status"] == "complete"
    assert result["status"] == "reoptimized" and result["resumed"] is True
    assert result["page"]["id"] == "page-3" and result["new_score"] == 77.5


def test_page_for_job_is_best_effort(monkeypatch):
    from services import local_seo_service

    class _Boom:
        def table(self, _n):
            raise RuntimeError("db down")

    monkeypatch.setattr(local_seo_service, "get_supabase", lambda: _Boom())
    assert local_seo_service._page_for_job("j") is None
    assert local_seo_service._page_for_job(None) is None
