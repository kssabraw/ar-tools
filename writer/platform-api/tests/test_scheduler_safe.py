"""Unit tests for the gsc_scheduler per-step guards (_safe / _safe_async).

The daily/weekly scheduler block runs ~30 enqueue steps in sequence. Each is
wrapped so a persistently-failing step can't abort the rest of the block (which
would stop the marker from advancing and re-fire every earlier step each tick).
"""

from __future__ import annotations

import asyncio

from services import gsc_scheduler as sched


def test_safe_swallows_and_continues():
    calls = []

    def ok(tag):
        calls.append(tag)

    def boom(_tag):
        raise RuntimeError("kaboom")

    # A failing step in the middle must not stop the ones after it.
    sched._safe("a", ok, "a")
    sched._safe("b", boom, "b")
    sched._safe("c", ok, "c")
    assert calls == ["a", "c"]


def test_safe_passes_args():
    seen = []
    sched._safe("x", lambda a, b: seen.append((a, b)), 1, 2)
    assert seen == [(1, 2)]


def test_safe_async_swallows_and_continues():
    calls = []

    async def ok(tag):
        calls.append(tag)

    async def boom(_tag):
        raise RuntimeError("kaboom")

    async def run():
        await sched._safe_async("a", ok, "a")
        await sched._safe_async("b", boom, "b")
        await sched._safe_async("c", ok, "c")

    asyncio.run(run())
    assert calls == ["a", "c"]


def test_safe_async_awaits_to_thread_style_callable():
    # Mirrors the client_pulse call: _safe_async("...", asyncio.to_thread, fn, arg).
    seen = []

    def sync_fn(arg):
        seen.append(arg)

    asyncio.run(sched._safe_async("pulse", asyncio.to_thread, sync_fn, "d"))
    assert seen == ["d"]
