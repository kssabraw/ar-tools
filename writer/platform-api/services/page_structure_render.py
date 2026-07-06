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
- ``"structure"`` — for the blog Writer's body sections. Like ``"opening"`` the
  blog outline is SEO-driven and client-agnostic, so we don't replace it; instead
  this emits the client's structural *texture* (heading-nesting depth, how much
  section length varies — some sections run 1–2 sentences — and which recurring
  blocks they use) as style guidance the section writer applies on top of the
  article's own outline. It does NOT force a section count/order (that would fight
  the SEO outline), which is what separates it from ``"full"``.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

# Human labels for each reference page type.
PAGE_TYPE_LABELS = {
    "local_landing": "local landing",
    "service": "service",
    "location": "location",
    "blog_post": "blog post",
    "product": "product",
    "solution": "solution",
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

# Human labels for the controlled intent vocabulary (page_structure_scraper.INTENT_TAGS).
_INTENT_LABELS = {
    "hero": "hero / value prop",
    "value_prop": "benefits",
    "service_detail": "service detail",
    "process": "how it works",
    "trust": "trust / social proof",
    "objection": "objection handling",
    "pricing": "pricing",
    "coverage": "service area",
    "comparison": "comparison",
    "faq": "FAQ",
    "cta": "call to action",
    "about": "about the business",
    "other": "",
}

# Tolerance we allow the writer around a section's reference word count.
_WORD_TOLERANCE_PCT = 15

RenderMode = Literal["full", "opening", "structure"]


def _section_words(item: dict[str, Any]) -> int:
    """Word count for one section — new `word_count` (exact) or legacy
    `approx_words` (LLM estimate on pre-upgrade analyses)."""
    val = item.get("word_count")
    if not isinstance(val, int):
        val = item.get("approx_words")
    return val if isinstance(val, int) else 0


def _intent_label(item: dict[str, Any]) -> str:
    intent = str(item.get("intent") or "").strip().lower()
    if not intent:
        return ""
    return _INTENT_LABELS.get(intent, intent.replace("_", " "))


def _format_blocks(blocks: Any) -> str:
    """Compact human string for a section's block composition, for both the new
    detailed shape (list of {type, count, words, items}) and the legacy list of
    type strings."""
    if not isinstance(blocks, list) or not blocks:
        return ""
    parts: list[str] = []
    for b in blocks:
        if isinstance(b, dict):
            t = str(b.get("type") or "")
            if not t:
                continue
            count = b.get("count") or 1
            piece = f"{count}× {t}" if count and count != 1 else t
            detail_bits = []
            if isinstance(b.get("words"), int) and b["words"]:
                detail_bits.append(f"~{b['words']}w")
            if isinstance(b.get("items"), int) and b["items"]:
                detail_bits.append(f"{b['items']} items")
            if detail_bits:
                piece += f" ({', '.join(detail_bits)})"
            parts.append(piece)
        elif b:
            parts.append(str(b))
    return ", ".join(parts)


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


def _block_type_list(blocks: Any) -> list[str]:
    """Ordered, de-duplicated block type names for both schema shapes."""
    out: list[str] = []
    if not isinstance(blocks, list):
        return out
    for b in blocks:
        t = b.get("type") if isinstance(b, dict) else b
        if t and str(t) not in out:
            out.append(str(t))
    return out


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
    if mode == "structure":
        return _render_structure(analysis, page_type)
    return _render_full(analysis, page_type)


def _outline_lines(outline: Any, with_targets: bool = False) -> list[str]:
    """Render an outline into indented bullet lines. Shared by the full +
    structure renderers.

    When `with_targets` is set (whole-page mirror), each line carries the
    section's intent, exact word count, and block composition as concrete
    targets. Otherwise it stays a lighter style reference."""
    lines: list[str] = []
    if not isinstance(outline, list):
        return lines
    for item in outline:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level") or "H2").upper()
        indent = _LEVEL_INDENT.get(level, "  ")
        heading = (item.get("heading") or "").strip()
        intent = _intent_label(item)
        intent_txt = f" · {intent}" if intent else ""
        words = _section_words(item)
        words_txt = f" (~{words} words)" if words else ""
        blocks_txt = _format_blocks(item.get("blocks"))
        blocks_part = f" [{blocks_txt}]" if blocks_txt else ""
        if with_targets:
            lines.append(f"{indent}- {level}: {heading}{intent_txt} — target{words_txt}{blocks_part}")
        else:
            lines.append(f"{indent}- {level}: {heading}{intent_txt}{words_txt}{blocks_part}")
    return lines


def _render_full(analysis: dict[str, Any], page_type: str) -> str:
    """Whole-page mirror block: outline + an explicit replication checklist."""
    outline = analysis.get("outline") or []
    summary = (analysis.get("structure_summary") or "").strip()
    elements = analysis.get("elements") or {}
    label = PAGE_TYPE_LABELS.get(page_type, page_type)

    lines: list[str] = [
        f"REFERENCE STRUCTURE — mirror how the client's own {label} pages are organized. "
        "Match the section layout, ordering, heading hierarchy, and per-section SIZE below; "
        "adapt ALL wording to this topic. Do not copy the reference's wording or topic. Still "
        "follow every other writing rule for this module."
    ]
    if summary:
        lines.append(f"Summary: {summary}")

    outline_lines = _outline_lines(outline, with_targets=True)
    if outline_lines:
        lines.append(
            "Outline: each section lists its purpose, target word count, and the content "
            "blocks to include — treat these as targets to hit."
        )
        lines.extend(outline_lines)

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
    checklist.append(
        f"Hit each section's target word count within about {_WORD_TOLERANCE_PCT}% — do not pad a "
        "short section or truncate a long one."
    )
    checklist.append(
        "Reproduce each section's block composition: the same number of paragraphs, lists "
        "(with a similar item count), tables, and CTAs shown in that section's target."
    )
    total_words = elements.get("approx_total_words") if isinstance(elements, dict) else None
    if isinstance(total_words, int) and total_words:
        checklist.append(f"Aim for roughly {total_words} total words across the page.")
    flags = _present_flags(elements) if isinstance(elements, dict) else []
    if flags:
        checklist.append(
            "Include the same recurring content blocks where the reference uses them: "
            + ", ".join(flags) + "."
        )
    intro_pattern = elements.get("intro_pattern") if isinstance(elements, dict) else None
    if intro_pattern:
        checklist.append(f"Open with the same pattern: {intro_pattern}.")
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
        block_types = _block_type_list(first.get("blocks"))
        if block_types:
            lines.append("Opening blocks: " + ", ".join(block_types))

    return "\n".join(lines)


# A section short enough to read as 1–2 sentences (used to flag deliberate
# brevity the writer should preserve rather than padding every section out).
_SHORT_SECTION_WORDS = 45


def _render_structure(analysis: dict[str, Any], page_type: str) -> str:
    """Body-structure style block for the blog Writer's sections: the client's
    structural texture (heading depth, length variation, recurring blocks) applied
    as style over the article's own outline — NOT a section-for-section replica."""
    outline = analysis.get("outline") or []
    summary = (analysis.get("structure_summary") or "").strip()
    elements = analysis.get("elements") or {}
    label = PAGE_TYPE_LABELS.get(page_type, page_type)

    items = [it for it in outline if isinstance(it, dict)]
    levels = {str(it.get("level") or "").upper() for it in items}
    word_vals = [w for w in (_section_words(it) for it in items) if w]
    short_sections = [w for w in word_vals if w <= _SHORT_SECTION_WORDS]

    lines: list[str] = [
        f"REFERENCE STRUCTURE STYLE — write this section in the structural style of the "
        f"client's own {label} pages. Apply this as texture over THIS article's outline; keep "
        "this article's own headings, topic, and wording (do NOT rename the section to the "
        "reference's topics, copy its text, or enumerate its outline)."
    ]

    if "H3" in levels:
        lines.append(
            "- Heading depth: the client splits sections with H3 sub-headings — use an H3 "
            "sub-point where this section naturally breaks into parts."
        )
    else:
        lines.append(
            "- Heading depth: the client keeps sections flat (H2s with few or no H3s) — prefer "
            "a flat section over nested sub-headings."
        )

    if short_sections:
        lines.append(
            "- Section length: the client varies it — some sections run only 1–2 sentences. If "
            "this section's point is simple, keep it tight; don't pad it to match longer sections."
        )
    elif word_vals:
        avg = round(sum(word_vals) / len(word_vals))
        lines.append(
            f"- Section length: the client's sections average ~{avg} words — match that density "
            "rather than over-writing."
        )

    flags = _present_flags(elements) if isinstance(elements, dict) else []
    block_flags = [f for f in flags if f in {"table", "lists", "CTA"}]
    if block_flags:
        lines.append(
            "- Blocks they use: " + ", ".join(block_flags) + " — use the same where they fit "
            "this section's content."
        )

    if summary:
        lines.append(f"How their page is organized (context only): {summary}")

    outline_lines = _outline_lines(outline)
    if outline_lines:
        lines.append("For reference, one of the client's pages is laid out like this (style, not a template to copy):")
        lines.extend(outline_lines)

    return "\n".join(lines)
