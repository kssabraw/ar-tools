"""Admin observability for the in-process async-job worker lanes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from middleware.auth import require_admin
from services import worker_lanes

router = APIRouter(tags=["admin"])


@router.get("/admin/worker-lanes")
async def get_worker_lanes(auth: dict = Depends(require_admin)) -> dict:
    """Live per-lane queue depth (pending/running) for the worker lanes, plus the
    bulk lane's per-client running breakdown — read-only, so you can see where
    async jobs are queueing and whether raising bulk_lane_workers is warranted."""
    return worker_lanes.lane_status()
