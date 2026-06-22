"""Google Search Console property connection router.

Organic Rank Tracker (Module #4), M1 "Connection (service account)". Lets the
team register a client's GSC property, surface the service-account email to add,
and verify access with a live test query.

Authorization follows the suite model: any authenticated user reads; admins
manage (mirrors clients). All DB access uses the service-role client.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from config import settings

from fastapi import APIRouter, Depends, HTTPException, Response

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.gsc import (
    BackfillResponse,
    GscProperty,
    GscPropertyCreateRequest,
    IngestResponse,
    ServiceAccountInfo,
    SyncRun,
    VerifyAccessResponse,
)
from services import gsc_ingest, gsc_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gsc"])


@router.get("/gsc/service-account-email", response_model=ServiceAccountInfo)
async def get_service_account_email(auth: dict = Depends(require_auth)) -> ServiceAccountInfo:
    """The email the client adds as a user on their Search Console property."""
    try:
        return ServiceAccountInfo(email=gsc_service.get_service_account_email())
    except RuntimeError as exc:
        # Service account not configured yet — a setup/ops problem, not the
        # caller's fault. Surface the specific reason for the onboarding UI.
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/clients/{client_id}/gsc-properties", response_model=list[GscProperty])
async def list_properties(
    client_id: UUID, auth: dict = Depends(require_auth)
) -> list[GscProperty]:
    supabase = get_supabase()
    result = (
        supabase.table("gsc_properties")
        .select("*")
        .eq("client_id", str(client_id))
        .order("created_at")
        .execute()
    )
    return [GscProperty(**row) for row in (result.data or [])]


@router.post("/clients/{client_id}/gsc-properties", response_model=GscProperty)
async def create_property(
    client_id: UUID,
    body: GscPropertyCreateRequest,
    auth: dict = Depends(require_auth),
) -> GscProperty:
    property_type = body.property_type or gsc_service.infer_property_type(body.site_url)
    try:
        site_url = gsc_service.normalize_site_url(body.site_url, property_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"validation_error: {exc}")

    supabase = get_supabase()
    try:
        result = (
            supabase.table("gsc_properties")
            .insert(
                {
                    "client_id": str(client_id),
                    "site_url": site_url,
                    "property_type": property_type,
                    "access_status": "pending",
                    "created_by": auth["user_id"],
                }
            )
            .execute()
        )
    except Exception as exc:
        # Most likely the (client_id, site_url) unique constraint.
        logger.error("gsc_property_create_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=409, detail="conflict: property already registered for this client"
        )
    return GscProperty(**result.data[0])


@router.delete("/gsc-properties/{property_id}", status_code=204, response_class=Response)
async def delete_property(property_id: UUID, auth: dict = Depends(require_auth)) -> Response:
    supabase = get_supabase()
    supabase.table("gsc_properties").delete().eq("id", str(property_id)).execute()
    return Response(status_code=204)


@router.post("/gsc-properties/{property_id}/verify", response_model=VerifyAccessResponse)
async def verify_property(
    property_id: UUID, auth: dict = Depends(require_auth)
) -> VerifyAccessResponse:
    """Run a live test query and update the property's access_status."""
    supabase = get_supabase()
    found = (
        supabase.table("gsc_properties")
        .select("*")
        .eq("id", str(property_id))
        .limit(1)
        .execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    prop = found.data[0]

    result = gsc_service.verify_property_access(prop["site_url"], prop["property_type"])

    # The access_status column only stores ok/no_access/pending. A transient
    # 'error' (e.g. key not configured) leaves the stored status unchanged and
    # is reported via `detail` so the UI can show the real reason.
    if result.status in ("ok", "no_access"):
        now = datetime.now(timezone.utc).isoformat()
        updated = (
            supabase.table("gsc_properties")
            .update(
                {
                    "access_status": result.status,
                    "last_verified_at": now,
                    "updated_at": now,
                }
            )
            .eq("id", str(property_id))
            .execute()
        )
        row = updated.data[0]
        return VerifyAccessResponse(
            property_id=property_id,
            access_status=row["access_status"],
            detail=result.detail,
            last_verified_at=row["last_verified_at"],
        )

    return VerifyAccessResponse(
        property_id=property_id,
        access_status=prop["access_status"],
        detail=result.detail,
        last_verified_at=prop.get("last_verified_at"),
    )


@router.post("/gsc-properties/{property_id}/ingest", response_model=IngestResponse)
async def trigger_ingest(
    property_id: UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    auth: dict = Depends(require_auth),
) -> IngestResponse:
    """Run a GSC ingest now (admin). Omit dates for the default trailing window;
    pass start_date/end_date (YYYY-MM-DD) for a wider initial backfill."""
    result = gsc_ingest.ingest_property(str(property_id), start_date, end_date)
    return IngestResponse(
        property_id=property_id,
        status=result.status,
        rows=result.rows,
        error=result.error,
    )


@router.post("/gsc-properties/{property_id}/backfill", response_model=BackfillResponse)
async def trigger_backfill(
    property_id: UUID, auth: dict = Depends(require_auth)
) -> BackfillResponse:
    """Queue a one-time historical pull (~16 months) so the store keeps GSC data
    forever. Runs in the background via the job worker (admin)."""
    supabase = get_supabase()
    found = (
        supabase.table("gsc_properties").select("id, access_status").eq("id", str(property_id)).limit(1).execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    if found.data[0]["access_status"] != "ok":
        raise HTTPException(status_code=422, detail="property_not_verified")

    end = date.today()
    start = end - timedelta(days=settings.gsc_backfill_days)
    # Dedupe: don't stack backfills if one is already queued/running.
    pending = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "gsc_ingest")
        .eq("entity_id", str(property_id))
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if not pending.data:
        supabase.table("async_jobs").insert(
            {
                "job_type": "gsc_ingest",
                "entity_id": str(property_id),
                "payload": {
                    "property_id": str(property_id),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                },
            }
        ).execute()
    return BackfillResponse(
        property_id=property_id, status="queued",
        start_date=start.isoformat(), end_date=end.isoformat(),
    )


@router.get("/gsc-properties/{property_id}/sync-runs", response_model=list[SyncRun])
async def list_sync_runs(
    property_id: UUID, auth: dict = Depends(require_auth)
) -> list[SyncRun]:
    supabase = get_supabase()
    result = (
        supabase.table("sync_runs")
        .select("*")
        .eq("property_id", str(property_id))
        .order("run_at", desc=True)
        .limit(20)
        .execute()
    )
    return [SyncRun(**row) for row in (result.data or [])]
