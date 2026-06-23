"""Maps / local-pack geo-grid ranker router (Module #5).

Per-client geo-grid config + keywords + scans via Local Dominator. The team
picks a 3/5/7-mile radius (1-mile pin spacing) around the business and tracked
keywords; scans run weekly on the shared scheduler plus on-demand. All DB access
uses the service-role client; any authenticated user can operate it.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.maps import (
    MapsConfig,
    MapsConfigUpdate,
    MapsKeyword,
    MapsKeywordCreate,
    MapsRunResponse,
    MapsScanDetail,
    MapsScanResultRow,
    MapsScanSummary,
)
from services import local_dominator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["maps"])

_CONFIG_FIELDS = (
    "client_id", "google_place_id", "business_name", "center_lat", "center_lng",
    "radius_miles", "shape", "resource_category", "serp_device", "cadence",
    "weekday", "active", "last_scanned_at",
)


def _prefill_center(gbp: dict | None) -> tuple[float | None, float | None]:
    """Best-effort lat/lng from the client's stored GBP payload."""
    if not isinstance(gbp, dict):
        return None, None
    lat = gbp.get("latitude") or gbp.get("lat")
    lng = gbp.get("longitude") or gbp.get("lng") or gbp.get("lon")
    loc = gbp.get("location") if isinstance(gbp.get("location"), dict) else None
    if loc:
        lat = lat or loc.get("latitude") or loc.get("lat")
        lng = lng or loc.get("longitude") or loc.get("lng")
    try:
        return (float(lat) if lat is not None else None, float(lng) if lng is not None else None)
    except (TypeError, ValueError):
        return None, None


@router.get("/clients/{client_id}/maps/config", response_model=MapsConfig)
async def get_config(client_id: UUID, auth: dict = Depends(require_auth)) -> MapsConfig:
    """The client's grid config, or a default prefilled from its GBP if unset."""
    supabase = get_supabase()
    existing = (
        supabase.table("maps_scan_configs").select("*").eq("client_id", str(client_id)).limit(1).execute()
    ).data
    if existing:
        return MapsConfig(**{k: existing[0].get(k) for k in _CONFIG_FIELDS}, configured=True)

    client = (
        supabase.table("clients").select("name, gbp_place_id, gbp").eq("id", str(client_id)).limit(1).execute()
    ).data
    if not client:
        raise HTTPException(status_code=404, detail="client_not_found")
    c = client[0]
    lat, lng = _prefill_center(c.get("gbp"))
    return MapsConfig(
        client_id=client_id,
        google_place_id=c.get("gbp_place_id"),
        business_name=c.get("name"),
        center_lat=lat,
        center_lng=lng,
        configured=False,
    )


@router.put("/clients/{client_id}/maps/config", response_model=MapsConfig)
async def put_config(
    client_id: UUID, body: MapsConfigUpdate, auth: dict = Depends(require_auth)
) -> MapsConfig:
    supabase = get_supabase()
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    update["client_id"] = str(client_id)
    update["updated_at"] = "now()"
    supabase.table("maps_scan_configs").upsert(update, on_conflict="client_id").execute()
    row = (
        supabase.table("maps_scan_configs").select("*").eq("client_id", str(client_id)).limit(1).execute()
    ).data[0]
    return MapsConfig(**{k: row.get(k) for k in _CONFIG_FIELDS}, configured=True)


@router.get("/clients/{client_id}/maps/keywords", response_model=list[MapsKeyword])
async def list_keywords(client_id: UUID, auth: dict = Depends(require_auth)) -> list[MapsKeyword]:
    rows = (
        supabase_keywords(client_id)
    )
    return [MapsKeyword(id=r["id"], keyword=r["keyword"], active=r["active"]) for r in rows]


def supabase_keywords(client_id: UUID) -> list[dict]:
    return (
        get_supabase().table("maps_keywords").select("id, keyword, active")
        .eq("client_id", str(client_id)).order("created_at").execute()
    ).data or []


@router.post("/clients/{client_id}/maps/keywords", response_model=list[MapsKeyword])
async def add_keywords(
    client_id: UUID, body: MapsKeywordCreate, auth: dict = Depends(require_auth)
) -> list[MapsKeyword]:
    supabase = get_supabase()
    seen: set[str] = set()
    rows = []
    for raw in body.keywords:
        kw = raw.strip()
        if not kw or kw.lower() in seen:
            continue
        seen.add(kw.lower())
        rows.append({"client_id": str(client_id), "keyword": kw})
    if rows:
        # Ignore duplicates already tracked (unique on client_id+keyword).
        supabase.table("maps_keywords").upsert(rows, on_conflict="client_id,keyword", ignore_duplicates=True).execute()
    return await list_keywords(client_id, auth=auth)


@router.delete("/maps-keywords/{keyword_id}", status_code=204, response_class=Response)
async def delete_keyword(keyword_id: UUID, auth: dict = Depends(require_auth)) -> Response:
    get_supabase().table("maps_keywords").delete().eq("id", str(keyword_id)).execute()
    return Response(status_code=204)


@router.post("/clients/{client_id}/maps/scan", response_model=MapsRunResponse)
async def run_scan(client_id: UUID, auth: dict = Depends(require_auth)) -> MapsRunResponse:
    """Enqueue an on-demand geo-grid scan. Validates the config + keywords first."""
    supabase = get_supabase()
    config = (
        supabase.table("maps_scan_configs").select("google_place_id, center_lat, center_lng")
        .eq("client_id", str(client_id)).limit(1).execute()
    ).data
    if not config:
        return MapsRunResponse(client_id=client_id, status="failed", error="no_config")
    c = config[0]
    if not c.get("google_place_id") or c.get("center_lat") is None or c.get("center_lng") is None:
        return MapsRunResponse(client_id=client_id, status="failed", error="config_incomplete")
    if not supabase_keywords(client_id):
        return MapsRunResponse(client_id=client_id, status="failed", error="no_keywords")

    local_dominator.enqueue_maps_scan(str(client_id), trigger="manual")
    return MapsRunResponse(client_id=client_id, status="enqueued")


@router.post("/clients/{client_id}/maps/poll")
async def poll_scans(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Advance this client's in-flight scans now (the UI calls this on an interval
    while a scan is running, so results land faster than the 5-min scheduler)."""
    advanced = await local_dominator.poll_client_scans(str(client_id))
    return {"polled": advanced}


@router.get("/clients/{client_id}/maps/scans", response_model=list[MapsScanSummary])
async def list_scans(client_id: UUID, auth: dict = Depends(require_auth)) -> list[MapsScanSummary]:
    rows = (
        get_supabase().table("maps_scans")
        .select("id, scan_uuid, status, trigger, radius_miles, grid_size, requested_at, completed_at, error")
        .eq("client_id", str(client_id)).order("created_at", desc=True).limit(50).execute()
    ).data or []
    return [MapsScanSummary(**r) for r in rows]


def _scan_detail(scan_id: str) -> MapsScanDetail:
    supabase = get_supabase()
    found = supabase.table("maps_scans").select("*").eq("id", scan_id).limit(1).execute().data
    if not found:
        raise HTTPException(status_code=404, detail="not_found")
    s = found[0]
    results = (
        supabase.table("maps_scan_results")
        .select("keyword, average_rank, found_pins, total_pins, top3_pins, top10_pins, rank_grid, heatmap_image_url, dynamic_url")
        .eq("scan_id", scan_id).order("keyword").execute()
    ).data or []
    return MapsScanDetail(
        id=s["id"], scan_uuid=s.get("scan_uuid"), status=s["status"], trigger=s["trigger"],
        radius_miles=s.get("radius_miles"), grid_size=s.get("grid_size"), shape=s.get("shape"),
        distance=s.get("distance"), center_lat=s.get("center_lat"), center_lng=s.get("center_lng"),
        resource_category=s.get("resource_category"), serp_device=s.get("serp_device"),
        requested_at=s.get("requested_at"), completed_at=s.get("completed_at"), error=s.get("error"),
        results=[MapsScanResultRow(**r) for r in results],
    )


@router.get("/maps-scans/{scan_id}", response_model=MapsScanDetail)
async def get_scan(scan_id: UUID, auth: dict = Depends(require_auth)) -> MapsScanDetail:
    return _scan_detail(str(scan_id))


@router.get("/clients/{client_id}/maps/latest", response_model=MapsScanDetail)
async def latest_scan(client_id: UUID, auth: dict = Depends(require_auth)) -> MapsScanDetail:
    """The most recent completed scan's detail (the module's landing view)."""
    rows = (
        get_supabase().table("maps_scans").select("id")
        .eq("client_id", str(client_id)).eq("status", "complete")
        .order("completed_at", desc=True).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="no_completed_scan")
    return _scan_detail(rows[0]["id"])
