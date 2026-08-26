"""Site name-scrape producer — the FREE owner/manager fallback (fetch + which pages).

When Outscraper enrichment returns no NAME for a prospect, this fetches the prospect's OWN site and
runs `name_extract` over it. FREE — an own HTTP GET, the exact posture as `scan_tech` (PRD §B3 "own
request, not a paid service") — so it is NOT a paid command and places no billed order.

**Owners are rarely on the homepage** (owner request 2026-08-XX), so this does a BOUNDED same-host
crawl: fetch the homepage, then follow a capped set of likely internal pages (about / team / contact
/ meet-the-team / leadership …), and merge the extractions. The whole thing is bounded by
`name_scrape_max_pages` so one prospect can never fan out into a crawl.

**Measured-vs-found, the coverage-denominator discipline.** A homepage fetch that FAILS records a
`fetch_status` (`unreachable`/`timeout`/`blocked`) and status `unreachable` — never "no owner
named". Only a page that genuinely loaded and named nobody is `no_names`. The report must be able to
say "couldn't read the site" distinctly from "the site names no owner".

The network lives here; `name_extract` is pure and never fetches. `fetch_page` / `normalize_site_url`
are reused verbatim from `scan_tech`, so "how we fetch a prospect's site" has ONE definition.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from ..config import Settings
from . import name_extract
from .name_extract import ExtractedName
from .scan_tech import (
    STATUS_OK,
    FetchResult,
    FetchFn,
    fetch_page,
    normalize_site_url,
)

logger = logging.getLogger(__name__)

# Internal-page hints, most-likely-first (a cap fetches the best few). Matched against a link's path
# and its anchor text. "contact" is included because a small business often names the owner only on
# the contact page; "meet"/"team"/"about"/"leadership" are the usual owner bios.
_PAGE_HINTS: tuple[str, ...] = (
    "about", "meet", "team", "our-story", "our-team", "who-we-are", "leadership",
    "management", "owner", "founder", "staff", "ownership", "bio", "company", "contact",
)

_UA = "Mozilla/5.0 (compatible; AR-Outreach-NameScan/1.0)"

# A tolerant <a href=…>text</a> reader — regex, no parser dependency (the module's posture).
_A_TAG = re.compile(r'(?is)<a\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>')
_STRIP_TAG = re.compile(r"(?s)<[^>]+>")


def _iter_links(html: str):
    """(href, inner_text) pairs from a page's anchors. Pure."""
    for m in _A_TAG.finditer(html):
        text = re.sub(r"\s+", " ", _STRIP_TAG.sub(" ", m.group(2))).strip()
        yield m.group(1), text


@dataclass(frozen=True)
class NameScrapeResult:
    """What scraping one prospect's site produced. A SUCCESSFUL read — `unreachable` is a status,
    never an empty `names` (unknown ≠ absent). `fetch_status` is the HOMEPAGE fetch outcome, so the
    report can distinguish 'site down' from 'site named nobody'."""

    prospect_id: str
    status: str            # found | no_names | unreachable
    fetch_status: str      # ok | blocked | timeout | unreachable  (the homepage)
    names: tuple[ExtractedName, ...]
    pages_fetched: int
    source_urls: tuple[str, ...]

    @property
    def name_count(self) -> int:
        return len(self.names)


def _canonical(url: str) -> str:
    """A dedup key for a URL: no fragment, no trailing slash, lower host."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return f"{parts.scheme}://{parts.netloc.lower()}{path}{('?' + parts.query) if parts.query else ''}"


def is_public_host(url: str) -> bool:
    """Whether a URL's host is a public web host we'll fetch — an SSRF guard. Pure.

    Blocks localhost and IP-LITERAL private/loopback/link-local/reserved addresses (e.g. the cloud
    metadata endpoint 169.254.169.254, 127.0.0.1, 10.x, 192.168.x). A plain HOSTNAME is allowed — we
    don't resolve DNS here, so DNS-rebinding is explicitly out of this guard's scope. Applied before
    fetching AND to the post-fetch `final_url`, so a same-host page that 301-redirects to an internal
    address is caught and its body discarded rather than parsed/stored."""
    host = (urlsplit(url).hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # a hostname, not an IP literal — allowed (no DNS resolution here)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def candidate_links(html: str | None, base_url: str, *, max_links: int) -> list[str]:
    """Likely owner-bio pages linked from a homepage, same-host, capped and priority-ordered. Pure.

    Reads `<a href=… >text</a>`, resolves relative hrefs against `base_url`, keeps only same-host
    http(s) links whose PATH or anchor TEXT carries a `_PAGE_HINTS` token, drops the homepage itself,
    de-dupes, and orders by hint priority so a cap fetches the most promising. Never raises."""
    if not html:
        return []
    base_host = urlsplit(base_url).netloc.lower()
    home_key = _canonical(base_url)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()

    for href, text in _iter_links(html):
        if not href:
            continue
        low_href = href.strip().lower()
        if low_href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        try:
            absolute = urljoin(base_url, href.strip())
        except ValueError:
            continue
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https") or parts.netloc.lower() != base_host:
            continue
        if not is_public_host(absolute):  # SSRF guard (also covers an IP-literal same "host")
            continue
        key = _canonical(absolute)
        if key == home_key or key in seen:
            continue
        hay = f"{parts.path.lower()} {text.lower()}"
        priority = next((i for i, hint in enumerate(_PAGE_HINTS) if hint in hay), None)
        if priority is None:
            continue
        seen.add(key)
        # Return the canonical (dedup-normalised) URL, so output matches what dedup considered and a
        # followed link fetches under one stable key.
        scored.append((priority, key))

    scored.sort(key=lambda t: t[0])
    return [url for _, url in scored[: max(0, max_links)]]


async def scrape_one(
    prospect: dict, settings: Settings, *, fetch: FetchFn
) -> NameScrapeResult | None:
    """Scrape one prospect's site for owner/manager names → a `NameScrapeResult` (or None when it
    has no fetchable website). Homepage first, then a bounded set of likely internal pages."""
    url = normalize_site_url(prospect.get("website"))
    if not url:
        return None
    if not is_public_host(url):
        # A private/loopback/metadata host from a bad ingest — refuse to fetch (SSRF guard).
        return NameScrapeResult(
            prospect_id=prospect["id"], status="unreachable", fetch_status="blocked",
            names=(), pages_fetched=0, source_urls=(url,),
        )

    home = await fetch(url)
    home_final = str(home.final_url or url)
    if home.status != STATUS_OK or not is_public_host(home_final):
        # Unknown, not absent — the site couldn't be read, OR a redirect landed on an internal host
        # (SSRF guard: don't parse or store its body). Either way: no names, status carries why.
        return NameScrapeResult(
            prospect_id=prospect["id"], status="unreachable",
            fetch_status=home.status if home.status != STATUS_OK else "blocked",
            names=(), pages_fetched=0, source_urls=(home_final,),
        )

    business_name = prospect.get("name")
    max_names = settings.name_scrape_max_names
    groups: list[list[ExtractedName]] = [
        name_extract.extract_names(home.body, business_name=business_name, max_names=max_names)
    ]
    fetched_urls = [home_final]

    follow = candidate_links(
        home.body, home_final, max_links=max(0, settings.name_scrape_max_pages - 1)
    )
    for link in follow:
        page = await fetch(link)
        page_final = str(page.final_url or link)
        fetched_urls.append(page_final)
        # Extract only from a public host that loaded — a followed page 301-ing to an internal host
        # is caught here and its body ignored (SSRF guard on the post-redirect final_url).
        if page.status == STATUS_OK and page.body and is_public_host(page_final):
            groups.append(
                name_extract.extract_names(
                    page.body, business_name=business_name, max_names=max_names
                )
            )

    names = name_extract.merge_names(*groups, max_names=max_names)
    return NameScrapeResult(
        prospect_id=prospect["id"],
        status="found" if names else "no_names",
        fetch_status=home.status,
        names=tuple(names),
        pages_fetched=len(fetched_urls),
        source_urls=tuple(fetched_urls),
    )


async def scrape_names(
    settings: Settings,
    prospects: list[dict],
    *,
    fetch: FetchFn | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[NameScrapeResult], list[str]]:
    """Scrape a set of prospects. Returns `(results, errors)`. FREE.

    Bounded concurrency across prospects (`name_scrape_concurrency`); each prospect's own pages are
    fetched sequentially inside `scrape_one`. One prospect's failure is REPORTED (never swallowed
    into "nobody anywhere") and never ends the batch — the `scan_tech`/`enrich_places` discipline.
    A prospect with no website is silently skipped (returns neither a result nor an error)."""
    if not prospects:
        return [], []

    timeout = settings.name_scrape_fetch_timeout_seconds
    owns = fetch is None
    http = None
    if fetch is None:
        http = client or httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": _UA}
        )

        async def fetch(url: str) -> FetchResult:  # noqa: E306
            return await fetch_page(
                url, timeout=timeout, max_bytes=settings.name_scrape_max_page_bytes, client=http
            )

    results: list[NameScrapeResult] = []
    errors: list[str] = []
    sem = asyncio.Semaphore(max(1, settings.name_scrape_concurrency))

    async def _guarded(prospect: dict) -> None:
        async with sem:
            try:
                got = await scrape_one(prospect, settings, fetch=fetch)
            except Exception as exc:  # noqa: BLE001 — one site must not end the batch
                errors.append(f"{prospect.get('id')}: {str(exc)[:200]}")
                logger.warning(
                    "name scrape failed",
                    extra={"prospect_id": prospect.get("id"), "error": str(exc)[:300]},
                )
                return
            if got is not None:
                results.append(got)

    try:
        await asyncio.gather(*(_guarded(p) for p in prospects))
    finally:
        if owns and http is not None and client is None:
            await http.aclose()
    return results, errors
