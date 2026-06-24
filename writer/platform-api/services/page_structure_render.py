"""Render a stored reference page structure into a compact prompt block.

The writing modules (blog brief, service brief, local SEO page generator) each
inject an optional "mirror this layout" block when the client has a reference
structure for the relevant page type. Rendering it to text once here keeps the
format consistent across modules and avoids duplicating the logic in each.

Two render modes shape the directive to the consumer:

- ``"full"`` (default) — for the service brief and the local-SEO generator, which
  produce the *whole* page. Emits the outline + an explicit replication checklist
  so the model mirrors section count, order, hierarchy, and recurring block types.
- ``"opening"`` — for the blog Writer's intro, which only shapes the opening. The
  blog brief is client-agnostic + globally cached, so the heading structure can't
  carry client layout; the intro honors the *opening pattern* only. This mode
  omits the full outline so the intro can't accidentally enumerate the sections.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

# Human labels for each reference page type.
PAGE_TYPE_LABELS = {
    "local_landing": "local landing",
    "service": "service",
    "location": "location",
    "blog_post": "blog post",
}

_LEVEL_INDENT = {"H1": "", "H2": "  ", "H3": "    "}

# elements flag key -> human label, used to surface + require recurring blocks.
_ELEMENT_FLAGS = (
    ("has_intro", "intro"),
    ("has_key_takeaways", "key-takeaways"),
    ("has_faq", "FAQ"),
    ("has_cta", "CTA"),
    ("has_table", "table"),
    ("has_lists", "lists"),
)

RenderMode = Literal["full", "opening"]


def _usable(entry: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return the analysis dict when the entry is complete + has content, else None."""
    if not isinstance(entry, dict) or entry.get("status") != "complete":
        return None
    analysis = entry.get("analysis")
    if not isinstance(analysis, dict):
        return None
    if not (analysis.get("outline") or (analysis.get("structure_summary") or "").strip()):
        return None
    return analysis


def _present_flags(elements: dict[str, Any]) -> list[str]:
    return [label for key, label in _ELEMENT_FLAGS if elements.get(key)]


def render_reference_structure(
    entry: Optional[dict[str, Any]],
    page_type: str,
    mode: RenderMode = "full",
) -> Optional[str]:
    """Return a compact text block describing the client's own page layout, or
    None when there's no usable analysis.

    `entry` is one value from clients.page_structures (e.g. the "service" key):
        {"url", "status", "error", "analysis": {outline, structure_summary, elements}}
    """
    analysis = _usable(entry)
    if analysis is None:
        return None
    if mode == "opening":
        return _render_opening(analysis, page_type)
    return _render_full(analysis, page_type)


def _render_full(analysis: dict[str, Any], page_type: str) -> str:
    """Whole-page mirror block: outline + an explicit replication checklist."""
    outline = analysis.get("outline") or []
    summary = (analysis.get("structure_summary") or "").strip()
    elements = analysis.get("elements") or {}
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
            blocks_txt = (
                f" [{', '.join(str(b) for b in blocks)}]"
                if isinstance(blocks, list) and blocks else ""
            )
            words = item.get("approx_words")
            words_txt = f" (~{words} words)" if isinstance(words, int) and words else ""
            lines.append(f"{indent}- {level}: {heading}{blocks_txt}{words_txt}")

    if isinstance(elements, dict) and elements:
        flags = _present_flags(elements)
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

    # Replication checklist — concrete, forceful directives so the model treats
    # the reference as a layout to reproduce, not loose inspiration.
    checklist: list[str] = []
    section_count = elements.get("section_count") if isinstance(elements, dict) else None
    if isinstance(section_count, int) and section_count:
        checklist.append(
            f"Produce roughly {section_count} main (H2) sections in the same order and purpose."
        )
    else:
        checklist.append("Keep the same number, order, and purpose of main sections.")
    checklist.append("Preserve the heading hierarchy depth (H2 vs H3 nesting) shown above.")
    flags = _present_flags(elements) if isinstance(elements, dict) else []
    if flags:
        checklist.append(
            "Include the same recurring content blocks where the reference uses them: "
            + ", ".join(flags) + "."
        )
    intro_pattern = elements.get("intro_pattern") if isinstance(elements, dict) else None
    if intro_pattern:
        checklist.append(f"Open with the same pattern: {intro_pattern}.")
    checklist.append(
        "Keep each section's relative length proportional to the reference (longer where it's "
        "longer, shorter where it's shorter)."
    )
    lines.append("Replication checklist:")
    lines.extend(f"  - {c}" for c in checklist)

    return "\n".join(lines)


def _render_opening(analysis: dict[str, Any], page_type: str) -> str:
    """Opening-only block for the blog intro: how the client leads in. Omits the
    full outline so the intro can't enumerate sections."""
    summary = (analysis.get("structure_summary") or "").strip()
    elements = analysis.get("elements") or {}
    outline = analysis.get("outline") or []
    label = PAGE_TYPE_LABELS.get(page_type, page_type)

    lines: list[str] = [
        f"REFERENCE OPENING — how the client opens their own {label} pages. Match the "
        "opening's shape and lead-in style; adapt all wording to this topic. Do NOT "
        "enumerate the outline or list the sections — write only the opening."
    ]
    intro_pattern = elements.get("intro_pattern") if isinstance(elements, dict) else None
    if intro_pattern:
        lines.append(f"Opening pattern: {intro_pattern}")
    if summary:
        lines.append(f"How the page is organized (context only): {summary}")
    # The first content heading's block types hint at how the opening is framed
    # (e.g. a stat or a list right after the lead), without exposing the full map.
    first = next(
        (
            it for it in outline
            if isinstance(it, dict) and str(it.get("level") or "").upper() in ("H1", "H2")
        ),
        None,
    )
    if first:
        blocks = first.get("blocks") or []
        if isinstance(blocks, list) and blocks:
            lines.append("Opening blocks: " + ", ".join(str(b) for b in blocks))

    return "\n".join(lines)
