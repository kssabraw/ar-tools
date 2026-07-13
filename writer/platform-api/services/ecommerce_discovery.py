"""Ecommerce page discovery — find a client's live product + collection URLs.

Powers the Reoptimizer's "bulk from sitemap/feed" flow: discover the client's
live site URLs (sitemap → DataForSEO `site:` fallback, via the shared
`site_page_index`), classify each as a product or collection page by URL-path
heuristics, and return the candidates for the user to select + bulk-reoptimize.
Best-effort: no website / unreadable sitemap → empty list + a degraded note,
never an aborted flow.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException

from db.supabase_client import get_supabase
from services.gbp_service import normalize_website_url
from services.site_page_index import discover_site_urls

logger = logging.getLogger(__name__)

# URL-path substrings that signal each ecommerce page type. Product hints are the
# common PDP patterns (Shopify /products/, WooCommerce /product/, generic /p/);
# collection hints are the common PLP/category patterns.
_PRODUCT_HINTS = ("/product/", "/products/", "/item/", "/p/", "/dp/", "/sku/")
_COLLECTION_HINTS = ("/collections/", "/collection/", "/category/", "/categories/", "/shop/", "/store/", "/c/")

# Default DataForSEO location code for the `site:` index fallback (US national).
_DEFAULT_LOCATION_CODE = 2840


def classify_ecommerce_url(url: str) -> Optional[str]:
    """Classify a URL as 'product' | 'collection' | None (not an ecommerce page).

    Collection hints are checked first because a Shopify collection path
    (`/collections/shoes`) also contains the `/collection` substring but is a PLP,
    not a PDP; the product `/products/` and collection `/collections/` patterns are
    distinct so order only matters for the looser hints."""
    path = urlparse(url).path.lower()
    if any(h in path for h in _COLLECTION_HINTS):
        return "collection"
    if any(h in path for h in _PRODUCT_HINTS):
        return "product"
    return None


async def discover_pages(client_id: str, page_type: Optional[str] = None) -> dict:
    """Discover a client's live product/collection URLs from its site.

    Returns ``{"items": [{"url", "page_type"}], "source", "count", "note"}``.
    ``page_type`` optionally filters to just 'product' or 'collection'.
    Never raises for a missing/unreadable site — returns an empty list + note."""
    supabase = get_supabase()
    res = supabase.table("clients").select("website_url, gbp").eq("id", client_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    gbp = res.data.get("gbp") or {}
    website = normalize_website_url(gbp.get("website") or res.data.get("website_url"))
    if not website:
        return {"items": [], "source": "none", "count": 0, "note": "This client has no website on file, so no live pages could be discovered."}

    urls, source = await discover_site_urls(website, _DEFAULT_LOCATION_CODE)
    wanted = page_type if page_type in ("product", "collection") else None

    seen: set[str] = set()
    items: list[dict] = []
    for url in urls:
        kind = classify_ecommerce_url(url)
        if not kind:
            continue
        if wanted and kind != wanted:
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({"url": url, "page_type": kind})

    if source == "none":
        note = "No sitemap was readable and no indexed pages were found for this site."
    elif not items:
        note = f"Discovered {len(urls)} site URLs ({source}), but none matched a product/collection URL pattern."
    else:
        note = f"Found {len(items)} product/collection pages via {source}."
    return {"items": items, "source": source, "count": len(items), "note": note}
