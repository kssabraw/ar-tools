"""Research module latency guards: the /research wall-clock deadline and the
global outbound-fetch concurrency cap.

Both defend against the failure mode where the per-heading fan-out (SERP + up to
5 ScrapeOwl render_js fetches at 45s each + claim-extraction LLM calls) has no
natural ceiling and a slow/rate-limited run churns for many minutes.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest
from fastapi import HTTPException

from config import settings
from models.research import ResearchRequest

fetcher = importlib.import_module("modules.research.fetcher")
# import_module (not `import ... as`) so we get the submodule, not the APIRouter
# the research package __init__ binds as its `router` attribute.
rr = importlib.import_module("modules.research.router")


async def test_research_router_enforces_deadline(monkeypatch):
    # run_research hangs past the (tiny, patched) budget -> the router cuts it
    # off with a 504 rather than letting it run to the caller's transport
    # timeout.
    async def _slow(_req):
        await asyncio.sleep(5)

    monkeypatch.setattr(rr, "run_research", _slow)
    monkeypatch.setattr(settings, "research_deadline_seconds", 0.05)

    req = ResearchRequest(run_id="r1", keyword="kw", brief_output={})
    with pytest.raises(HTTPException) as ei:
        await rr.generate_research(req)
    assert ei.value.status_code == 504
    assert ei.value.detail == "research_timeout"


async def test_research_router_passes_through_on_success(monkeypatch):
    # A fast run is unaffected by the deadline wrapper. The stub carries the
    # nested fields the success-path log line reads.
    from types import SimpleNamespace

    result = SimpleNamespace(
        citations_metadata=SimpleNamespace(
            total_citations=2,
            h2s_with_citations=2,
            citations_by_tier=SimpleNamespace(tier_1=1, tier_2=1),
        )
    )

    async def _fast(_req):
        return result

    monkeypatch.setattr(rr, "run_research", _fast)
    monkeypatch.setattr(settings, "research_deadline_seconds", 5.0)

    req = ResearchRequest(run_id="r1", keyword="kw", brief_output={})
    assert await rr.generate_research(req) is result


async def test_global_fetch_semaphore_bounds_concurrency(monkeypatch):
    # The shared fetch semaphore must cap simultaneous outbound fetches across
    # all targets, regardless of the per-target local Semaphore(6).
    monkeypatch.setattr(settings, "research_fetch_global_concurrency", 3)
    fetcher._GLOBAL_FETCH_SEM = None  # force a fresh semaphore on this loop

    active = 0
    peak = 0

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"html": "<html><body>ok body content here</body></html>",
                    "final_url": "http://x"}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.02)
                return _FakeResp()
            finally:
                active -= 1

    monkeypatch.setattr(fetcher.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(settings, "scrapeowl_api_key", "test-key")

    # 12 URLs, local concurrency 6 - without the global cap peak would reach 6+;
    # with a global cap of 3 it must never exceed 3.
    urls = [f"http://example.com/{i}" for i in range(12)]
    await fetcher.fetch_many(urls, concurrency=6)

    assert peak <= 3
    fetcher._GLOBAL_FETCH_SEM = None  # don't leak the low cap into other tests
