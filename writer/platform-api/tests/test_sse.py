import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sse import _sse_run  # noqa: E402


async def _collect(coro):
    return [chunk async for chunk in _sse_run(coro)]


def _events(chunks):
    """Parse the `data:` SSE chunks into dicts (skips heartbeat comments)."""
    out = []
    for c in chunks:
        if c.startswith("data:"):
            out.append(json.loads(c[len("data:"):].strip()))
    return out


@pytest.mark.asyncio
async def test_done_event_carries_result():
    async def _op():
        return {"id": "page-1", "score": 88}

    events = _events(await _collect(_op()))
    assert events == [{"step": "done", "result": {"id": "page-1", "score": 88}}]


@pytest.mark.asyncio
async def test_http_exception_becomes_error_event():
    async def _op():
        raise HTTPException(status_code=502, detail="local_seo_provider_error")

    events = _events(await _collect(_op()))
    assert events == [{"step": "error", "status": 502, "detail": "local_seo_provider_error"}]


@pytest.mark.asyncio
async def test_unexpected_exception_is_masked_as_internal_error():
    async def _op():
        raise ValueError("boom")  # e.g. a JSON decode error leaking through

    chunks = await _collect(_op())
    assert _events(chunks) == [{"step": "error", "status": 500, "detail": "internal_error"}]
    # The raw exception message must not leak to the client.
    assert all("boom" not in c for c in chunks)
