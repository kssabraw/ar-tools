"""On-site content comparison (Maps strategy PRD, Tier B / B5).

For a keyword, compares the client's ranking page against the top organic
competitor pages on content depth (word count) and topic coverage (section
headings competitors cover that the client's page doesn't) — so "expand your
page" becomes a concrete recommendation.

Reuses DataForSEO SERP (for the URLs) + ScrapeOwl (`website_scraper`) for the
HTML. Extraction + comparison are pure (unit-tested). Deep semantic/entity
comparison (TextRazor via nlp-api) is a follow-up; v1 uses depth + heading
coverage, which are reliable and need no LLM.
"""

from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup

from config import settings
from db.supabase_client import get_supabase
from services.dataforseo_rank import _BASE_URL, _SERP_PATH, _TIMEOUT, _auth_header
from services.website_scraper import scrapeowl_fetch

logger = logging.getLogger(__name__)

_MIN_HEADING_LEN = 3
_MAX_HEADING_LEN = 80


def _domain(url: "str | None") -> str:
    if not url:
        return ""
    u = url.lower()
    if "//" in u:
        u = u.split("//", 1)[1]
    u = u.split("/", 1)[0].split("@")[-1].split(":")[0]
    return u[4:] if u.startswith("www.") else u


def extract_outline(html: "str | None") -> dict:
    """Word count + normalized H2/H3 headings from a page's HTML. Pure."""
    if not html:
        return {"word_count": 0, "headings": []}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    word_count = len(text.split())
    headings: list[str] = []
    seen: set[str] = set()
    for h in soup.find_all(["h2", "h3"]):
        t = " ".join(h.get_text(" ", strip=True).split()).lower()
        if _MIN_HEADING_LEN <= len(t) <= _MAX_HEADING_LEN and t not in seen:
            seen.add(t)
            headings.append(t)
    return {"word_count": word_count, "headings": headings}


def _median_int(values: list[int]) -> "int | None":
    vals = sorted(v for v in values if v is not None)
    return vals[len(vals) // 2] if vals else None


def compare_content(client_outline: dict, competitor_outlines: list[dict], max_gaps: int = 8) -> dict:
    """Depth + topic-coverage gaps: client vs competitor pages. Pure (unit-tested).
    Returns {client_word_count, competitor_median_word_count, depth_behind,
    topic_gaps}."""
    client_wc = (client_outline or {}).get("word_count") or 0
    comp_wcs = [o.get("word_count") or 0 for o in competitor_outlines]
    median = _median_int(comp_wcs)
    depth_behind = (median - client_wc) if median is not None and median > client_wc else None

    client_headings = {h for h in (client_outline or {}).get("headings") or []}
    counts: dict[str, int] = {}
    for o in competitor_outlines:
        for h in set(o.get("headings") or []):
            counts[h] = counts.get(h, 0) + 1
    threshold = (len(competitor_outlines) + 1) // 2 if competitor_outlines else 0
    topic_gaps = [
        h for h, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= threshold and h not in client_headings
    ][:max_gaps]
    return {
        "client_word_count": client_wc,
        "competitor_median_word_count": median,
        "depth_behind": depth_behind,
        "topic_gaps": topic_gaps,
    }


def detect_content_gap(comparison: dict, min_depth_behind: int, min_topic_gaps: int) -> "dict | None":
    """Action-Plan signal: client page meaningfully thinner than competitors or
    missing several topics they all cover. Pure."""
    depth = comparison.get("depth_behind")
    gaps = comparison.get("topic_gaps") or []
    if (depth is None or depth < min_depth_behind) and len(gaps) < min_topic_gaps:
        return None
    return {
        "depth_behind": depth,
        "topic_gaps": gaps,
        "keyword": comparison.get("keyword"),
    }


# --- impure: SERP + scrape + store ------------------------------------------
async def _fetch_top_organic_urls(keyword: str, location_code: int, n: int) -> list[str]:
    payload = [{
        "keyword": keyword,
        "language_code": settings.dataforseo_default_language_code,
        "location_code": location_code,
        "depth": settings.dataforseo_serp_depth,
        "calculate_rectangles": False,
    }]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{_SERP_PATH}", headers=_auth_header(), json=payload)
        resp.raise_for_status()
        body = resp.json()
    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        raise RuntimeError("dataforseo_serp_error")
    items = (tasks[0].get("result") or [{}])[0].get("items") or []
    urls = [it.get("url") for it in items if it.get("type") == "organic" and it.get("url")]
    return urls[:n]


async def analyze_keyword(client_id: str, keyword: str, location_code: int, client_domain: str) -> dict:
    """Fetch the SERP for `keyword`, pick the client's page + the top competitor
    pages, scrape + compare, and store one website_analyses row."""
    urls = await _fetch_top_organic_urls(keyword, location_code, settings.content_intel_max_pages + 5)
    client_url = next((u for u in urls if _domain(u) == client_domain), None)
    competitor_urls = [u for u in urls if _domain(u) != client_domain][: settings.content_intel_max_pages]

    async def _outline(url: str) -> dict:
        try:
            return extract_outline(await scrapeowl_fetch(url))
        except Exception as exc:
            logger.warning("content_intel_scrape_failed", extra={"url": url, "error": str(exc)})
            return {"word_count": 0, "headings": []}

    client_outline = await _outline(client_url) if client_url else {"word_count": 0, "headings": []}
    competitor_outlines = [await _outline(u) for u in competitor_urls]

    comparison = compare_content(client_outline, competitor_outlines)
    row = {
        "client_id": client_id,
        "keyword": keyword,
        "client_url": client_url,
        "client_word_count": comparison["client_word_count"],
        "competitor_median_word_count": comparison["competitor_median_word_count"],
        "depth_behind": comparison["depth_behind"],
        "topic_gaps": comparison["topic_gaps"],
        "competitor_urls": competitor_urls,
    }
    try:
        get_supabase().table("website_analyses").insert(row).execute()
    except Exception as exc:
        logger.error("content_intel_store_failed", extra={"client_id": client_id, "error": str(exc)})
        raise
    return {"keyword": keyword, "client_url": client_url, "competitors": len(competitor_urls),
            "depth_behind": comparison["depth_behind"], "topic_gaps": len(comparison["topic_gaps"])}


def _resolve_keyword_and_location(supabase, client_id: str, keyword: "str | None") -> "tuple[str | None, int, str]":
    client = supabase.table("clients").select(
        "website, website_url, rank_tracking_location_code"
    ).eq("id", client_id).limit(1).execute().data
    c = client[0] if client else {}
    domain = _domain(c.get("website") or c.get("website_url"))
    location_code = c.get("rank_tracking_location_code") or settings.dataforseo_default_location_code
    if not keyword:
        kw = supabase.table("maps_keywords").select("keyword").eq("client_id", client_id).eq("active", True).limit(1).execute().data
        keyword = kw[0]["keyword"] if kw else None
    return keyword, location_code, domain


def latest_analyses(client_id: str) -> list[dict]:
    rows = (
        get_supabase().table("website_analyses")
        .select("keyword, client_url, client_word_count, competitor_median_word_count, "
                "depth_behind, topic_gaps, competitor_urls, captured_at")
        .eq("client_id", client_id).order("captured_at", desc=True).limit(200).execute()
    ).data or []
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        if r.get("keyword") in seen:
            continue
        seen.add(r.get("keyword"))
        out.append(r)
    return out


def enqueue_content_intel(client_id: str, keyword: "str | None" = None) -> bool:
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "content_intel").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return False
    supabase.table("async_jobs").insert(
        {"job_type": "content_intel", "entity_id": client_id, "payload": {"client_id": client_id, "keyword": keyword}}
    ).execute()
    return True


async def run_content_intel_job(job: dict) -> None:
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
        keyword, location_code, domain = _resolve_keyword_and_location(supabase, client_id, payload.get("keyword"))
        if not keyword:
            result = {"skipped": "no_keyword"}
        else:
            result = await analyze_keyword(client_id, keyword, location_code, domain)
    except Exception as exc:
        logger.warning("content_intel_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
