"""Brand Voice module router (client-level, converged — Option A).

Every route is auth-gated; the nlp service is reached only server-side. The
scan is long-running (probe + up to ~25 scrapes + 3 LLM calls) so it streams
via `sse_response` to survive load-balancer idle timeouts, mirroring local_seo.
GET / PUT are instant and stay plain JSON.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from middleware.auth import require_auth
from models.brand_voice import (
    BrandVoiceResponse,
    BrandVoiceScanRequest,
    BrandVoiceUpdateRequest,
)
from services import brand_voice_service
from sse import sse_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["brand_voice"])


@router.get("/clients/{client_id}/brand-voice", response_model=BrandVoiceResponse)
async def get_brand_voice(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> BrandVoiceResponse:
    return BrandVoiceResponse(**brand_voice_service.get_brand_voice(str(client_id)))


@router.post("/clients/{client_id}/brand-voice/scan")
async def scan_brand_voice(
    client_id: UUID,
    body: BrandVoiceScanRequest,
    auth: dict = Depends(require_auth),
) -> StreamingResponse:
    async def _run() -> dict:
        result = await brand_voice_service.scan(
            client_id=str(client_id),
            force=body.force,
            user_id=auth["user_id"],
        )
        return BrandVoiceResponse(**result).model_dump(mode="json")

    return sse_response(_run())


@router.put("/clients/{client_id}/brand-voice", response_model=BrandVoiceResponse)
async def update_brand_voice(
    client_id: UUID,
    body: BrandVoiceUpdateRequest,
    auth: dict = Depends(require_auth),
) -> BrandVoiceResponse:
    result = brand_voice_service.update(
        str(client_id),
        raw_text=body.raw_text,
        current_voice=body.current_voice,
        recommended_accepted=body.recommended_accepted,
        user_id=auth["user_id"],
    )
    return BrandVoiceResponse(**result)
