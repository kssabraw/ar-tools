"""Brand Voice module router (client-level, converged — Option A).

Every route is auth-gated; the nlp service is reached only server-side. The
scan is long-running (probe + up to ~25 scrapes + 3 LLM calls) so it's enqueued
as an `async_jobs` job and the client polls `.../scan/{job_id}`; running
server-side means the scan completes (and the voice persists) even if the user
navigates away and comes back. GET / PUT are instant and stay plain JSON.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends

from middleware.auth import require_auth
from models.brand_voice import (
    BrandVoiceResponse,
    BrandVoiceScanJob,
    BrandVoiceScanJobStatus,
    BrandVoiceScanRequest,
    BrandVoiceUpdateRequest,
)
from services import brand_voice_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["brand_voice"])


@router.get("/clients/{client_id}/brand-voice", response_model=BrandVoiceResponse)
async def get_brand_voice(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> BrandVoiceResponse:
    return BrandVoiceResponse(**brand_voice_service.get_brand_voice(str(client_id)))


@router.post("/clients/{client_id}/brand-voice/scan", response_model=BrandVoiceScanJob)
async def scan_brand_voice(
    client_id: UUID,
    body: BrandVoiceScanRequest,
    auth: dict = Depends(require_auth),
) -> BrandVoiceScanJob:
    """Enqueue a brand-voice scan (background job). Surfaces the supersede guard as
    a real 409 up front, then returns a job handle to poll via `.../scan/{job_id}`."""
    brand_voice_service.ensure_scannable(str(client_id), body.force)
    job_id = await brand_voice_service.enqueue_scan(str(client_id), body.force, auth["user_id"])
    return BrandVoiceScanJob(job_id=job_id, status="pending")


@router.get("/clients/{client_id}/brand-voice/scan/{job_id}", response_model=BrandVoiceScanJobStatus)
async def get_brand_voice_scan(
    client_id: UUID,
    job_id: UUID,
    auth: dict = Depends(require_auth),
) -> BrandVoiceScanJobStatus:
    """Poll a background brand-voice scan; refetch the voice on completion."""
    return BrandVoiceScanJobStatus(**brand_voice_service.get_scan_job(str(job_id), str(client_id)))


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
