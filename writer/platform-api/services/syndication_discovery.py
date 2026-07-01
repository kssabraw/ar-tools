"""Content Syndication — site discovery + new-content detection.

Reuses the suite's sitemap crawler (`site_page_index.discover_site_urls`, which
already falls back to a DataForSEO `site:` query when no sitemap is readable),
classifies each URL into blog_post / page / product by URL-path heuristics, and
records any URL the client hasn't seen before as a new `syndication_items` row.
The unique (client_id, source_url) constraint is the actual "new content"
detector — a re-scan never re-processes a known URL.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# URL-path / sitemap-name substrings that signal each content type. Product is
# checked first (a store URL is never a blog post), then blog, else a generic
# page. Matching is on the lowercased path + the (optional) source sitemap name.
_PRODUCT_HINTS = ("/product/", "/products/", "/shop/", "/store/", "/item/", "/p/")
_PRODUCT_SITEMAP_HINTS = ("product", "shop", "store")
_BLOG_HINTS = (
    "/blog/", "/news/", "/article/", "/articles/", "/post/", "/posts/",
    "/insights/", "/stories/", "/journal/",
)
_BLOG_SITEMAP_HINTS = ("post", "blog", "news", "article")
# A dated path segment (/2024/05/...) is a strong blog/post signal.
_DATED_PATH = re.compile(r"/(?:19|20)\d{2}/(?:0[1-9]|1[0-2])(?:/|$)")


def classify_content_type(url: str, sitemap_name: str = "") -> str:
    """Classify a URL as 'product' | 'blog_post' | 'page' (pure heuristic)."""
    path = (urlparse(url).path or "/").lower()
    name = (sitemap_name or "").lower()

    if any(h in name for h in _PRODUCT_SITEMAP_HINTS) or any(h in path for h in _PRODUCT_HINTS):
        return "product"
    if (
        any(h in name for h in _BLOG_SITEMAP_HINTS)
        or any(h in path for h in _BLOG_HINTS)
        or _DATED_PATH.search(path)
    ):
        return "blog_post"
    return "page"


def _included_types(config: dict) -> set[str]:
    """The content types the client has opted in to syndicate."""
    types: set[str] = set()
    if config.get("include_blog", True):
        types.add("blog_post")
    if config.get("include_pages", True):
        types.add("page")
    if config.get("include_products", True):
        types.add("product")
    return types


async def scan_client(client: dict, config: dict | None = None) -> dict:
    """Discover the client's site URLs and record any not seen before.

    **First scan** (the client has no prior items): every existing URL is
    recorded as a *baseline* — status ``skipped`` — and nothing is published.
    Only content that appears on a LATER scan (i.e. published after the baseline)
    is syndicated. This means enabling the tool never mass-publishes a site's
    existing back catalogue; it only acts on genuinely new content going forward.

    Returns {discovered, new, baseline, source}. ``new`` is the count of
    newly-syndicatable items (always 0 on the baseline scan). Best-effort — a
    site with no readable sitemap/index yields all-zero counts."""
    from services import site_page_index
    from services.dataforseo_rank import location_code_for

    client_id = client["id"]
    website = (client.get("website_url") or "").strip()
    if not website:
        return {"discovered": 0, "new": 0, "baseline": False, "source": "none", "note": "no_website"}

    config = config or {}
    included = _included_types(config)

    code = location_code_for(client)
    urls, source = await site_page_index.discover_site_urls(website, code)
    if not urls:
        return {"discovered": 0, "new": 0, "baseline": False, "source": source}

    supabase = get_supabase()
    existing = (
        supabase.table("syndication_items")
        .select("source_url")
        .eq("client_id", client_id)
        .execute()
    ).data or []
    seen = {row["source_url"] for row in existing}
    # No prior items → this is the baseline scan: seed everything as 'skipped' so
    # the existing site is remembered but never published.
    is_baseline = not seen
    seed_status = "skipped" if is_baseline else "discovered"

    new_rows: list[dict] = []
    batch_seen: set[str] = set()
    for url in urls:
        if url in seen or url in batch_seen:
            continue
        content_type = classify_content_type(url)
        if content_type not in included:
            continue
        batch_seen.add(url)
        new_rows.append(
            {
                "client_id": client_id,
                "source_url": url,
                "content_type": content_type,
                "status": seed_status,
            }
        )

    if new_rows:
        # Insert in one call; ignore_duplicates guards the unique constraint in
        # case a concurrent scan inserted the same URL between our read + write.
        try:
            supabase.table("syndication_items").upsert(
                new_rows, on_conflict="client_id,source_url", ignore_duplicates=True
            ).execute()
        except Exception as exc:  # noqa: BLE001 — degrade rather than abort the scan
            logger.warning("syndication_insert_failed", extra={"client_id": client_id, "error": str(exc)})

    # On the baseline scan nothing is publishable; otherwise the new rows are.
    new_count = 0 if is_baseline else len(new_rows)
    logger.info(
        "syndication_scan",
        extra={
            "client_id": client_id,
            "discovered": len(urls),
            "new": new_count,
            "baseline": is_baseline,
            "seeded": len(new_rows),
            "source": source,
        },
    )
    return {
        "discovered": len(urls),
        "new": new_count,
        "baseline": is_baseline,
        "source": source,
    }
