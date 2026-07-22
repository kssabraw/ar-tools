"""QA reviewer chat — `POST /qa/chat`.

The QA sidebar chatbox's endpoint — the quality-gate sibling of `/assistant/chat`
(SerMaStr) and `/pace/chat` (PACE). Thin: auth + validation here, the turn itself
(scope resolution, QA digest, the bare-URL review / task review, Sonnet) in
`services/qa_agent`.

Like `/pace/chat`, this surface calls `qa_agent.maybe_handle_web(..., force=True)`
so QA answers *every* turn (deferring strategy/PM asks to SerMaStr/PACE in prose).
Everything here is gated on `settings.qa_chat_enabled`; while it's off the
endpoints 503 and the sidebar entry stays hidden (see `GET /qa/status`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import settings
from middleware.auth import require_auth
from services import pace_auth, qa_agent

logger = logging.getLogger(__name__)

router = APIRouter()


class QaChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class QaChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[QaChatTurn] = Field(default_factory=list, max_length=40)
    # The conversation's sticky client (echoed back from the previous response).
    client_id: Optional[str] = None
    # One-time token of a staged (confirm-gated, actor-bound) task review.
    pending_token: Optional[str] = None


class QaChatResponse(BaseModel):
    reply: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    pending_token: Optional[str] = None


def _require_enabled() -> None:
    if not settings.qa_chat_enabled:
        raise HTTPException(status_code=503, detail="qa_chat_not_enabled")
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="assistant_not_configured")


async def _run_turn(body: QaChatRequest, auth: dict, on_event=None) -> dict:
    actor = pace_auth.context_from_auth(auth)
    result = await qa_agent.maybe_handle_web(
        body.message.strip(),
        [t.model_dump() for t in body.history],
        body.client_id,
        body.pending_token,
        actor,
        on_event=on_event,
        force=True,
    )
    return result or {"reply": "Sorry — QA couldn't answer that."}


@router.get("/qa/status")
async def qa_status(auth: dict = Depends(require_auth)) -> dict:
    """Whether the QA persona chat is enabled, so the frontend can gate the
    sidebar entry. Cheap config read — no side effects."""
    return {"enabled": bool(settings.qa_chat_enabled)}


@router.post("/qa/chat", response_model=QaChatResponse)
async def qa_chat_turn(
    body: QaChatRequest, auth: dict = Depends(require_auth)
) -> QaChatResponse:
    _require_enabled()
    try:
        result = await _run_turn(body, auth)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("qa_chat_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="qa_error")
    return QaChatResponse(**result)


@router.post("/qa/chat/stream")
async def qa_chat_stream(
    body: QaChatRequest, auth: dict = Depends(require_auth)
) -> StreamingResponse:
    """SSE variant of /qa/chat — the reply streams as it generates.

    Events mirror /pace/chat/stream: {type:"text", text} token deltas,
    {type:"status", label} markers, then exactly one {type:"done", reply,
    client_id?, client_name?, pending_token?} or {type:"error", detail}.
    Comment lines are keepalives — ignore them.
    """
    _require_enabled()
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(evt: dict) -> None:
        await queue.put(evt)

    async def produce() -> None:
        try:
            result = await _run_turn(body, auth, on_event=on_event)
            await queue.put({"type": "done", **result})
        except Exception as exc:
            logger.exception("qa_chat_stream_failed", extra={"error": str(exc)})
            await queue.put({"type": "error", "detail": "qa_error"})

    async def gen():
        # Like /pace/chat/stream, the producer is deliberately NOT cancelled on
        # client disconnect — an in-flight turn (which may be mid-review or
        # mid-confirm-stage) runs to completion server-side.
        asyncio.create_task(produce())
        while True:
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            if evt.get("type") in ("done", "error"):
                return

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/qa/brief")
async def qa_brief(auth: dict = Depends(require_auth)) -> dict:
    """Deterministic QA digest for the /qa page empty state — recent failures /
    needs-human across the agency, no LLM call."""
    if not settings.qa_chat_enabled:
        return {"text": ""}
    try:
        text = await run_in_threadpool(qa_agent.brief_text)
        return {"text": text}
    except Exception as exc:
        logger.warning("qa_brief_failed", extra={"error": str(exc)})
        return {"text": ""}
