"""Render a stored reference page structure into a compact prompt block.

The writing modules (blog brief, service brief, local SEO page generator) each
inject an optional "mirror this layout" block when the client has a reference
structure for the relevant page type. Rendering it to text once here keeps the
format consistent across modules and avoids duplicating the logic in each.
"""

from __future__ import annotations

from typing import Any, Optional

# Human labels for each reference page type.
PAGE_TYPE_LABELS = {
    "local_landing": "local landing",
    "service": "service",
    "location": "location",
    "blog_post": "blog post",
}

_LEVEL_INDENT = {"H1": "", "H2": "  ", "H3": "    "}


def render_reference_structure(entry: Optional[dict[str, Any]], page_type: str) -> Optional[str]:
    """Return a compact text block describing the client's own page layout, or
    None when there's no usable analysis. The block instructs the model to
    mirror the section layout/order while adapting all wording to the new topic.

    `entry` is one value from clients.page_structures (e.g. the "service" key):
        {"url", "status", "error", "analysis": {outline, structure_summary, elements}}
    """
    if not isinstance(entry, dict) or entry.get("status") != "complete":
        return None
    analysis = entry.get("analysis")
    if not isinstance(analysis, dict):
        return None

    outline = analysis.get("outline") or []
    summary = (analysis.get("structure_summary") or "").strip()
    elements = analysis.get("elements") or {}

    if not outline and not summary:
        return None

    label = PAGE_TYPE_LABELS.get(page_type, page_type)
    lines: list[str] = [
        f"REFERENCE STRUCTURE — mirror how the client's own {label} pages are organized. "
        "Match the section layout, ordering, and heading hierarchy below; adapt ALL wording "
        "to this topic. Do not copy the reference's wording or topic. Still follow every "
        "other writing rule for this module."
    ]
    if summary:
        lines.append(f"Summary: {summary}")

    if isinstance(outline, list) and outline:
        lines.append("Outline:")
        for item in outline:
            if not isinstance(item, dict):
                continue
            level = str(item.get("level") or "H2").upper()
            indent = _LEVEL_INDENT.get(level, "  ")
            heading = (item.get("heading") or "").strip()
            blocks = item.get("blocks") or []
            blocks_txt = f" [{', '.join(str(b) for b in blocks)}]" if isinstance(blocks, list) and blocks else ""
            words = item.get("approx_words")
            words_txt = f" (~{words} words)" if isinstance(words, int) and words else ""
            lines.append(f"{indent}- {level}: {heading}{blocks_txt}{words_txt}")

    if isinstance(elements, dict) and elements:
        flags = []
        for key, txt in (
            ("has_intro", "intro"),
            ("has_key_takeaways", "key-takeaways"),
            ("has_faq", "FAQ"),
            ("has_cta", "CTA"),
            ("has_table", "table"),
            ("has_lists", "lists"),
        ):
            if elements.get(key):
                flags.append(txt)
        meta_bits = []
        if flags:
            meta_bits.append("includes: " + ", ".join(flags))
        if elements.get("section_count"):
            meta_bits.append(f"{elements['section_count']} main sections")
        if elements.get("approx_total_words"):
            meta_bits.append(f"~{elements['approx_total_words']} words")
        if elements.get("intro_pattern"):
            meta_bits.append(f"opens with: {elements['intro_pattern']}")
        if meta_bits:
            lines.append("Elements: " + "; ".join(meta_bits))

    return "\n".join(lines)
