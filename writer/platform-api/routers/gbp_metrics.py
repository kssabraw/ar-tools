"""Google Business Profile performance-metrics connection + ingest router.

GBP metrics ingestion. Lets the team register a client's GBP location, surface
the service-account email to add as a Manager, resolve the ``locations/{id}``
the Performance API needs, verify access, and trigger/observe ingests.

Mirrors routers/gsc.py. Authorization follows the suite model: any authenticated
user reads/manages (like clients). All DB access uses the service-role client.
The whole surface no-ops with clear errors while ``gbp_metrics_enabled`` is off.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from config import settings
from fastapi import APIRouter, Depends, HTTPException, Response

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.gbp_metrics import (
    GbpBackfillResponse,
    GbpIngestResponse,
    GbpLocation,
    GbpLocationCreateRequest,
    GbpServiceAccountInfo,
    GbpSyncRun,
    GbpVerifyResponse,
    ResolvedLocation,
    ResolveLocationsResponse,
)
from services import gbp_metrics_ingest
from services import gbp_performance_service as gbp

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gbp-metrics"])


@router.get("/gbp/service-account-email", response_model=GbpServiceAccountInfo)
async def get_service_account_email(auth: dict = Depends(require_auth)) -> GbpServiceAccountInfo:
    """The email the client adds as a Manager on their Business Profile."""
    try:
        return GbpServiceAccountInfo(email=gbp.get_service_account_email())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/gbp/resolve-locations", response_model=ResolveLocationsResponse)
async def resolve_locations(auth: dict = Depends(require_auth)) -> ResolveLocationsResponse:
    """List the GBP locations the service account can see, to register one.

    The Performance API keys on ``locations/{id}`` (not the Place ID we store),
    and only returns locations the service account manages — so this is how the
    team finds the right id after adding the SA as a Manager."""
    result = gbp.resolve_locations()
    return ResolveLocationsResponse(
        locations=[
            ResolvedLocation(
                location_id=loc.location_id,
                account_id=loc.account_id,
                title=loc.title,
                address=loc.address,
                place_id=loc.place_id,
            )
            for loc in result.locations
        ],
        detail=result.detail,
    )


@router.get("/clients/{client_id}/gbp-locations", response_model=list[GbpLocation])
async def list_locations(
    client_id: UUID, auth: dict = Depends(require_auth)
) -> list[GbpLocation]:
    supabase = get_supabase()
    result = (
        supabase.table("gbp_locations")
        .select("*")
        .eq("client_id", str(client_id))
        .order("created_at")
        .execute()
    )
    return [GbpLocation(**row) for row in (result.data or [])]


@router.post("/clients/{client_id}/gbp-locations", response_model=GbpLocation)
async def create_location(
    client_id: UUID,
    body: GbpLocationCreateRequest,
    auth: dict = Depends(require_auth),
) -> GbpLocation:
    try:
        location_id = gbp.normalize_location_id(body.location_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"validation_error: {exc}")

    supabase = get_supabase()
    try:
        result = (
            supabase.table("gbp_locations")
            .insert(
                {
                    "client_id": str(client_id),
                    "location_id": location_id,
                    "account_id": body.account_id,
                    "place_id": body.place_id,
                    "title": body.title,
                    "access_status": "pending",
                    "created_by": auth["user_id"],
                }
            )
            .execute()
        )
    except Exception as exc:
        logger.error("gbp_location_create_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=409, detail="conflict: location already registered for this client"
        )
    return GbpLocation(**result.data[0])


@router.delete("/gbp-locations/{location_row_id}", status_code=204, response_class=Response)
async def delete_location(location_row_id: UUID, auth: dict = Depends(require_auth)) -> Response:
    supabase = get_supabase()
    supabase.table("gbp_locations").delete().eq("id", str(location_row_id)).execute()
    return Response(status_code=204)


@router.post("/gbp-locations/{location_row_id}/verify", response_model=GbpVerifyResponse)
async def verify_location(
    location_row_id: UUID, auth: dict = Depends(require_auth)
) -> GbpVerifyResponse:
    """Run a live 1-day fetch and update the location's access_status."""
    supabase = get_supabase()
    found = (
        supabase.table("gbp_locations").select("*").eq("id", str(location_row_id)).limit(1).execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    loc = found.data[0]

    result = gbp.verify_location_access(loc["location_id"])

    # Persist only definitive ok/no_access; a transient 'error' (key/quota)
    # leaves the stored status unchanged and is surfaced via `detail`.
    if result.status in ("ok", "no_access"):
        now = datetime.now(timezone.utc).isoformat()
        updated = (
            supabase.table("gbp_locations")
            .update({"access_status": result.status, "last_verified_at": now, "updated_at": now})
            .eq("id", str(location_row_id))
            .execute()
        )
        row = updated.data[0]
        return GbpVerifyResponse(
            location_row_id=location_row_id,
            access_status=row["access_status"],
            detail=result.detail,
            last_verified_at=row["last_verified_at"],
        )

    return GbpVerifyResponse(
        location_row_id=location_row_id,
        access_status=loc["access_status"],
        detail=result.detail,
        last_verified_at=loc.get("last_verified_at"),
    )


@router.post("/gbp-locations/{location_row_id}/ingest", response_model=GbpIngestResponse)
async def trigger_ingest(
    location_row_id: UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    auth: dict = Depends(require_auth),
) -> GbpIngestResponse:
    """Run a GBP metrics ingest now. Omit dates for the default trailing window."""
    result = gbp_metrics_ingest.ingest_location(str(location_row_id), start_date, end_date)
    return GbpIngestResponse(
        location_row_id=location_row_id,
        status=result.status,
        rows=result.rows,
        error=result.error,
    )


@router.post("/gbp-locations/{location_row_id}/backfill", response_model=GbpBackfillResponse)
async def trigger_backfill(
    location_row_id: UUID, auth: dict = Depends(require_auth)
) -> GbpBackfillResponse:
    """Queue a one-time historical pull (~18 months) via the job worker."""
    supabase = get_supabase()
    found = (
        supabase.table("gbp_locations")
        .select("id, access_status")
        .eq("id", str(location_row_id))
        .limit(1)
        .execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    if found.data[0]["access_status"] != "ok":
        raise HTTPException(status_code=422, detail="location_not_verified")

    end = date.today()
    start = end - timedelta(days=settings.gbp_metrics_backfill_days)
    pending = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "gbp_metrics_ingest")
        .eq("entity_id", str(location_row_id))
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if not pending.data:
        supabase.table("async_jobs").insert(
            {
                "job_type": "gbp_metrics_ingest",
                "entity_id": str(location_row_id),
                "payload": {
                    "location_row_id": str(location_row_id),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                },
            }
        ).execute()
    return GbpBackfillResponse(
        location_row_id=location_row_id,
        status="queued",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )


@router.get("/gbp-locations/{location_row_id}/sync-runs", response_model=list[GbpSyncRun])
async def list_sync_runs(
    location_row_id: UUID, auth: dict = Depends(require_auth)
) -> list[GbpSyncRun]:
    supabase = get_supabase()
    result = (
        supabase.table("gbp_sync_runs")
        .select("*")
        .eq("location_row_id", str(location_row_id))
        .order("run_at", desc=True)
        .limit(20)
        .execute()
    )
    return [GbpSyncRun(**row) for row in (result.data or [])]
