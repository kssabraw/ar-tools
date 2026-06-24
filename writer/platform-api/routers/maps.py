"""Maps / local-pack geo-grid ranker router (Module #5).

Per-client geo-grid config + keywords + scans via Local Dominator. The team
picks a 3/5/7-mile radius (1-mile pin spacing) around the business and tracked
keywords; scans run weekly on the shared scheduler plus on-demand. All DB access
uses the service-role client; any authenticated user can operate it.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.maps import (
    MapsClientThreats,
    MapsCompetitorTrend,
    MapsCompetitorTrendPoint,
    MapsCompetitorTrendsResponse,
    MapsConfig,
    MapsConfigUpdate,
    MapsKeyword,
    MapsKeywordCreate,
    MapsKeywordTrend,
    MapsRunResponse,
    MapsScanDetail,
    MapsScanResultRow,
    MapsScanSummary,
    MapsThreat,
    MapsThreatsResponse,
    MapsTrendPoint,
    MapsTrendsResponse,
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


@router.post("/clients/{client_id}/maps/scan/cancel")
async def cancel_client_scan(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Stop the client's in-flight scan and drop any queued (not-yet-started) one.
    Drives the Heatmap "Stop scan" control, covering both a running scan and a
    scan that's still sitting in the job queue."""
    return local_dominator.cancel_client_scans(str(client_id))


@router.get("/clients/{client_id}/maps/scans", response_model=list[MapsScanSummary])
async def list_scans(client_id: UUID, auth: dict = Depends(require_auth)) -> list[MapsScanSummary]:
    rows = (
        get_supabase().table("maps_scans")
        .select("id, scan_uuid, status, trigger, radius_miles, grid_size, search_terms, requested_at, completed_at, error")
        .eq("client_id", str(client_id)).order("created_at", desc=True).limit(50).execute()
    ).data or []
    return [MapsScanSummary(**r) for r in rows]


@router.delete("/clients/{client_id}/maps/scans")
async def clear_scans(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Clear the client's scan history. Deletes every terminal scan (and its
    per-keyword results, via cascade); in-flight scans are left untouched —
    stop them first if you want them gone."""
    res = (
        get_supabase().table("maps_scans").delete()
        .eq("client_id", str(client_id))
        .in_("status", ["complete", "failed", "cancelled"]).execute()
    )
    return {"deleted": len(res.data or [])}


@router.post("/maps-scans/{scan_id}/cancel")
async def cancel_scan(scan_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Cancel a single in-flight scan (the History list's Stop control)."""
    return local_dominator.cancel_scan(str(scan_id))


@router.delete("/maps-scans/{scan_id}")
async def delete_scan(scan_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Hard-delete one scan and its results. Blocked while the scan is in flight
    (cancel it first) so a running scan can't be silently orphaned."""
    supabase = get_supabase()
    found = supabase.table("maps_scans").select("status").eq("id", str(scan_id)).limit(1).execute().data
    if not found:
        raise HTTPException(status_code=404, detail="not_found")
    if found[0]["status"] in ("pending", "polling"):
        raise HTTPException(status_code=409, detail="scan_in_flight")
    supabase.table("maps_scans").delete().eq("id", str(scan_id)).execute()
    return {"deleted": True}


def _scan_detail(scan_id: str) -> MapsScanDetail:
    supabase = get_supabase()
    found = supabase.table("maps_scans").select("*").eq("id", scan_id).limit(1).execute().data
    if not found:
        raise HTTPException(status_code=404, detail="not_found")
    s = found[0]
    results = (
        supabase.table("maps_scan_results")
        .select("keyword, average_rank, found_pins, total_pins, top3_pins, top10_pins, rank_grid, heatmap_image_url, dynamic_url, competitors, competitors_above, report_status, report_md, report_weak_directions, report_top_competitors, report_octant_pins, report_analytics, report_doc_url, report_generated_at")
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


@router.post("/clients/{client_id}/maps/report")
async def trigger_maps_report(
    client_id: UUID, scan_id: Optional[UUID] = None, auth: dict = Depends(require_auth),
) -> dict:
    """(Re)generate the Local Rank Analysis report for a scan — defaults to the
    client's latest completed scan. Reports also generate automatically when a
    scan completes; this backfills existing scans and forces a regeneration."""
    from services.maps_report import enqueue_maps_report

    supabase = get_supabase()
    if scan_id is None:
        rows = (
            supabase.table("maps_scans").select("id")
            .eq("client_id", str(client_id)).eq("status", "complete")
            .order("completed_at", desc=True).limit(1).execute()
        ).data
        if not rows:
            raise HTTPException(status_code=404, detail="no_completed_scan")
        target = rows[0]["id"]
    else:
        target = str(scan_id)
    enqueued = enqueue_maps_report(target)
    return {"scan_id": target, "enqueued": enqueued}


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


def _pct(n: int | None, d: int | None) -> float | None:
    """A 0–100 percentage rounded to 1 dp, or None when there are no pins."""
    if not d:
        return None
    return round(100 * (n or 0) / d, 1)


def build_maps_trends(scans: list[dict], results: list[dict]) -> MapsTrendsResponse:
    """Pure aggregation: turn completed scans + their per-keyword results into a
    per-keyword time series (oldest → newest) of coverage metrics. Kept free of
    DB access so it can be unit-tested directly."""
    meta = {s["id"]: s for s in scans}
    by_keyword: dict[str, list[MapsTrendPoint]] = {}
    for r in results:
        s = meta.get(r.get("scan_id"))
        if not s:
            continue
        total = r.get("total_pins") or 0
        point = MapsTrendPoint(
            scan_id=r["scan_id"],
            completed_at=s.get("completed_at"),
            trigger=s.get("trigger", "scheduled"),
            total_pins=total,
            found_pins=r.get("found_pins") or 0,
            top3_pins=r.get("top3_pins") or 0,
            top10_pins=r.get("top10_pins") or 0,
            average_rank=r.get("average_rank"),
            found_pct=_pct(r.get("found_pins"), total),
            top3_pct=_pct(r.get("top3_pins"), total),
            top10_pct=_pct(r.get("top10_pins"), total),
        )
        by_keyword.setdefault(r["keyword"], []).append(point)
    keywords = [
        MapsKeywordTrend(
            keyword=kw,
            points=sorted(by_keyword[kw], key=lambda p: p.completed_at or ""),
        )
        for kw in sorted(by_keyword)
    ]
    return MapsTrendsResponse(keywords=keywords)


@router.get("/clients/{client_id}/maps/trends", response_model=MapsTrendsResponse)
async def maps_trends(
    client_id: UUID, limit: int = 52, auth: dict = Depends(require_auth)
) -> MapsTrendsResponse:
    """Per-keyword trend across the client's completed scans — Top-3 %, Top-10 %,
    Found %, and average rank over time — for charting in History/reporting."""
    supabase = get_supabase()
    scans = (
        supabase.table("maps_scans").select("id, completed_at, trigger")
        .eq("client_id", str(client_id)).eq("status", "complete")
        .order("completed_at", desc=True).limit(max(1, min(limit, 200))).execute()
    ).data or []
    if not scans:
        return MapsTrendsResponse()
    results = (
        supabase.table("maps_scan_results")
        .select("scan_id, keyword, average_rank, found_pins, total_pins, top3_pins, top10_pins")
        .in_("scan_id", [s["id"] for s in scans]).execute()
    ).data or []
    return build_maps_trends(scans, results)


def build_competitor_trends(scans: list[dict], results: list[dict], top_n: int = 15) -> MapsCompetitorTrendsResponse:
    """Pure aggregation: across completed scans, how each competitor's pressure on
    the client changes over time. For each scan we tally, per competitor, the
    in-circle pins (summed over keywords) where it ranks above the client, over
    the scan's total in-circle pins → a "beats you %" series. Only scans that
    actually carry competitor data are included (older pre-capture scans are
    skipped so they don't read as a false 0%). DB-free for unit testing."""
    meta = {s["id"]: s for s in scans}
    comp_scan_ids: set = set()
    slots: dict = {}                 # scan_id -> total in-circle pins
    beats: dict = {}                 # scan_id -> place_id -> {pins, rank_sum}
    names: dict = {}                 # place_id -> latest name seen
    for r in results:
        sid = r.get("scan_id")
        if sid not in meta:
            continue
        slots[sid] = slots.get(sid, 0) + (r.get("total_pins") or 0)
        ca = r.get("competitors_above")
        if ca:
            comp_scan_ids.add(sid)
        directory = (ca or {}).get("directory") or {}
        for pid, info in directory.items():
            if isinstance(info, dict) and info.get("name"):
                names[pid] = info["name"]
        sb = beats.setdefault(sid, {})
        for row in (ca or {}).get("grid") or []:
            for cell in row or []:
                if not cell:  # None (out-of-circle) or [] (client ranks 1st)
                    continue
                for entry in cell:
                    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                        continue
                    pid, rank = entry[0], entry[1]
                    e = sb.setdefault(pid, {"pins": 0, "rank_sum": 0})
                    e["pins"] += 1
                    if isinstance(rank, (int, float)):
                        e["rank_sum"] += rank

    order = sorted(comp_scan_ids, key=lambda sid: meta[sid].get("completed_at") or "")
    all_pids: set = set()
    for sid in order:
        all_pids |= set(beats.get(sid, {}).keys())

    competitors: list[MapsCompetitorTrend] = []
    for pid in all_pids:
        points: list[MapsCompetitorTrendPoint] = []
        for sid in order:
            e = beats.get(sid, {}).get(pid)
            total = slots.get(sid, 0)
            pins = e["pins"] if e else 0
            points.append(
                MapsCompetitorTrendPoint(
                    scan_id=sid,
                    completed_at=meta[sid].get("completed_at"),
                    beats_pins=pins,
                    total_slots=total,
                    beats_pct=round(pins / total * 100, 1) if total else None,
                    avg_rank_above=round(e["rank_sum"] / e["pins"], 2) if e and e["pins"] else None,
                )
            )
        pcts = [p.beats_pct for p in points if p.beats_pct is not None]
        competitors.append(
            MapsCompetitorTrend(
                place_id=pid,
                name=names.get(pid),
                latest_pct=pcts[-1] if pcts else None,
                delta_pct=round(pcts[-1] - pcts[0], 1) if len(pcts) >= 2 else None,
                points=points,
            )
        )
    competitors.sort(key=lambda c: -(c.latest_pct or 0))
    return MapsCompetitorTrendsResponse(scan_count=len(order), competitors=competitors[:top_n])


@router.get("/clients/{client_id}/maps/competitor-trends", response_model=MapsCompetitorTrendsResponse)
async def maps_competitor_trends(
    client_id: UUID, limit: int = 52, auth: dict = Depends(require_auth)
) -> MapsCompetitorTrendsResponse:
    """Per-competitor "are they gaining on us?" trend across the client's
    completed scans, from the per-pin above-us capture."""
    supabase = get_supabase()
    scans = (
        supabase.table("maps_scans").select("id, completed_at")
        .eq("client_id", str(client_id)).eq("status", "complete")
        .order("completed_at", desc=True).limit(max(1, min(limit, 200))).execute()
    ).data or []
    if not scans:
        return MapsCompetitorTrendsResponse()
    results = (
        supabase.table("maps_scan_results").select("scan_id, total_pins, competitors_above")
        .in_("scan_id", [s["id"] for s in scans]).execute()
    ).data or []
    return build_competitor_trends(scans, results)


@router.get("/maps/threats", response_model=MapsThreatsResponse)
async def maps_dashboard_threats(top_n: int = 3, auth: dict = Depends(require_auth)) -> MapsThreatsResponse:
    """Top-threat competitors per client for the suite dashboard tiles — the
    businesses currently outranking each client on the most of their grid. One
    call covers every client (two bulk queries), grouped + ranked in memory via
    the same build_competitor_trends used by the per-client view."""
    supabase = get_supabase()
    scans = (
        supabase.table("maps_scans").select("id, client_id, completed_at")
        .eq("status", "complete").order("completed_at", desc=True).limit(300).execute()
    ).data or []
    if not scans:
        return MapsThreatsResponse()
    results = (
        supabase.table("maps_scan_results").select("scan_id, client_id, total_pins, competitors_above")
        .in_("scan_id", [s["id"] for s in scans]).execute()
    ).data or []

    scans_by_client: dict = defaultdict(list)
    results_by_client: dict = defaultdict(list)
    for s in scans:
        scans_by_client[s["client_id"]].append(s)
    for r in results:
        results_by_client[r["client_id"]].append(r)

    out: list[MapsClientThreats] = []
    for client_id, client_scans in scans_by_client.items():
        trends = build_competitor_trends(client_scans, results_by_client.get(client_id, []))
        threats = [
            MapsThreat(name=c.name, beats_pct=c.latest_pct, delta_pct=c.delta_pct)
            for c in trends.competitors[: max(1, top_n)]
            if c.latest_pct
        ]
        if threats:
            out.append(MapsClientThreats(client_id=client_id, scan_count=trends.scan_count, threats=threats))
    return MapsThreatsResponse(clients=out)
