"""Durable Fanout expansion (issue #686 Phase 1): the async_jobs envelope around
the expand pipeline.

The pipeline body itself (`_expand_core`) is unchanged and only runs live, so
these pin the envelope logic instead: the idempotent durable claim, the
error/cancel/settle handling, the enqueue + durable-marker handshake (and its
revert-on-failure), and the flag routing between the durable and executor paths.

NOTE: importing `fanout.jobs` pulls in the full pipeline dependency stack
(numpy/networkx/spaCy/anthropic/…), so this module runs in CI, not the sandbox.
The lighter run_recovery durable-skip case lives in test_fanout_run_recovery.py.
"""

import contextlib
import types

import pytest

import fanout.jobs as jobs
from fanout.cancellation import CancelledByUser


@contextlib.contextmanager
def _noop_meter(*_a, **_k):
    yield


class _Store:
    def __init__(self, runnable=True):
        self.runnable = runnable
        self.mark_calls = 0
        self.finalized: list[tuple[str, dict]] = []
        self.active_jobs: list[tuple[str, dict]] = []

    def try_mark_running_durable(self, session_id):
        self.mark_calls += 1
        return self.runnable

    def try_finalize_running(self, session_id, fields):
        self.finalized.append((session_id, fields))
        return True

    def set_active_job(self, session_id, payload):
        self.active_jobs.append((session_id, payload))


def _patch_durable(monkeypatch, store, core):
    monkeypatch.setattr(jobs, "store", store)
    monkeypatch.setattr(jobs, "metered_run", _noop_meter)
    monkeypatch.setattr(jobs, "_expand_core", core)
    monkeypatch.setattr(jobs, "bind_session_id", lambda *_a, **_k: None)
    monkeypatch.setattr(jobs.cancellation, "clear", lambda *_a, **_k: None)


# ---- run_expand_durable: claim / settle -----------------------------------

def test_durable_skips_when_session_not_runnable(monkeypatch):
    """A cancelled session — or an already-finished run whose row got requeued —
    is no longer queued/running, so the claim returns False and we neither run the
    pipeline nor clobber the terminal status."""
    store = _Store(runnable=False)
    ran = []
    _patch_durable(monkeypatch, store, lambda sid: ran.append(sid))
    jobs.run_expand_durable("s1")
    assert store.mark_calls == 1
    assert ran == []
    assert store.finalized == []


def test_durable_success_leaves_terminal_status_to_core(monkeypatch):
    """On success `_expand_core` writes awaiting_article_planning itself; the
    wrapper must not write an error/cancelled status over it."""
    store = _Store(runnable=True)
    _patch_durable(monkeypatch, store, lambda sid: None)
    jobs.run_expand_durable("s1")
    assert store.finalized == []


def test_durable_pipeline_error_is_recorded_as_error(monkeypatch):
    store = _Store(runnable=True)

    def boom(_sid):
        raise RuntimeError("dfs 500")

    _patch_durable(monkeypatch, store, boom)
    jobs.run_expand_durable("s1")
    assert [f[1]["status"] for f in store.finalized] == ["error"]
    assert "dfs 500" in store.finalized[0][1]["last_error"]


def test_durable_cancel_is_recorded_as_cancelled(monkeypatch):
    """CancelledByUser is a BaseException (bypasses the pipeline's per-stage
    `except Exception`), so the wrapper catches it explicitly and finalizes
    cancelled rather than error."""
    store = _Store(runnable=True)

    def cancel(_sid):
        raise CancelledByUser("s1")

    _patch_durable(monkeypatch, store, cancel)
    jobs.run_expand_durable("s1")
    assert [f[1]["status"] for f in store.finalized] == ["cancelled"]


def test_durable_error_clears_checkpoint_when_resumable(monkeypatch):
    """Flag on (Phase 2): a terminal error clears the resumable checkpoint so a
    requeue starts fresh rather than resuming stale partial work. (Flag off, the
    other durable tests prove the clear is a no-op — the store's checkpoint
    methods are never touched.)"""
    store = _Store(runnable=True)
    cleared: list[str] = []
    store.clear_expansion_checkpoint = lambda sid: cleared.append(sid)
    monkeypatch.setattr(jobs, "store", store)
    monkeypatch.setattr(jobs, "metered_run", _noop_meter)
    monkeypatch.setattr(jobs, "bind_session_id", lambda *_a, **_k: None)
    monkeypatch.setattr(jobs.cancellation, "clear", lambda *_a, **_k: None)
    monkeypatch.setattr(
        jobs, "get_settings",
        lambda: types.SimpleNamespace(fanout_resumable_expand_enabled=True),
    )

    def boom(_sid):
        raise RuntimeError("dfs 500")

    monkeypatch.setattr(jobs, "_run_expand_core", boom)
    jobs.run_expand_durable("s1")
    assert cleared == ["s1"]
    assert [f[1]["status"] for f in store.finalized] == ["error"]


# ---- enqueue + durable-marker handshake -----------------------------------

class _Tbl:
    def __init__(self, sink, fail):
        self._sink = sink
        self._fail = fail

    def insert(self, row):
        self._sink["row"] = row
        return self

    def execute(self):
        if self._fail:
            raise RuntimeError("insert failed")
        return None


class _SB:
    def __init__(self, sink, fail=False):
        self._sink = sink
        self._fail = fail

    def table(self, name):
        self._sink["table"] = name
        return _Tbl(self._sink, self._fail)


def test_enqueue_durable_marks_then_enqueues(monkeypatch):
    store = _Store()
    sink: dict = {}
    monkeypatch.setattr(jobs, "store", store)
    monkeypatch.setattr("db.supabase_client.get_supabase", lambda: _SB(sink))
    jobs._enqueue_durable_expand("s1")
    assert sink["table"] == "async_jobs"
    assert sink["row"]["job_type"] == "fanout_expand"
    assert sink["row"]["entity_id"] == "s1"
    assert sink["row"]["payload"] == {"session_id": "s1"}
    # durable marker set exactly once, never reverted
    assert store.active_jobs == [("s1", {"kind": "expand", "durable": True})]


def test_enqueue_durable_reverts_marker_when_enqueue_fails(monkeypatch):
    """If the async_jobs insert fails, revert the durable marker so the still-queued
    session falls back to run_recovery salvage instead of being ignored by both."""
    store = _Store()
    sink: dict = {}
    monkeypatch.setattr(jobs, "store", store)
    monkeypatch.setattr("db.supabase_client.get_supabase", lambda: _SB(sink, fail=True))
    with pytest.raises(RuntimeError):
        jobs._enqueue_durable_expand("s1")
    assert store.active_jobs == [
        ("s1", {"kind": "expand", "durable": True}),
        ("s1", {"kind": "expand"}),
    ]


# ---- flag routing ----------------------------------------------------------

def test_submit_expand_routes_on_flag(monkeypatch):
    calls = {"durable": 0, "executor": 0}
    monkeypatch.setattr(
        jobs, "_enqueue_durable_expand", lambda _sid: calls.__setitem__("durable", calls["durable"] + 1)
    )
    monkeypatch.setattr(jobs, "_record_active_job", lambda *_a, **_k: None)

    class _Exec:
        def submit(self, *_a, **_k):
            calls["executor"] += 1

    monkeypatch.setattr(jobs, "_EXECUTOR", _Exec())

    monkeypatch.setattr(
        jobs, "get_settings", lambda: types.SimpleNamespace(fanout_durable_expand_enabled=True)
    )
    jobs.submit_expand("s1")
    assert calls == {"durable": 1, "executor": 0}

    monkeypatch.setattr(
        jobs, "get_settings", lambda: types.SimpleNamespace(fanout_durable_expand_enabled=False)
    )
    jobs.submit_expand("s2")
    assert calls == {"durable": 1, "executor": 1}
