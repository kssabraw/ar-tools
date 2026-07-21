"""Reference page-structure scraper — ScrapeOwl fetch + chrome strip + analysis.

Given one of a client's reference page URLs (local landing / service / location /
blog post), this fetches the page, strips the site chrome (nav, header, footer,
sidebars, popups/modals/cookie banners) so only the main content remains, then
analyzes the page's *structure* so generated content can be built to fit it.

Analysis is a two-part split so the result is robust enough to drive hard
word/block targets:

- **Deterministic pass** (page_structure_eval.extract_outline_from_html): the
  heading outline, the EXACT word count per section, and the per-block
  composition (how many paragraphs / lists / tables / CTAs and their sizes).
  The LLM never counts — counting is where models are unreliable, and "content
  must fit the template" needs real numbers.
- **LLM annotation pass** (llm_annotate_structure): only the semantic layer the
  deterministic pass can't produce — each section's *intent* (from a controlled
  vocabulary) + a short note, a generalized heading, the opening pattern, and a
  natural-language structure summary.

The merged result is stored on the client (clients.page_structures) and reused
indefinitely by the writing modules to mirror the client's own layouts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bs4 import BeautifulSoup, Comment

from services.page_structure_eval import extract_outline_from_html

logger = logging.getLogger(__name__)

# Valid reference page types (matches the keys in clients.page_structures).
PAGE_TYPES = ("local_landing", "service", "location", "blog_post", "product", "solution")

# Controlled vocabulary for a section's intent. The LLM must pick one of these
# per section (falls back to "other"); a fixed set keeps the intent legible to
# the renderer and scoreable in the eval, rather than free-form drift.
INTENT_TAGS = (
    "hero",              # opening hero / value proposition
    "value_prop",        # benefits / why-choose-us
    "service_detail",    # what the service/offer actually is
    "process",           # how it works / steps
    "trust",             # social proof, reviews, credentials, guarantees
    "objection",         # addresses a concern/hesitation
    "pricing",           # cost / quotes / packages
    "coverage",          # service area / locations served
    "comparison",        # option-vs-option or us-vs-them
    "faq",               # frequently asked questions
    "cta",               # conversion / contact push
    "about",             # background on the business
    "other",
)

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


# The aggressive strip is trusted unless it yields NO visible text at all — only
# then is the gentler fallback tried. Kept at "essentially empty" (not a larger
# floor) so a legitimately short main-content strip is never second-guessed.
_MIN_CONTENT_CHARS = 1


def _text_len(fragment: str) -> int:
    return len(BeautifulSoup(fragment or "", "html.parser").get_text(" ", strip=True))


def _strip_soup(soup: BeautifulSoup, *, hints: bool) -> None:
    """Remove chrome from ``soup`` in place. Always drops hard chrome tags,
    ARIA-landmark chrome, and aria-hidden elements. When ``hints`` is True, ALSO
    decomposes elements whose id/class substring-matches a chrome hint — the
    aggressive pass."""
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": True}):
        if str(tag.get("role", "")).lower() in _DROP_ROLES:
            tag.decompose()
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()
    if hints:
        for tag in soup.find_all(attrs={"class": _hint_match}):
            tag.decompose()
        for tag in soup.find_all(attrs={"id": _hint_match}):
            tag.decompose()


def strip_chrome(html: str) -> str:
    """Return the page's main content HTML with site chrome removed.

    Aggressive pass: drop chrome tags, ARIA-landmark chrome, and elements whose
    id/class hint at nav/popups/overlays, then prefer a <main>/role=main/
    <article> landmark. BUT the id/class hint-matching is a substring test, so
    on builder-heavy sites (WordPress + Divi/Elementor, Squarespace…) it can
    wrongly nuke real content — a hero wrapper classed 'hero-banner', a section
    titled '…header', etc. — leaving nothing. So if the aggressive pass strips
    the page to (near) nothing, fall back to a GENTLE pass that keeps the
    id/class-hinted elements (dropping only hard chrome tags + ARIA landmarks)
    and doesn't force a main/article landmark. Last resort: the raw body.
    Best-effort — the LLM is also told to ignore any chrome that slips through.
    """
    # Aggressive pass.
    soup = BeautifulSoup(html or "", "html.parser")
    _strip_soup(soup, hints=True)
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")
    aggressive = str(main if main is not None else (soup.body or soup))
    if _text_len(aggressive) >= _MIN_CONTENT_CHARS:
        return aggressive

    # Gentle fallback — real content survived the hard-chrome removal but was
    # over-matched by the hint pass; keep the hinted elements this time.
    soup2 = BeautifulSoup(html or "", "html.parser")
    _strip_soup(soup2, hints=False)
    gentle = str(soup2.body or soup2)
    if _text_len(gentle) >= _MIN_CONTENT_CHARS:
        return gentle

    # Nothing usable either way — return whatever body we have.
    return gentle or aggressive


_SYSTEM_PROMPT = (
    "You annotate the STRUCTURE of a single web page. The page's main content has "
    "already been parsed deterministically into an ordered list of sections — each "
    "with its exact word count and block composition. You are ALSO given the "
    "main-content HTML for context (chrome is already stripped; ignore any that "
    "remains).\n\n"
    "Your job is the SEMANTIC layer only. Do NOT recount words, do NOT re-derive "
    "the outline, do NOT change section order — those are fixed. You do NOT "
    "summarize the topic or copy the wording. For each provided section, in order, "
    "you return:\n"
    "  - a GENERALIZED heading (strip any specific brand/topic/place name so it "
    "reads as a reusable section label),\n"
    "  - the section's INTENT — its purpose on the page — as EXACTLY ONE tag from "
    "this fixed list:\n"
    "      " + ", ".join(INTENT_TAGS) + "\n"
    "  - a short intent_note (<= 12 words) saying what the section does.\n\n"
    "Return ONLY valid JSON matching this exact schema — no prose, no markdown fences:\n"
    "{\n"
    '  "sections": [\n'
    '    {"index": <int, matching the given section index>, "generalized_heading": "...", '
    '"intent": "<one tag>", "intent_note": "..."}\n'
    "  ],\n"
    '  "structure_summary": "2-5 sentence plain-English description of how the page is organized: '
    'the opening pattern, the order and purpose of the main sections, recurring content blocks, and how it closes.",\n'
    '  "intro_pattern": "short description of how the page opens (e.g. \'direct answer then context\', '
    "'problem framing', 'hero statement + value prop')\"\n"
    "}\n\n"
    "Return one sections entry per given section, with matching index values. If a "
    "section's purpose is unclear, use intent \"other\". If the page has no clear "
    "structure, return an empty sections list and say so in structure_summary."
)


def _outline_digest(outline: list[dict[str, Any]]) -> str:
    """Compact, indexed rendering of the deterministic outline for the LLM to
    annotate — headings + block composition + exact word counts."""
    lines: list[str] = []
    for idx, item in enumerate(outline):
        level = str(item.get("level") or "H2")
        heading = (item.get("heading") or "").strip() or "(no heading)"
        words = item.get("word_count") or 0
        blocks = item.get("blocks") or []
        block_bits = []
        for b in blocks:
            if isinstance(b, dict):
                bit = f"{b.get('count', 1)}×{b.get('type')}"
                if b.get("items"):
                    bit += f"/{b['items']}items"
                block_bits.append(bit)
        blocks_txt = ", ".join(block_bits) if block_bits else "—"
        lines.append(f"[{idx}] {level} \"{heading}\" — ~{words} words; blocks: {blocks_txt}")
    return "\n".join(lines)


async def llm_annotate_structure(
    html: str, outline: list[dict[str, Any]], page_type: str
) -> dict[str, Any]:
    """Call Claude to add the semantic layer (per-section intent + generalized
    heading, opening pattern, structure summary) on top of the deterministic
    outline. Returns {"sections": [...], "structure_summary": str,
    "intro_pattern": str}; degrades to empty on any failure."""
    if not outline:
        return {"sections": [], "structure_summary": "", "intro_pattern": ""}

    truncated_html = html[:60_000] if len(html) > 60_000 else html

    from services import report_llm

    # Runs on Anthropic; a transient (429/5xx/connection) failure falls back to
    # OpenAI→Gemini automatically — one 429 previously failed the whole
    # page_structure_scrape job.
    raw = (await report_llm.generate_text(
        system=_SYSTEM_PROMPT,
        user=(
            f"Reference page type: {page_type}\n\n"
            f"Parsed sections (index, level, heading, size, blocks):\n"
            f"{_outline_digest(outline)}\n\n"
            f"Main-content HTML for context:\n\n{truncated_html}"
        ),
        model="claude-sonnet-4-6",
        max_tokens=2048,
        log_tag="page_structure",
    )).strip()
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
        return {"sections": [], "structure_summary": "", "intro_pattern": ""}

    return result


def _merge_annotations(
    outline: list[dict[str, Any]], annotations: dict[str, Any]
) -> list[dict[str, Any]]:
    """Overlay the LLM's per-section semantics onto the deterministic outline.

    The deterministic fields (level, word_count, blocks) are authoritative and
    kept as-is; the LLM only supplies heading/intent/intent_note, matched by
    index. Sections the LLM omitted keep their real heading and no intent."""
    by_index: dict[int, dict[str, Any]] = {}
    for entry in annotations.get("sections") or []:
        if isinstance(entry, dict) and isinstance(entry.get("index"), int):
            by_index[entry["index"]] = entry

    merged: list[dict[str, Any]] = []
    for idx, item in enumerate(outline):
        out = dict(item)  # keep level, word_count, blocks
        ann = by_index.get(idx)
        if ann:
            heading = (ann.get("generalized_heading") or "").strip()
            if heading:
                out["heading"] = heading
            intent = str(ann.get("intent") or "").strip().lower()
            out["intent"] = intent if intent in INTENT_TAGS else "other"
            note = (ann.get("intent_note") or "").strip()
            if note:
                out["intent_note"] = note
        merged.append(out)
    return merged


async def analyze_page_structure(html: str, page_type: str) -> dict[str, Any]:
    """Strip chrome, measure structure deterministically, then annotate with the
    LLM. Returns {"outline", "structure_summary", "elements"} — the shape the
    renderer + eval consume, with exact word counts and per-block detail."""
    cleaned = strip_chrome(html)
    deterministic = extract_outline_from_html(cleaned)
    outline = deterministic.get("outline") or []
    elements = dict(deterministic.get("elements") or {})

    annotations = await llm_annotate_structure(cleaned, outline, page_type)

    merged_outline = _merge_annotations(outline, annotations)
    intro_pattern = (annotations.get("intro_pattern") or "").strip()
    if intro_pattern:
        elements["intro_pattern"] = intro_pattern

    return {
        "outline": merged_outline,
        "structure_summary": (annotations.get("structure_summary") or "").strip(),
        "elements": elements,
    }
