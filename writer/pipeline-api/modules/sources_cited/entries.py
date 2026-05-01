"""Step 3 + 4 — MLA-derived entry generation + Sources Cited section assembly.

Per sources-cited-module-prd-v1_1.md §7 Steps 3 + 4. Format (no author/date in v1):
    "Title of Page." <em>Publication Name</em>, <a href="URL" rel="nofollow">URL</a>.
"""

from __future__ import annotations

import html
from typing import Any, Optional
from urllib.parse import urlparse


PLACEHOLDER_TEXT = "[Citation data unavailable — manual review required]"


def _root_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or url
    except Exception:
        return url


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def render_entry(
    citation: dict[str, Any],
) -> tuple[str, list[str], bool]:
    """Render one MLA-derived entry for a citation.

    Returns (html_body, flags, used_placeholder).
    flags is a list like ["entries_with_missing_publication", ...] for the
    metadata block. used_placeholder is True when title or URL was missing.
    """
    title = (citation.get("title") or "").strip()
    publication = (citation.get("publication") or "").strip()
    url = (citation.get("url") or "").strip()
    cid = citation.get("citation_id", "")

    flags: list[str] = []

    # Hard-required: title and URL. Either missing → placeholder
    if not title or not url:
        flags.append("entries_with_placeholder")
        return (PLACEHOLDER_TEXT, flags, True)

    # Publication fallback: root domain of URL
    if not publication:
        publication = _root_domain(url)
        flags.append("entries_with_missing_publication")

    body = (
        f'"{_esc(title)}." '
        f'<em>{_esc(publication)}</em>, '
        f'<a href="{_esc(url)}" rel="nofollow">{_esc(url)}</a>.'
    )
    return (body, flags, False)


def build_sources_cited_html(
    ordered_used_citations: list[str],
    citations_by_id: dict[str, dict],
) -> tuple[str, dict[str, list[str]]]:
    """Render the full <ol class="sources-cited"> block.

    Returns (html_string, flags_by_kind) where flags_by_kind aggregates
    per-citation flags into:
        {
            "entries_with_missing_publication": [...],
            "entries_with_placeholder": [...],
        }
    """
    items: list[str] = []
    aggregated: dict[str, list[str]] = {
        "entries_with_missing_publication": [],
        "entries_with_placeholder": [],
    }

    for index, cid in enumerate(ordered_used_citations, start=1):
        citation = citations_by_id.get(cid) or {}
        entry_html, flags, _ = render_entry(citation)
        items.append(f'  <li id="sources-cited-{index}">{entry_html}</li>')
        for flag in flags:
            if flag in aggregated:
                aggregated[flag].append(cid)

    return (
        "<ol class=\"sources-cited\">\n" + "\n".join(items) + "\n</ol>",
        aggregated,
    )


def build_sources_cited_sections(
    ordered_used_citations: list[str],
    citations_by_id: dict[str, dict],
    conclusion_order: int,
) -> tuple[list[dict], dict[str, list[str]]]:
    """Build the two sections to append to the article (header + body).

    Returns (sections, flags_by_kind).
    """
    body_html, flags = build_sources_cited_html(ordered_used_citations, citations_by_id)

    header = {
        "order": conclusion_order + 1,
        "level": "H2",
        "type": "sources-cited-header",
        "heading": "Sources Cited",
        "body": None,
        "word_count": None,
        "section_budget": None,
        "citations_referenced": [],
    }
    body = {
        "order": conclusion_order + 2,
        "level": "none",
        "type": "sources-cited-body",
        "heading": None,
        "body": body_html,
        "word_count": None,
        "section_budget": None,
        "citations_referenced": [],
    }
    return ([header, body], flags)
