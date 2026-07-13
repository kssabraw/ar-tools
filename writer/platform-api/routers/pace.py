"""PACE dashboard chat — `POST /pace/chat`.

The PACE sidebar chatbox's endpoint — the delivery-PM sibling of
`/assistant/chat`. Thin: auth + validation here, the turn itself (client
resolution, board digest, Haiku, confirm-gated + actor-bound actions) in
`services/pace_agent`. Same persona as the Slack/PACE-channel assistant.

Unlike `/assistant/chat` — where PACE only gets first-refusal on PACE-shaped
messages and otherwise falls through to SerMaStr — this surface calls
`pace_agent.maybe_handle_web(..., force=True)` so PACE answers *every* turn
(deferring strategy questions to SerMaStr in prose). Everything here is gated
on `settings.pace_enabled`; while it's off the endpoints 503 and the sidebar
entry stays hidden (see `GET /pace/status`).
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
from services import pace_agent, pace_auth

logger = logging.getLogger(__name__)

router = APIRouter()


class PaceChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class PaceChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[PaceChatTurn] = Field(default_factory=list, max_length=40)
    # The conversation's sticky client (echoed back from the previous response)
    # so follow-ups needn't re-name the client.
    client_id: Optional[str] = None
    # One-time token of a staged (confirm-gated, actor-bound) PACE action.
    pending_token: Optional[str] = None


class PaceChatResponse(BaseModel):
    reply: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    pending_token: Optional[str] = None


def _require_enabled() -> None:
    if not settings.pace_enabled:
        raise HTTPException(status_code=503, detail="pace_not_enabled")
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="assistant_not_configured")


async def _run_turn(body: PaceChatRequest, auth: dict, on_event=None) -> dict:
    actor = pace_auth.context_from_auth(auth)
    result = await pace_agent.maybe_handle_web(
        body.message.strip(),
        [t.model_dump() for t in body.history],
        body.client_id,
        body.pending_token,
        actor,
        on_event=on_event,
        force=True,
    )
    # force=True always handles, but stay defensive.
    return result or {"reply": "Sorry — PACE couldn't answer that."}


@router.get("/pace/status")
async def pace_status(auth: dict = Depends(require_auth)) -> dict:
    """Whether the PACE persona is enabled, so the frontend can gate the sidebar
    entry. Cheap config read — no side effects."""
    return {"enabled": bool(settings.pace_enabled)}


@router.post("/pace/chat", response_model=PaceChatResponse)
async def pace_chat_turn(
    body: PaceChatRequest, auth: dict = Depends(require_auth)
) -> PaceChatResponse:
    _require_enabled()
    try:
        result = await _run_turn(body, auth)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("pace_chat_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="pace_error")
    return PaceChatResponse(**result)


@router.post("/pace/chat/stream")
async def pace_chat_stream(
    body: PaceChatRequest, auth: dict = Depends(require_auth)
) -> StreamingResponse:
    """SSE variant of /pace/chat — the reply streams as it generates.

    Events mirror /assistant/chat/stream: {type:"text", text} token deltas,
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
            logger.exception("pace_chat_stream_failed", extra={"error": str(exc)})
            await queue.put({"type": "error", "detail": "pace_error"})

    async def gen():
        # Like /assistant/chat/stream, the producer is deliberately NOT cancelled
        # on client disconnect — an in-flight turn (which may be mid-action or
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


@router.get("/pace/brief")
async def pace_brief(auth: dict = Depends(require_auth)) -> dict:
    """Deterministic personal brief for the /pace page empty state — the actor's
    own My-Tasks digest (overdue → today → this week), no LLM call."""
    if not settings.pace_enabled:
        return {"text": ""}
    try:
        actor = pace_auth.context_from_auth(auth)
        text = await run_in_threadpool(pace_agent.personal_brief_text, actor)
        return {"text": text}
    except Exception as exc:
        logger.warning("pace_brief_failed", extra={"error": str(exc)})
        return {"text": ""}
