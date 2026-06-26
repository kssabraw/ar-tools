"""Sitemap fetcher — discover and enumerate a site's published page URLs.

Best-effort, network-bound, and dependency-free (stdlib XML + httpx). Given a
website URL it discovers the site's sitemap(s) — honouring `robots.txt` `Sitemap:`
directives, then falling back to the conventional `/sitemap.xml` and
`/sitemap_index.xml` — walks any nested sitemap-index entries, and returns the flat
list of `<urlset>` page URLs (bounded, deduped, order-preserving).

Used by the service-page planner to drop candidate pages a client already publishes,
but kept generic so other modules can reuse it. Every failure path degrades to an
empty list rather than raising — the caller decides what to do when the site can't
be read.
"""

from __future__ import annotations

import gzip
import logging
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; AR-Tools-SitemapBot/1.0)"
# Cap the body we parse so a hostile/huge sitemap can't exhaust memory or feed an
# XML-expansion bomb to the stdlib parser (clients' own sites, but still untrusted).
_MAX_BYTES = 10 * 1024 * 1024


def _base_url(website_url: str) -> str | None:
    """Reduce a website URL to its `scheme://host` origin. Defaults to https when no
    scheme is given. Returns None when there's no host to work with."""
    raw = (website_url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _strip_ns(tag: str) -> str:
    """`{ns}url` → `url` (sitemaps are namespaced; we match on local names)."""
    return tag.rsplit("}", 1)[-1].lower()


def _decode_body(url: str, response: httpx.Response) -> str | None:
    """Return the sitemap body as text, transparently gunzipping `.xml.gz` (httpx
    only auto-decodes Content-Encoding, not gzipped file bodies)."""
    content = response.content[:_MAX_BYTES]
    if url.lower().endswith(".gz") or content[:2] == b"\x1f\x8b":
        try:
            content = gzip.decompress(content)[:_MAX_BYTES]
        except (OSError, EOFError):
            return None
    try:
        return content.decode(response.encoding or "utf-8", errors="replace")
    except (LookupError, ValueError):
        return content.decode("utf-8", errors="replace")


def _parse(body: str) -> tuple[str, list[str]]:
    """Parse a sitemap body → ("index" | "urlset" | "", [loc, ...]). A sitemapindex
    yields child sitemap URLs; a urlset yields page URLs."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return "", []
    kind = _strip_ns(root.tag)
    locs: list[str] = []
    for child in root:
        if _strip_ns(child.tag) not in ("sitemap", "url"):
            continue
        for sub in child:
            if _strip_ns(sub.tag) == "loc" and (sub.text or "").strip():
                locs.append(sub.text.strip())
                break
    if kind == "sitemapindex":
        return "index", locs
    if kind == "urlset":
        return "urlset", locs
    return "", []


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        resp = await client.get(url)
    except httpx.HTTPError:
        return None
    return resp if resp.status_code == 200 else None


async def _discover_sitemaps(client: httpx.AsyncClient, base: str) -> list[str]:
    """Sitemap URLs declared in robots.txt, else the conventional defaults."""
    found: list[str] = []
    resp = await _get(client, f"{base}/robots.txt")
    if resp is not None:
        for line in resp.text.splitlines():
            if line.strip().lower().startswith("sitemap:"):
                loc = line.split(":", 1)[1].strip()
                if loc:
                    found.append(loc)
    if found:
        return found
    return [f"{base}/sitemap.xml", f"{base}/sitemap_index.xml"]


async def fetch_sitemap_urls(
    website_url: str,
    *,
    max_sitemaps: int = 25,
    max_urls: int = 3000,
    timeout: float = 20.0,
) -> list[str]:
    """Discover + walk a site's sitemap(s) and return its page URLs (deduped,
    order-preserving, bounded by `max_urls`). Best-effort: returns [] on any failure
    (no host, no reachable sitemap, all parses empty)."""
    base = _base_url(website_url)
    if not base:
        return []

    page_urls: list[str] = []
    seen_pages: set[str] = set()
    visited: set[str] = set()
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": _UA}
        ) as client:
            queue = await _discover_sitemaps(client, base)
            while queue and len(visited) < max_sitemaps and len(page_urls) < max_urls:
                sitemap_url = queue.pop(0)
                if sitemap_url in visited:
                    continue
                visited.add(sitemap_url)
                resp = await _get(client, sitemap_url)
                if resp is None:
                    continue
                body = _decode_body(sitemap_url, resp)
                if not body:
                    continue
                kind, locs = _parse(body)
                if kind == "index":
                    for loc in locs:
                        if loc not in visited:
                            queue.append(loc)
                elif kind == "urlset":
                    for loc in locs:
                        if loc not in seen_pages:
                            seen_pages.add(loc)
                            page_urls.append(loc)
                            if len(page_urls) >= max_urls:
                                break
    except Exception as exc:  # network/parse edge cases — degrade to empty
        logger.warning("sitemap.fetch_failed", extra={"url": website_url, "error": str(exc)})
        return page_urls

    return page_urls
