"""Content fetcher for the Research module.

Wraps ScrapeOwl with PDF support, paywall and bot-block detection, and
language filtering per Research PRD §4.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from config import settings

from .recency import detect_html_date, detect_pdf_date

logger = logging.getLogger(__name__)

SCRAPEOWL_URL = "https://api.scrapeowl.com/v1/scrape"
DEFAULT_TIMEOUT = 45.0

PAYWALL_MARKERS = (
    "subscribe", "subscription", "log in to read", "sign in to read",
    "members only", "premium content", "paid subscribers",
)
LOGIN_URL_PATTERNS = re.compile(r"/(login|signin|account|subscribe)\b", re.IGNORECASE)
BOT_BLOCK_MARKERS = (
    "just a moment...", "verifying you are human", "checking your browser",
    "verify you're not a robot", "verify you are human",
    "access denied", "request blocked",
)
BOT_BLOCK_FINGERPRINTS = (
    "cf-chl-", "_cf_chl_opt", "datadome", "px-captcha",
    "g-recaptcha", "h-captcha",
)


@dataclass
class FetchedContent:
    url: str
    success: bool = False
    failure_reason: Optional[str] = None
    html: str = ""
    body_text: str = ""
    title: str = ""
    author: Optional[str] = None
    publication: Optional[str] = None
    published_iso: Optional[str] = None
    is_pdf: bool = False
    paywall_detected: bool = False
    bot_block_detected: bool = False
    language: str = "en"
    final_url: str = ""


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _extract_metadata(soup: BeautifulSoup) -> tuple[str, Optional[str], Optional[str]]:
    """Extract (title, author, publication) from HTML."""
    title = ""
    if soup.title and soup.title.string:
        title = _clean_text(soup.title.string)
    # OG title takes precedence if present
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.attrs.get("content"):
        title = _clean_text(og_title.attrs["content"])

    author = None
    for selector in (
        ("meta", {"name": "author"}),
        ("meta", {"property": "article:author"}),
        ("meta", {"name": "byl"}),
    ):
        tag = soup.find(*selector)
        if tag and tag.attrs.get("content"):
            author = _clean_text(tag.attrs["content"])
            break

    publication = None
    for selector in (
        ("meta", {"property": "og:site_name"}),
        ("meta", {"name": "publisher"}),
        ("meta", {"name": "application-name"}),
    ):
        tag = soup.find(*selector)
        if tag and tag.attrs.get("content"):
            publication = _clean_text(tag.attrs["content"])
            break

    return (title, author, publication)


def _detect_paywall(html: str, body_text: str, final_url: str) -> bool:
    if LOGIN_URL_PATTERNS.search(final_url):
        return True
    lowered = body_text.lower()
    word_count = len(body_text.split())
    has_marker = any(m in lowered for m in PAYWALL_MARKERS)
    if word_count < 300 and has_marker:
        return True
    return False


def _detect_bot_block(html: str, body_text: str) -> bool:
    lowered_body = body_text.lower()
    if any(m in lowered_body for m in BOT_BLOCK_MARKERS):
        return True
    word_count = len(body_text.split())
    if word_count < 200:
        lowered_html = html.lower()
        if any(fp in lowered_html for fp in BOT_BLOCK_FINGERPRINTS):
            return True
    return False


def _detect_language(text: str) -> str:
    """Best-effort language detection. Default to 'en' on error or short text."""
    if not text or len(text.split()) < 30:
        return "en"
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(text)
    except Exception:
        return "en"


async def _scrapeowl_html(url: str) -> tuple[str, str, Optional[str]]:
    """Fetch raw HTML via ScrapeOwl. Returns (html, final_url, error_or_none)."""
    if not settings.scrapeowl_api_key:
        return ("", url, "scrapeowl_not_configured")
    payload = {
        "api_key": settings.scrapeowl_api_key,
        "url": url,
        "render_js": True,
    }
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(SCRAPEOWL_URL, json=payload)
        if response.status_code != 200:
            return ("", url, f"http_{response.status_code}")
        data = response.json()
        html = data.get("html") or data.get("body") or ""
        final_url = data.get("final_url") or data.get("url") or url
        if not html:
            return ("", url, "empty_html")
        return (html, final_url, None)
    except Exception as exc:
        return ("", url, f"scrape_error: {exc.__class__.__name__}")


async def _fetch_pdf_bytes(url: str) -> tuple[bytes, Optional[str]]:
    """Direct fetch of a PDF file (no JS rendering needed)."""
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ar-tools-research/1.0)"},
        ) as client:
            response = await client.get(url)
        if response.status_code != 200:
            return (b"", f"http_{response.status_code}")
        return (response.content, None)
    except Exception as exc:
        return (b"", f"pdf_fetch_error: {exc.__class__.__name__}")


def _extract_pdf(content: bytes) -> tuple[str, dict, Optional[str]]:
    """Extract text + metadata from PDF bytes."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        pages_text = []
        for page in reader.pages:
            try:
                pages_text.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(pages_text)
        metadata = {}
        if reader.metadata:
            for key in reader.metadata.keys():
                metadata[key] = reader.metadata.get(key)
        return (text, metadata, None)
    except Exception as exc:
        return ("", {}, f"pdf_parse_error: {exc.__class__.__name__}")


async def fetch_content(url: str) -> FetchedContent:
    """Fetch a URL, returning structured content + flags. Never raises."""
    is_pdf = url.lower().endswith(".pdf")

    if is_pdf:
        pdf_bytes, err = await _fetch_pdf_bytes(url)
        if err:
            return FetchedContent(url=url, success=False, failure_reason=err, is_pdf=True)
        text, metadata, parse_err = _extract_pdf(pdf_bytes)
        if parse_err:
            return FetchedContent(url=url, success=False, failure_reason=parse_err, is_pdf=True)
        if not text or len(text.split()) < 50:
            return FetchedContent(url=url, success=False, failure_reason="pdf_empty", is_pdf=True)
        published = detect_pdf_date(metadata)
        title = ""
        author = None
        if metadata:
            title = str(metadata.get("/Title", "") or "")
            author_val = metadata.get("/Author", "")
            author = str(author_val) if author_val else None
        return FetchedContent(
            url=url,
            success=True,
            body_text=text,
            title=title,
            author=author,
            published_iso=published.isoformat() if published else None,
            is_pdf=True,
            language=_detect_language(text),
            final_url=url,
        )

    html, final_url, err = await _scrapeowl_html(url)
    if err:
        return FetchedContent(url=url, success=False, failure_reason=err, final_url=url)

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    body_text = _clean_text(soup.get_text(" ", strip=True))
    bot_blocked = _detect_bot_block(html, body_text)
    if bot_blocked:
        return FetchedContent(
            url=url, success=False, failure_reason="bot_blocked",
            bot_block_detected=True, final_url=final_url,
        )

    paywalled = _detect_paywall(html, body_text, final_url)
    if paywalled:
        return FetchedContent(
            url=url, success=False, failure_reason="paywalled",
            paywall_detected=True, final_url=final_url,
        )

    title, author, publication = _extract_metadata(soup)
    published = detect_html_date(html)
    language = _detect_language(body_text)
    if language != "en":
        return FetchedContent(
            url=url, success=False, failure_reason="non_english",
            language=language, final_url=final_url,
        )

    return FetchedContent(
        url=url,
        success=True,
        html=html,
        body_text=body_text,
        title=title,
        author=author,
        publication=publication,
        published_iso=published.isoformat() if published else None,
        is_pdf=False,
        language=language,
        final_url=final_url,
    )


async def fetch_many(urls: list[str], concurrency: int = 6) -> list[FetchedContent]:
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(u: str) -> FetchedContent:
        async with semaphore:
            return await fetch_content(u)

    return await asyncio.gather(*[_bounded(u) for u in urls])
