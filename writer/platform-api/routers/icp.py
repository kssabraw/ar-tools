"""ICP Creator module router (client-level, converged — Option A).

Every route is auth-gated; the nlp service is reached only server-side. The scan
is long-running (page discovery + title/H1 enrichment + 1 LLM call) so it streams
via `sse_response`; GET / PUT are instant and stay plain JSON.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from middleware.auth import require_auth
from models.icp import IcpResponse, IcpScanRequest, IcpUpdateRequest
from services import icp_service
from sse import sse_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["icp"])


@router.get("/clients/{client_id}/icp", response_model=IcpResponse)
async def get_icp(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> IcpResponse:
    return IcpResponse(**icp_service.get_icp(str(client_id)))


@router.post("/clients/{client_id}/icp/scan")
async def scan_icp(
    client_id: UUID,
    body: IcpScanRequest,
    auth: dict = Depends(require_auth),
) -> StreamingResponse:
    # Surface the supersede guard as a real 409 before the SSE stream opens.
    icp_service.ensure_scannable(str(client_id), body.force)

    async def _run() -> dict:
        result = await icp_service.scan(
            client_id=str(client_id),
            force=body.force,
            user_id=auth["user_id"],
        )
        return IcpResponse(**result).model_dump(mode="json")

    return sse_response(_run())


@router.put("/clients/{client_id}/icp", response_model=IcpResponse)
async def update_icp(
    client_id: UUID,
    body: IcpUpdateRequest,
    auth: dict = Depends(require_auth),
) -> IcpResponse:
    result = icp_service.update(
        str(client_id),
        raw_text=body.raw_text,
        segments=body.segments,
        reasoning=body.reasoning,
        differentiators=body.differentiators,
        user_id=auth["user_id"],
    )
    return IcpResponse(**result)
