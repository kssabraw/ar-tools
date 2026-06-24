"""Structural-fidelity eval for reference page-structure mirroring.

The writing modules now mirror a client's stored reference page structure
(clients.page_structures) when generating output. To *tune* that mirroring you
need to measure how faithfully a generated page reproduces the reference's
layout. This module does that deterministically (no LLM, no network), so it can
run in CI and against live-generated output alike:

  reference analysis (outline + elements)  +  generated page (HTML or Markdown)
        ──►  extract the generated page's outline the same way
        ──►  score section-count / heading-order / block-type / element fidelity
        ──►  a 0–100 composite + a per-dimension breakdown + notes

The generated-page extractor mirrors the *shape* the scraper's LLM produces
(`{outline: [{level, heading, blocks, approx_words}], elements: {...}}`) so the
reference and the candidate are compared like-for-like.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Optional

from bs4 import BeautifulSoup

# Block-type element flags shared with the scraper's `elements` schema.
_ELEMENT_FLAGS = (
    "has_intro",
    "has_key_takeaways",
    "has_faq",
    "has_cta",
    "has_table",
    "has_lists",
)

_FAQ_RE = re.compile(r"\b(faq|frequently asked)", re.IGNORECASE)
_KEY_TAKEAWAYS_RE = re.compile(r"\b(key takeaway|key point|tl;dr|in (a |this )?nutshell)", re.IGNORECASE)
_CTA_RE = re.compile(
    r"\b(call|contact|book|schedule|get (a |your )?(quote|estimate|free)|request|sign up|"
    r"get started|reach out|call us|today)\b",
    re.IGNORECASE,
)


# ── generated-page → outline extraction ─────────────────────────────────────

def extract_outline_from_html(html: str) -> dict[str, Any]:
    """Extract a structure analysis ({outline, elements}) from generated HTML.

    Deterministic: walks headings in document order and classifies the content
    blocks between each heading and the next."""
    soup = BeautifulSoup(html or "", "html.parser")
    # Prefer the article/main subtree the generators emit; fall back to body.
    root = soup.find("article") or soup.find("main") or soup.body or soup

    headings = root.find_all(["h1", "h2", "h3"]) if root else []
    outline: list[dict[str, Any]] = []
    for idx, h in enumerate(headings):
        level = h.name.upper()
        heading_text = h.get_text(" ", strip=True)
        # Siblings up to the next heading form this section's body.
        blocks: set[str] = set()
        words = 0
        for sib in h.next_siblings:
            name = getattr(sib, "name", None)
            if name in ("h1", "h2", "h3"):
                break
            if name is None:
                continue
            words += len(sib.get_text(" ", strip=True).split())
            blocks |= _classify_html_block(sib)
        if _FAQ_RE.search(heading_text):
            blocks.add("faq")
        outline.append({
            "level": level,
            "heading": heading_text,
            "blocks": sorted(blocks),
            "approx_words": words,
        })

    full_text = root.get_text(" ", strip=True) if root else ""
    return {"outline": outline, "elements": _derive_elements(outline, full_text)}


def _classify_html_block(node: Any) -> set[str]:
    blocks: set[str] = set()
    name = getattr(node, "name", None)
    if name in ("ul", "ol"):
        blocks.add("list")
    elif name == "table":
        blocks.add("table")
    elif name == "blockquote":
        blocks.add("quote")
    elif name in ("p", "div", "section"):
        # Nested lists/tables/quotes inside a wrapper.
        if node.find("table"):
            blocks.add("table")
        if node.find(["ul", "ol"]):
            blocks.add("list")
        if node.find("blockquote"):
            blocks.add("quote")
        text = node.get_text(" ", strip=True)
        if text:
            blocks.add("paragraph")
        if _CTA_RE.search(text):
            blocks.add("cta")
    return blocks


_MD_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*\S)\s*$")
_MD_LIST_RE = re.compile(r"^\s*([-*+]|\d+\.)\s+\S")
_MD_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
_MD_QUOTE_RE = re.compile(r"^\s*>\s+\S")


def extract_outline_from_markdown(md: str) -> dict[str, Any]:
    """Extract a structure analysis ({outline, elements}) from generated Markdown."""
    outline: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    block_acc: set[str] = set()
    word_acc = 0

    def _flush() -> None:
        nonlocal current, block_acc, word_acc
        if current is not None:
            if _FAQ_RE.search(current["heading"]):
                block_acc.add("faq")
            current["blocks"] = sorted(block_acc)
            current["approx_words"] = word_acc
            outline.append(current)
        block_acc = set()
        word_acc = 0

    for line in (md or "").splitlines():
        m = _MD_HEADING_RE.match(line)
        if m:
            _flush()
            level = f"H{len(m.group(1))}"
            current = {"level": level, "heading": m.group(2).strip(), "blocks": [], "approx_words": 0}
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if _MD_TABLE_RE.match(line):
            if not re.match(r"^\s*\|[\s:|-]+\|\s*$", line):  # skip the |---| separator row
                block_acc.add("table")
        elif _MD_LIST_RE.match(line):
            block_acc.add("list")
        elif _MD_QUOTE_RE.match(line):
            block_acc.add("quote")
        else:
            block_acc.add("paragraph")
            if _CTA_RE.search(stripped):
                block_acc.add("cta")
        word_acc += len(stripped.split())
    _flush()

    full_text = re.sub(r"[#>*|`-]", " ", md or "")
    return {"outline": outline, "elements": _derive_elements(outline, full_text)}


def _derive_elements(outline: list[dict[str, Any]], full_text: str) -> dict[str, Any]:
    h2s = [it for it in outline if str(it.get("level")).upper() == "H2"]
    all_blocks: set[str] = set()
    for it in outline:
        for b in it.get("blocks") or []:
            all_blocks.add(b)
    headings_text = " ".join(it.get("heading", "") for it in outline)
    return {
        "section_count": len(h2s),
        "approx_total_words": sum(int(it.get("approx_words") or 0) for it in outline),
        "has_intro": bool(outline),  # any prose body before/around the first H2
        "has_key_takeaways": bool(_KEY_TAKEAWAYS_RE.search(headings_text)),
        "has_faq": "faq" in all_blocks or bool(_FAQ_RE.search(headings_text)),
        "has_cta": "cta" in all_blocks or bool(_CTA_RE.search(full_text)),
        "has_table": "table" in all_blocks,
        "has_lists": "list" in all_blocks,
    }


# ── scoring ─────────────────────────────────────────────────────────────────

def _analysis_of(structure: dict[str, Any]) -> dict[str, Any]:
    """Accept either a full page_structures entry ({status, analysis}) or a bare
    analysis dict, and return the analysis."""
    if isinstance(structure.get("analysis"), dict):
        return structure["analysis"]
    return structure


def _level_sequence(outline: list[dict[str, Any]]) -> list[str]:
    return [str(it.get("level") or "").upper() for it in outline if isinstance(it, dict)]


def _section_count(analysis: dict[str, Any]) -> int:
    el = analysis.get("elements") or {}
    if isinstance(el.get("section_count"), int) and el["section_count"]:
        return el["section_count"]
    return sum(1 for it in (analysis.get("outline") or []) if str(it.get("level")).upper() == "H2")


def score_structural_fidelity(
    reference: dict[str, Any],
    generated: dict[str, Any],
) -> dict[str, Any]:
    """Score how faithfully `generated` reproduces `reference`'s structure.

    Both args are structure analyses ({outline, elements, ...}) or full
    page_structures entries. Returns:

        {
          "composite": 0-100,
          "dimensions": {section_count, heading_order, block_types, elements},
          "notes": [str, ...],
        }
    """
    ref = _analysis_of(reference)
    gen = _analysis_of(generated)
    notes: list[str] = []

    # 1. Section-count fidelity.
    ref_n = _section_count(ref)
    gen_n = _section_count(gen)
    if ref_n == 0:
        section_score = 100.0 if gen_n == 0 else 0.0
    else:
        section_score = max(0.0, 1.0 - abs(ref_n - gen_n) / ref_n) * 100.0
    notes.append(f"sections: reference {ref_n} vs generated {gen_n}")

    # 2. Heading-order alignment — similarity of the ordered level sequence.
    ref_levels = _level_sequence(ref.get("outline") or [])
    gen_levels = _level_sequence(gen.get("outline") or [])
    if not ref_levels:
        order_score = 100.0 if not gen_levels else 0.0
    else:
        order_score = SequenceMatcher(None, ref_levels, gen_levels).ratio() * 100.0

    # 3. Block-type coverage — recall of block types the reference uses.
    ref_blocks = _all_block_types(ref.get("outline") or [])
    gen_blocks = _all_block_types(gen.get("outline") or [])
    if not ref_blocks:
        block_score = 100.0
    else:
        covered = ref_blocks & gen_blocks
        block_score = len(covered) / len(ref_blocks) * 100.0
        missing = ref_blocks - gen_blocks
        if missing:
            notes.append("missing block types: " + ", ".join(sorted(missing)))

    # 4. Element-flag fidelity — recall of structural elements the reference has.
    ref_el = ref.get("elements") or {}
    gen_el = gen.get("elements") or {}
    ref_flags = {f for f in _ELEMENT_FLAGS if ref_el.get(f)}
    if not ref_flags:
        element_score = 100.0
    else:
        present = {f for f in ref_flags if gen_el.get(f)}
        element_score = len(present) / len(ref_flags) * 100.0
        missing_flags = ref_flags - present
        if missing_flags:
            notes.append("missing elements: " + ", ".join(sorted(missing_flags)))

    dimensions = {
        "section_count": round(section_score, 1),
        "heading_order": round(order_score, 1),
        "block_types": round(block_score, 1),
        "elements": round(element_score, 1),
    }
    # Weighted composite — order + section count carry the most signal.
    composite = (
        section_score * 0.30
        + order_score * 0.30
        + block_score * 0.20
        + element_score * 0.20
    )
    return {"composite": round(composite, 1), "dimensions": dimensions, "notes": notes}


def _all_block_types(outline: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for it in outline:
        if not isinstance(it, dict):
            continue
        for b in it.get("blocks") or []:
            out.add(str(b))
    return out
