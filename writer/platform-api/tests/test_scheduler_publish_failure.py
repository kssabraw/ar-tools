"""Tests for the content scheduler's publish-failure surfacing
(fanout.writer.scheduler._record_publish_failure / _notify_publish_failure).

A scheduled article that generates fine but fails to publish — e.g. a host
firewall 400-ing the WordPress REST call, the Nova Life Peptides incident — must
not read as a clean `complete`: the reason is written to the run's `publish_error`
and a `content_publish_failed` notification is emitted so a human sees it instead
of it being swallowed. Exercised with a recording fake of the supabase client +
a stubbed notifier — no network.
"""

from __future__ import annotations

from unittest.mock import patch

from fanout.writer import scheduler


class _Table:
    def __init__(self, name, log, fail=False):
        self.ctx = {"table": name, "op": "select", "eq": {}, "payload": None}
        self._log = log
        self._fail = fail

    def update(self, payload):
        self.ctx["op"] = "update"
        self.ctx["payload"] = payload
        return self

    def eq(self, key, val):
        self.ctx["eq"][key] = val
        return self

    def execute(self):
        self._log.append(dict(self.ctx))
        if self._fail:
            raise RuntimeError("db down")
        return type("R", (), {"data": [{"id": "r1"}]})()


class _Client:
    def __init__(self, fail=False):
        self.log = []
        self._fail = fail

    def table(self, name):
        return _Table(name, self.log, self._fail)


# --- _record_publish_failure ------------------------------------------------


def test_record_publish_failure_writes_error_and_notifies():
    row = {"id": "r1", "cluster_id": "c1", "session_id": "s1", "content_schedule_id": "sch1"}
    client = _Client()
    with patch("fanout.writer.scheduler.get_service_client", return_value=client), \
         patch("fanout.writer.scheduler._notify_publish_failure") as notify:
        scheduler._record_publish_failure(
            "r1", row, "cl1", [("WordPress", "boom"), ("Google Drive", "nope")])

    updates = [c for c in client.log if c["op"] == "update"]
    assert len(updates) == 1
    # Both channels' reasons combined, scoped to this run.
    assert updates[0]["payload"]["publish_error"] == "WordPress: boom; Google Drive: nope"
    assert updates[0]["eq"] == {"id": "r1"}
    notify.assert_called_once()
    assert notify.call_args.args[0] is row and notify.call_args.args[1] == "cl1"


def test_record_publish_failure_swallows_db_error_and_still_notifies():
    # A failed publish_error write must not skip the alert (the alert is the point).
    client = _Client(fail=True)
    with patch("fanout.writer.scheduler.get_service_client", return_value=client), \
         patch("fanout.writer.scheduler._notify_publish_failure") as notify:
        scheduler._record_publish_failure("r1", {"id": "r1"}, "cl1", [("WordPress", "boom")])
    notify.assert_called_once()


# --- _notify_publish_failure ------------------------------------------------


def test_notify_publish_failure_emits_warning():
    import services.notifications as notifications_mod

    row = {"id": "r1", "cluster_id": "c1", "session_id": "s1", "content_schedule_id": "sch1"}
    with patch.object(notifications_mod, "emit", return_value="n1") as emit:
        scheduler._notify_publish_failure(row, "cl1", [("WordPress", "boom")])

    emit.assert_called_once()
    assert emit.call_args.args[0] == "cl1"                       # client_id positional
    kw = emit.call_args.kwargs
    assert kw["kind"] == "content_publish_failed"
    assert kw["severity"] == "warning"
    assert kw["payload"]["run_id"] == "r1" and kw["payload"]["cluster_id"] == "c1"


def test_notify_publish_failure_resolves_client_from_session():
    import services.notifications as notifications_mod

    row = {"id": "r1", "session_id": "s1"}
    with patch.object(notifications_mod, "emit", return_value="n1") as emit, \
         patch("fanout.storage.silo.get_session", return_value={"client_id": "resolved"}):
        scheduler._notify_publish_failure(row, None, [("WordPress", "boom")])
    assert emit.call_args.args[0] == "resolved"


def test_notify_publish_failure_never_raises():
    import services.notifications as notifications_mod

    with patch.object(notifications_mod, "emit", side_effect=RuntimeError("emit down")):
        # A notification blip can't break the worker.
        scheduler._notify_publish_failure({"id": "r1"}, "cl1", [("WordPress", "boom")])
