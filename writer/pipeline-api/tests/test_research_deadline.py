"""Research module latency guards: the soft per-target budget (partial results),
the /research hard-deadline backstop, and the global outbound-fetch concurrency
cap.

All defend against the failure mode where the per-heading fan-out (SERP + up to
5 ScrapeOwl render_js fetches at 45s each + claim-extraction LLM calls) has no
natural ceiling and a slow/rate-limited run churns for many minutes.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest
from fastapi import HTTPException

from config import settings
from models.research import Citation, ResearchRequest

fetcher = importlib.import_module("modules.research.fetcher")
# import_module (not `import ... as`) so we get the submodule, not the APIRouter
# the research package __init__ binds as its `router` attribute.
rr = importlib.import_module("modules.research.router")
pipeline = importlib.import_module("modules.research.pipeline")


def _citation(target):
    return Citation(
        citation_id="",
        heading_order=target.heading_order,
        heading_text=target.heading_text,
        scope="heading",
        url=f"http://ex/{target.target_id}",
        tier=1,
        recency_label="fresh",
    )


def _targets():
    return [
        pipeline.CitationTarget(target_id="fast1", scope="heading", heading_text="A", heading_order=1),
        pipeline.CitationTarget(target_id="fast2", scope="heading", heading_text="B", heading_order=2),
        pipeline.CitationTarget(target_id="slow", scope="heading", heading_text="C", heading_order=3),
    ]


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


async def _patch_pipeline(monkeypatch, targets):
    async def _fake_queries(*a, **k):
        return {t.target_id: [] for t in targets}

    async def _fake_supp_queries(*a, **k):
        return []

    async def _fake_process(*, keyword, target, queries, competitor_domains):
        if target.target_id == "slow":
            await asyncio.sleep(1.0)  # exceeds the patched soft budget
        return _citation(target)

    monkeypatch.setattr(pipeline, "_extract_targets", lambda brief: (targets, []))
    monkeypatch.setattr(pipeline, "_generate_all_queries", _fake_queries)
    monkeypatch.setattr(pipeline, "generate_supplemental_queries", _fake_supp_queries)
    monkeypatch.setattr(pipeline, "_process_target", _fake_process)


async def test_run_research_returns_partial_on_soft_budget(monkeypatch):
    # One target hangs past the soft budget: the stage keeps the finished
    # citations, drops the straggler, and flags the run partial instead of
    # aborting.
    targets = _targets()
    await _patch_pipeline(monkeypatch, targets)
    monkeypatch.setattr(settings, "research_soft_budget_seconds", 0.1)

    req = ResearchRequest(run_id="r1", keyword="kw", brief_output={"heading_structure": []})
    resp = await pipeline.run_research(req)

    meta = resp.citations_metadata
    assert meta.research_deadline_hit is True
    assert meta.targets_incomplete == 1
    assert meta.total_citations == 2
    assert "http://ex/slow" not in {c.url for c in resp.citations}


async def test_run_research_complete_when_within_budget(monkeypatch):
    # All targets finish within the budget: no partial flag, every citation kept.
    targets = _targets()

    async def _fast_process(*, keyword, target, queries, competitor_domains):
        return _citation(target)

    await _patch_pipeline(monkeypatch, targets)
    monkeypatch.setattr(pipeline, "_process_target", _fast_process)
    monkeypatch.setattr(settings, "research_soft_budget_seconds", 30.0)

    req = ResearchRequest(run_id="r1", keyword="kw", brief_output={"heading_structure": []})
    resp = await pipeline.run_research(req)

    meta = resp.citations_metadata
    assert meta.research_deadline_hit is False
    assert meta.targets_incomplete == 0
    assert meta.total_citations == 3


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
