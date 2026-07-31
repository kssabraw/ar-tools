"""PACE dashboard chat — `POST /pace/chat`.

The PACE sidebar chatbox's endpoint — the delivery-PM sibling of
`/assistant/chat`. Thin: auth + validation here, the turn itself (client
resolution, board digest, Haiku, confirm-gated + actor-bound actions) in
`services/pace_agent`. Same persona as the Slack/PACE-channel assistant.

The two web personas are separated **by surface**: `/assistant/chat` is
SerMaStr's alone and never delegates here, and this endpoint calls
`pace_agent.maybe_handle_web(..., force=True)` so PACE answers *every* turn
(deferring strategy questions to SerMaStr in prose). It used to be a shape gate
on the shared SerMaStr surface, which meant clicking the SerMaStr icon could
return a reply in PACE's persona. (Slack still routes by shape — one channel,
one bot, so `is_pace_message` is the only way to reach PACE there.) Everything here is gated
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
from pydantic import BaseModel, Field, field_validator

from config import settings
from middleware.auth import require_auth
from services import assistant_store, pace_agent, pace_auth

logger = logging.getLogger(__name__)

router = APIRouter()

_SURFACE = "pace"


class PaceChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    # Clipped, never rejected. The assistant's own replies exceed any cap we
    # pick (director-mode strategies run 9-10k chars after the max_tokens raise),
    # and a max_length here turned every follow-up into a 422 — which the
    # frontend's stream-recovery path then masked by re-showing the previous
    # answer. History only seeds a brand-new thread (the store is the real
    # history), so a clipped seed is harmless; a rejected request is not.
    content: str

    @field_validator("content")
    @classmethod
    def _clip(cls, v: str) -> str:
        return v[:8000]


class PaceChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # Only seeds a brand-new thread (and serves frontends predating
    # persistence); once a conversation exists, history comes from the store.
    history: list[PaceChatTurn] = Field(default_factory=list, max_length=40)
    # The conversation's sticky client (echoed back from the previous response)
    # so follow-ups needn't re-name the client.
    client_id: Optional[str] = None
    # One-time token of a staged (confirm-gated, actor-bound) PACE action.
    pending_token: Optional[str] = None
    # The durable thread this turn belongs to; omit to start a new one.
    conversation_id: Optional[str] = None


class PaceChatResponse(BaseModel):
    reply: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    pending_token: Optional[str] = None
    conversation_id: Optional[str] = None


class PaceConversationSummary(BaseModel):
    id: str
    title: Optional[str] = None
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _require_enabled() -> None:
    if not settings.pace_enabled:
        raise HTTPException(status_code=503, detail="pace_not_enabled")
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="assistant_not_configured")


async def _open_turn(body: PaceChatRequest, auth: dict) -> tuple[Optional[str], list[dict]]:
    """Resolve this turn's durable thread → (conversation_id, prompt history).

    Mirrors `routers/assistant._open_turn`: a supplied id must be one the caller
    owns (admins read transcripts, they don't append to them), and an unknown or
    foreign id is refused rather than silently starting a fresh thread.
    """
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


async def _run_turn(body: PaceChatRequest, auth: dict, on_event=None) -> dict:
    conversation_id, history = await _open_turn(body, auth)
    return await _finish_turn(body, auth, conversation_id, history, on_event)


async def _finish_turn(
    body: PaceChatRequest, auth: dict, conversation_id, history, on_event=None
) -> dict:
    """The turn itself, once its durable thread is resolved.

    Split out so the streaming path can open the thread BEFORE the response
    generator starts — the conversation id is the first thing sent, and it has
    to exist by then.
    """
    actor = pace_auth.context_from_auth(auth)
    result = await pace_agent.maybe_handle_web(
        body.message.strip(),
        history,
        body.client_id,
        body.pending_token,
        actor,
        on_event=on_event,
        force=True,
    )
    # force=True always handles, but stay defensive.
    result = result or {"reply": "Sorry — PACE couldn't answer that."}
    # Stored before the caller returns/streams 'done', so a turn abandoned
    # mid-stream still lands in the thread (the producer outlives the request).
    await run_in_threadpool(
        assistant_store.end_turn, conversation_id,
        result.get("reply") or "", result.get("client_id"),
    )
    return {**result, "conversation_id": conversation_id}


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

    # Resolved before the generator runs: gen() sends this id first, so it must
    # already exist (and a 404/403 here should fail the request, not the stream).
    conversation_id, history = await _open_turn(body, auth)

    async def produce() -> None:
        try:
            result = await _finish_turn(body, auth, conversation_id, history, on_event)
            await queue.put({"type": "done", **result})
        except Exception as exc:
            logger.exception("pace_chat_stream_failed", extra={"error": str(exc)})
            await queue.put({"type": "error", "detail": "pace_error"})

    async def gen():
        # The conversation id goes out FIRST, before any work that could drop the
        # connection, so a client whose stream dies can still fetch back the
        # reply the producer stored (see /assistant/chat/stream).
        yield f"data: {json.dumps({'type': 'meta', 'conversation_id': conversation_id})}\n\n"
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


@router.get("/pace/conversations")
async def list_pace_conversations(auth: dict = Depends(require_auth)) -> dict:
    """The signed-in user's PACE threads, most recently active first."""
    rows = await run_in_threadpool(
        assistant_store.list_conversations, auth["user_id"], _SURFACE
    )
    names = await run_in_threadpool(assistant_store.client_names_for, rows)
    return {
        "conversations": [
            PaceConversationSummary(
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


@router.get("/pace/conversations/{conversation_id}")
async def get_pace_conversation(
    conversation_id: str, auth: dict = Depends(require_auth)
) -> dict:
    """One PACE thread's transcript — author, or an admin diagnosing it."""
    convo = await run_in_threadpool(assistant_store.get_conversation, conversation_id)
    if not convo or convo.get("surface") != _SURFACE:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    if not assistant_store.can_read(convo, auth.get("user_id"), auth.get("role")):
        # 404, not 403 — an unreadable thread is indistinguishable from a
        # missing one, so ids can't be probed.
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


@router.delete("/pace/conversations/{conversation_id}")
async def delete_pace_conversation(
    conversation_id: str, auth: dict = Depends(require_auth)
) -> dict:
    """Archive a PACE thread (soft). Author only."""
    convo = await run_in_threadpool(assistant_store.get_conversation, conversation_id)
    if not convo or convo.get("surface") != _SURFACE:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    if not assistant_store.can_write(convo, auth.get("user_id")):
        raise HTTPException(status_code=404, detail="conversation_not_found")
    await run_in_threadpool(assistant_store.archive_conversation, conversation_id)
    return {"ok": True}


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
