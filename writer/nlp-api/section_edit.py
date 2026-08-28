"""Section-scoped editing for generated local-SEO pages.

Generated pages are a flat list of ``<section id="...">`` blocks (intro, usp,
features, services, ... , faq). This module lets a corrective pass rewrite only
the sections that need fixing and splice them back in, instead of regenerating
the whole page. The LLM then emits a few sections rather than a full ~16k-token
page, so the second (SEO + voice) corrective pass fits the wall-clock budget.

Pure + bs4-only, unit-testable in isolation. A section is addressed by a stable
KEY: its ``id`` attribute when present, else a slug of its heading, else its
document position. `split_sections` and `apply_section_edits` derive that key
identically, so a key taken from the digest always resolves back to its section.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60]


def _iter_top_sections(soup: BeautifulSoup):
    """Top-level ``<section>`` elements in document order, with a stable key.

    Yields ``(key, section_element)``. Nested sections are skipped (only the
    outermost is addressable); duplicate keys are disambiguated by position so
    the mapping is always 1:1."""
    seen: set[str] = set()
    for i, sec in enumerate(soup.find_all("section")):
        if sec.find_parent("section") is not None:
            continue  # only top-level sections are addressable
        sid = (sec.get("id") or "").strip()
        heading_el = sec.find(_HEADING_TAGS)
        heading = heading_el.get_text(" ", strip=True) if heading_el else ""
        key = sid or _slug(heading) or f"section-{i}"
        if key in seen:
            key = f"{key}-{i}"
        seen.add(key)
        yield key, sec


def split_sections(html: str) -> list[dict]:
    """The generated article's top-level sections, in document order.

    Each entry: ``{"key", "id", "heading", "inner", "text"}`` where ``inner`` is
    the section's inner HTML and ``text`` its readable text. Returns ``[]`` when
    the page has no ``<section>`` wrappers — the caller then falls back to a
    whole-page rewrite rather than section-scoping a page it can't address."""
    if not (html or "").strip():
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for key, sec in _iter_top_sections(soup):
        heading_el = sec.find(_HEADING_TAGS)
        out.append({
            "key": key,
            "id": (sec.get("id") or "").strip(),
            "heading": heading_el.get_text(" ", strip=True) if heading_el else "",
            "inner": sec.decode_contents(),
            "text": sec.get_text(" ", strip=True),
        })
    return out


def apply_section_edits(html: str, edits: dict) -> tuple[str, list[str], list[str]]:
    """Replace the inner HTML of named ``<section>`` blocks.

    ``edits`` maps a section KEY (its id, else heading slug, else position) to
    the section's new inner HTML. A key that does not resolve to a section, or a
    non-string edit, is SKIPPED — never appended — so a hallucinated section id
    can never corrupt the page or add stray content. Returns
    ``(new_html, applied_keys, skipped_keys)``."""
    if not edits or not (html or "").strip():
        return html or "", [], list((edits or {}).keys())
    soup = BeautifulSoup(html, "html.parser")
    keymap = {key: sec for key, sec in _iter_top_sections(soup)}
    applied: list[str] = []
    skipped: list[str] = []
    for key, new_inner in edits.items():
        sec = keymap.get(key)
        if sec is None or not isinstance(new_inner, str) or not new_inner.strip():
            skipped.append(key)
            continue
        frag = BeautifulSoup(new_inner, "html.parser")
        sec.clear()
        for child in list(frag.contents):
            sec.append(child)
        applied.append(key)
    return str(soup), applied, skipped


def section_digest(sections: list[dict], max_inner_chars: int = 4000) -> str:
    """A compact, addressable index of the page's sections for a corrective
    prompt: each section's ``[key]`` + heading + current inner HTML (capped), so
    the model can target edits by key and preserve each section's structure
    (lists, tables) instead of rewriting from plain text."""
    lines: list[str] = []
    for s in sections:
        inner = s.get("inner") or ""
        if len(inner) > max_inner_chars:
            inner = inner[:max_inner_chars] + " …[truncated]"
        lines.append(
            f'[{s["key"]}] heading: {s.get("heading") or "(no heading)"}\n{inner}'
        )
    return "\n\n".join(lines)
