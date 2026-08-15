"""Google Analytics (GA4) property connection router.

Client Reporting Phase 2, "Connection (service account)". Lets the team register
a client's GA4 property, surface the service-account email to add as a Viewer,
discover visible properties via the Admin API, and verify access with a live
report query.

Authorization follows the suite model: any authenticated user reads; admins
manage (mirrors clients/GSC). All DB access uses the service-role client.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.ga4 import (
    Ga4IngestJobStatus,
    Ga4IngestResponse,
    Ga4Property,
    Ga4PropertyCreateRequest,
    Ga4PropertySummary,
    Ga4SyncRun,
    Ga4VerifyResponse,
)
from models.gsc import ServiceAccountInfo
from services import ga4_ingest, ga4_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ga4"])


@router.get("/ga4/service-account-email", response_model=ServiceAccountInfo)
async def get_service_account_email(auth: dict = Depends(require_auth)) -> ServiceAccountInfo:
    """The email the client adds as a Viewer on their GA4 property."""
    try:
        return ServiceAccountInfo(email=ga4_service.get_service_account_email())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/ga4/property-summaries", response_model=list[Ga4PropertySummary])
async def list_property_summaries(auth: dict = Depends(require_auth)) -> list[Ga4PropertySummary]:
    """Every GA4 property the service account can see (Admin API), so the connect
    UI can offer a picker instead of hand-typed numeric ids."""
    try:
        # Blocking Google HTTP call — run off the event loop.
        summaries = await run_in_threadpool(ga4_service.list_property_summaries)
    except ga4_service.Ga4ApiError as exc:
        verdict = ga4_service.classify_access_error(exc.status_code, exc.message)
        # API not enabled or SA added nowhere yet — actionable setup states.
        raise HTTPException(status_code=502, detail=verdict.detail or "ga4_admin_api_error")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [
        Ga4PropertySummary(
            property_id=s.property_id, display_name=s.display_name, account_name=s.account_name
        )
        for s in summaries
    ]


@router.get("/clients/{client_id}/ga4-properties", response_model=list[Ga4Property])
async def list_properties(client_id: UUID, auth: dict = Depends(require_auth)) -> list[Ga4Property]:
    supabase = get_supabase()
    result = (
        supabase.table("ga4_properties")
        .select("*")
        .eq("client_id", str(client_id))
        .order("created_at")
        .execute()
    )
    return [Ga4Property(**row) for row in (result.data or [])]


@router.post("/clients/{client_id}/ga4-properties", response_model=Ga4Property)
async def create_property(
    client_id: UUID,
    body: Ga4PropertyCreateRequest,
    auth: dict = Depends(require_auth),
) -> Ga4Property:
    try:
        property_id = ga4_service.normalize_property_id(body.property_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"validation_error: {exc}")

    supabase = get_supabase()
    try:
        result = (
            supabase.table("ga4_properties")
            .insert(
                {
                    "client_id": str(client_id),
                    "property_id": property_id,
                    "display_name": body.display_name,
                    "access_status": "pending",
                    "created_by": auth["user_id"],
                }
            )
            .execute()
        )
    except Exception as exc:
        logger.error("ga4_property_create_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=409, detail="conflict: property already registered for this client"
        )
    return Ga4Property(**result.data[0])


@router.delete("/ga4-properties/{property_id}", status_code=204, response_class=Response)
async def delete_property(property_id: UUID, auth: dict = Depends(require_auth)) -> Response:
    supabase = get_supabase()
    supabase.table("ga4_properties").delete().eq("id", str(property_id)).execute()
    return Response(status_code=204)


@router.post("/ga4-properties/{property_id}/verify", response_model=Ga4VerifyResponse)
async def verify_property(property_id: UUID, auth: dict = Depends(require_auth)) -> Ga4VerifyResponse:
    """Run a live test report and update the property's access_status."""
    supabase = get_supabase()
    found = (
        supabase.table("ga4_properties").select("*").eq("id", str(property_id)).limit(1).execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    prop = found.data[0]

    # Blocking Google HTTP call — run off the event loop.
    result = await run_in_threadpool(ga4_service.verify_property_access, prop["property_id"])

    if result.status in ("ok", "no_access"):
        now = datetime.now(timezone.utc).isoformat()
        updated = (
            supabase.table("ga4_properties")
            .update(
                {"access_status": result.status, "last_verified_at": now, "updated_at": now}
            )
            .eq("id", str(property_id))
            .execute()
        )
        row = updated.data[0]
        return Ga4VerifyResponse(
            property_id=property_id,
            access_status=row["access_status"],
            detail=result.detail,
            last_verified_at=row["last_verified_at"],
        )

    # Transient 'error' (key missing/API not enabled) leaves stored status alone.
    return Ga4VerifyResponse(
        property_id=property_id,
        access_status=prop["access_status"],
        detail=result.detail,
        last_verified_at=prop.get("last_verified_at"),
    )


@router.post("/ga4-properties/{property_id}/ingest", response_model=Ga4IngestResponse)
async def trigger_ingest(
    property_id: UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    auth: dict = Depends(require_auth),
) -> Ga4IngestResponse:
    """Sync GA4 now. Enqueues a background ingest for the default trailing window
    (poll ``GET .../ingest/{job_id}``). An explicit start_date/end_date runs
    synchronously — used for a bounded, deliberate re-pull/backfill."""
    if start_date or end_date:
        # Blocking (GA4 HTTP + DB) — run off the event loop for the sync path.
        result = await run_in_threadpool(
            ga4_ingest.ingest_property, str(property_id), start_date, end_date
        )
        return Ga4IngestResponse(
            property_id=property_id, status=result.status, rows=result.rows, error=result.error
        )
    job_id = ga4_ingest.enqueue_ingest(str(property_id))
    return Ga4IngestResponse(property_id=property_id, status="queued", job_id=job_id)


@router.get("/ga4-properties/{property_id}/ingest/{job_id}", response_model=Ga4IngestJobStatus)
async def ingest_status(
    property_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)
) -> Ga4IngestJobStatus:
    rows = (
        get_supabase().table("async_jobs")
        .select("id, status, result, error")
        .eq("id", str(job_id)).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="job_not_found")
    row = rows[0]
    result = row.get("result") or {}
    return Ga4IngestJobStatus(
        job_id=job_id, status=row["status"], rows=result.get("rows", 0), error=row.get("error")
    )


@router.get("/ga4-properties/{property_id}/sync-runs", response_model=list[Ga4SyncRun])
async def list_sync_runs(property_id: UUID, auth: dict = Depends(require_auth)) -> list[Ga4SyncRun]:
    supabase = get_supabase()
    result = (
        supabase.table("ga4_sync_runs")
        .select("*")
        .eq("property_id", str(property_id))
        .order("run_at", desc=True)
        .limit(20)
        .execute()
    )
    return [Ga4SyncRun(**row) for row in (result.data or [])]
