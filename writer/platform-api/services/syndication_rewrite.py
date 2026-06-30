"""Content Syndication — source extraction + unique rewrite.

Fetches a source page (ScrapeOwl), strips site chrome, converts the main content
to Markdown, then asks Claude to produce a *heavier* unique rewrite (a fresh
angle and restructuring — not a paraphrase) that preserves the facts and intent
but reads as original content. The rewrite is what gets published to the public
Google Doc + Sheet; the original page on the site is left untouched.
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from config import settings
from services.html_to_markdown import html_to_markdown
from services.page_structure_scraper import strip_chrome
from services.website_scraper import scrapeowl_fetch

logger = logging.getLogger(__name__)


class RewriteError(RuntimeError):
    """Raised when source extraction or the rewrite call hard-fails."""


def _extract_title(html: str) -> str:
    """Best-effort page title from <title> (trimmed of the trailing site name) or
    the first <h1>."""
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        # Strip a trailing " | Site Name" / " - Site Name" suffix when present.
        for sep in (" | ", " – ", " — ", " - "):
            if sep in title:
                title = title.split(sep)[0].strip()
                break
        if title:
            return title
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    return ""


async def extract_source_content(url: str) -> tuple[str, str]:
    """Fetch `url`, strip chrome, return (title, markdown) of the main content.

    Raises RewriteError when the page can't be fetched or has no usable body."""
    html = await scrapeowl_fetch(url, timeout=45)
    if not html:
        raise RewriteError("source_fetch_empty")
    title = _extract_title(html)
    markdown = html_to_markdown(strip_chrome(html))
    if not markdown.strip():
        raise RewriteError("source_content_empty")
    return title, markdown


_SYSTEM_PROMPT = (
    "You are a senior content writer. You will be given a web article in Markdown. "
    "Rewrite it into a UNIQUE, original piece on the same topic: take a fresh angle, "
    "reorganize the structure, and rephrase everything in your own words so it does "
    "not read as a copy of the source. Preserve the facts, the core message, and the "
    "search intent; do not invent fake statistics, quotes, or claims. Keep a similar "
    "length. Use clean Markdown with descriptive headings.\n\n"
    "Output ONLY the rewritten article in Markdown. The VERY FIRST line must be a "
    "single H1 heading with a new title for the piece (e.g. `# Your New Title`), "
    "followed by the body. No preamble, no commentary, no code fences."
)


def _split_title(markdown: str) -> tuple[str, str]:
    """Pull a leading `# Title` H1 off the rewritten Markdown. Returns
    (title, body); body has the H1 removed so it isn't duplicated under the Doc's
    own title. Falls back to ('', markdown) when there's no leading H1."""
    text = (markdown or "").lstrip()
    lines = text.split("\n")
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        body = "\n".join(lines[1:]).lstrip("\n")
        return title, body
    return "", text


async def rewrite_unique(title: str, markdown: str) -> tuple[str, str]:
    """Heavier unique rewrite of `markdown`. Returns (new_title, new_markdown).

    Raises RewriteError on an API failure or empty output so the item lands
    'failed' with a clear error rather than publishing the original verbatim."""
    import anthropic

    if not settings.anthropic_api_key:
        raise RewriteError("anthropic_not_configured")

    source = markdown if len(markdown) <= 24_000 else markdown[:24_000]
    user = f"Source title: {title or '(none)'}\n\nSource article (Markdown):\n\n{source}"

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        message = await client.messages.create(
            model=settings.syndication_rewrite_model,
            max_tokens=settings.syndication_rewrite_max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:  # noqa: BLE001 — map provider errors to our envelope
        logger.warning("syndication_rewrite_failed", extra={"error": str(exc)})
        raise RewriteError(f"rewrite_call_failed: {exc}") from exc

    out = "".join(block.text for block in message.content if getattr(block, "type", None) == "text").strip()
    if not out:
        raise RewriteError("rewrite_empty")

    new_title, body = _split_title(out)
    return (new_title or title or "Untitled"), (body or out)
