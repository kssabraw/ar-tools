"""Tests for the event-loop lag watchdog (regression: 2026-09-16 outage)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from config import settings
from services import event_loop_watchdog


async def test_watchdog_logs_when_the_loop_is_blocked(monkeypatch, caplog):
    """A synchronous block ON the loop makes the watchdog's sleep wake late, and
    that lag (over threshold) is logged."""
    monkeypatch.setattr(settings, "event_loop_watchdog_enabled", True)
    monkeypatch.setattr(settings, "event_loop_watchdog_interval_seconds", 0.05)
    monkeypatch.setattr(settings, "event_loop_watchdog_lag_threshold_seconds", 0.1)
    caplog.set_level(logging.WARNING, logger="services.event_loop_watchdog")

    task = asyncio.create_task(event_loop_watchdog.event_loop_watchdog())
    try:
        await asyncio.sleep(0.06)   # let the watchdog enter its first sleep
        time.sleep(0.5)             # BLOCK the loop >> threshold → induces lag
        await asyncio.sleep(0.06)   # yield so the watchdog wakes, measures, logs
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert any("event_loop_lag_high" in r.getMessage() for r in caplog.records)


async def test_watchdog_quiet_on_a_healthy_loop(monkeypatch, caplog):
    """With no blocking, no lag warning is emitted."""
    monkeypatch.setattr(settings, "event_loop_watchdog_enabled", True)
    monkeypatch.setattr(settings, "event_loop_watchdog_interval_seconds", 0.02)
    monkeypatch.setattr(settings, "event_loop_watchdog_lag_threshold_seconds", 0.5)
    caplog.set_level(logging.WARNING, logger="services.event_loop_watchdog")

    task = asyncio.create_task(event_loop_watchdog.event_loop_watchdog())
    try:
        await asyncio.sleep(0.15)   # several healthy intervals, no blocking
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert not any("event_loop_lag_high" in r.getMessage() for r in caplog.records)


async def test_watchdog_disabled_returns_immediately(monkeypatch):
    """When disabled the coroutine returns at once (does not run forever)."""
    monkeypatch.setattr(settings, "event_loop_watchdog_enabled", False)
    # Would never return if it entered the loop; wrap in a tight timeout to prove it.
    await asyncio.wait_for(event_loop_watchdog.event_loop_watchdog(), timeout=1.0)
