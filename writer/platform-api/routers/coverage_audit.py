"""Coverage Audit API — the whole-site location & service gap finder (Phase 1:
Tier 1, city × main-service).

Point the audit at a client and it scans their site as it stands, derives the
service + location axes, diffs the ideal coverage universe against what exists,
demand-ranks the gaps, and seeds a Service×Location Matrix (AXES ONLY) so the
recommendations are one click from execution. Its own client-workspace card + a
standalone `/coverage-audit` page (not a Local SEO tab).

Design: docs/modules/coverage-audit-module-plan-v1_0.md.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth
from services import coverage_audit_service as svc

router = APIRouter(tags=["coverage-audit"])
logger = logging.getLogger(__name__)


class StartAuditRequest(BaseModel):
    tier: int = 1


class EditServiceAxisRequest(BaseModel):
    # The confirmed/edited main-service axis — a plain list of service labels. The
    # audit re-runs on this exact axis (skips auto-derivation).
    services: list[str]


def _require_enabled() -> None:
    if not settings.coverage_audit_enabled:
        raise HTTPException(status_code=403, detail="coverage_audit_disabled")


@router.get("/clients/{client_id}/coverage-audit")
async def get_coverage_audit(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Module status + run history + the latest Tier-1 run for the client."""
    try:
        return {
            "enabled": settings.coverage_audit_enabled,
            "budget_remaining": svc.budget_remaining(),
            "audits": svc.list_audits(str(client_id)),
            "latest": svc.latest_audit(str(client_id), 1),
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("coverage_audit.list_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/clients/{client_id}/coverage-audit")
async def start_coverage_audit(
    client_id: UUID, body: StartAuditRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Enqueue a Tier-1 coverage audit (poll the job, then GET the run)."""
    _require_enabled()
    if body.tier not in svc.SUPPORTED_TIERS:
        raise HTTPException(status_code=400, detail="coverage_audit_tier_unsupported")
    if svc.budget_remaining() <= 0:
        raise HTTPException(status_code=429, detail="budget_exceeded")
    try:
        audit_id, job_id = svc.enqueue_coverage_audit(str(client_id), body.tier, auth["user_id"])
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("coverage_audit.start_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"audit_id": audit_id, "job_id": job_id, "tier": body.tier}


@router.get("/clients/{client_id}/coverage-audit/jobs/{job_id}")
async def coverage_audit_job_status(
    client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    rows = (
        get_supabase()
        .table("async_jobs")
        .select("id, status, result, error, entity_id")
        .eq("id", str(job_id))
        .limit(1)
        .execute()
    ).data
    if not rows or rows[0].get("entity_id") != str(client_id):
        raise HTTPException(status_code=404, detail="job_not_found")
    return rows[0]


@router.get("/clients/{client_id}/coverage-audit/{audit_id}")
async def get_coverage_audit_run(
    client_id: UUID, audit_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    run = svc.get_audit(str(client_id), str(audit_id))
    if not run:
        raise HTTPException(status_code=404, detail="coverage_audit_not_found")
    return run


@router.put("/clients/{client_id}/coverage-audit/{audit_id}/service-axis")
async def edit_service_axis(
    client_id: UUID, audit_id: UUID, body: EditServiceAxisRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Confirm/edit the auto-derived service axis and re-run the audit on it. Starts
    a FRESH run (the prior run stays as history); returns the new audit + job ids."""
    _require_enabled()
    run = svc.get_audit(str(client_id), str(audit_id))
    if not run:
        raise HTTPException(status_code=404, detail="coverage_audit_not_found")
    services = [s.strip() for s in body.services if s and s.strip()]
    if not services:
        raise HTTPException(status_code=400, detail="coverage_audit_service_axis_empty")
    try:
        new_audit_id, job_id = svc.enqueue_coverage_audit(
            str(client_id), run.get("tier") or 1, auth["user_id"], service_axis=services
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("coverage_audit.edit_axis_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"audit_id": new_audit_id, "job_id": job_id, "tier": run.get("tier") or 1}


@router.post("/clients/{client_id}/coverage-audit/{audit_id}/seed-matrix")
async def seed_matrix(
    client_id: UUID, audit_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """Seed a Service×Location Matrix from the audit's axes (AXES ONLY — the Matrix
    marks per-cell coverage itself). Returns the created matrix."""
    _require_enabled()
    try:
        matrix = await svc.seed_matrix_from_audit(str(client_id), str(audit_id), auth["user_id"])
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("coverage_audit.seed_matrix_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"matrix": matrix}
