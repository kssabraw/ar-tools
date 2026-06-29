"""Backlink-gap audit (design §6.3). Phase 3.

DataForSEO Backlinks: pull the client's referring-domain profile and each unified
competitor's, then surface domains linking to ≥ N competitors but **not** the
client — a ranked prospect list (`backlink` actions are *assigned*; outreach is
human craft, never auto). Competitors come from
`brand_tracked_competitors.competitor_website` (the §4.8.5 domain-keyed source),
capped at `backlink_max_competitors`.

The gap computation + domain normalization are pure and unit-tested; the
DataForSEO calls are best-effort (a dead target degrades the run, never aborts it).
"""

from __future__ import annotations

import base64
import logging
from collections import Counter
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger("backlink_gap")

_BASE_URL = "https://api.dataforseo.com"
_REFERRING = "/v3/backlinks/referring_domains/live"


# ── pure helpers (unit-tested) ───────────────────────────────────────────────
def registrable_domain(url_or_domain: Optional[str]) -> Optional[str]:
    """Best-effort eTLD+1-ish host: strip scheme/path/port/www. Pure."""
    if not url_or_domain:
        return None
    s = url_or_domain.strip().lower()
    if "://" not in s:
        s = "http://" + s
    host = (urlparse(s).netloc or "").split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def compute_link_gap(
    client_rd: set[str], competitor_rd: dict[str, set[str]], min_competitors: int = 2
) -> list[dict]:
    """Referring domains linking to ≥ min_competitors competitors but not the client. Pure."""
    counter: Counter = Counter()
    for rds in competitor_rd.values():
        for rd in rds:
            counter[rd] += 1
    gaps = [
        {"referring_domain": rd, "competitors_linking": n}
        for rd, n in counter.items()
        if rd not in client_rd and n >= min_competitors
    ]
    gaps.sort(key=lambda g: (g["competitors_linking"], g["referring_domain"]), reverse=True)
    return gaps


def build_result(
    client_domain: Optional[str],
    client_rd: set[str],
    competitor_rd: dict[str, set[str]],
    min_competitors: int,
) -> dict:
    gaps = compute_link_gap(client_rd, competitor_rd, min_competitors)
    return {
        "client_domain": client_domain,
        "client_referring_domains": len(client_rd),
        "competitors_analyzed": len(competitor_rd),
        "gap_count": len(gaps),
        "gaps": gaps[:100],
    }


# ── DataForSEO Backlinks I/O (best-effort) ───────────────────────────────────
def _auth_header() -> str:
    raw = f"{settings.dataforseo_login}:{settings.dataforseo_password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def _referring_domains(client: httpx.AsyncClient, domain: str) -> set[str]:
    try:
        resp = await client.post(
            _BASE_URL + _REFERRING,
            json=[{"target": domain, "limit": settings.backlink_referring_domains_limit}],
            headers={"Authorization": _auth_header()},
            timeout=90,
        )
        resp.raise_for_status()
        tasks = resp.json().get("tasks") or []
        result = (tasks[0].get("result") if tasks else None) or []
        items = (result[0].get("items") if result else None) or []
        return {d for it in items if (d := registrable_domain(it.get("domain")))}
    except Exception as exc:
        logger.warning("backlink_gap.referring_failed", extra={"domain": domain, "error": str(exc)})
        return set()


async def run_backlink_audit(engagement_id: str) -> dict:
    supabase = get_supabase()
    eng = (
        supabase.table("engagements").select("client_id").eq("id", engagement_id).limit(1).execute()
    ).data
    if not eng:
        raise ValueError("engagement_not_found")
    client_id = eng[0]["client_id"]
    client = (
        supabase.table("clients").select("website_url").eq("id", client_id).limit(1).execute()
    ).data
    client_domain = registrable_domain(client[0].get("website_url")) if client else None

    comps = (
        supabase.table("brand_tracked_competitors").select("competitor_website")
        .eq("client_id", client_id).execute()
    ).data or []
    comp_domains: list[str] = []
    for c in comps:
        d = registrable_domain(c.get("competitor_website"))
        if d and d != client_domain and d not in comp_domains:
            comp_domains.append(d)
    comp_domains = comp_domains[: settings.backlink_max_competitors]

    run = (
        supabase.table("audit_runs")
        .insert({"engagement_id": engagement_id, "kind": "backlink_gap", "status": "running"})
        .execute()
    ).data[0]

    async with httpx.AsyncClient() as hc:
        client_rd = await _referring_domains(hc, client_domain) if client_domain else set()
        competitor_rd = {d: await _referring_domains(hc, d) for d in comp_domains}

    result = build_result(client_domain, client_rd, competitor_rd, settings.backlink_min_competitors)
    if not client_domain:
        result["degraded"] = "no_client_domain"
    elif not comp_domains:
        result["degraded"] = "no_competitors"

    supabase.table("audit_runs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", run["id"]).execute()
    logger.info("backlink_audit_complete", extra={"engagement_id": engagement_id, "gaps": result["gap_count"]})
    return {"audit_run_id": run["id"], **result}


# ── async_jobs plumbing ──────────────────────────────────────────────────────
def enqueue_backlink_audit(engagement_id: str) -> None:
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "backlink_audit").eq("entity_id", engagement_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "backlink_audit", "entity_id": engagement_id, "payload": {"engagement_id": engagement_id}}
    ).execute()


async def run_backlink_audit_job(job: dict) -> None:
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
        result = await run_backlink_audit(engagement_id)
    except Exception as exc:
        logger.warning("backlink_audit_job_failed", extra={"engagement_id": engagement_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
