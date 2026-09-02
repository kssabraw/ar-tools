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


def remove_sections(html: str, keys) -> tuple[str, list[str]]:
    """Drop whole top-level ``<section>`` blocks by key (plan §5.4 Phase 4:
    a section the spec doesn't know, when the page is over its section cap).
    Unknown keys are ignored. Returns ``(new_html, removed_keys)``."""
    wanted = {k for k in (keys or []) if isinstance(k, str) and k.strip()}
    if not wanted or not (html or "").strip():
        return html or "", []
    soup = BeautifulSoup(html, "html.parser")
    removed: list[str] = []
    for key, sec in list(_iter_top_sections(soup)):
        if key in wanted:
            sec.decompose()
            removed.append(key)
    return str(soup), removed


def insert_sections(html: str, additions: dict, order: list[str]) -> tuple[str, list[str], list[str]]:
    """Insert NEW top-level ``<section id="KEY">`` blocks at their spec
    position. ``additions`` maps a key to the section's inner HTML; ``order``
    is the spec's section key order. Each new section is placed right after
    the nearest preceding key (in ``order``) that already exists on the page,
    else before the nearest following one, else appended to the article. A key
    that already exists on the page, or a non-string/empty body, is SKIPPED —
    this helper only ever ADDS sections the page lacks. Returns
    ``(new_html, inserted_keys, skipped_keys)``."""
    if not additions or not (html or "").strip():
        return html or "", [], list((additions or {}).keys())
    soup = BeautifulSoup(html, "html.parser")
    inserted: list[str] = []
    skipped: list[str] = []
    order = [k for k in (order or []) if isinstance(k, str)]
    for key in [k for k in order if k in additions] + [k for k in additions if k not in order]:
        body = additions.get(key)
        present = {k: sec for k, sec in _iter_top_sections(soup)}
        if key in present or not isinstance(body, str) or not body.strip():
            skipped.append(key)
            continue
        new_sec = soup.new_tag("section", id=key)
        frag = BeautifulSoup(body, "html.parser")
        for child in list(frag.contents):
            new_sec.append(child)
        pos = order.index(key) if key in order else len(order)
        anchor_after = next((present[k] for k in reversed(order[:pos]) if k in present), None)
        if anchor_after is not None:
            anchor_after.insert_after(new_sec)
        else:
            anchor_before = next((present[k] for k in order[pos + 1:] if k in present), None)
            if anchor_before is not None:
                anchor_before.insert_before(new_sec)
            else:
                container = (next(iter(present.values())).parent if present else None) or soup.find("article") or soup
                container.append(new_sec)
        inserted.append(key)
    return str(soup), inserted, skipped


def reorder_sections(html: str, order: list[str]) -> tuple[str, bool]:
    """Put the top-level ``<section>`` blocks whose keys the spec knows into
    spec order, leaving unknown sections where they are relative to their
    neighbours. Returns ``(new_html, changed)``. Deterministic; the cheapest
    structural fix there is, so it never needs an LLM."""
    known = [k for k in (order or []) if isinstance(k, str)]
    if not known or not (html or "").strip():
        return html or "", False
    soup = BeautifulSoup(html, "html.parser")
    entries = list(_iter_top_sections(soup))
    slots = [(k, sec) for k, sec in entries if k in known]
    if len(slots) < 2:
        return html, False
    current = [k for k, _ in slots]
    wanted = sorted(current, key=known.index)
    if current == wanted:
        return html, False
    by_key = {k: sec for k, sec in slots}
    # Re-fill the same DOM positions with the sections in spec order, so the
    # unknown sections between them keep their relative place.
    placeholders = []
    for k, sec in slots:
        marker = soup.new_tag("span", **{"data-reorder": k})
        sec.replace_with(marker)
        placeholders.append(marker)
    for marker, k in zip(placeholders, wanted):
        marker.replace_with(by_key[k])
    return str(soup), True
