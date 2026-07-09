"""SerMaStr dashboard chat — `POST /assistant/chat`.

The Home-page chatbox's endpoint. Thin: auth + validation here, the turn
itself (client resolution, context build, Claude, confirm-gated actions) in
`services/assistant_chat`. Same brain as the Slack assistant; requires only
the Anthropic key (no Slack credentials).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import settings
from middleware.auth import require_auth
from services import assistant_chat

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    # The conversation's sticky client (echoed back from the previous response)
    # so follow-ups needn't re-name the client.
    client_id: Optional[str] = None
    # One-time token of a staged confirm-gated action (from the previous
    # response); an affirmative message carrying it executes the action.
    pending_token: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    pending_token: Optional[str] = None


@router.post("/assistant/chat", response_model=ChatResponse)
async def assistant_chat_turn(
    body: ChatRequest, auth: dict = Depends(require_auth)
) -> ChatResponse:
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="assistant_not_configured")
    try:
        result = await assistant_chat.handle_chat(
            body.message.strip(),
            [t.model_dump() for t in body.history],
            body.client_id,
            body.pending_token,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("assistant_chat_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="assistant_error")
    return ChatResponse(**result)


@router.post("/assistant/chat/stream")
async def assistant_chat_stream(
    body: ChatRequest, auth: dict = Depends(require_auth)
) -> StreamingResponse:
    """SSE variant of /assistant/chat — the reply streams as it generates.

    Events (one JSON object per `data:` line): {type:"text", text} token
    deltas, {type:"status", label} tool-activity markers ("Reading SOP…"),
    then exactly one {type:"done", reply, client_id?, client_name?,
    pending_token?} (the same payload the non-stream endpoint returns) or
    {type:"error", detail}. Comment lines are keepalives — ignore them.
    """
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="assistant_not_configured")
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(evt: dict) -> None:
        await queue.put(evt)

    async def produce() -> None:
        try:
            result = await assistant_chat.handle_chat(
                body.message.strip(),
                [t.model_dump() for t in body.history],
                body.client_id,
                body.pending_token,
                on_event=on_event,
            )
            await queue.put({"type": "done", **result})
        except Exception as exc:
            logger.exception("assistant_chat_stream_failed", extra={"error": str(exc)})
            await queue.put({"type": "error", "detail": "assistant_error"})

    async def gen():
        # The producer is deliberately NOT cancelled on client disconnect —
        # like the non-stream endpoint, an in-flight turn (which may be
        # mid-action or mid-memory-write) runs to completion server-side.
        asyncio.create_task(produce())
        while True:
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"  # comment line — defeats LB idle timeouts
                continue
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            if evt.get("type") in ("done", "error"):
                return

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/assistant/brief")
async def assistant_brief(auth: dict = Depends(require_auth)) -> dict:
    """Deterministic 'since you were last here' digest for the /assistant page
    empty state — recent notifications across all clients, no LLM call."""
    from fastapi.concurrency import run_in_threadpool

    try:
        return await run_in_threadpool(assistant_chat.build_brief)
    except Exception as exc:
        logger.warning("assistant_brief_failed", extra={"error": str(exc)})
        return {"window_hours": 0, "items": []}
