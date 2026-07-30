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
from services import assistant_chat, assistant_store

logger = logging.getLogger(__name__)

router = APIRouter()

_SURFACE = "sermastr"


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # Browser-supplied history. Only used to seed a brand-new thread (and by
    # frontends predating persistence) — once a conversation exists, history is
    # read from the store, which is authoritative and not client-controlled.
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    # The conversation's sticky client (echoed back from the previous response)
    # so follow-ups needn't re-name the client.
    client_id: Optional[str] = None
    # One-time token of a staged confirm-gated action (from the previous
    # response); an affirmative message carrying it executes the action.
    pending_token: Optional[str] = None
    # The durable thread this turn belongs to. Omit to start a new one; the
    # response echoes the id to continue with.
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    pending_token: Optional[str] = None
    conversation_id: Optional[str] = None


class ConversationSummary(BaseModel):
    id: str
    title: Optional[str] = None
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


async def _open_turn(body: ChatRequest, auth: dict) -> tuple[Optional[str], list[dict]]:
    """Resolve the thread for this turn and return (conversation_id, history).

    A supplied id must be one the caller owns — admins can read a colleague's
    transcript but not append to it, so a thread always reflects one person's
    real conversation. An unknown or someone else's id is refused rather than
    silently starting a new thread, so a frontend bug can't scatter turns.
    """
    from fastapi.concurrency import run_in_threadpool

    history = [t.model_dump() for t in body.history]
    if body.conversation_id:
        convo = await run_in_threadpool(assistant_store.get_conversation, body.conversation_id)
        if not convo or convo.get("surface") != _SURFACE:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        if not assistant_store.can_write(convo, auth.get("user_id")):
            raise HTTPException(status_code=403, detail="forbidden")
    return await run_in_threadpool(
        assistant_store.begin_turn,
        body.conversation_id,
        auth.get("user_id"),
        _SURFACE,
        body.message.strip(),
        history,
    )


@router.post("/assistant/chat", response_model=ChatResponse)
async def assistant_chat_turn(
    body: ChatRequest, auth: dict = Depends(require_auth)
) -> ChatResponse:
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="assistant_not_configured")
    from fastapi.concurrency import run_in_threadpool

    conversation_id, history = await _open_turn(body, auth)
    try:
        from services import pace_auth

        result = await assistant_chat.handle_chat(
            body.message.strip(),
            history,
            body.client_id,
            body.pending_token,
            action_context=pace_auth.context_from_auth(auth),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("assistant_chat_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="assistant_error")
    await run_in_threadpool(
        assistant_store.end_turn, conversation_id, result.get("reply") or "",
        result.get("client_id"),
    )
    return ChatResponse(**result, conversation_id=conversation_id)


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

    from fastapi.concurrency import run_in_threadpool
    from services import pace_auth

    actor = pace_auth.context_from_auth(auth)
    conversation_id, history = await _open_turn(body, auth)

    async def produce() -> None:
        try:
            result = await assistant_chat.handle_chat(
                body.message.strip(),
                history,
                body.client_id,
                body.pending_token,
                on_event=on_event,
                action_context=actor,
            )
            # Stored before the 'done' event: because the producer survives a
            # client disconnect, a turn the user walked away from still lands in
            # their thread instead of being lost with the dropped stream.
            await run_in_threadpool(
                assistant_store.end_turn, conversation_id,
                result.get("reply") or "", result.get("client_id"),
            )
            await queue.put({"type": "done", "conversation_id": conversation_id, **result})
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


# ---------------------------------------------------------------------------
# Conversation history — the durable threads behind the chatbox.
# ---------------------------------------------------------------------------
@router.get("/assistant/conversations")
async def list_conversations(auth: dict = Depends(require_auth)) -> dict:
    """The signed-in user's SerMaStr threads, most recently active first."""
    from fastapi.concurrency import run_in_threadpool

    rows = await run_in_threadpool(
        assistant_store.list_conversations, auth["user_id"], _SURFACE
    )
    names = await run_in_threadpool(assistant_store.client_names_for, rows)
    return {
        "conversations": [
            ConversationSummary(
                id=str(r["id"]),
                title=r.get("title"),
                client_id=r.get("client_id"),
                client_name=names.get(r.get("client_id")),
                created_at=r.get("created_at"),
                updated_at=r.get("updated_at"),
            ).model_dump()
            for r in rows
        ]
    }


@router.get("/assistant/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str, auth: dict = Depends(require_auth)
) -> dict:
    """One thread's full transcript. Readable by its author, or by an admin
    (diagnosing a bad answer needs the actual conversation)."""
    from fastapi.concurrency import run_in_threadpool

    convo = await run_in_threadpool(assistant_store.get_conversation, conversation_id)
    if not convo or convo.get("surface") != _SURFACE:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    if not assistant_store.can_read(convo, auth.get("user_id"), auth.get("role")):
        # 404 rather than 403: a thread you may not read is indistinguishable
        # from one that doesn't exist, so ids can't be probed.
        raise HTTPException(status_code=404, detail="conversation_not_found")
    messages = await run_in_threadpool(assistant_store.get_messages, conversation_id)
    return {
        "id": str(convo["id"]),
        "title": convo.get("title"),
        "client_id": convo.get("client_id"),
        "updated_at": convo.get("updated_at"),
        "messages": [
            {"role": m["role"], "content": m["content"], "created_at": m.get("created_at")}
            for m in messages
        ],
    }


@router.delete("/assistant/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str, auth: dict = Depends(require_auth)
) -> dict:
    """Archive a thread (soft — the row stays for admin diagnosis). Author only:
    an admin can read someone's transcript but not clear it for them."""
    from fastapi.concurrency import run_in_threadpool

    convo = await run_in_threadpool(assistant_store.get_conversation, conversation_id)
    if not convo or convo.get("surface") != _SURFACE:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    if not assistant_store.can_write(convo, auth.get("user_id")):
        raise HTTPException(status_code=404, detail="conversation_not_found")
    await run_in_threadpool(assistant_store.archive_conversation, conversation_id)
    return {"ok": True}
