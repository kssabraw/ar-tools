"""The orphan-run recovery sweep must not race the outgoing container.

`recover_stuck_runs` re-dispatches every run sitting in a non-terminal status.
It used to be awaited inline at startup — at second 0 of the new container's
boot, while Railway keeps the OUTGOING container working for ~15s. A run still
executing over there is non-terminal, so the incoming container would re-dispatch
it: two orchestrators driving one run, double module spend, and racing
`module_outputs` writes where the loser's payload can overwrite the winner's.
Interactive runs carry no `source_ref`, so nothing else stops that.

The fix is a delayed, cancellable task. These tests pin the three properties that
make it safe; the middle one is the whole point of the change.
"""

from __future__ import annotations

import asyncio

import main


def _run(coro):
    return asyncio.run(coro)


def _patch(monkeypatch, delay, recover):
    monkeypatch.setattr(main, "recover_stuck_runs", recover)
    monkeypatch.setattr(main.settings, "run_recovery_delay_seconds", delay)


def test_sweep_runs_once_the_delay_elapses(monkeypatch):
    """The recovery still happens — it is deferred, not dropped."""
    calls: list[str] = []

    async def recover():
        calls.append("swept")

    _patch(monkeypatch, 0.01, recover)
    _run(main._recover_stuck_runs_later())
    assert calls == ["swept"]


def test_a_container_cancelled_inside_the_window_never_sweeps(monkeypatch):
    """The race guard. A container that goes away before its delay elapses must
    NOT have touched the previous container's still-live runs — the next boot
    owns the sweep instead."""
    calls: list[str] = []

    async def recover():
        calls.append("swept")

    _patch(monkeypatch, 30.0, recover)

    async def cancel_mid_wait():
        task = asyncio.create_task(main._recover_stuck_runs_later())
        await asyncio.sleep(0.01)  # still inside the delay
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    _run(cancel_mid_wait())
    assert calls == []


def test_a_failing_sweep_never_takes_the_app_down(monkeypatch):
    """It runs as a bare background task, so an exception escaping it would be an
    unhandled task error on a healthy container."""

    async def boom():
        raise RuntimeError("supabase unavailable")

    _patch(monkeypatch, 0, boom)
    _run(main._recover_stuck_runs_later())  # must not raise


def test_zero_delay_still_sweeps(monkeypatch):
    """0 disables the wait (the old inline behavior) without disabling recovery."""
    calls: list[str] = []

    async def recover():
        calls.append("swept")

    _patch(monkeypatch, 0, recover)
    _run(main._recover_stuck_runs_later())
    assert calls == ["swept"]
