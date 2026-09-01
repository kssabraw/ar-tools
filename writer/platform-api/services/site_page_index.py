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


# ── keyword ↔ live-page matching (content-word-set equality) ──────────────────
#
# `match_site_location_page` above only catches a *generic* location page
# (``/melbourne/``). But a local business usually publishes service+city landing
# pages (``/roof-restoration-melbourne/``), and the silo planner offers those same
# "<service> <city>" targets — so without a keyword-level match a page that already
# exists gets offered for creation again (a false "missing"). These helpers match a
# planned keyword against a live URL by comparing content-word *sets*, so word order
# and generic wrapper words ("services", "areas") don't matter, while a genuinely
# more-specific page (``/emergency-roof-restoration-melbourne/``) stays distinct.
#
# This mirrors the proven matcher in ``services.service_page_plan`` (national service
# pages); it lives here — the shared home for "does the client's site already have
# this page" — because the local silo planner needs the same test.

# Generic tokens that don't distinguish a page: connectors, the "service(s)"
# wrapper, structural area/location directory words, and file extensions. Stripped
# from every token set so ``/service-areas/inner-west/`` and ``inner west`` match.
_GENERIC_TOKENS = {
    "the", "a", "an", "and", "or", "for", "of", "in", "on", "to", "your", "our",
    "near", "me", "service", "services", "page", "pages", "index", "html", "htm",
    "php", "aspx", "area", "areas", "location", "locations", "region", "regions",
    "serving",
}

# A URL carrying any of these path segments is content/taxonomy/store — it may
# *mention* a service without being its landing page (``/blog/why-roof-restoration/``),
# so it must never suppress a candidate. Matches the whole URL, not one segment.
_NON_PAGE_SEGMENTS = {
    "blog", "blogs", "post", "posts", "article", "articles", "news", "story",
    "stories", "tag", "tags", "category", "categories", "topic", "topics",
    "author", "authors", "product", "products", "shop", "store", "cart",
    "checkout", "account", "feed", "rss", "search", "privacy", "terms",
    "cookie", "cookies", "sitemap", "wp-content", "wp-json", "wp-admin",
}


def content_tokens(text: str) -> frozenset[str]:
    """Distinguishing content words of a string: lowercase alphanumerics with the
    generic/connector words and 1-char noise dropped.

    "Roof Restoration Melbourne" → {"roof","restoration","melbourne"};
    "drain-cleaning-services" → {"drain","cleaning"}."""
    return frozenset(
        tok
        for tok in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(tok) > 1 and tok not in _GENERIC_TOKENS
    )


def page_match_keys(url: str) -> list[frozenset[str]]:
    """Content-word-set keys a live URL can be matched on, or ``[]`` when the URL is
    content/store (a non-page segment) or has no usable slug.

    Two keys, so both flat and nested site layouts match a "<service> <city>"
    keyword:
      1. the **final path segment** — ``/roof-restoration-melbourne/`` →
         {"roof","restoration","melbourne"}; and
      2. the **union of all non-generic segments** — ``/service-areas/roof-restoration/
         melbourne/`` → {"roof","restoration","melbourne"} after the generic
         "service"/"areas" directory drops out.

    Both use the same content-word set, so word order and generic wrapper words never
    matter, while an extra distinguishing word ("emergency", "commercial", "cbd")
    keeps a more-specific page a distinct target rather than a false match."""
    try:
        path = urlparse(url or "").path or ""
    except ValueError:
        return []
    segments = [seg for seg in path.split("/") if seg.strip()]
    if not segments:
        return []
    if any(slugify_place(seg) in _NON_PAGE_SEGMENTS for seg in segments):
        return []
    keys: list[frozenset[str]] = []
    final = content_tokens(segments[-1])
    if final:
        keys.append(final)
    union: set[str] = set()
    for seg in segments:
        union |= content_tokens(seg)
    union_key = frozenset(union)
    if union_key and union_key not in keys:
        keys.append(union_key)
    return keys


def build_page_token_index(urls: list[str]) -> dict[frozenset[str], str]:
    """Map each URL's content-word-set key(s) → the first URL carrying it, for O(1)
    keyword lookup. First URL wins (sitemaps list canonical/top-level pages first)."""
    index: dict[frozenset[str], str] = {}
    for url in urls:
        for key in page_match_keys(url):
            index.setdefault(key, url)
    return index


def match_site_page_for_keyword(
    keyword: str, index: dict[frozenset[str], str]
) -> Optional[str]:
    """Return the live URL whose page slug is the *same* topic as `keyword` (exact
    content-word-set equality), else None.

    "roof restoration melbourne" matches ``/roof-restoration-melbourne/`` and
    ``/melbourne-roof-restoration/`` but NOT ``/emergency-roof-restoration-melbourne/``
    (a distinct, more-specific page). A keyword whose content words are all generic
    (empty set) never matches."""
    if not index:
        return None
    key = content_tokens(keyword)
    if not key:
        return None
    return index.get(key)


def match_site_service_page(
    keyword: str, place_name: str, index: dict[frozenset[str], str]
) -> Optional[str]:
    """Return the live URL of a *city-less* (national) service page matching
    `keyword` with `place_name` stripped out, or None.

    A local business sometimes publishes one page per service with no geo in the
    slug (``/roof-restoration/``) — for a single-city business that page *is* the
    "<service> <city>" target. Stripping the place words from the keyword and
    matching the remaining service words catches it: "roof restoration melbourne"
    with place "Melbourne" → {"roof","restoration"} → ``/roof-restoration/``. A
    *modified* variation matches only its own national page — "storm damage roof
    restoration melbourne" → {"storm","damage","roof","restoration"}, never the bare
    ``/roof-restoration/`` — so this widens recall without collapsing distinct
    variations onto one service page.

    Returns None when the place strips nothing (then the caller's exact-keyword
    match already covers it — this must stay strictly a *fallback*) or the remaining
    service words are empty."""
    if not index:
        return None
    kw_tokens = content_tokens(keyword)
    service_tokens = kw_tokens - content_tokens(place_name)
    # Only a genuine city-strip qualifies: an empty remainder, or one identical to
    # the full keyword (place contributed nothing), is not a national match.
    if not service_tokens or service_tokens == kw_tokens:
        return None
    return index.get(service_tokens)


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
    except ElementTree.ParseError as exc:
        logger.warning("site_page_index.sitemap_parse_failed", extra={"error": str(exc)})
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
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": settings.crawler_user_agent},
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


async def discover_site_urls(
    website_url: str, location_code: int, *, use_paid_fallback: bool = True
) -> tuple[list[str], str]:
    """Discover the client's site URLs. Returns ``(urls, source)`` where source is
    ``"sitemap"`` | ``"google_index"`` | ``"none"``. Never raises — a site with no
    readable sitemap and no indexed pages yields ``([], "none")``.

    ``use_paid_fallback`` (default True) gates the DataForSEO ``site:`` query used
    when no sitemap is readable; pass False to keep discovery free (sitemap-only)."""
    base = site_base_url(website_url)
    if not base:
        return [], "none"

    urls = await _fetch_sitemap_urls(base)
    if urls:
        return urls, "sitemap"

    if not use_paid_fallback:
        return [], "none"

    from services.dataforseo_rank import extract_domain

    domain = extract_domain(website_url)
    urls = await _fetch_google_indexed_urls(domain, location_code)
    if urls:
        return urls, "google_index"
    return [], "none"
