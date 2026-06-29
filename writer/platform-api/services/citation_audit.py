"""Local-citation audit (design §6.4). Phase 3.

Checks the client's presence across a curated **target-directory checklist**
(`settings.citation_directories`) via the existing DataForSEO SERP
(`site:{directory} "{business name}"`). The gap = directories the client is NOT
listed on — "where you need to be." Presence evaluation + the host match are
pure and unit-tested; the SERP lookups are best-effort. NAP-consistency scoring +
the DataForSEO Business Listings API are deferred enhancements (§6.4).
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services.backlink_gap import registrable_domain

logger = logging.getLogger("citation_audit")

_BASE_URL = "https://api.dataforseo.com"
_SERP = "/v3/serp/google/organic/live/advanced"


# ── pure helpers (unit-tested) ───────────────────────────────────────────────
def host_matches_directory(url: Optional[str], directory: str) -> bool:
    """Is `url` hosted on `directory` (or a subdomain of it)? Pure."""
    host = registrable_domain(url)
    if not host:
        return False
    directory = directory.lower().lstrip(".")
    return host == directory or host.endswith("." + directory)


def evaluate_listing(directory: str, serp_urls: list[str]) -> dict:
    """Whether any SERP result is on this directory. Pure."""
    for url in serp_urls:
        if host_matches_directory(url, directory):
            return {"directory": directory, "listed": True, "url": url}
    return {"directory": directory, "listed": False, "url": None}


def build_result(checks: list[dict]) -> dict:
    listed = [c for c in checks if c["listed"]]
    missing = [c["directory"] for c in checks if not c["listed"]]
    return {
        "directories_checked": len(checks),
        "listed_count": len(listed),
        "missing_count": len(missing),
        "missing": missing,         # the "where you need to be" gap
        "listings": listed,
    }


# ── DataForSEO SERP I/O (best-effort) ────────────────────────────────────────
def _auth_header() -> str:
    raw = f"{settings.dataforseo_login}:{settings.dataforseo_password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def _serp_urls(client: httpx.AsyncClient, query: str) -> list[str]:
    try:
        resp = await client.post(
            _BASE_URL + _SERP,
            json=[{"keyword": query, "language_code": "en", "location_code": 2840, "depth": 10}],
            headers={"Authorization": _auth_header()},
            timeout=60,
        )
        resp.raise_for_status()
        tasks = resp.json().get("tasks") or []
        result = (tasks[0].get("result") if tasks else None) or []
        items = (result[0].get("items") if result else None) or []
        return [it.get("url") for it in items if it.get("url")]
    except Exception as exc:
        logger.warning("citation_audit.serp_failed", extra={"query": query, "error": str(exc)})
        return []


async def run_citation_audit(engagement_id: str) -> dict:
    supabase = get_supabase()
    eng = (
        supabase.table("engagements").select("client_id").eq("id", engagement_id).limit(1).execute()
    ).data
    if not eng:
        raise ValueError("engagement_not_found")
    client = (
        supabase.table("clients").select("name, gbp").eq("id", eng[0]["client_id"]).limit(1).execute()
    ).data
    c = client[0] if client else {}
    gbp = c.get("gbp") or {}
    business_name = gbp.get("business_name") or c.get("name")

    run = (
        supabase.table("audit_runs")
        .insert({"engagement_id": engagement_id, "kind": "local_citation", "status": "running"})
        .execute()
    ).data[0]

    checks: list[dict] = []
    if business_name:
        async with httpx.AsyncClient() as hc:
            for directory in settings.citation_directories:
                urls = await _serp_urls(hc, f'site:{directory} "{business_name}"')
                checks.append(evaluate_listing(directory, urls))

    result = build_result(checks)
    if not business_name:
        result["degraded"] = "no_business_name"

    supabase.table("audit_runs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", run["id"]).execute()
    logger.info(
        "citation_audit_complete",
        extra={"engagement_id": engagement_id, "missing": result["missing_count"]},
    )
    return {"audit_run_id": run["id"], **result}


# ── async_jobs plumbing ──────────────────────────────────────────────────────
def enqueue_citation_audit(engagement_id: str) -> None:
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "citation_audit").eq("entity_id", engagement_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "citation_audit", "entity_id": engagement_id, "payload": {"engagement_id": engagement_id}}
    ).execute()


async def run_citation_audit_job(job: dict) -> None:
    payload = job.get("payload") or {}
    engagement_id = payload.get("engagement_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not engagement_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing engagement_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        result = await run_citation_audit(engagement_id)
    except Exception as exc:
        logger.warning("citation_audit_job_failed", extra={"engagement_id": engagement_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
