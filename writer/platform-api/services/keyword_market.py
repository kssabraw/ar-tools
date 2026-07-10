"""Keyword market data — CPC / search volume / competition.

Organic Rank Tracker (Module #4). Pulls Google Ads market numbers from
DataForSEO and caches them cross-client by (keyword, location_code), refreshed
monthly. Powers the CPC/volume columns and the estimated-monthly-value ROI
figure. Works regardless of GSC (it's keyword-level, not per-property).

See docs/modules/organic-rank-tracker-prd-v1_0.md §4, §6.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
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

# DataForSEO Google Ads search_volume validation caps. A single keyword over
# either cap fails the ENTIRE batch request ("Invalid Field: 'keywords'"), so
# ineligible keywords are filtered out before the call (they simply get no
# market data) instead of poisoning every other keyword in the refresh.
_MAX_KEYWORD_CHARS = 80
_MAX_KEYWORD_WORDS = 10
# The endpoint accepts at most 1000 keywords per request; larger sets are
# chunked into multiple requests (billed per request, not per keyword).
_MAX_KEYWORDS_PER_REQUEST = 1000

# Rate-limit retry (mirrors serp_snapshot._post_dfs). DataForSEO throttling can
# arrive as an HTTP 429 OR as an HTTP 200 whose task body says "Too many
# requests" — both are retried with backoff before failing the refresh job.
_DFS_MAX_RETRIES = 3
_DFS_RETRY_BASE_SECONDS = 2.0

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


def market_eligible(keyword: str) -> bool:
    """Whether DataForSEO's Google Ads endpoint will accept this keyword
    (length + word-count caps). Ineligible keywords (long conversational
    queries, full questions) are skipped rather than sent."""
    kw = (keyword or "").strip()
    if not kw or len(kw) > _MAX_KEYWORD_CHARS:
        return False
    return len(kw.split()) <= _MAX_KEYWORD_WORDS


def partition_market_keywords(keywords: list[str]) -> tuple[list[str], list[str]]:
    """Split into (eligible, skipped) for a market fetch. Pure."""
    eligible: list[str] = []
    skipped: list[str] = []
    for kw in keywords:
        (eligible if market_eligible(kw) else skipped).append(kw)
    return eligible, skipped


def chunk_keywords(keywords: list[str], size: int = _MAX_KEYWORDS_PER_REQUEST) -> list[list[str]]:
    """Chunk a keyword list to the endpoint's per-request cap. Pure."""
    return [keywords[i : i + size] for i in range(0, len(keywords), size)]


def is_rate_limited_body(body: dict) -> bool:
    """Whether a DataForSEO response body signals throttling despite HTTP 200
    (the observed live failure: task status_message 'Too many requests.'). Pure."""
    tasks = body.get("tasks") or []
    task = tasks[0] if tasks else {}
    msg = str(task.get("status_message") or body.get("status_message") or "").lower()
    return "too many requests" in msg


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
            # 12-month volume history [{year, month, search_volume}] — powers
            # the trend watcher's seasonality read; comes free on this call.
            "monthly_searches": item.get("monthly_searches"),
        }
    return out


# ----------------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------------
async def fetch_market(keywords: list[str], location_code: int) -> dict[str, dict]:
    """Batch fetch market data for keywords. Filters out keywords DataForSEO
    would reject (one bad keyword fails the whole request) and chunks the rest
    to the 1000-keyword per-request cap (one POST per chunk)."""
    eligible, skipped = partition_market_keywords(keywords)
    if skipped:
        logger.info(
            "keyword_market_skipped_ineligible",
            extra={"skipped": len(skipped), "sample": skipped[:3]},
        )
    if not eligible:
        return {}

    out: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for chunk in chunk_keywords(eligible):
            payload = [
                {
                    "keywords": chunk,
                    "location_code": location_code,
                    "language_code": settings.dataforseo_default_language_code,
                }
            ]
            body = await _post_volume(client, payload)
            tasks = body.get("tasks") or []
            if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
                raise RuntimeError(
                    f"dataforseo_market_error: {tasks[0].get('status_message') if tasks else 'no tasks'}"
                )
            out.update(parse_market_items(tasks[0].get("result") or []))
    return out


async def _post_volume(client: httpx.AsyncClient, payload: list[dict]) -> dict:
    """One search_volume POST with rate-limit retry + exponential backoff
    (jittered, honoring Retry-After). Retries HTTP 429/5xx AND HTTP-200 bodies
    whose task says "Too many requests". After the budget exhausts, the last
    response is returned/raised as before so the caller's validation applies."""
    attempt = 0
    while True:
        resp = await client.post(f"{_BASE_URL}{_VOLUME_PATH}", headers=_auth_header(), json=payload)
        throttled_http = resp.status_code == 429 or resp.status_code >= 500
        body: Optional[dict] = None
        if not throttled_http:
            resp.raise_for_status()
            body = resp.json()
            if not is_rate_limited_body(body):
                return body
        if attempt >= _DFS_MAX_RETRIES:
            if body is not None:
                return body  # body-level throttle after retries → caller raises
            resp.raise_for_status()
        try:
            retry_after = float(resp.headers.get("Retry-After") or 0)
        except ValueError:
            retry_after = 0.0
        delay = max(
            retry_after,
            _DFS_RETRY_BASE_SECONDS * (2 ** attempt) * (0.5 + secrets.randbelow(1000) / 1000.0),
        )
        logger.warning(
            "keyword_market_dfs_retry",
            extra={"status": resp.status_code, "attempt": attempt + 1, "delay_s": round(delay, 1)},
        )
        await asyncio.sleep(delay)
        attempt += 1


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
            "monthly_searches": market.get(kw.lower(), {}).get("monthly_searches"),
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
    covers the rank tracker's tracked_keywords."""
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
    result = await refresh_client_market(client_id)
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.get("status") == "ok" else "failed",
            "result": result,
            "error": result.get("error"),
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()
