"""Backlink profiling (Maps strategy PRD, Tier B / B4).

Domain-level backlink authority (Domain Rating, referring domains, total
backlinks) for the client vs its top local-pack competitors — so an authority
gap becomes a concrete Action Plan signal. Reuses the SERP snapshot's DataForSEO
Backlinks summary call (`serp_snapshot.fetch_domain_summary`); stores a
time-series in `backlink_profiles`; comparison is deterministic on read.

Referring-domain-level gap analysis (the specific domains competitors have that
the client lacks) needs the heavier per-domain endpoint and is a follow-up; v1
compares the summary metrics, which are the headline authority signal.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from config import settings
from db.supabase_client import get_supabase
from services import competitor_gbp, serp_snapshot

logger = logging.getLogger(__name__)


def domain_of(url: "str | None") -> "str | None":
    """Bare registrable-ish domain from a URL or host string (drops scheme/path
    and a leading www). Pure (unit-tested)."""
    if not url:
        return None
    u = url.strip().lower()
    if not u:
        return None
    if "//" not in u:
        u = "http://" + u
    host = urlparse(u).netloc or ""
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _median(values: list[float]) -> "float | None":
    vals = sorted(v for v in values if v is not None)
    return vals[len(vals) // 2] if vals else None


def compare(client: dict, competitors: list[dict]) -> dict:
    """Client DR / referring domains vs competitor medians. Pure (unit-tested)."""
    comp_dr = _median([c.get("domain_rating") for c in competitors])
    comp_rd = _median([c.get("referring_domains") for c in competitors])
    cdr = client.get("domain_rating")
    crd = client.get("referring_domains")
    return {
        "competitor_median_dr": comp_dr,
        "competitor_median_referring_domains": comp_rd,
        "dr_behind": round(comp_dr - cdr, 1) if comp_dr is not None and cdr is not None and comp_dr > cdr else None,
        "referring_domains_behind": (comp_rd - crd) if comp_rd is not None and crd is not None and comp_rd > crd else None,
    }


def detect_backlink_gap(comparison: dict, min_dr_behind: float, min_rd_behind: int) -> "dict | None":
    """Action-Plan signal: client authority meaningfully behind the competitor
    median (DR or referring domains). Pure."""
    dr_behind = comparison.get("dr_behind")
    rd_behind = comparison.get("referring_domains_behind")
    if (dr_behind is None or dr_behind < min_dr_behind) and (rd_behind is None or rd_behind < min_rd_behind):
        return None
    return {
        "dr_behind": dr_behind,
        "referring_domains_behind": rd_behind,
        "competitor_median_dr": comparison.get("competitor_median_dr"),
        "competitor_median_referring_domains": comparison.get("competitor_median_referring_domains"),
    }


# --- impure: fetch + store + read -------------------------------------------
async def fetch_and_store(client_id: str) -> dict:
    """Fetch + store backlink summaries for the client domain + top competitor
    domains. Returns {fetched, skipped}."""
    supabase = get_supabase()
    rows: list[dict] = []
    skipped = 0

    client = supabase.table("clients").select("website").eq("id", client_id).limit(1).execute().data
    client_domain = domain_of(client[0].get("website")) if client else None
    targets: list[tuple[str, bool]] = []
    if client_domain:
        targets.append((client_domain, True))
    seen = {client_domain}
    for p in competitor_gbp.latest_profiles(client_id)[: settings.competitor_gbp_max]:
        d = domain_of(p.get("website"))
        if d and d not in seen:
            seen.add(d)
            targets.append((d, False))

    for domain, is_client in targets:
        try:
            s = await serp_snapshot.fetch_domain_summary(domain)
            rows.append({
                "client_id": client_id,
                "domain": domain,
                "is_client": is_client,
                "domain_rating": s.get("domain_rating"),
                "referring_domains": s.get("referring_domains"),
                "backlinks": s.get("backlinks"),
            })
        except Exception as exc:  # one bad domain must not abort the run
            skipped += 1
            logger.warning("backlink_intel_fetch_failed", extra={"client_id": client_id, "domain": domain, "error": str(exc)})

    if rows:
        try:
            supabase.table("backlink_profiles").insert(rows).execute()
        except Exception as exc:
            logger.error("backlink_intel_store_failed", extra={"client_id": client_id, "error": str(exc)})
            raise
    return {"fetched": len(rows), "skipped": skipped}


def get_backlink_intel(client_id: str) -> dict:
    """Latest backlink profile per domain → client vs competitors + comparison."""
    supabase = get_supabase()
    rows = (
        supabase.table("backlink_profiles")
        .select("domain, is_client, domain_rating, referring_domains, backlinks, captured_at")
        .eq("client_id", client_id)
        .order("captured_at", desc=True)
        .limit(500)
        .execute()
    ).data or []
    seen: set[str] = set()
    client: dict = {}
    competitors: list[dict] = []
    for r in rows:  # newest-first → first per domain is latest
        d = r.get("domain")
        if d in seen:
            continue
        seen.add(d)
        if r.get("is_client"):
            client = r
        else:
            competitors.append(r)
    competitors.sort(key=lambda c: -(c.get("domain_rating") or 0))
    return {"client": client, "competitors": competitors, "comparison": compare(client, competitors)}


def enqueue_backlink_intel(client_id: str) -> bool:
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "backlink_intel").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return False
    supabase.table("async_jobs").insert(
        {"job_type": "backlink_intel", "entity_id": client_id, "payload": {"client_id": client_id}}
    ).execute()
    return True


async def run_backlink_intel_job(job: dict) -> None:
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        result = await fetch_and_store(client_id)
    except Exception as exc:
        logger.warning("backlink_intel_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
