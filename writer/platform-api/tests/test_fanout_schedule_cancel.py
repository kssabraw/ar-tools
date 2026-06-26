"""Tests for the Topic Fanout per-article cancel path
(fanout.writer.schedule_store.cancel_run / complete_if_drained).

These exercise the store layer with a recording fake of the supabase service
client — no network. The key guarantees under test:

  * cancel_run only cancels a run that is still `queued` (the update is
    filtered on status='queued'), so it cannot stomp a run the worker has
    already claimed (running) — and reports whether it actually cancelled.
  * complete_if_drained settles an active parent schedule to `complete` once
    no queued/running runs remain, and leaves it alone otherwise.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class _Table:
    """A chainable fake of a supabase table query. Records the op type, eq
    filters, in_ filters, and payload; `execute()` returns whatever the
    `responder(ctx)` callback yields for the accumulated context."""

    def __init__(self, name: str, responder, log: list[dict]):
        self.ctx = {"table": name, "op": "select", "eq": {}, "in": {}, "payload": None}
        self._responder = responder
        self._log = log

    def select(self, *args, **kwargs):
        self.ctx["op"] = "select"
        return self

    def update(self, payload):
        self.ctx["op"] = "update"
        self.ctx["payload"] = payload
        return self

    def insert(self, payload):
        self.ctx["op"] = "insert"
        self.ctx["payload"] = payload
        return self

    def eq(self, k, v):
        self.ctx["eq"][k] = v
        return self

    def in_(self, k, v):
        self.ctx["in"][k] = v
        return self

    def limit(self, *_):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, *_):
        return self

    def execute(self):
        self._log.append(dict(self.ctx))
        data = self._responder(self.ctx)

        class _Res:
            def __init__(self, d):
                self.data = d

        return _Res(data)


class _Client:
    def __init__(self, responder):
        self.log: list[dict] = []
        self._responder = responder

    def table(self, name: str) -> _Table:
        return _Table(name, self._responder, self.log)


def _patched(responder):
    """Patch the store's service-client factory to return our fake."""
    client = _Client(responder)
    return patch(
        "fanout.writer.schedule_store.get_service_client", return_value=client
    ), client


# ---------------------------------------------------------------------------
# cancel_run
# ---------------------------------------------------------------------------


def test_cancel_run_cancels_queued_run_and_filters_on_status():
    from fanout.writer import schedule_store

    # An UPDATE that matched a queued row returns that row.
    def responder(ctx):
        if ctx["op"] == "update":
            return [{"id": "run-1", "status": "cancelled"}]
        return []

    p, client = _patched(responder)
    with p:
        assert schedule_store.cancel_run("run-1") is True

    upd = [c for c in client.log if c["op"] == "update"]
    assert len(upd) == 1
    # Race-safety: the cancel is scoped to this run AND only while still queued.
    assert upd[0]["eq"] == {"id": "run-1", "status": "queued"}
    assert upd[0]["payload"] == {"status": "cancelled"}


def test_cancel_run_noops_when_already_claimed():
    from fanout.writer import schedule_store

    # The worker already moved the row to `running`, so the status-filtered
    # update matches nothing and returns no rows.
    def responder(ctx):
        return []

    p, _client = _patched(responder)
    with p:
        assert schedule_store.cancel_run("run-1") is False


# ---------------------------------------------------------------------------
# complete_if_drained
# ---------------------------------------------------------------------------


def test_complete_if_drained_completes_active_schedule_when_empty():
    from fanout.writer import schedule_store

    def responder(ctx):
        if ctx["table"] == "scheduled_article_runs" and ctx["op"] == "select":
            return []  # no queued/running runs left
        if ctx["table"] == "content_schedules" and ctx["op"] == "select":
            return [{"id": "sch-1", "status": "active"}]
        return []

    p, client = _patched(responder)
    with p:
        schedule_store.complete_if_drained("sch-1")

    sched_updates = [
        c for c in client.log
        if c["table"] == "content_schedules" and c["op"] == "update"
    ]
    assert len(sched_updates) == 1
    assert sched_updates[0]["payload"] == {"status": "complete"}


def test_complete_if_drained_noop_when_runs_pending():
    from fanout.writer import schedule_store

    def responder(ctx):
        if ctx["table"] == "scheduled_article_runs" and ctx["op"] == "select":
            return [{"id": "still-queued"}]  # pending work remains
        if ctx["table"] == "content_schedules" and ctx["op"] == "select":
            return [{"id": "sch-1", "status": "active"}]
        return []

    p, client = _patched(responder)
    with p:
        schedule_store.complete_if_drained("sch-1")

    assert not [c for c in client.log if c["table"] == "content_schedules" and c["op"] == "update"]


def test_complete_if_drained_leaves_non_active_schedule_alone():
    from fanout.writer import schedule_store

    # Drained, but the parent was already cancelled — don't flip it to complete.
    def responder(ctx):
        if ctx["table"] == "scheduled_article_runs" and ctx["op"] == "select":
            return []
        if ctx["table"] == "content_schedules" and ctx["op"] == "select":
            return [{"id": "sch-1", "status": "cancelled"}]
        return []

    p, client = _patched(responder)
    with p:
        schedule_store.complete_if_drained("sch-1")

    assert not [c for c in client.log if c["table"] == "content_schedules" and c["op"] == "update"]
