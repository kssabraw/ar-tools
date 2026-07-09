"""ICP Creator module router (client-level, converged — Option A).

Every route is auth-gated; the nlp service is reached only server-side. The scan
is long-running (page discovery + title/H1 enrichment + 1 LLM call) so it's
enqueued as an `async_jobs` job and the client polls `.../scan/{job_id}`; running
server-side means the scan completes (and the ICP persists) even if the user
navigates away and comes back. GET / PUT are instant and stay plain JSON.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends

from middleware.auth import require_auth
from models.icp import (
    IcpResponse,
    IcpScanJob,
    IcpScanJobStatus,
    IcpScanRequest,
    IcpUpdateRequest,
)
from services import icp_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["icp"])


@router.get("/clients/{client_id}/icp", response_model=IcpResponse)
async def get_icp(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> IcpResponse:
    return IcpResponse(**icp_service.get_icp(str(client_id)))


@router.post("/clients/{client_id}/icp/scan", response_model=IcpScanJob)
async def scan_icp(
    client_id: UUID,
    body: IcpScanRequest,
    auth: dict = Depends(require_auth),
) -> IcpScanJob:
    """Enqueue an ICP scan (background job). Surfaces the supersede guard as a real
    409 up front, then returns a job handle to poll via `.../scan/{job_id}`."""
    icp_service.ensure_scannable(str(client_id), body.force)
    job_id = await icp_service.enqueue_scan(str(client_id), body.force, auth["user_id"])
    return IcpScanJob(job_id=job_id, status="pending")


@router.get("/clients/{client_id}/icp/scan/{job_id}", response_model=IcpScanJobStatus)
async def get_icp_scan(
    client_id: UUID,
    job_id: UUID,
    auth: dict = Depends(require_auth),
) -> IcpScanJobStatus:
    """Poll a background ICP scan; refetch the ICP on completion."""
    return IcpScanJobStatus(**icp_service.get_scan_job(str(job_id), str(client_id)))


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
