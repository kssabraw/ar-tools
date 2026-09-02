"""DORA dashboard chat — `POST /director/chat`.

The Director-of-Operations chat page's endpoint — the cross-agent-lens sibling of
`/assistant/chat` (SerMaStr) and `/pace/chat` (PACE). Thin: auth + validation
here, the turn itself (scope resolution, the cross-agent read model, the Sonnet
answer) in `services/director_agent`. Same persona as the dedicated DORA Slack
channel.

DORA is READ-ONLY, answer-only — no actions, so (unlike `/pace/chat`) there is no
pending-token / confirm machinery here. Everything is gated on
`settings.director_enabled`; while it's off the endpoints 503 and the sidebar
entry stays hidden (see `GET /director/status`).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from config import settings
from middleware.auth import require_auth
from services import assistant_store, director_agent, guide_sync

logger = logging.getLogger(__name__)

router = APIRouter()

_SURFACE = "director"


class DirectorChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    # Clipped, never rejected (mirrors routers/pace.py) — the assistant's own
    # replies exceed any cap we'd pick, and history only seeds a brand-new thread,
    # so a clipped seed is harmless while a rejected request is not.
    content: str

    @field_validator("content")
    @classmethod
    def _clip(cls, v: str) -> str:
        return v[:8000]


class DirectorChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # Only seeds a brand-new thread (and serves frontends predating persistence);
    # once a conversation exists, history comes from the store.
    history: list[DirectorChatTurn] = Field(default_factory=list, max_length=40)
    # The conversation's sticky client (echoed back from the previous response) so
    # follow-ups needn't re-name the client.
    client_id: Optional[str] = None
    # The durable thread this turn belongs to; omit to start a new one.
    conversation_id: Optional[str] = None


class DirectorChatResponse(BaseModel):
    reply: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    conversation_id: Optional[str] = None


class DirectorConversationSummary(BaseModel):
    id: str
    title: Optional[str] = None
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _require_enabled() -> None:
    if not settings.director_enabled:
        raise HTTPException(status_code=503, detail="director_not_enabled")
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="assistant_not_configured")


async def _open_turn(body: DirectorChatRequest, auth: dict) -> tuple[Optional[str], list[dict]]:
    """Resolve this turn's durable thread → (conversation_id, prompt history).
    Mirrors routers/pace._open_turn: a supplied id must be one the caller owns,
    and an unknown/foreign id is refused rather than silently starting fresh."""
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


async def _run_turn(body: DirectorChatRequest, auth: dict, on_event=None) -> dict:
    conversation_id, history = await _open_turn(body, auth)
    return await _finish_turn(body, auth, conversation_id, history, on_event)


async def _finish_turn(
    body: DirectorChatRequest, auth: dict, conversation_id, history, on_event=None
) -> dict:
    """The turn itself, once its durable thread is resolved. Split out so the
    streaming path can open the thread BEFORE the response generator starts."""
    result = await director_agent.maybe_handle_web(
        body.message.strip(),
        history,
        body.client_id,
        on_event=on_event,
    )
    result = result or {"reply": "Sorry — DORA couldn't answer that."}
    # Stored before the caller returns/streams 'done', so a turn abandoned
    # mid-stream still lands in the thread (the producer outlives the request).
    await run_in_threadpool(
        assistant_store.end_turn, conversation_id,
        result.get("reply") or "", result.get("client_id"),
    )
    return {**result, "conversation_id": conversation_id}


@router.get("/director/status")
async def director_status(auth: dict = Depends(require_auth)) -> dict:
    """Whether DORA is enabled, so the frontend can gate the sidebar entry. Cheap
    config read — no side effects."""
    return {"enabled": bool(settings.director_enabled)}


# ---------------------------------------------------------------------------
# Guide sync inbound — CI reports a merged module change (services/guide_sync.py)
# ---------------------------------------------------------------------------
class ModuleCommit(BaseModel):
    sha: str = ""
    title: str = ""
    body: str = ""

    @field_validator("sha", "title", "body")
    @classmethod
    def _clip_commit(cls, v: str) -> str:
        return (v or "")[:4000]


class ModuleChange(BaseModel):
    module: str = Field(min_length=1, max_length=64)
    files: list[str] = Field(default_factory=list, max_length=500)
    diff: str = ""
    commits: list[ModuleCommit] = Field(default_factory=list, max_length=50)

    @field_validator("diff")
    @classmethod
    def _clip_diff(cls, v: str) -> str:
        # The reporter bounds this already; a hard ceiling keeps a runaway
        # payload out of the row (the service clips again to the prompt bound).
        return (v or "")[:400_000]


class ModuleChangesRequest(BaseModel):
    commit_sha: str = Field(min_length=7, max_length=40)
    commit_range: Optional[str] = Field(default=None, max_length=120)
    repository: Optional[str] = Field(default=None, max_length=200)
    changes: list[ModuleChange] = Field(default_factory=list, max_length=60)


def _presented_secret(request: Request) -> str:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("x-guide-sync-secret") or "").strip()


@router.post("/director/module-changes")
async def report_module_changes(body: ModuleChangesRequest, request: Request) -> dict:
    """The CI reporter's inbound (``scripts/report_module_changes.py``): one
    entry per module a merge to ``main`` touched, with the user-facing files,
    commit messages, and a bounded diff. Public endpoint guarded ONLY by the
    shared bearer secret (``GUIDE_SYNC_SECRET``) — fail-closed: no secret
    configured ⇒ 503 and nothing recorded; wrong secret ⇒ 401. Idempotent per
    (commit, module), so a re-run of the workflow can't double-review."""
    if not guide_sync.gate_open():
        raise HTTPException(status_code=503, detail="guide_sync_disabled")
    if not settings.guide_sync_secret:
        raise HTTPException(status_code=503, detail="guide_sync_not_configured")
    presented = _presented_secret(request)
    if not presented or not hmac.compare_digest(presented, settings.guide_sync_secret):
        raise HTTPException(status_code=401, detail="invalid_secret")
    try:
        result = await run_in_threadpool(guide_sync.ingest_module_changes, body.model_dump())
    except Exception as exc:
        logger.exception("guide_sync_ingest_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="guide_sync_error")
    return {"ok": True, **result}


@router.post("/director/chat", response_model=DirectorChatResponse)
async def director_chat_turn(
    body: DirectorChatRequest, auth: dict = Depends(require_auth)
) -> DirectorChatResponse:
    _require_enabled()
    try:
        result = await _run_turn(body, auth)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("director_chat_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="director_error")
    return DirectorChatResponse(**result)


@router.post("/director/chat/stream")
async def director_chat_stream(
    body: DirectorChatRequest, auth: dict = Depends(require_auth)
) -> StreamingResponse:
    """SSE variant of /director/chat — the reply streams as it generates.

    Events mirror /pace/chat/stream: {type:"text", text} deltas, {type:"status",
    label} markers, then exactly one {type:"done", reply, client_id?,
    client_name?} or {type:"error", detail}. Comment lines are keepalives.
    """
    _require_enabled()
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(evt: dict) -> None:
        await queue.put(evt)

    # Resolved before the generator runs: gen() sends this id first, so it must
    # already exist (a 404/403 here should fail the request, not the stream).
    conversation_id, history = await _open_turn(body, auth)

    async def produce() -> None:
        try:
            result = await _finish_turn(body, auth, conversation_id, history, on_event)
            await queue.put({"type": "done", **result})
        except Exception as exc:
            logger.exception("director_chat_stream_failed", extra={"error": str(exc)})
            await queue.put({"type": "error", "detail": "director_error"})

    async def gen():
        yield f"data: {json.dumps({'type': 'meta', 'conversation_id': conversation_id})}\n\n"
        # Like /pace/chat/stream, the producer is deliberately NOT cancelled on
        # client disconnect — an in-flight turn runs to completion server-side.
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


@router.get("/director/conversations")
async def list_director_conversations(auth: dict = Depends(require_auth)) -> dict:
    """The signed-in user's DORA threads, most recently active first."""
    rows = await run_in_threadpool(
        assistant_store.list_conversations, auth["user_id"], _SURFACE
    )
    names = await run_in_threadpool(assistant_store.client_names_for, rows)
    return {
        "conversations": [
            DirectorConversationSummary(
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


@router.get("/director/conversations/{conversation_id}")
async def get_director_conversation(
    conversation_id: str, auth: dict = Depends(require_auth)
) -> dict:
    """One DORA thread's transcript — author, or an admin diagnosing it."""
    convo = await run_in_threadpool(assistant_store.get_conversation, conversation_id)
    if not convo or convo.get("surface") != _SURFACE:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    if not assistant_store.can_read(convo, auth.get("user_id"), auth.get("role")):
        # 404, not 403 — an unreadable thread is indistinguishable from a missing
        # one, so ids can't be probed.
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


@router.delete("/director/conversations/{conversation_id}")
async def delete_director_conversation(
    conversation_id: str, auth: dict = Depends(require_auth)
) -> dict:
    """Archive a DORA thread (soft). Author only."""
    convo = await run_in_threadpool(assistant_store.get_conversation, conversation_id)
    if not convo or convo.get("surface") != _SURFACE:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    if not assistant_store.can_write(convo, auth.get("user_id")):
        raise HTTPException(status_code=404, detail="conversation_not_found")
    await run_in_threadpool(assistant_store.archive_conversation, conversation_id)
    return {"ok": True}


@router.get("/director/brief")
async def director_brief(auth: dict = Depends(require_auth)) -> dict:
    """Deterministic opening brief for the /director page empty state — the open
    cross-agent seam flags right now, no LLM call."""
    if not settings.director_enabled:
        return {"text": ""}
    try:
        text = await run_in_threadpool(director_agent.opening_brief_text)
        return {"text": text}
    except Exception as exc:
        logger.warning("director_brief_failed", extra={"error": str(exc)})
        return {"text": ""}
