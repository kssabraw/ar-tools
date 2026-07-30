"""Client site inventory — what pages the client's LIVE website actually has.

SerMaStr could see everything about a campaign except the site it is being run
on. Its `content` context module counts what THIS suite generated (runs, Local
SEO pages), which is a different question from "does a page for Pompano Beach
already exist?" — the one a ranking-strategy answer turns on. Without it the
advice is guesswork about the client's own site.

Discovery reuses `site_page_index.discover_site_urls` (the sitemap chain, with
a paid DataForSEO ``site:`` query when no sitemap is readable) — the same
source Local SEO, syndication and competitor content-watch already trust. That
is a live network call and sometimes a paid one, so it never runs inside a chat
turn: a weekly `site_inventory` job refreshes one row per client in
`client_site_pages`, and the context provider does a single cheap read.

Pure helpers (`normalize_path`, `classify_path`, `summarize_inventory`) do the
shaping and are unit-tested; everything touching the network or the DB is
impure and best-effort — a site with no readable sitemap yields an empty
inventory and a note, never an error that breaks an answer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Path segments that mark a URL as editorial rather than a landing page. A
# strategy answer cares about the landing pages (do we have a page for this
# service, in this city); 300 blog posts would swamp the prompt.
_BLOG_SEGMENTS = {"blog", "news", "articles", "post", "posts", "insights",
                  "resources", "guides", "updates", "case-studies", "press"}
_LOCATION_SEGMENTS = {"locations", "location", "areas", "area", "service-area",
                      "service-areas", "areas-we-serve", "cities", "suburbs",
                      "regions", "neighborhoods", "neighbourhoods"}
_SERVICE_SEGMENTS = {"services", "service", "our-services", "what-we-do",
                     "solutions", "treatments", "specialties"}
_PRODUCT_SEGMENTS = {"product", "products", "shop", "store", "collections",
                     "collection", "category", "categories"}
# Non-content paths worth dropping outright — they tell a strategy nothing.
_NOISE_SEGMENTS = {"wp-content", "wp-json", "feed", "tag", "author", "cart",
                   "checkout", "my-account", "privacy-policy", "terms",
                   "terms-of-service", "sitemap", "search", "page"}


def normalize_path(url: str) -> str:
    """The path of `url`, lower-cased, without query/fragment, with a single
    leading slash and no trailing one (''/'' for the homepage). Pure."""
    if not url:
        return ""
    try:
        path = urlsplit(str(url).strip()).path or "/"
    except ValueError:
        return ""
    path = path.lower().rstrip("/")
    if not path:
        return "/"
    return path if path.startswith("/") else "/" + path


def _segments(path: str) -> list[str]:
    return [s for s in (path or "").split("/") if s]


def classify_path(path: str) -> str:
    """Bucket a path: home | blog | location | service | product | noise | other.

    Segment-based and deliberately coarse — this drives a prompt summary, not a
    decision. Pure."""
    segs = _segments(path)
    if not segs:
        return "home"
    if any(s in _NOISE_SEGMENTS for s in segs):
        return "noise"
    if any(s in _BLOG_SEGMENTS for s in segs):
        return "blog"
    if any(s in _LOCATION_SEGMENTS for s in segs):
        return "location"
    if any(s in _SERVICE_SEGMENTS for s in segs):
        return "service"
    if any(s in _PRODUCT_SEGMENTS for s in segs):
        return "product"
    return "other"


def summarize_inventory(
    urls: list[str], *, max_paths: Optional[int] = None
) -> dict:
    """Compact the raw URL list into something a prompt can carry. Pure.

    Returns per-bucket counts plus a capped list of LANDING paths (everything
    that isn't a blog post or noise), shallowest first — that ordering puts the
    service and city pages a strategy question is about at the top, and drops
    the deep tail rather than the pages that matter.
    """
    cap = max_paths if max_paths is not None else settings.site_inventory_context_paths
    seen: set[str] = set()
    counts: dict[str, int] = {}
    landing: list[str] = []
    for url in urls or []:
        path = normalize_path(url)
        if not path or path in seen:
            continue
        seen.add(path)
        bucket = classify_path(path)
        counts[bucket] = counts.get(bucket, 0) + 1
        if bucket not in ("blog", "noise"):
            landing.append(path)
    # Shallow before deep, then alphabetical — stable and readable.
    landing.sort(key=lambda p: (len(_segments(p)), p))
    return {
        "page_count": len(seen),
        "counts": counts,
        "landing_pages": landing[:cap],
        "landing_truncated": max(0, len(landing) - cap),
    }


# ---------------------------------------------------------------------------
# Reads + refresh (impure)
# ---------------------------------------------------------------------------


def get_inventory(client_id: str) -> Optional[dict]:
    """The stored snapshot for a client, or None. One PK lookup — safe to call
    on a chat turn. Never raises."""
    try:
        rows = (
            get_supabase().table("client_site_pages")
            .select("urls, page_count, source, error, fetched_at")
            .eq("client_id", client_id)
            .limit(1)
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("site_inventory.read_failed", extra={"error": str(exc)})
        return None
    return rows[0] if rows else None


async def refresh_site_inventory(client_id: str) -> dict:
    """Re-discover the client's live URLs and upsert the snapshot.

    Best-effort: a client with no website, an unreadable sitemap or a failed
    fallback stores an empty inventory with `source='none'` (and `error` when
    something actually broke) rather than raising — an absent inventory must
    never break an answer that only wanted to mention it.
    """
    from services import dataforseo_rank, site_page_index

    supabase = get_supabase()
    rows = (
        supabase.table("clients")
        .select("website_url, rank_tracking_location_code, gbp")
        .eq("id", client_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        return {"page_count": 0, "source": "none", "error": "client_not_found"}
    client = rows[0]
    website = (client.get("website_url") or "").strip()
    if not website:
        _store(client_id, [], "none", "no_website")
        return {"page_count": 0, "source": "none", "error": "no_website"}

    location_code = dataforseo_rank.location_code_for(client)
    error: Optional[str] = None
    try:
        urls, source = await site_page_index.discover_site_urls(
            website,
            location_code,
            use_paid_fallback=settings.site_inventory_paid_fallback,
        )
    except Exception as exc:  # discover_site_urls is best-effort, but belt-and-braces
        logger.warning(
            "site_inventory.discover_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )
        urls, source, error = [], "none", str(exc)[:300]

    urls = urls[: settings.site_inventory_max_urls]
    _store(client_id, urls, source, error)
    logger.info(
        "site_inventory.refreshed",
        extra={"client_id": client_id, "pages": len(urls), "source": source},
    )
    return {"page_count": len(urls), "source": source, "error": error}


def _store(client_id: str, urls: list[str], source: str, error: Optional[str]) -> None:
    try:
        get_supabase().table("client_site_pages").upsert(
            {
                "client_id": client_id,
                "urls": urls,
                "page_count": len(urls),
                "source": source,
                "error": error,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="client_id",
        ).execute()
    except Exception as exc:
        logger.error(
            "site_inventory.store_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )


# ---------------------------------------------------------------------------
# Job + schedule
# ---------------------------------------------------------------------------


def enqueue_site_inventory(client_id: str) -> Optional[str]:
    """Queue one refresh; returns the job id (None if it couldn't be queued)."""
    try:
        res = (
            get_supabase().table("async_jobs")
            .insert({
                "job_type": "site_inventory",
                "entity_id": client_id,
                "status": "pending",
                "payload": {"client_id": client_id},
            })
            .execute()
        )
        return (res.data or [{}])[0].get("id")
    except Exception as exc:
        logger.error(
            "site_inventory.enqueue_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )
        return None


async def run_site_inventory_job(job: dict) -> None:
    """Worker entry point for a `site_inventory` job.

    The worker loop only logs unhandled errors — a handler must settle its own
    async_jobs row, else the job sits `running` until the stale reaper requeues
    it and the refresh (with its paid fallback) re-runs on a loop.
    """
    supabase = get_supabase()
    client_id = (job.get("payload") or {}).get("client_id") or job.get("entity_id")
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
        return
    try:
        result = await refresh_site_inventory(client_id)
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:
        logger.warning(
            "site_inventory.job_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


def enqueue_due_site_inventory() -> int:
    """Daily tick: enqueue a refresh for every client whose snapshot is older
    than `site_inventory_interval_days` (or missing entirely). Returns the
    number queued."""
    if not settings.site_inventory_enabled:
        return 0
    supabase = get_supabase()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.site_inventory_interval_days)
    try:
        clients = (
            supabase.table("clients")
            .select("id, website_url")
            .eq("archived", False)
            .execute()
        ).data or []
        fetched = {
            r["client_id"]: r.get("fetched_at")
            for r in (
                supabase.table("client_site_pages")
                .select("client_id, fetched_at").execute()
            ).data or []
        }
        due = []
        for c in clients:
            if not (c.get("website_url") or "").strip():
                continue  # nothing to discover
            ts = fetched.get(c["id"])
            if ts is None or datetime.fromisoformat(ts.replace("Z", "+00:00")) <= cutoff:
                due.append(c["id"])
        if not due:
            return 0
        pending = {
            r["entity_id"] for r in (
                supabase.table("async_jobs").select("entity_id")
                .eq("job_type", "site_inventory")
                .in_("status", ["pending", "running"]).execute()
            ).data or []
        }
    except Exception as exc:
        logger.error("site_inventory.due_check_failed", extra={"error": str(exc)})
        return 0
    queued = 0
    for client_id in due:
        if client_id in pending:
            continue
        if enqueue_site_inventory(client_id):
            queued += 1
    if queued:
        logger.info("site_inventory.enqueued_due", extra={"count": queued})
    return queued
