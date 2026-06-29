"""Site / technical audit (design §6.2). Phase 3 · PR1.

Audits the client's key pages via DataForSEO **OnPage instant-pages** (one
synchronous call per URL, seeded from the sitemap via `site_page_index`) into a
typed, severity-scored issue list stored on `audit_runs`. The parse + scoring
are pure and unit-tested; the crawl itself is best-effort (a dead URL or missing
creds degrades the run, never aborts it).

A full task-based crawl (DataForSEO OnPage `task_post`) is a follow-up; v1 audits
the top `site_audit_max_pages` URLs, which is enough to surface the dominant
technical issues.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services import site_page_index

logger = logging.getLogger("site_audit")

_BASE_URL = "https://api.dataforseo.com"
_INSTANT_PAGES = "/v3/on_page/instant_pages"

# DataForSEO OnPage `checks` flag → (issue type, severity, human detail).
ISSUE_RULES: list[tuple[str, str, str, str]] = [
    ("no_title", "missing_title", "high", "Page has no <title> tag"),
    ("title_too_long", "title_length", "low", "Title tag is too long"),
    ("title_too_short", "title_length", "low", "Title tag is too short"),
    ("no_description", "missing_meta_description", "medium", "Page has no meta description"),
    ("no_h1_tag", "missing_h1", "medium", "Page has no H1"),
    ("duplicate_title_tag", "duplicate_title", "high", "Duplicate <title> across pages"),
    ("duplicate_meta_tags", "duplicate_meta", "medium", "Duplicate meta description across pages"),
    ("duplicate_content", "duplicate_content", "high", "Duplicate page content"),
    ("low_content_rate", "thin_content", "medium", "Low text-to-code ratio (thin content)"),
    ("small_page_size", "thin_content", "low", "Very small page"),
    ("high_loading_time", "slow_page", "medium", "Slow page load"),
    ("large_page_size", "page_weight", "low", "Large page size"),
    ("no_image_alt", "image_alt", "low", "Images missing alt text"),
    ("is_redirect", "redirect", "low", "Page is a redirect"),
    ("is_4xx_code", "broken_page", "high", "Page returns a 4xx error"),
    ("is_5xx_code", "broken_page", "high", "Page returns a 5xx error"),
    ("is_broken", "broken_page", "high", "Page is broken"),
    ("canonical_another_domain", "canonical_issue", "medium", "Canonical points to another domain"),
    ("no_doctype", "no_doctype", "low", "Missing <!doctype>"),
    ("https_to_http_links", "mixed_content", "medium", "HTTPS page links to HTTP resources"),
    ("no_favicon", "no_favicon", "low", "No favicon"),
]

SEVERITY_WEIGHT = {"high": 8, "medium": 4, "low": 1}


# ── pure parse + score (unit-tested) ─────────────────────────────────────────
def parse_page(page: dict) -> list[dict]:
    """Typed issues for one OnPage page item."""
    url = page.get("url")
    checks = page.get("checks") or {}
    issues = [
        {"type": itype, "severity": sev, "url": url, "detail": detail}
        for key, itype, sev, detail in ISSUE_RULES
        if checks.get(key)
    ]
    sc = page.get("status_code")
    if isinstance(sc, int) and sc >= 400 and not any(i["type"] == "broken_page" for i in issues):
        issues.append({"type": "broken_page", "severity": "high", "url": url, "detail": f"HTTP {sc}"})
    return issues


def score_issues(issues: list[dict], pages_scanned: int) -> int:
    """0–100 health score — clean pages score 100; weighted penalties pull it down."""
    penalty = sum(SEVERITY_WEIGHT.get(i["severity"], 1) for i in issues)
    norm = penalty / max(1, pages_scanned)
    return max(0, min(100, round(100 - norm * 6)))


def build_result(pages: list[dict]) -> dict:
    """Aggregate parsed pages into the stored audit result."""
    issues: list[dict] = []
    for p in pages:
        issues.extend(parse_page(p))
    counts = {"high": 0, "medium": 0, "low": 0}
    for i in issues:
        counts[i["severity"]] = counts.get(i["severity"], 0) + 1
    return {
        "pages_scanned": len(pages),
        "issue_count": len(issues),
        "counts_by_severity": counts,
        "score": score_issues(issues, len(pages)),
        "issues": issues[:200],  # cap what we store
    }


# ── DataForSEO OnPage I/O (best-effort) ──────────────────────────────────────
def _auth_header() -> str:
    raw = f"{settings.dataforseo_login}:{settings.dataforseo_password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def _instant_page(client: httpx.AsyncClient, url: str) -> Optional[dict]:
    try:
        resp = await client.post(
            _BASE_URL + _INSTANT_PAGES,
            json=[{"url": url}],
            headers={"Authorization": _auth_header()},
            timeout=60,
        )
        resp.raise_for_status()
        tasks = resp.json().get("tasks") or []
        result = (tasks[0].get("result") if tasks else None) or []
        items = (result[0].get("items") if result else None) or []
        return items[0] if items else None
    except Exception as exc:  # best-effort per URL
        logger.warning("site_audit.instant_page_failed", extra={"url": url, "error": str(exc)})
        return None


async def _seed_urls(website_url: Optional[str]) -> list[str]:
    if not website_url:
        return []
    loc = getattr(settings, "dataforseo_default_location_code", 2840)
    try:
        urls, _src = await site_page_index.discover_site_urls(website_url, loc)
    except Exception as exc:
        logger.warning("site_audit.seed_failed", extra={"error": str(exc)})
        urls = []
    seeded = [website_url, *[u for u in urls if u != website_url]]
    return seeded[: settings.site_audit_max_pages]


async def run_site_audit(engagement_id: str) -> dict:
    """Create + complete a site_technical audit_runs row for the engagement."""
    supabase = get_supabase()
    eng = (
        supabase.table("engagements").select("client_id").eq("id", engagement_id).limit(1).execute()
    ).data
    if not eng:
        raise ValueError("engagement_not_found")
    client = (
        supabase.table("clients").select("website_url")
        .eq("id", eng[0]["client_id"]).limit(1).execute()
    ).data
    website = client[0].get("website_url") if client else None

    run = (
        supabase.table("audit_runs")
        .insert({"engagement_id": engagement_id, "kind": "site_technical", "status": "running"})
        .execute()
    ).data[0]

    urls = await _seed_urls(website)
    pages: list[dict] = []
    async with httpx.AsyncClient() as hc:
        for u in urls:
            pg = await _instant_page(hc, u)
            if pg:
                pages.append(pg)

    result = build_result(pages)
    degraded = None if website and pages else "no_website" if not website else "crawl_empty"
    if degraded:
        result["degraded"] = degraded

    supabase.table("audit_runs").update(
        {"status": "complete", "result": result, "score": result["score"], "completed_at": "now()"}
    ).eq("id", run["id"]).execute()
    logger.info(
        "site_audit_complete",
        extra={"engagement_id": engagement_id, "pages": len(pages), "issues": result["issue_count"]},
    )
    return {"audit_run_id": run["id"], **result}


# ── async_jobs plumbing ──────────────────────────────────────────────────────
def enqueue_site_audit(engagement_id: str) -> None:
    """Enqueue a site_audit job (deduped against any in-flight one for the engagement)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "site_audit").eq("entity_id", engagement_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "site_audit", "entity_id": engagement_id, "payload": {"engagement_id": engagement_id}}
    ).execute()


async def run_site_audit_job(job: dict) -> None:
    """async_jobs handler for job_type='site_audit'."""
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
        result = await run_site_audit(engagement_id)
    except Exception as exc:
        logger.warning("site_audit_job_failed", extra={"engagement_id": engagement_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
