"""SerMaStr dashboard chat — `POST /assistant/chat`.

The Home-page chatbox's endpoint. Thin: auth + validation here, the turn
itself (client resolution, context build, Claude, confirm-gated actions) in
`services/assistant_chat`. Same brain as the Slack assistant; requires only
the Anthropic key (no Slack credentials).
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
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
