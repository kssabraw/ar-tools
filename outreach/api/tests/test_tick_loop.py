"""The always-on worker (`tick-loop`) — the daemon that drains signed orders within seconds.

What matters: it is a registered command, it is NOT spend-gated (its spend is authorized per signed
order, exactly like `tick`), it keeps running when a single tick raises, and it stops cleanly when
the shutdown flag is set (so a Railway deploy doesn't sever a drain mid-flight).
"""

from api.scripts import run_market


def test_tick_loop_is_a_registered_command_and_not_paid():
    parser = run_market.build_parser()
    ns = parser.parse_args(["tick-loop", "markets/anything.json"])
    assert ns.command == "tick-loop"
    # The order row is the spend confirmation; the daemon must never demand the env token, or every
    # loop iteration would refuse (the §8a collect-gating mistake, respelled as a daemon).
    assert "tick-loop" not in run_market.PAID_COMMANDS


def _tiny_settings(monkeypatch):
    class _S:
        tick_loop_interval_seconds = 0.001

    monkeypatch.setattr(run_market, "get_settings", lambda: _S())


def test_tick_loop_runs_tick_until_stopped(monkeypatch):
    _tiny_settings(monkeypatch)
    calls = {"n": 0}

    def fake_tick(_args):
        calls["n"] += 1
        if calls["n"] >= 3:
            run_market._tick_loop_stop = True  # simulate SIGTERM after the 3rd tick
        return 0

    monkeypatch.setattr(run_market, "cmd_tick", fake_tick)
    rc = run_market.cmd_tick_loop(object())
    assert rc == 0
    assert calls["n"] == 3


def test_a_failing_tick_does_not_kill_the_daemon(monkeypatch):
    """One bad iteration is logged and swallowed — the daemon keeps draining every other order."""
    _tiny_settings(monkeypatch)
    calls = {"n": 0}

    def flaky_tick(_args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient provider error")
        if calls["n"] >= 3:
            run_market._tick_loop_stop = True
        return 0

    monkeypatch.setattr(run_market, "cmd_tick", flaky_tick)
    rc = run_market.cmd_tick_loop(object())
    assert rc == 0
    assert calls["n"] == 3  # it survived the raise and kept going


def test_a_systemexit_from_a_tick_still_propagates(monkeypatch):
    """A genuine refusal/exit (not a transient error) must not be swallowed by the daemon guard."""
    import pytest

    _tiny_settings(monkeypatch)

    def exiting_tick(_args):
        raise SystemExit("refused")

    monkeypatch.setattr(run_market, "cmd_tick", exiting_tick)
    with pytest.raises(SystemExit):
        run_market.cmd_tick_loop(object())
