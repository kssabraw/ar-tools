"""Sitemap fetcher — discover and enumerate a site's published page URLs.

Best-effort, network-bound, and dependency-free (stdlib XML + httpx). Given a
website URL it discovers the site's sitemap(s) — honouring `robots.txt` `Sitemap:`
directives (resolving relative ones against the origin), then falling back to a set
of conventional paths — walks any nested sitemap-index entries, and returns the flat
list of `<urlset>` page URLs (bounded, deduped, order-preserving).

Used by the service-page planner to drop candidate pages a client already publishes,
but kept generic so other modules can reuse it. Every failure path degrades to an
empty list rather than raising — the caller decides what to do when the site can't
be read.

Safety: downloads are read in bounded chunks (`_MAX_DOWNLOAD`) so a giant body can't
be pulled into memory, and gzipped bodies are inflated with a hard output cap
(`_MAX_BYTES`) so a compression bomb can't expand unbounded before we look at it.
"""

from __future__ import annotations

import logging
import zlib
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; AR-Tools-SitemapBot/1.0)"
# Hard cap on bytes read off the wire per request (bounds memory for plain bodies).
_MAX_DOWNLOAD = 25 * 1024 * 1024
# Hard cap on bytes handed to the XML parser / produced by gzip inflation (bounds a
# compression bomb: a small gzip can't expand past this before we slice it).
_MAX_BYTES = 10 * 1024 * 1024

# Conventional sitemap paths tried (in order) only when robots.txt declares none.
# A wider net than the bare spec default, covering the common CMS/plugin layouts —
# WordPress core (`/wp-sitemap.xml`), Yoast/Rank Math indexes, gzipped variants, and
# nested `/sitemap/` dirs. Unreachable candidates 404 and are skipped cheaply; the
# walker dedupes and is bounded by `max_sitemaps`, so an over-broad list is safe.
_DEFAULT_SITEMAP_PATHS = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
    "/sitemap/sitemap.xml",
    "/sitemap.xml.gz",
    "/sitemap_index.xml.gz",
)


def _base_url(website_url: str) -> str | None:
    """Reduce a website URL to its `scheme://host` origin. Defaults to https when no
    scheme is given. Returns None when there's no host to work with."""
    raw = (website_url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    # A netloc with whitespace (or no host at all) isn't a real origin — bail rather
    # than emit a bogus base that just wastes connect attempts.
    if not parts.netloc or any(c.isspace() for c in parts.netloc):
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _strip_ns(tag: str) -> str:
    """`{ns}url` → `url` (sitemaps are namespaced; we match on local names)."""
    return tag.rsplit("}", 1)[-1].lower()


def _gunzip(data: bytes) -> bytes | None:
    """Inflate a gzip body, capping output at `_MAX_BYTES` so a compression bomb
    can't expand unbounded. Returns None when the data isn't valid gzip."""
    try:
        # wbits=31 selects gzip framing; the max_length arg stops inflation once
        # _MAX_BYTES have been produced (the rest is left unconsumed, not expanded).
        return zlib.decompressobj(wbits=31).decompress(data, _MAX_BYTES)
    except (zlib.error, OSError):
        return None


def _sitemap_body(raw: bytes) -> bytes | None:
    """Normalize a fetched sitemap body to parseable XML bytes. Inflates only when
    the body is *actually* gzip (magic bytes), regardless of a `.gz` extension —
    so a `.gz` URL the transport already decoded is parsed, not double-inflated.
    Returns None on a failed inflation."""
    data = raw[:_MAX_DOWNLOAD]
    if data[:2] == b"\x1f\x8b":
        return _gunzip(data)
    return data[:_MAX_BYTES]


def _parse(body: bytes | str) -> tuple[str, list[str]]:
    """Parse a sitemap body → ("index" | "urlset" | "", [loc, ...]). A sitemapindex
    yields child sitemap URLs; a urlset yields page URLs. Accepts bytes (so the XML
    prolog's own encoding declaration is honoured) or str."""
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


async def _fetch_bytes(client: httpx.AsyncClient, url: str) -> bytes | None:
    """GET `url`, streaming the body and stopping once `_MAX_DOWNLOAD` bytes are
    read. Returns the raw bytes on HTTP 200, else None (non-200 or any transport
    error). A relative/invalid URL surfaces as httpx.HTTPError and degrades to None."""
    try:
        async with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                return None
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf += chunk
                if len(buf) >= _MAX_DOWNLOAD:
                    break
            return bytes(buf)
    except (httpx.HTTPError, httpx.InvalidURL):
        # InvalidURL isn't an HTTPError subclass — catch it too so one malformed
        # <loc> skips that fetch instead of aborting the whole sitemap walk.
        return None


async def _discover_sitemaps(client: httpx.AsyncClient, base: str) -> list[str]:
    """Sitemap URLs declared in robots.txt (relative ones resolved against the
    origin), else the conventional defaults."""
    found: list[str] = []
    raw = await _fetch_bytes(client, f"{base}/robots.txt")
    if raw is not None:
        for line in raw.decode("utf-8", "replace").splitlines():
            stripped = line.strip()
            key, sep, val = stripped.partition(":")
            if not sep or key.strip().lower() != "sitemap":
                continue
            loc = val.strip()
            if loc:
                found.append(urljoin(base, loc))  # absolute kept; relative resolved
    if found:
        return found
    return [f"{base}{path}" for path in _DEFAULT_SITEMAP_PATHS]


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
    # Short connect timeout so an unreachable host fails fast rather than burning the
    # full read budget on each conventional-path probe (worst case is ~8 requests).
    timeouts = httpx.Timeout(timeout, connect=min(5.0, timeout))
    try:
        async with httpx.AsyncClient(
            timeout=timeouts, follow_redirects=True, headers={"User-Agent": _UA}
        ) as client:
            queue = await _discover_sitemaps(client, base)
            while queue and len(visited) < max_sitemaps and len(page_urls) < max_urls:
                sitemap_url = queue.pop(0)
                if sitemap_url in visited:
                    continue
                visited.add(sitemap_url)
                raw = await _fetch_bytes(client, sitemap_url)
                if raw is None:
                    continue
                body = _sitemap_body(raw)
                if not body:
                    continue
                kind, locs = _parse(body)
                if kind == "index":
                    for loc in locs:
                        absolute = urljoin(base, loc)
                        if absolute not in visited:
                            queue.append(absolute)
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
