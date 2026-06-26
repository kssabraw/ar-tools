"""Existing location-page detection — does the client's live site already have a
generic location page for a given place?

The silo planner proposes area/location page targets (the Neighborhoods silo).
Before offering an area as `missing` (i.e. "create this"), we want to know whether
the client's site already has a *generic location page* for it — the bare
place-name URL a local business uses, e.g. ``site.com/los-angeles/`` or
``site.com/service-areas/inner-west/``. This module discovers the site's URLs and
matches a place name against them.

Discovery is two-tier and best-effort:
  1. **Sitemap** — read ``robots.txt`` for ``Sitemap:`` directives plus the common
     ``/sitemap.xml`` / ``/sitemap_index.xml`` paths, following sitemap-index files
     one level into their child sitemaps. Cheap, no JS, whole-site coverage.
  2. **DataForSEO `site:` fallback** — when no sitemap is readable, query Google's
     index for ``site:<domain>`` and take the returned URLs.

Matching is deliberately conservative — only a URL whose path contains a segment
that *exactly* equals the place's slug counts (so ``/inner-west/`` matches
"Inner West", but ``/inner-west-plumber/`` — a service page — does not). That
keeps the check to genuine generic location pages, per the module's intent.

The pure helpers (slugify / parse / index / match) are unit-tested; the network
calls are thin wrappers around them.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 20.0
# Common sitemap locations to probe when robots.txt doesn't list one.
_DEFAULT_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml")


# ── pure helpers (no I/O) — unit-tested ──────────────────────────────────────

def slugify_place(name: str) -> str:
    """Normalize a place name to a URL slug: lowercase, accent-stripped, with
    runs of non-alphanumerics collapsed to single hyphens.

    "Inner West" → "inner-west"; "Côte-d'Or" → "cote-d-or"."""
    if not name:
        return ""
    # Decompose accents (é → e) and drop combining marks.
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def url_path_slugs(url: str) -> list[str]:
    """Normalized, non-empty path segments of a URL, each slugified.

    ``https://x.com/service-areas/Inner-West/`` → ``["service-areas", "inner-west"]``.
    A trailing file extension on the last segment (``.html``) is stripped first."""
    try:
        path = urlparse(url).path or ""
    except ValueError:
        return ""
    segs: list[str] = []
    for raw in path.split("/"):
        seg = raw.strip()
        if not seg:
            continue
        seg = re.sub(r"\.(html?|php|aspx?)$", "", seg, flags=re.IGNORECASE)
        slug = slugify_place(seg)
        if slug:
            segs.append(slug)
    return segs


def build_location_slug_index(urls: list[str]) -> dict[str, str]:
    """Map every path-segment slug across the site to the first URL that contains
    it. Lookups only ever use *place* slugs, so generic segments ("services",
    "blog") sit harmlessly in the index. First URL wins (sitemaps tend to list
    canonical/top-level pages first)."""
    index: dict[str, str] = {}
    for url in urls:
        for slug in url_path_slugs(url):
            index.setdefault(slug, url)
    return index


def match_site_location_page(place_name: str, index: dict[str, str]) -> Optional[str]:
    """Return the live URL of a generic location page for `place_name`, or None.

    A match requires a path segment that *exactly* equals the place's slug — a
    bare place-name page — not a mere substring, so service+location slugs
    ("inner-west-plumber") don't count."""
    if not index:
        return None
    return index.get(slugify_place(place_name))


def parse_robots_sitemaps(text: str) -> list[str]:
    """Extract ``Sitemap:`` directive URLs from a robots.txt body."""
    out: list[str] = []
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key.strip().lower() == "sitemap":
            url = value.strip()
            if url:
                out.append(url)
    return out


def parse_sitemap_xml(xml: str) -> tuple[list[str], list[str]]:
    """Parse a sitemap document, returning ``(page_urls, child_sitemap_urls)``.

    A ``<urlset>`` yields page URLs; a ``<sitemapindex>`` yields child sitemap
    URLs to recurse into. Namespace-agnostic (matches on the local tag name), so
    it tolerates the varied namespaces sitemaps ship with. Returns empties on
    malformed XML rather than raising."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return [], []

    def _localname(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.lower()

    page_urls: list[str] = []
    child_sitemaps: list[str] = []
    for child in root:
        kind = _localname(child.tag)
        loc = None
        for sub in child:
            if _localname(sub.tag) == "loc" and (sub.text or "").strip():
                loc = sub.text.strip()
                break
        if not loc:
            continue
        if kind == "sitemap":
            child_sitemaps.append(loc)
        elif kind == "url":
            page_urls.append(loc)
    return page_urls, child_sitemaps


def site_base_url(website_url: str) -> str:
    """Scheme+host origin for a client website (defaults to https), e.g.
    ``acme.com/about`` → ``https://acme.com``. Empty if unparseable."""
    if not website_url:
        return ""
    raw = website_url if "//" in website_url else f"//{website_url}"
    parsed = urlparse(raw, scheme="https")
    host = parsed.hostname
    if not host:
        return ""
    return f"{parsed.scheme or 'https'}://{host}"


# ── network discovery (best-effort) ──────────────────────────────────────────

async def _fetch_text(client: httpx.AsyncClient, url: str) -> Optional[str]:
    try:
        resp = await client.get(url)
        if resp.status_code == 200 and resp.text:
            return resp.text
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("site_page_index.fetch_failed", extra={"url": url, "error": str(exc)})
    return None


async def _fetch_sitemap_urls(base_url: str) -> list[str]:
    """Collect page URLs from the site's sitemap(s). robots.txt directives first,
    then common default paths; sitemap-index files are followed one level into
    their children. Bounded by `local_seo_sitemap_max_files` / `_max_urls`."""
    max_files = settings.local_seo_sitemap_max_files
    max_urls = settings.local_seo_sitemap_max_urls
    page_urls: list[str] = []
    seen_sitemaps: set[str] = set()

    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": "ar-tools-sitemap/1.0"}
    ) as client:
        # Seed the queue from robots.txt + the conventional sitemap paths.
        queue: list[str] = []
        robots = await _fetch_text(client, f"{base_url}/robots.txt")
        if robots:
            queue.extend(parse_robots_sitemaps(robots))
        queue.extend(f"{base_url}{p}" for p in _DEFAULT_SITEMAP_PATHS)

        while queue and len(seen_sitemaps) < max_files and len(page_urls) < max_urls:
            sm_url = queue.pop(0)
            if sm_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sm_url)
            xml = await _fetch_text(client, sm_url)
            if not xml:
                continue
            pages, children = parse_sitemap_xml(xml)
            page_urls.extend(pages)
            # Recurse one level into index files (children are plain sitemaps).
            for ch in children:
                if ch not in seen_sitemaps:
                    queue.append(ch)

    # De-dupe while preserving order; trim to the cap.
    deduped: list[str] = []
    seen: set[str] = set()
    for u in page_urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
        if len(deduped) >= max_urls:
            break
    return deduped


async def _fetch_google_indexed_urls(domain: str, location_code: int) -> list[str]:
    """Fallback: URLs Google has indexed for the domain, via a DataForSEO
    ``site:<domain>`` organic query. Best-effort — returns [] on any error."""
    if not domain or not settings.dataforseo_login:
        return []
    # Imported lazily so the pure helpers (and their tests) don't pull in the
    # Supabase-backed DataForSEO module just to slugify a URL.
    from services.dataforseo_rank import _BASE_URL, _SERP_PATH, _auth_header

    payload = [
        {
            "keyword": f"site:{domain}",
            "language_code": settings.dataforseo_default_language_code,
            "location_code": location_code,
            "depth": settings.local_seo_site_index_dataforseo_depth,
            "calculate_rectangles": False,
        }
    ]
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{_BASE_URL}{_SERP_PATH}", headers=_auth_header(), json=payload)
            resp.raise_for_status()
            body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("site_page_index.dataforseo_failed", extra={"domain": domain, "error": str(exc)})
        return []

    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        return []
    items = (tasks[0].get("result") or [{}])[0].get("items") or []
    urls: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item.get("type") != "organic":
            continue
        url = item.get("url")
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


async def discover_site_urls(website_url: str, location_code: int) -> tuple[list[str], str]:
    """Discover the client's site URLs. Returns ``(urls, source)`` where source is
    ``"sitemap"`` | ``"google_index"`` | ``"none"``. Never raises — a site with no
    readable sitemap and no indexed pages yields ``([], "none")``."""
    base = site_base_url(website_url)
    if not base:
        return [], "none"

    urls = await _fetch_sitemap_urls(base)
    if urls:
        return urls, "sitemap"

    from services.dataforseo_rank import extract_domain

    domain = extract_domain(website_url)
    urls = await _fetch_google_indexed_urls(domain, location_code)
    if urls:
        return urls, "google_index"
    return [], "none"
