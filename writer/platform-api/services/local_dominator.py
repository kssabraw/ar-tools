"""Local Dominator client + geo-grid scan orchestration (Module #5).

Maps / local-pack geo-grid ranker. The team configures a per-client grid (a
3/5/7-mile radius at 1-mile spacing around the business) and tracked keywords;
this runs scans via the Local Dominator API and stores the business's Maps rank
per pin for a heatmap + a trend over time.

Flow (async, decoupled so the worker never blocks on a multi-minute scan):
  - `run_maps_scan_job` (async_jobs 'maps_scan') POSTs /v1/scans and stores the
    returned scan_uuid with status 'polling' — quick.
  - the shared scheduler's `poll_pending_maps_scans` GETs /v1/scans/{uuid} each
    tick; 202 = still running, 200 = done → parse the per-keyword `content`
    grids into maps_scan_results and mark the scan complete.

The Local Dominator `Scan` row gives us `keyword`, `center_lat/lng`,
`average_rank` (precomputed) and `content` — a 2-D grid of the business's rank
per pin (integer, 1 = best; `null` = not ranked at that pin).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from statistics import mean
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services import maps_grid

logger = logging.getLogger(__name__)

_SCANS_PATH = "/v1/scans"
_TIMEOUT = 60.0
# Maps ranking universe — pins ranked beyond this are treated as "not in top N".
RANK_UNIVERSE = 20


def _auth_header() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.local_dominator_api_key}",
        "Content-Type": "application/json",
    }


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def summarize_grid(content: list[list]) -> dict:
    """Roll a `content` rank grid up into pin counts + a computed average.

    `content[row][col]` is the business's rank at that pin (int, 1 = best) or
    None when it doesn't rank there. Returns total/found/top3/top10 pin counts
    and the mean rank over pins where it ranks (None if it ranks nowhere).
    """
    ranks: list[int] = []
    total = 0
    top3 = top10 = 0
    for row in content or []:
        for cell in row:
            total += 1
            if isinstance(cell, (int, float)) and 1 <= cell <= RANK_UNIVERSE:
                r = int(cell)
                ranks.append(r)
                if r <= 3:
                    top3 += 1
                if r <= 10:
                    top10 += 1
    return {
        "total_pins": total,
        "found_pins": len(ranks),
        "top3_pins": top3,
        "top10_pins": top10,
        "computed_average": round(mean(ranks), 2) if ranks else None,
    }


def build_scan_request(config: dict, keywords: list[str]) -> dict:
    """The POST /v1/scans body for a client's grid config + active keywords."""
    radius = config["radius_miles"]
    params = maps_grid.grid_params(radius)  # {grid_size, distance} (1-mile spacing)
    return {
        "latitude": config["center_lat"],
        "longitude": config["center_lng"],
        "shape": "circle",  # the grid is always a circle (user decision)
        "distance": params["distance"],
        "google_place_id": config["google_place_id"],
        "grid_size": params["grid_size"],
        "search_terms": keywords,
        "resource_category": config.get("resource_category") or "googleMaps",
        "serp_device": config.get("serp_device") or "desktop",
    }


# ----------------------------------------------------------------------------
# Fetch (I/O)
# ----------------------------------------------------------------------------
async def create_scan(body: dict) -> str:
    """POST a one-off scan; returns the Local Dominator scan_uuid."""
    url = f"{settings.local_dominator_base_url}{_SCANS_PATH}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=_auth_header(), json=body)
    if resp.status_code == 401:
        raise RuntimeError("local_dominator_unauthorized: invalid API key")
    if resp.status_code >= 400:
        raise RuntimeError(f"local_dominator_create_failed: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    scan_uuid = data.get("scan_uuid")
    if not scan_uuid:
        raise RuntimeError(f"local_dominator_no_scan_uuid: {str(data)[:200]}")
    return scan_uuid


async def get_scan_rows(scan_uuid: str) -> tuple[str, Optional[list[dict]]]:
    """GET scan details. Returns ('complete', rows) at 200, ('running', None)
    at 202, or raises on 4xx/5xx (404 = scan not found)."""
    url = f"{settings.local_dominator_base_url}{_SCANS_PATH}/{scan_uuid}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, headers=_auth_header())
    if resp.status_code == 202:
        return "running", None
    if resp.status_code == 200:
        rows = resp.json()
        return "complete", rows if isinstance(rows, list) else []
    raise RuntimeError(f"local_dominator_get_failed: {resp.status_code} {resp.text[:300]}")


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
async def start_client_scan(client_id: str, trigger: str = "scheduled") -> dict:
    """Validate a client's grid config, POST a scan, and record it as 'polling'."""
    supabase = get_supabase()
    config = (
        supabase.table("maps_scan_configs").select("*").eq("client_id", client_id).limit(1).execute()
    ).data
    if not config:
        return {"status": "failed", "error": "no_config"}
    config = config[0]
    if not config.get("google_place_id") or config.get("center_lat") is None or config.get("center_lng") is None:
        return {"status": "failed", "error": "config_incomplete"}

    keywords = [
        k["keyword"]
        for k in (
            supabase.table("maps_keywords")
            .select("keyword")
            .eq("client_id", client_id)
            .eq("active", True)
            .execute()
        ).data
        or []
    ]
    if not keywords:
        return {"status": "failed", "error": "no_keywords"}

    body = build_scan_request(config, keywords)
    try:
        scan_uuid = await create_scan(body)
    except Exception as exc:
        logger.warning("maps_scan_create_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("maps_scans").insert(
            {
                "client_id": client_id, "status": "failed", "trigger": trigger,
                "grid_size": body["grid_size"], "distance": body["distance"], "shape": body["shape"],
                "radius_miles": config["radius_miles"], "center_lat": body["latitude"],
                "center_lng": body["longitude"], "resource_category": body["resource_category"],
                "serp_device": body["serp_device"], "search_terms": keywords, "error": str(exc)[:500],
            }
        ).execute()
        return {"status": "failed", "error": str(exc)}

    supabase.table("maps_scans").insert(
        {
            "client_id": client_id, "scan_uuid": scan_uuid, "status": "polling", "trigger": trigger,
            "grid_size": body["grid_size"], "distance": body["distance"], "shape": body["shape"],
            "radius_miles": config["radius_miles"], "center_lat": body["latitude"],
            "center_lng": body["longitude"], "resource_category": body["resource_category"],
            "serp_device": body["serp_device"], "search_terms": keywords,
        }
    ).execute()
    logger.info("maps_scan_started", extra={"client_id": client_id, "scan_uuid": scan_uuid, "keywords": len(keywords)})
    return {"status": "polling", "scan_uuid": scan_uuid, "keywords": len(keywords)}


def _store_results(supabase, scan_row: dict, rows: list[dict]) -> int:
    """Parse the Local Dominator Scan rows into maps_scan_results (one per
    keyword). Returns the number of keyword results stored."""
    stored: set[str] = set()
    inserts: list[dict] = []
    for r in rows:
        keyword = r.get("keyword")
        if not keyword or keyword in stored:
            continue  # one result per keyword (default desktop → one row each)
        stored.add(keyword)
        content = r.get("content") or []
        summary = summarize_grid(content)
        api_avg = r.get("average_rank")
        inserts.append(
            {
                "scan_id": scan_row["id"],
                "client_id": scan_row["client_id"],
                "keyword": keyword,
                "average_rank": api_avg if api_avg is not None else summary["computed_average"],
                "found_pins": summary["found_pins"],
                "total_pins": summary["total_pins"],
                "top3_pins": summary["top3_pins"],
                "top10_pins": summary["top10_pins"],
                "rank_grid": content,
            }
        )
    if inserts:
        supabase.table("maps_scan_results").insert(inserts).execute()
    return len(inserts)


async def poll_scan(scan_row: dict) -> str:
    """Poll one in-flight scan; store results + mark complete when done, or fail
    it on timeout. Returns the resulting status."""
    supabase = get_supabase()
    scan_id = scan_row["id"]
    scan_uuid = scan_row.get("scan_uuid")
    if not scan_uuid:
        supabase.table("maps_scans").update({"status": "failed", "error": "missing scan_uuid"}).eq("id", scan_id).execute()
        return "failed"

    try:
        status, rows = await get_scan_rows(scan_uuid)
    except Exception as exc:
        logger.warning("maps_scan_poll_error", extra={"scan_id": scan_id, "error": str(exc)})
        return "polling"  # transient — try again next tick (until timeout below)

    if status == "running":
        requested = scan_row.get("requested_at") or scan_row.get("created_at")
        if requested:
            started = datetime.fromisoformat(str(requested).replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - started).total_seconds() / 60
            if age_min > settings.maps_scan_poll_timeout_minutes:
                supabase.table("maps_scans").update(
                    {"status": "failed", "error": "poll_timeout"}
                ).eq("id", scan_id).execute()
                return "failed"
        return "polling"

    # Complete — store per-keyword results, mark done, stamp the config.
    n = _store_results(supabase, scan_row, rows or [])
    supabase.table("maps_scans").update(
        {"status": "complete", "completed_at": "now()"}
    ).eq("id", scan_id).execute()
    supabase.table("maps_scan_configs").update({"last_scanned_at": "now()"}).eq(
        "client_id", scan_row["client_id"]
    ).execute()
    logger.info("maps_scan_complete", extra={"scan_id": scan_id, "keywords": n})
    return "complete"


async def poll_pending_maps_scans() -> int:
    """Scheduler pass: advance every in-flight ('polling') scan. Returns count."""
    supabase = get_supabase()
    pending = (
        supabase.table("maps_scans").select("*").eq("status", "polling").limit(50).execute()
    ).data or []
    for scan_row in pending:
        try:
            await poll_scan(scan_row)
        except Exception as exc:
            logger.warning("maps_scan_poll_failed", extra={"scan_id": scan_row.get("id"), "error": str(exc)})
    return len(pending)


# ----------------------------------------------------------------------------
# Jobs + scheduler enqueue
# ----------------------------------------------------------------------------
def enqueue_maps_scan(client_id: str, trigger: str = "scheduled") -> bool:
    """Enqueue a maps_scan create job (deduped against pending/running ones)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "maps_scan").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return False
    supabase.table("async_jobs").insert(
        {"job_type": "maps_scan", "entity_id": client_id, "payload": {"client_id": client_id, "trigger": trigger}}
    ).execute()
    return True


async def run_maps_scan_job(job: dict) -> None:
    """async_jobs handler for job_type='maps_scan' — creates the scan (quick)."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    result = await start_client_scan(client_id, trigger=payload.get("trigger", "scheduled"))
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.get("status") in ("polling", "complete") else "failed",
            "result": result, "error": result.get("error"), "completed_at": "now()",
        }
    ).eq("id", job_id).execute()


def enqueue_due_maps_scans() -> int:
    """Weekly: enqueue a scan for each client with an active weekly config + keywords."""
    supabase = get_supabase()
    configs = (
        supabase.table("maps_scan_configs").select("client_id")
        .eq("active", True).eq("cadence", "weekly").execute()
    ).data or []
    enqueued = 0
    for cfg in configs:
        kw = (
            supabase.table("maps_keywords").select("id")
            .eq("client_id", cfg["client_id"]).eq("active", True).limit(1).execute()
        ).data
        if kw and enqueue_maps_scan(cfg["client_id"], trigger="scheduled"):
            enqueued += 1
    if enqueued:
        logger.info("maps_scans_enqueued", extra={"clients": enqueued})
    return enqueued
