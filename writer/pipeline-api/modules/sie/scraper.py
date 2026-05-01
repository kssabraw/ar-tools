"""ScrapeOwl client for fetching page HTML for the SIE module.

ScrapeOwl handles JavaScript rendering and rotates proxies. Per the SIE PRD
(Module 4), we need raw HTML so the zone extractor can parse it with
BeautifulSoup.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

SCRAPEOWL_URL = "https://api.scrapeowl.com/v1/scrape"
DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 2


@dataclass
class ScrapeResult:
    url: str
    html: str = ""
    text: str = ""
    status_code: int = 0
    success: bool = False
    failure_reason: Optional[str] = None


async def scrape(url: str, render_js: bool = True) -> ScrapeResult:
    """Fetch a single URL via ScrapeOwl. Returns ScrapeResult (success or
    populated failure_reason). Never raises."""
    if not settings.scrapeowl_api_key:
        return ScrapeResult(url=url, failure_reason="scrapeowl_not_configured")

    payload = {
        "api_key": settings.scrapeowl_api_key,
        "url": url,
        "render_js": render_js,
        "premium_proxies": False,
    }

    last_error: Optional[str] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.post(SCRAPEOWL_URL, json=payload)
            if response.status_code == 200:
                data = response.json()
                html = data.get("html") or data.get("body") or ""
                if not html:
                    last_error = "empty_html"
                else:
                    return ScrapeResult(
                        url=url,
                        html=html,
                        status_code=200,
                        success=True,
                    )
            elif response.status_code == 429:
                last_error = "rate_limited"
                await asyncio.sleep(2 ** attempt)
                continue
            else:
                last_error = f"http_{response.status_code}"
        except httpx.TimeoutException:
            last_error = "timeout"
        except Exception as exc:
            last_error = f"scrape_exception: {exc.__class__.__name__}"
            logger.warning("scrape failed for %s: %s", url, exc)

    return ScrapeResult(url=url, failure_reason=last_error or "unknown_error")


async def scrape_many(urls: list[str], concurrency: int = 5) -> list[ScrapeResult]:
    """Scrape a list of URLs concurrently with a semaphore limit."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(u: str) -> ScrapeResult:
        async with semaphore:
            return await scrape(u)

    return await asyncio.gather(*[_bounded(u) for u in urls])
