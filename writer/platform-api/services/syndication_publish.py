"""Content Syndication — build + publish the public Doc and Sheet.

Each rewritten piece is published twice: as a Google Doc (the article, natively
formatted) and as a Google Sheet (the content laid out down rows). Both carry a
backlink to the original page on the client's site, and both are shared so they
are discoverable by search engines (or link-only, per the client's share_mode).
"""

from __future__ import annotations

import logging
from html import escape

from services.markdown_html import markdown_to_html

logger = logging.getLogger(__name__)


def _backlink_html(source_url: str) -> str:
    safe = escape(source_url, quote=True)
    label = escape(source_url)
    return f'<p>Originally published at <a href="{safe}">{label}</a></p>'


def build_doc_html(title: str, markdown: str, source_url: str) -> str:
    """Semantic HTML for the Doc: the rewritten article + a backlink to the
    source page (so the public copy links back to the client's site)."""
    article = markdown_to_html(markdown)
    parts = []
    if source_url:
        parts.append(_backlink_html(source_url))
    parts.append(article)
    if source_url:
        parts.append(_backlink_html(source_url))
    return "\n".join(parts)


def build_sheet_rows(title: str, markdown: str, source_url: str) -> list[list[str]]:
    """Rows for the Sheet: a title row, a backlink row, then one row per content
    line of the rewritten Markdown (blank lines collapsed)."""
    rows: list[list[str]] = [[title or "Untitled"]]
    if source_url:
        rows.append(["Originally published at", source_url])
    rows.append([""])  # spacer
    for line in (markdown or "").split("\n"):
        stripped = line.strip()
        if stripped:
            rows.append([stripped])
    return rows
