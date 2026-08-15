"""Durable Fanout pipeline (issue #686): the async_jobs envelope around every
pipeline stage (expand / plan / regate / fanout / architecture).

Since Phase 3 EVERY stage runs durably — no `fanout_durable_expand_enabled` flag,
no in-process executor, no run_recovery salvage — so these pin the shared
envelope (`_run_pipeline_durable`): the idempotent durable claim, error / cancel /
settle handling, and the enqueue + durable-marker handshake (revert-on-failure)
with the right job_type + payload per stage.

NOTE: importing `fanout.jobs` pulls in the full pipeline dependency stack
(numpy/networkx/spaCy/anthropic/…), so this module runs in CI, not the sandbox.
"""

import contextlib
import types

import pytest

import fanout.jobs as jobs
from fanout.cancellation import CancelledByUser


@contextlib.contextmanager
def _noop_meter(*_a, **_k):
    yield


def _boom(*_a, **_k):
    raise RuntimeError("dfs 500")


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


def _patch_envelope(monkeypatch, store):
    """Patch the shared durable-envelope dependencies."""
    monkeypatch.setattr(jobs, "store", store)
    monkeypatch.setattr(jobs, "metered_run", _noop_meter)
    monkeypatch.setattr(jobs, "bind_session_id", lambda *_a, **_k: None)
    monkeypatch.setattr(jobs.cancellation, "clear", lambda *_a, **_k: None)


def _patch_durable(monkeypatch, store, core):
    """Expand path: run_expand_durable calls _run_expand_core -> _expand_core;
    patching _expand_core drives behavior with the resumable flag defaulting off."""
    _patch_envelope(monkeypatch, store)
    monkeypatch.setattr(jobs, "_expand_core", core)


# ---- run_expand_durable: claim / settle (representative of the shared envelope)

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
    envelope must not write an error/cancelled status over it."""
    store = _Store(runnable=True)
    _patch_durable(monkeypatch, store, lambda sid: None)
    jobs.run_expand_durable("s1")
    assert store.finalized == []


def test_durable_pipeline_error_is_recorded_as_error(monkeypatch):
    store = _Store(runnable=True)
    _patch_durable(monkeypatch, store, _boom)
    jobs.run_expand_durable("s1")
    assert [f[1]["status"] for f in store.finalized] == ["error"]
    assert "dfs 500" in store.finalized[0][1]["last_error"]


def test_durable_cancel_is_recorded_as_cancelled(monkeypatch):
    """CancelledByUser is a BaseException (bypasses the pipeline's per-stage
    `except Exception`), so the envelope catches it explicitly and finalizes
    cancelled rather than error."""
    store = _Store(runnable=True)

    def cancel(_sid):
        raise CancelledByUser("s1")

    _patch_durable(monkeypatch, store, cancel)
    jobs.run_expand_durable("s1")
    assert [f[1]["status"] for f in store.finalized] == ["cancelled"]


def test_durable_error_clears_checkpoint_when_resumable(monkeypatch):
    """Resumable flag on (Phase 2): a terminal error clears the resumable
    checkpoint so a requeue starts fresh rather than resuming stale partial work.
    (Flag off, the other durable tests prove the clear is a no-op — the store's
    checkpoint methods are never touched.)"""
    store = _Store(runnable=True)
    cleared: list[str] = []
    store.clear_expansion_checkpoint = lambda sid: cleared.append(sid)
    _patch_envelope(monkeypatch, store)
    monkeypatch.setattr(
        jobs, "get_settings",
        lambda: types.SimpleNamespace(fanout_resumable_expand_enabled=True),
    )
    monkeypatch.setattr(jobs, "_run_expand_core", _boom)
    jobs.run_expand_durable("s1")
    assert cleared == ["s1"]
    assert [f[1]["status"] for f in store.finalized] == ["error"]


# ---- the shared envelope covers every stage (Phase 3) ----------------------

# (core attribute to patch, a thunk that invokes the stage's durable handler)
_STAGES = [
    ("_plan_core", lambda: jobs.run_plan_durable("s1", False)),
    ("_regate_core", lambda: jobs.run_regate_durable("s1", 0.6, 0.5, 1.0, 0, [], [], None)),
    ("_fanout_core", lambda: jobs.run_fanout_durable("s1", 0.6, 0.5, 1.0, 0, [], [])),
    ("_architecture_core", lambda: jobs.run_architecture_durable("s1")),
]


@pytest.mark.parametrize("core_attr, run", _STAGES)
def test_new_stage_error_settles_via_envelope(monkeypatch, core_attr, run):
    """Every durable stage rides the same envelope: a pipeline error settles the
    session error (the async_jobs row still completes — no auto-retry/re-spend)."""
    store = _Store(runnable=True)
    _patch_envelope(monkeypatch, store)
    monkeypatch.setattr(jobs, core_attr, _boom)
    run()
    assert [f[1]["status"] for f in store.finalized] == ["error"]
    assert "dfs 500" in store.finalized[0][1]["last_error"]


@pytest.mark.parametrize("core_attr, run", _STAGES)
def test_new_stage_skips_when_not_runnable(monkeypatch, core_attr, run):
    """A non-claimable (cancelled/finished) session skips without running the
    core or writing a terminal status."""
    store = _Store(runnable=False)
    ran = []
    _patch_envelope(monkeypatch, store)
    monkeypatch.setattr(jobs, core_attr, lambda *_a, **_k: ran.append(1))
    run()
    assert store.mark_calls == 1
    assert ran == []
    assert store.finalized == []


@pytest.mark.parametrize("core_attr, run", _STAGES)
def test_new_stage_cancel_settles_cancelled(monkeypatch, core_attr, run):
    store = _Store(runnable=True)
    _patch_envelope(monkeypatch, store)

    def cancel(*_a, **_k):
        raise CancelledByUser("s1")

    monkeypatch.setattr(jobs, core_attr, cancel)
    run()
    assert [f[1]["status"] for f in store.finalized] == ["cancelled"]


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
    jobs._enqueue_durable("s1", "fanout_expand", "expand")
    assert sink["table"] == "async_jobs"
    assert sink["row"]["job_type"] == "fanout_expand"
    assert sink["row"]["entity_id"] == "s1"
    assert sink["row"]["payload"] == {"session_id": "s1"}
    # durable marker set exactly once, never reverted
    assert store.active_jobs == [("s1", {"kind": "expand", "durable": True})]


def test_enqueue_durable_folds_payload_extra(monkeypatch):
    store = _Store()
    sink: dict = {}
    monkeypatch.setattr(jobs, "store", store)
    monkeypatch.setattr("db.supabase_client.get_supabase", lambda: _SB(sink))
    jobs._enqueue_durable("s1", "fanout_plan", "plan", {"direct": True})
    assert sink["row"]["job_type"] == "fanout_plan"
    assert sink["row"]["payload"] == {"session_id": "s1", "direct": True}


def test_enqueue_durable_reverts_marker_when_enqueue_fails(monkeypatch):
    """If the async_jobs insert fails, revert the durable marker and re-raise so
    the endpoint surfaces the failure rather than leaving a queued-but-unworked
    run."""
    store = _Store()
    sink: dict = {}
    monkeypatch.setattr(jobs, "store", store)
    monkeypatch.setattr("db.supabase_client.get_supabase", lambda: _SB(sink, fail=True))
    with pytest.raises(RuntimeError):
        jobs._enqueue_durable("s1", "fanout_expand", "expand")
    assert store.active_jobs == [
        ("s1", {"kind": "expand", "durable": True}),
        ("s1", {"kind": "expand"}),
    ]


# ---- submit_* endpoints all enqueue durable rows (no flag, no executor) -----

_SUBMITS = [
    (lambda: jobs.submit_expand("s1"), "fanout_expand", {"session_id": "s1"}),
    (lambda: jobs.submit_plan("s1", direct=True), "fanout_plan",
     {"session_id": "s1", "direct": True}),
    (lambda: jobs.submit_architecture("s1"), "fanout_architecture", {"session_id": "s1"}),
    (lambda: jobs.submit_regate("s1", 0.6, 0.5, 1.0, 10, ["a"], ["b"], 0.1), "fanout_regate",
     {"session_id": "s1", "threshold": 0.6, "edge_threshold": 0.5, "resolution": 1.0,
      "active_per_silo_cap": 10, "seed_terms": ["a"], "peer_terms": ["b"], "silo_margin": 0.1}),
    (lambda: jobs.submit_fanout("s1", 0.6, 0.5, 1.0, 10, ["a"], ["b"]), "fanout_fanout",
     {"session_id": "s1", "threshold": 0.6, "edge_threshold": 0.5, "resolution": 1.0,
      "active_per_silo_cap": 10, "seed_terms": ["a"], "peer_terms": ["b"]}),
]


@pytest.mark.parametrize("submit, job_type, payload", _SUBMITS)
def test_submit_enqueues_durable_row(monkeypatch, submit, job_type, payload):
    """Every pipeline endpoint enqueues a durable async_jobs row with the right
    job_type + full payload — the only path since Phase 3."""
    store = _Store()
    sink: dict = {}
    monkeypatch.setattr(jobs, "store", store)
    monkeypatch.setattr("db.supabase_client.get_supabase", lambda: _SB(sink))
    submit()
    assert sink["row"]["job_type"] == job_type
    assert sink["row"]["entity_id"] == "s1"
    assert sink["row"]["payload"] == payload
