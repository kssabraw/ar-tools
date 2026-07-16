"""Tests for the content scheduler's transient-failure handling
(fanout.writer.scheduler._retry_or_fail).

Exercised with a recording fake of the supabase service client — no network.
The guarantees under test:

  * A failure under the attempt cap requeues the run to `queued` with the
    attempt counter incremented and the write scoped to `status='running'`.
  * That status scope means a run cancelled mid-generation (running -> cancelled)
    is NOT resurrected: the guarded update no-ops and nothing is dead-lettered
    or notified.
  * At the attempt cap the run is dead-lettered (`failed`) and a notification is
    emitted — but only when the row was still `running` (a matched update).
  * `immediate=True` (restart recovery) requeues due-now with no backoff.
"""

from __future__ import annotations

from unittest.mock import patch


class _Table:
    """Chainable fake of a supabase table query. Records op, eq filters, and
    payload; `execute()` returns whatever `responder(ctx)` yields."""

    def __init__(self, name, responder, log):
        self.ctx = {"table": name, "op": "select", "eq": {}, "payload": None}
        self._responder = responder
        self._log = log

    def select(self, *a, **k):
        self.ctx["op"] = "select"
        return self

    def update(self, payload):
        self.ctx["op"] = "update"
        self.ctx["payload"] = payload
        return self

    def eq(self, key, val):
        self.ctx["eq"][key] = val
        return self

    def execute(self):
        self._log.append(dict(self.ctx))

        class _Res:
            def __init__(self, d):
                self.data = d

        return _Res(self._responder(self.ctx))


class _Client:
    def __init__(self, responder):
        self.log = []
        self._responder = responder

    def table(self, name):
        return _Table(name, self._responder, self.log)


def _run(row, responder, **kwargs):
    """Call _retry_or_fail with a fake client and a stubbed notifier; return
    (client_log, notify_mock)."""
    from fanout.writer import scheduler

    client = _Client(responder)
    with patch("fanout.writer.scheduler.get_service_client", return_value=client), \
         patch("fanout.writer.scheduler._notify_dead_letter") as notify:
        scheduler._retry_or_fail(row, "content generation failed", **kwargs)
    return client.log, notify


# --- requeue under the cap --------------------------------------------------


def test_retry_requeues_when_running_and_under_cap():
    row = {"id": "r1", "attempts": 0, "cluster_id": "c1", "session_id": "s1",
           "content_schedule_id": "sch1"}
    # The guarded update matched a still-running row.
    log, notify = _run(row, lambda ctx: [{"id": "r1"}] if ctx["op"] == "update" else [],
                       client_id="cl1")

    updates = [c for c in log if c["op"] == "update"]
    assert len(updates) == 1
    assert updates[0]["payload"]["status"] == "queued"
    assert updates[0]["payload"]["attempts"] == 1           # incremented from 0
    # Write is scoped to this run AND only while still running (the anti-resurrection guard).
    assert updates[0]["eq"] == {"id": "r1", "status": "running"}
    notify.assert_not_called()


def test_retry_noops_when_cancelled_midflight():
    # User cancelled the run mid-generation, so the status-scoped update matches
    # nothing (returns no rows). The run must NOT be resurrected or dead-lettered.
    row = {"id": "r1", "attempts": 0, "session_id": "s1"}
    log, notify = _run(row, lambda ctx: [])

    updates = [c for c in log if c["op"] == "update"]
    assert len(updates) == 1                                # attempted, but guarded
    assert updates[0]["payload"]["status"] == "queued"
    assert updates[0]["eq"]["status"] == "running"
    notify.assert_not_called()                              # no zombie, no alert


def test_immediate_requeue_has_no_backoff_but_same_guard():
    # Restart recovery: requeue due-now (scheduled_at ~ now), still guarded on running.
    row = {"id": "r1", "attempts": 1, "session_id": "s1"}
    log, notify = _run(row, lambda ctx: [{"id": "r1"}] if ctx["op"] == "update" else [],
                       immediate=True)

    upd = [c for c in log if c["op"] == "update"][0]
    assert upd["payload"]["status"] == "queued"
    assert upd["payload"]["attempts"] == 2
    assert upd["eq"] == {"id": "r1", "status": "running"}
    notify.assert_not_called()


# --- dead-letter at the cap -------------------------------------------------


def test_dead_letter_at_max_attempts_notifies():
    # attempts=3 -> next=4 == default max_attempts(4) -> should_retry False -> dead-letter.
    row = {"id": "r1", "attempts": 3, "cluster_id": "c1", "session_id": "s1",
           "content_schedule_id": "sch1"}
    log, notify = _run(row, lambda ctx: [{"id": "r1"}] if ctx["op"] == "update" else [],
                       client_id="cl1")

    upd = [c for c in log if c["op"] == "update"][0]
    assert upd["payload"]["status"] == "failed"
    assert upd["payload"]["attempts"] == 4
    assert upd["eq"] == {"id": "r1", "status": "running"}   # guarded here too
    notify.assert_called_once()
    # Notified with the resolved client and the final attempt count.
    args = notify.call_args.args
    assert args[0] is row and args[1] == "cl1" and args[2] == 4


def test_dead_letter_skipped_when_cancelled_at_cap():
    # Out of attempts AND the row was cancelled mid-flight -> update matches nothing,
    # so we neither mark it failed-over-cancelled nor fire a false alert.
    row = {"id": "r1", "attempts": 3, "session_id": "s1"}
    log, notify = _run(row, lambda ctx: [])

    upd = [c for c in log if c["op"] == "update"][0]
    assert upd["payload"]["status"] == "failed"
    assert upd["eq"]["status"] == "running"
    notify.assert_not_called()
