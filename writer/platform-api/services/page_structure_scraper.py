"""Reference page-structure scraper — ScrapeOwl fetch + chrome strip + LLM analysis.

Given one of a client's reference page URLs (local landing / service / location /
blog post), this fetches the page, strips the site chrome (nav, header, footer,
sidebars, popups/modals/cookie banners) so only the main content remains, then
asks Claude to describe the page's *structure*: a heading outline (with the kind
of content block under each heading) plus a natural-language summary of how the
page is organized. The result is stored on the client and reused indefinitely by
the writing modules so generated output can mirror the client's own layouts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bs4 import BeautifulSoup, Comment

logger = logging.getLogger(__name__)

# Valid reference page types (matches the keys in clients.page_structures).
PAGE_TYPES = ("local_landing", "service", "location", "blog_post", "product", "solution")

# Tags that are never page content — drop wholesale.
_DROP_TAGS = (
    "nav", "header", "footer", "aside", "script", "style", "noscript",
    "svg", "iframe", "form", "button", "template", "dialog",
)

# ARIA landmark roles that mark chrome rather than main content.
_DROP_ROLES = {"navigation", "banner", "contentinfo", "search", "dialog", "alertdialog", "menu", "menubar"}

# Substrings in id/class that strongly signal chrome / popups / overlays.
_DROP_HINTS = (
    "nav", "navbar", "menu", "header", "footer", "sidebar", "side-bar",
    "popup", "pop-up", "modal", "overlay", "cookie", "consent", "gdpr",
    "newsletter", "subscribe", "banner", "breadcrumb", "social", "share",
    "skip-link", "skip-to", "back-to-top", "offcanvas", "drawer", "toast",
    "announcement", "promo-bar", "topbar", "top-bar",
)


def _hint_match(value: Any) -> bool:
    if not value:
        return False
    text = " ".join(value) if isinstance(value, (list, tuple)) else str(value)
    text = text.lower()
    return any(hint in text for hint in _DROP_HINTS)


def strip_chrome(html: str) -> str:
    """Return the page's main content HTML with site chrome removed.

    Heuristic, deterministic pass: drops chrome tags, ARIA-landmark chrome,
    and elements whose id/class hint at nav/popups/overlays. If the page
    exposes a clear main-content landmark (<main>, role=main, or <article>),
    that subtree is preferred. Best-effort — the LLM is also instructed to
    ignore any chrome that slips through.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    # Drop comments (often wrap hidden widgets / tracking).
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()

    # ARIA-landmark chrome + hidden elements.
    for tag in soup.find_all(attrs={"role": True}):
        if str(tag.get("role", "")).lower() in _DROP_ROLES:
            tag.decompose()
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()

    # id/class-hinted chrome, popups, overlays.
    for tag in soup.find_all(attrs={"class": _hint_match}):
        tag.decompose()
    for tag in soup.find_all(attrs={"id": _hint_match}):
        tag.decompose()

    # Prefer an explicit main-content landmark when present.
    main = (
        soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find("article")
    )
    root = main if main is not None else (soup.body or soup)
    return str(root)


_SYSTEM_PROMPT = (
    "You analyze the STRUCTURE of a single web page from its main-content HTML "
    "(site chrome — navigation, header, footer, sidebars, popups, cookie banners — "
    "has already been removed; ignore any that remains). You do NOT summarize the "
    "topic or copy the wording. You describe how the page is ORGANIZED so another "
    "writer could reproduce the same layout for a different topic.\n\n"
    "Return ONLY valid JSON matching this exact schema — no prose, no markdown fences:\n"
    "{\n"
    '  "outline": [\n'
    '    {\n'
    '      "level": "H1" | "H2" | "H3",\n'
    '      "heading": "the heading text, generalized if it names a specific topic/brand",\n'
    '      "blocks": ["paragraph" | "list" | "table" | "faq" | "cta" | "form" | "image" | "quote" | "stat" | "steps" | "key_takeaways"],\n'
    '      "approx_words": <integer estimate of body words under this heading>\n'
    "    }\n"
    "  ],\n"
    '  "structure_summary": "2-5 sentence plain-English description of how the page is organized: '
    'the opening pattern, the order and purpose of the main sections, recurring content blocks, and how it closes.",\n'
    '  "elements": {\n'
    '    "section_count": <integer count of top-level H2 sections>,\n'
    '    "approx_total_words": <integer estimate of total body words>,\n'
    '    "has_intro": <bool>,\n'
    '    "has_key_takeaways": <bool>,\n'
    '    "has_faq": <bool>,\n'
    '    "has_cta": <bool>,\n'
    '    "has_table": <bool>,\n'
    '    "has_lists": <bool>,\n'
    '    "intro_pattern": "short description of how the page opens (e.g. \'direct answer then context\', \'problem framing\', \'hero statement + value prop\')"\n'
    "  }\n"
    "}\n\n"
    "Keep headings concise. If the page has no clear structure, return an empty outline and say so in structure_summary."
)


async def llm_extract_page_structure(html: str, page_type: str) -> dict[str, Any]:
    """Call Claude to describe the page's structure (outline + summary)."""
    import anthropic

    from config import settings

    truncated_html = html[:60_000] if len(html) > 60_000 else html

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Reference page type: {page_type}\n\n"
                    f"Analyze the structure of this page's main content:\n\n{truncated_html}"
                ),
            }
        ],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "page_structure_scraper.llm_json_parse_failed",
            extra={"page_type": page_type, "raw_len": len(raw)},
        )
        result = {"outline": [], "structure_summary": "", "elements": {}}

    return result


async def analyze_page_structure(html: str, page_type: str) -> dict[str, Any]:
    """Strip chrome from raw page HTML and return its analyzed structure."""
    cleaned = strip_chrome(html)
    return await llm_extract_page_structure(cleaned, page_type)
