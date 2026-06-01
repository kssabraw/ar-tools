"""Server-Sent-Events keepalive wrapper for long-running operations.

Some Local SEO operations (generate / reoptimize / score / analyze) block for
1–5 minutes while the private nlp service scrapes competitors and runs Claude.
A plain JSON POST sends no bytes until it finishes, so any intermediary
load-balancer idle timeout can drop the connection mid-flight and the browser
sees a 502 even though the work succeeds.

`sse_response` runs the operation as a background task while emitting periodic
heartbeat comments to keep the connection warm, then a final SSE event:

  data: {"step": "done", "result": <payload>}\n\n
  data: {"step": "error", "status": <int>, "detail": <str>}\n\n

The client reads the stream, ignores heartbeats, and resolves on done / error.
HTTP-level concerns (auth, request-body validation) still happen before the
response starts, so they surface as normal 401/422 responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Awaitable

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# How often to emit a heartbeat while the operation is still running. Must be
# comfortably below any proxy/LB idle timeout (Railway, nginx, etc.).
HEARTBEAT_SECONDS = 10


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _retrieve_exception(task: "asyncio.Task") -> None:
    """Done-callback so a detached task's exception is retrieved even if the
    client disconnected before we read the result (avoids asyncio warnings)."""
    if not task.cancelled():
        task.exception()


async def _sse_run(coro: Awaitable[Any]) -> AsyncIterator[str]:
    task: asyncio.Task = asyncio.ensure_future(coro)
    task.add_done_callback(_retrieve_exception)
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
            if not done:
                # SSE comment line — keeps the connection alive, ignored by clients.
                yield ": keepalive\n\n"
        # task is done — re-raises inside the operation if it failed.
        result = task.result()
        yield sse_event({"step": "done", "result": result})
    except asyncio.CancelledError:
        # Client disconnected. Leave the task running so any in-flight
        # persistence completes (the page still lands in Saved Pages); just
        # stop streaming.
        raise
    except HTTPException as exc:
        yield sse_event({"step": "error", "status": exc.status_code, "detail": exc.detail})
    except Exception:
        logger.exception("sse_run.unexpected_error")
        yield sse_event({"step": "error", "status": 500, "detail": "internal_error"})


def sse_response(coro: Awaitable[Any]) -> StreamingResponse:
    """Wrap a result-returning coroutine in a heartbeat SSE StreamingResponse."""
    return StreamingResponse(
        _sse_run(coro),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx/proxy response buffering
        },
    )
