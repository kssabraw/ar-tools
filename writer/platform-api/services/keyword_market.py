"""Keyword market data — CPC / search volume / competition.

Organic Rank Tracker (Module #4). Pulls Google Ads market numbers from
DataForSEO and caches them cross-client by (keyword, location_code), refreshed
monthly. Powers the CPC/volume columns and the estimated-monthly-value ROI
figure. Works regardless of GSC (it's keyword-level, not per-property).

See docs/modules/organic-rank-tracker-prd-v1_0.md §4, §6.
"""

from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services.dataforseo_rank import location_code_for

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"
_VOLUME_PATH = "/v3/keywords_data/google_ads/search_volume/live"
_TIMEOUT = 60.0

# Organic click-through rate by position — a standard decay curve used to turn
# (volume, position, cpc) into an estimated monthly traffic value. Approximate;
# good enough for a relative ROI argument in client reviews (PRD §12).
_CTR_BY_POSITION = {
    1: 0.281, 2: 0.152, 3: 0.106, 4: 0.073, 5: 0.053,
    6: 0.040, 7: 0.030, 8: 0.024, 9: 0.020, 10: 0.017,
}


def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    return {"Authorization": f"Basic {base64.b64encode(creds.encode()).decode()}", "Content-Type": "application/json"}


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def ctr_for_position(position: Optional[float]) -> float:
    """Estimated organic CTR at a SERP position (0 when absent/very low)."""
    if position is None:
        return 0.0
    p = round(position)
    if p in _CTR_BY_POSITION:
        return _CTR_BY_POSITION[p]
    if p <= 20:
        return 0.015
    if p <= 50:
        return 0.005
    if p <= 100:
        return 0.001
    return 0.0


def estimate_monthly_value(
    search_volume: Optional[int], position: Optional[float], cpc: Optional[float]
) -> Optional[float]:
    """volume × CTR-at-position × CPC — the keyword's est. monthly traffic value."""
    if not search_volume or cpc is None or position is None:
        return None
    value = search_volume * ctr_for_position(position) * cpc
    return round(value, 2)


def parse_market_items(items: list[dict]) -> dict[str, dict]:
    """Map DataForSEO search-volume items to {keyword: {volume, cpc, competition}}."""
    out: dict[str, dict] = {}
    for item in items or []:
        kw = item.get("keyword")
        if not kw:
            continue
        out[kw.lower()] = {
            "search_volume": item.get("search_volume"),
            "cpc": item.get("cpc"),
            "competition": item.get("competition"),  # LOW / MEDIUM / HIGH or None
        }
    return out


# ----------------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------------
async def fetch_market(keywords: list[str], location_code: int) -> dict[str, dict]:
    """Batch fetch market data for keywords (one DataForSEO call)."""
    if not keywords:
        return {}
    payload = [
        {
            "keywords": keywords,
            "location_code": location_code,
            "language_code": settings.dataforseo_default_language_code,
        }
    ]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{_VOLUME_PATH}", headers=_auth_header(), json=payload)
        resp.raise_for_status()
        body = resp.json()
    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        raise RuntimeError(f"dataforseo_market_error: {tasks[0].get('status_message') if tasks else 'no tasks'}")
    return parse_market_items(tasks[0].get("result") or [])


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def fetch_cached_market(supabase, keywords: list[str], location_code: int) -> dict[str, dict]:
    """Cached market rows for these keywords at a location, keyed by lower keyword."""
    if not keywords:
        return {}
    rows = (
        supabase.table("keyword_market")
        .select("keyword, search_volume, cpc, competition, refreshed_at")
        .in_("keyword", keywords)
        .eq("location_code", location_code)
        .execute()
    ).data or []
    return {r["keyword"].lower(): r for r in rows}


def stale_keywords(kw_list: list[str], cached: dict[str, dict], stale_cutoff: datetime) -> list[str]:
    """Keywords with no cache row, or one refreshed before the cutoff."""
    out: list[str] = []
    for kw in kw_list:
        row = cached.get(kw.lower())
        if not row:
            out.append(kw)
            continue
        refreshed = row.get("refreshed_at")
        if refreshed and datetime.fromisoformat(refreshed.replace("Z", "+00:00")) < stale_cutoff:
            out.append(kw)
    return out


async def refresh_keywords(supabase, kw_list: list[str], location_code: int, *, force: bool = False) -> dict:
    """Stale-check → one batched DataForSEO fetch → cache upsert, for any keyword
    list. The shared core of the rank tracker's and the brand module's market
    refreshes. force=True re-fetches every keyword — including rows cached with
    null volume/cpc, which the staleness pass deliberately treats as fresh."""
    if not kw_list:
        return {"status": "ok", "fetched": 0}
    cached = fetch_cached_market(supabase, kw_list, location_code)
    if force:
        to_fetch = list(kw_list)
    else:
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.keyword_market_refresh_days)
        to_fetch = stale_keywords(kw_list, cached, stale_cutoff)
    if not to_fetch:
        return {"status": "ok", "fetched": 0, "skipped": len(kw_list)}

    try:
        market = await fetch_market(to_fetch, location_code)
    except Exception as exc:
        logger.warning("keyword_market_failed", extra={"error": str(exc)})
        return {"status": "failed", "error": str(exc), "fetched": 0}

    now_iso = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "keyword": kw,
            "location_code": location_code,
            "search_volume": market.get(kw.lower(), {}).get("search_volume"),
            "cpc": market.get(kw.lower(), {}).get("cpc"),
            "competition": market.get(kw.lower(), {}).get("competition"),
            "refreshed_at": now_iso,
        }
        for kw in to_fetch
    ]
    supabase.table("keyword_market").upsert(records, on_conflict="keyword,location_code").execute()
    return {"status": "ok", "fetched": len(records), "skipped": len(kw_list) - len(to_fetch)}


def _client_location_code(supabase, client_id: str) -> Optional[int]:
    res = supabase.table("clients").select(
        "id, website_url, gbp, rank_tracking_location_code"
    ).eq("id", client_id).limit(1).execute()
    if not res.data:
        return None
    return location_code_for(res.data[0])


async def refresh_client_market(client_id: str, today: Optional[date] = None) -> dict:
    """Refresh stale/missing market data for a client's rank-tracker keywords
    (monthly cadence)."""
    supabase = get_supabase()
    location_code = _client_location_code(supabase, client_id)
    if location_code is None:
        return {"status": "failed", "error": "client_not_found", "fetched": 0}

    keywords = (
        supabase.table("tracked_keywords").select("keyword").eq("client_id", client_id).eq("active", True).execute()
    ).data or []
    kw_list = [k["keyword"] for k in keywords]
    if not kw_list:
        return {"status": "ok", "fetched": 0}

    result = await refresh_keywords(supabase, kw_list, location_code)
    if result.get("status") == "ok" and result.get("fetched"):
        logger.info("keyword_market_complete", extra={"client_id": client_id, "fetched": result["fetched"]})
    return result


async def refresh_brand_market(client_id: str, *, force: bool = False) -> dict:
    """The same refresh for the AI Visibility module's active brand keywords
    (Lead Valuation card) — scope='brand' of the keyword_market job."""
    supabase = get_supabase()
    location_code = _client_location_code(supabase, client_id)
    if location_code is None:
        return {"status": "failed", "error": "client_not_found", "fetched": 0}

    keywords = (
        supabase.table("brand_tracked_keywords").select("keyword")
        .eq("client_id", client_id).eq("is_active", True).execute()
    ).data or []
    kw_list = [k["keyword"] for k in keywords]
    if not kw_list:
        return {"status": "ok", "fetched": 0}
    return await refresh_keywords(supabase, kw_list, location_code, force=force)


def market_job_pending(supabase, client_id: str, scope: str) -> bool:
    """Is a keyword_market job for this client+scope already pending/running?"""
    rows = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "keyword_market")
        .eq("entity_id", client_id)
        .eq("payload->>scope", scope)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    ).data
    return bool(rows)


def enqueue_keyword_market(client_id: str, *, scope: str = "rank", force: bool = False) -> None:
    """Enqueue a market refresh (idempotent per client+scope). scope='rank'
    covers tracked_keywords; scope='brand' covers brand_tracked_keywords."""
    supabase = get_supabase()
    if market_job_pending(supabase, client_id, scope):
        return
    supabase.table("async_jobs").insert(
        {
            "job_type": "keyword_market",
            "entity_id": client_id,
            "payload": {"client_id": client_id, "scope": scope, "force": force},
        }
    ).execute()


async def run_keyword_market_job(job: dict) -> None:
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    if (payload.get("scope") or "rank") == "brand":
        result = await refresh_brand_market(client_id, force=bool(payload.get("force")))
    else:
        result = await refresh_client_market(client_id)
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.get("status") == "ok" else "failed",
            "result": result,
            "error": result.get("error"),
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()
