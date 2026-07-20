"""Structural-fidelity eval for reference page-structure mirroring.

The writing modules now mirror a client's stored reference page structure
(clients.page_structures) when generating output. To *tune* that mirroring you
need to measure how faithfully a generated page reproduces the reference's
layout. This module does that deterministically (no LLM, no network), so it can
run in CI and against live-generated output alike:

  reference analysis (outline + elements)  +  generated page (HTML or Markdown)
        ──►  extract the generated page's outline the same way
        ──►  score section-count / heading-order / block-type / word-fit /
             element fidelity
        ──►  a 0–100 composite + a per-dimension breakdown + notes

The extractors here are also the *source of truth* the scraper uses to measure
the reference page itself (see page_structure_scraper.analyze_page_structure):
the LLM never counts words. Both sides therefore produce the same detailed
shape and compare like-for-like:

    {"outline": [{
        "level", "heading",
        "word_count": <int, exact>,
        "blocks": [{"type", "count", "words", "items"}],   # per-block detail
     }],
     "elements": {section_count, approx_total_words, has_*, ...}}

Back-compat: analyses stored before this upgrade carry `approx_words` (an LLM
estimate) and `blocks` as a bare list of type strings. The readers here accept
both shapes.
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

# A paragraph short enough to read as a pure call-to-action (rather than prose
# that merely mentions "contact") when it matches the CTA vocabulary.
_CTA_MAX_WORDS = 25

# Block-level tags we segment a page into. Headings delimit sections; the rest
# are content units. `find_all` returns them in document order regardless of how
# deeply they're nested, which is what makes segmentation robust on real pages.
_HEADING_TAGS = ("h1", "h2", "h3")
_CONTENT_TAGS = ("p", "ul", "ol", "table", "blockquote", "figure", "pre", "dl")
# Containers we count as ONE unit — never descend into them for inner <p>/<li>
# (that would double-count their text).
_UNIT_CONTAINERS = {"ul", "ol", "table", "blockquote", "figure", "pre", "dl"}


# ── word / block detail helpers ─────────────────────────────────────────────

def _block_words(text: str) -> int:
    return len(text.split())


def word_count_of(item: dict[str, Any]) -> int:
    """Word count for one outline section, tolerant of both schema versions."""
    val = item.get("word_count")
    if not isinstance(val, int):
        val = item.get("approx_words")
    return int(val) if isinstance(val, int) else 0


def block_types_of(item: dict[str, Any]) -> set[str]:
    """The set of block types in a section, for both detailed (list-of-dict) and
    legacy (list-of-str) `blocks`."""
    out: set[str] = set()
    for b in item.get("blocks") or []:
        if isinstance(b, dict):
            t = b.get("type")
            if t:
                out.add(str(t))
        elif b:
            out.add(str(b))
    return out


def _group_blocks(instances: list[dict[str, Any]], faq: bool = False) -> list[dict[str, Any]]:
    """Aggregate per-instance blocks ({type, words, items}) into per-type groups
    ({type, count, words, items}) in a stable, document-ish order."""
    order: list[str] = []
    groups: dict[str, dict[str, Any]] = {}
    for inst in instances:
        t = inst["type"]
        g = groups.get(t)
        if g is None:
            g = {"type": t, "count": 0, "words": 0, "items": 0}
            groups[t] = g
            order.append(t)
        g["count"] += 1
        g["words"] += int(inst.get("words") or 0)
        g["items"] += int(inst.get("items") or 0)
    if faq and "faq" not in groups:
        groups["faq"] = {"type": "faq", "count": 1, "words": 0, "items": 0}
        order.append("faq")
    result: list[dict[str, Any]] = []
    for t in order:
        g = groups[t]
        if not g["items"]:
            g.pop("items", None)
        result.append(g)
    return result


# ── page → outline extraction ───────────────────────────────────────────────

def extract_outline_from_html(html: str) -> dict[str, Any]:
    """Extract a structure analysis ({outline, elements}) from page HTML.

    Deterministic and document-order robust: it segments the page by headings
    and attributes every content block that follows a heading (at any nesting
    depth) to that section, so it works on the deeply-wrapped markup of real
    reference pages as well as the flat article HTML the generators emit."""
    soup = BeautifulSoup(html or "", "html.parser")
    # Prefer the article/main subtree; fall back to body then the whole doc.
    root = soup.find("article") or soup.find("main") or soup.body or soup
    if root is None:
        return {"outline": [], "elements": _derive_elements([], "")}

    outline: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    inst_acc: list[dict[str, Any]] = []

    def _flush() -> None:
        nonlocal current, inst_acc
        if current is not None:
            faq = bool(_FAQ_RE.search(current["heading"]))
            current["blocks"] = _group_blocks(inst_acc, faq=faq)
            current["word_count"] = sum(int(i.get("words") or 0) for i in inst_acc)
            outline.append(current)
        current = None
        inst_acc = []

    for el in root.find_all([*_HEADING_TAGS, *_CONTENT_TAGS]):
        name = el.name
        if name in _HEADING_TAGS:
            _flush()
            current = {"level": name.upper(), "heading": el.get_text(" ", strip=True)}
            continue
        # Content before the first heading isn't part of any section.
        if current is None:
            continue
        # Skip content nested inside a unit container we already count wholesale.
        if el.find_parent(_UNIT_CONTAINERS) is not None:
            continue
        inst = _classify_html_block(el)
        if inst is not None:
            inst_acc.append(inst)
    _flush()

    full_text = root.get_text(" ", strip=True)
    return {"outline": outline, "elements": _derive_elements(outline, full_text)}


def _classify_html_block(node: Any) -> Optional[dict[str, Any]]:
    """Classify one block-level element into {type, words, items} or None."""
    name = getattr(node, "name", None)
    text = node.get_text(" ", strip=True)
    words = _block_words(text)
    if name in ("ul", "ol", "dl"):
        items = len(node.find_all("li", recursive=False)) or len(node.find_all("li"))
        return {"type": "list", "words": words, "items": items}
    if name == "table":
        return {"type": "table", "words": words, "items": len(node.find_all("tr"))}
    if name == "blockquote":
        return {"type": "quote", "words": words, "items": 0}
    if name == "figure":
        return {"type": "image", "words": words, "items": 0}
    if name == "pre":
        return {"type": "code", "words": words, "items": 0}
    # <p> (and anything else that slipped through) → prose or a CTA.
    if not text:
        return None
    if words <= _CTA_MAX_WORDS and _CTA_RE.search(text):
        return {"type": "cta", "words": words, "items": 0}
    return {"type": "paragraph", "words": words, "items": 0}


_MD_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*\S)\s*$")
_MD_LIST_RE = re.compile(r"^\s*([-*+]|\d+\.)\s+\S")
_MD_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
_MD_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_MD_QUOTE_RE = re.compile(r"^\s*>\s+\S")


def extract_outline_from_markdown(md: str) -> dict[str, Any]:
    """Extract a structure analysis ({outline, elements}) from Markdown, with the
    same detailed per-block shape as the HTML extractor."""
    outline: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    inst_acc: list[dict[str, Any]] = []
    # An in-progress run of same-type lines (list items / table rows / a
    # paragraph's wrapped lines) collapsed into one block instance.
    run: Optional[dict[str, Any]] = None

    def _close_run() -> None:
        nonlocal run
        if run is not None:
            inst_acc.append(run)
            run = None

    def _flush() -> None:
        nonlocal current, inst_acc, run
        _close_run()
        if current is not None:
            faq = bool(_FAQ_RE.search(current["heading"]))
            current["blocks"] = _group_blocks(inst_acc, faq=faq)
            current["word_count"] = sum(int(i.get("words") or 0) for i in inst_acc)
            outline.append(current)
        current = None
        inst_acc = []

    def _add(kind: str, words: int, is_item: bool) -> None:
        nonlocal run
        if run is not None and run["type"] != kind:
            _close_run()
        if run is None:
            run = {"type": kind, "words": 0, "items": 0}
        run["words"] += words
        if is_item:
            run["items"] += 1

    for line in (md or "").splitlines():
        m = _MD_HEADING_RE.match(line)
        if m:
            _flush()
            current = {"level": f"H{len(m.group(1))}", "heading": m.group(2).strip()}
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            _close_run()  # a blank line ends a paragraph/list run
            continue
        if _MD_TABLE_RE.match(line):
            if not _MD_TABLE_SEP_RE.match(line):  # skip the |---| separator row
                cells = _block_words(stripped.strip("|"))
                _add("table", cells, is_item=True)
        elif _MD_LIST_RE.match(line):
            _add("list", _block_words(stripped), is_item=True)
        elif _MD_QUOTE_RE.match(line):
            _add("quote", _block_words(stripped), is_item=False)
        else:
            words = _block_words(stripped)
            kind = "cta" if (words <= _CTA_MAX_WORDS and _CTA_RE.search(stripped)) else "paragraph"
            _add(kind, words, is_item=False)
    _flush()

    full_text = re.sub(r"[#>*|`-]", " ", md or "")
    return {"outline": outline, "elements": _derive_elements(outline, full_text)}


def _derive_elements(outline: list[dict[str, Any]], full_text: str) -> dict[str, Any]:
    h2s = [it for it in outline if str(it.get("level")).upper() == "H2"]
    all_blocks: set[str] = set()
    for it in outline:
        all_blocks |= block_types_of(it)
    headings_text = " ".join(it.get("heading", "") for it in outline)
    return {
        "section_count": len(h2s),
        "approx_total_words": sum(word_count_of(it) for it in outline),
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

    # 4. Word-fit fidelity — how closely section + total word counts match.
    word_score = _word_fit_score(ref, gen, notes)

    # 5. Element-flag fidelity — recall of structural elements the reference has.
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
        "word_fit": round(word_score, 1),
        "elements": round(element_score, 1),
    }
    # Weighted composite — order + section count carry the most signal; word-fit
    # (does the generated content actually fit the template's section sizes?)
    # is a first-class dimension now that reference counts are exact.
    composite = (
        section_score * 0.25
        + order_score * 0.25
        + block_score * 0.15
        + word_score * 0.20
        + element_score * 0.15
    )
    return {"composite": round(composite, 1), "dimensions": dimensions, "notes": notes}


def _word_fit_score(ref: dict[str, Any], gen: dict[str, Any], notes: list[str]) -> float:
    """Blend total-word closeness with mean per-section (order-aligned) closeness.

    Each closeness is 1 - min(1, |ref - gen| / max(ref, floor)); a section the
    generated page omits entirely counts as a full miss for that slot."""
    ref_outline = ref.get("outline") or []
    gen_outline = gen.get("outline") or []
    ref_total = sum(word_count_of(it) for it in ref_outline if isinstance(it, dict))
    gen_total = sum(word_count_of(it) for it in gen_outline if isinstance(it, dict))
    if ref_total <= 0:
        return 100.0

    def _closeness(ref_w: int, gen_w: int) -> float:
        denom = max(ref_w, 1)
        return max(0.0, 1.0 - min(1.0, abs(ref_w - gen_w) / denom))

    total_close = _closeness(ref_total, gen_total)

    # Per-section, aligned by position over the reference's sections.
    ref_words = [word_count_of(it) for it in ref_outline if isinstance(it, dict)]
    gen_words = [word_count_of(it) for it in gen_outline if isinstance(it, dict)]
    per_section = [
        _closeness(rw, gen_words[i] if i < len(gen_words) else 0)
        for i, rw in enumerate(ref_words)
    ]
    section_close = sum(per_section) / len(per_section) if per_section else total_close

    score = (total_close * 0.5 + section_close * 0.5) * 100.0
    notes.append(f"words: reference {ref_total} vs generated {gen_total}")
    return score


def _all_block_types(outline: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for it in outline:
        if isinstance(it, dict):
            out |= block_types_of(it)
    return out


# ── corrective feedback (drives the generation retry loop) ───────────────────
# Human-readable label per element flag the reference can require. Drives the
# "you dropped these blocks" correction. `has_intro` is omitted — it's true for
# any non-empty page, so it's never a meaningful miss.
_FLAG_LABELS = {
    "has_faq": "an FAQ section",
    "has_cta": "a call-to-action",
    "has_table": "a comparison/data table",
    "has_lists": "a bulleted/numbered list",
    "has_key_takeaways": "a key-takeaways block",
}

# Below this ordered-level similarity, the generated heading hierarchy has
# drifted enough to correct (reordered / wrong H2-vs-H3 nesting).
_ORDER_CORRECTION_RATIO = 0.75


def _levels_desc(levels: list[str]) -> str:
    h2 = levels.count("H2")
    h3 = levels.count("H3")
    if h3:
        return f"{h2} H2 sections with {h3} H3 sub-points"
    return f"{h2} H2 sections, no H3 nesting"


def build_structure_corrections(
    reference: dict[str, Any], generated: dict[str, Any]
) -> str:
    """Return imperative, layout-focused corrections for regenerating a page that
    drifted from the reference structure — or "" when the layout already matches.

    Deliberately scoped to the layout dimensions that drive real drift (section
    count, dropped structural blocks, heading-hierarchy order) rather than exact
    word counts, so the retry directive stays concrete and short. Both args are
    structure analyses or full page_structures entries. Pure — no I/O."""
    ref = _analysis_of(reference)
    gen = _analysis_of(generated)
    lines: list[str] = []

    ref_n = _section_count(ref)
    gen_n = _section_count(gen)
    if ref_n and gen_n != ref_n:
        verb = "Add sections" if gen_n < ref_n else "Consolidate sections"
        lines.append(
            f"- Produce exactly {ref_n} main H2 sections — you produced {gen_n}. "
            f"{verb} to match, preserving the reference's section order and purpose."
        )

    ref_el = ref.get("elements") or {}
    gen_el = gen.get("elements") or {}
    missing = [
        label
        for flag, label in _FLAG_LABELS.items()
        if ref_el.get(flag) and not gen_el.get(flag)
    ]
    if missing:
        lines.append(
            "- Include these blocks the reference has and your draft dropped: "
            + ", ".join(missing)
            + " — place each where the reference uses it."
        )

    ref_levels = _level_sequence(ref.get("outline") or [])
    gen_levels = _level_sequence(gen.get("outline") or [])
    if ref_levels and SequenceMatcher(None, ref_levels, gen_levels).ratio() < _ORDER_CORRECTION_RATIO:
        lines.append(
            f"- Match the reference's heading hierarchy ({_levels_desc(ref_levels)}) — "
            "same H2/H3 nesting depth and section order."
        )

    return "\n".join(lines)


def structure_deficiency(
    reference: dict[str, Any],
    generated: dict[str, Any],
    *,
    label: str,
    min_composite: float,
) -> Optional[dict[str, Any]]:
    """Return a synthetic scorer-deficiency (`{engine, issues, recommendations}`)
    describing structural drift of `generated` vs `reference`, or None when there's
    no reference outline or the layout already matches (composite >= min_composite).

    For generators whose reoptimize pass is driven by the scorer's deficiency list
    (the service/location Writer) rather than a dedicated corrections field, this
    shapes the same `build_structure_corrections` feedback as one more deficiency —
    so no new plumbing is needed in the writer. Pure — no I/O."""
    ref = _analysis_of(reference)
    if not (ref.get("outline") or []):
        return None
    try:
        fidelity = score_structural_fidelity(reference, generated)
    except Exception:  # noqa: BLE001 — defensive; scoring must never raise here
        return None
    if (fidelity.get("composite") or 0.0) >= min_composite:
        return None
    corrections = build_structure_corrections(reference, generated)
    if not corrections:
        return None
    recs = [ln.lstrip("- ").strip() for ln in corrections.splitlines() if ln.strip()]
    return {
        "engine": f"Page structure fidelity ({label})",
        "issues": [f"the draft's layout drifted from the client's reference {label} page structure"],
        "recommendations": recs,
    }
