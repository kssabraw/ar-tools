"""Deterministic, app-owned article structure for media planning + placement.

The media-planning prompt requires the *application* (never the model) to assign
stable IDs to every heading and paragraph, and to resolve/insert assets against
those real IDs. This module does exactly that, working from the article Markdown
the publish path already assembles:

  1. `parse_blocks` — split Markdown into ordered blocks with source line spans
     (so insertion splices into the original text, preserving it verbatim).
  2. `assign_ids` — stamp `section-NNN` (H2) / `subsection-NNN` (H3) /
     `paragraph-NNN` IDs on heading + paragraph blocks only (never lists, tables,
     blockquotes, HR, or raw-HTML blocks — per the spec).
  3. `render_html_with_ids` — the ID-bearing HTML fragment handed to the planner.
  4. `build_id_index` — the authoritative set of valid anchor/section IDs +
     paragraph→section containment, for validating the model's placements.
  5. `resolve_placement` — anchor_id → section_id → fallback_excerpt, in that
     order (the app's placement contract; no fuzzy matching).
  6. `insert_figures` — splice `<figure>` blocks into the Markdown body at the
     resolved anchors, idempotently (keyed by `data-media-id`).

All pure and unit-tested.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.markdown_html import (
    _HEADING_RE,
    _HR_RE,
    _OL_RE,
    _UL_RE,
    _inline,
    _is_table_start,
)

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


@dataclass
class Block:
    """One Markdown block with its source line span (end exclusive)."""

    kind: str            # heading | paragraph | list | table | blockquote | hr | html
    start: int
    end: int
    text: str            # verbatim source lines joined by newline
    level: int | None = None  # heading level (1..6) when kind == 'heading'
    heading_text: str | None = None  # plain heading text when kind == 'heading'
    id: str | None = None    # assigned by assign_ids (heading/paragraph only)


def _plain(text: str) -> str:
    """Strip inline Markdown marks + HTML tags to plain text (for headings)."""
    t = re.sub(r"<[^>]+>", "", text)
    t = re.sub(r"[*_`]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_blocks(markdown: str) -> list[Block]:
    """Split Markdown into ordered blocks, each carrying its source line span.

    Mirrors the constructs `markdown_html` recognizes (headings, paragraphs,
    lists, tables, blockquotes, HR) plus a passthrough `html` block for lines
    that begin with '<' (e.g. the Sources Cited `<ol>`). Blank lines separate
    blocks and belong to no block."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            i += 1
            continue

        # Table (header + delimiter + rows).
        if _is_table_start(lines, i):
            start = i
            i += 2
            while i < n and lines[i].strip() and "|" in lines[i]:
                i += 1
            blocks.append(Block("table", start, i, "\n".join(lines[start:i])))
            continue

        # Heading (single line).
        m = _HEADING_RE.match(stripped)
        if m:
            blocks.append(
                Block("heading", i, i + 1, raw, level=len(m.group(1)),
                      heading_text=_plain(m.group(2).strip()))
            )
            i += 1
            continue

        # Horizontal rule.
        if _HR_RE.match(stripped):
            blocks.append(Block("hr", i, i + 1, raw))
            i += 1
            continue

        # List (consecutive item lines of the same ordered-ness are one block).
        if _UL_RE.match(stripped) or _OL_RE.match(stripped):
            start = i
            while i < n and lines[i].strip() and (_UL_RE.match(lines[i].strip()) or _OL_RE.match(lines[i].strip())):
                i += 1
            blocks.append(Block("list", start, i, "\n".join(lines[start:i])))
            continue

        # Blockquote (consecutive '>' lines).
        if stripped.startswith(">"):
            start = i
            while i < n and lines[i].strip().startswith(">"):
                i += 1
            blocks.append(Block("blockquote", start, i, "\n".join(lines[start:i])))
            continue

        # Raw HTML block (e.g. the Sources Cited <ol>) — passthrough until blank.
        if stripped.startswith("<"):
            start = i
            while i < n and lines[i].strip():
                i += 1
            blocks.append(Block("html", start, i, "\n".join(lines[start:i])))
            continue

        # Paragraph (consecutive plain-text lines until a blank or a new block).
        start = i
        para: list[str] = []
        while i < n:
            s = lines[i].strip()
            if not s:
                break
            if (
                _HEADING_RE.match(s) or _HR_RE.match(s) or _UL_RE.match(s)
                or _OL_RE.match(s) or s.startswith(">") or s.startswith("<")
                or _is_table_start(lines, i)
            ):
                break
            para.append(s)
            i += 1
        blocks.append(Block("paragraph", start, i, "\n".join(lines[start:i]),
                            heading_text=None))
    return blocks


def assign_ids(blocks: list[Block]) -> list[Block]:
    """Stamp stable IDs on heading + paragraph blocks in document order.

    H2 → section-NNN, H3+ → subsection-NNN, paragraph → paragraph-NNN. Lists,
    tables, blockquotes, HR and raw-HTML blocks get no ID (never anchor targets).
    Mutates + returns the same blocks (sequential, zero-padded to 3)."""
    sec = sub = para = 0
    for b in blocks:
        if b.kind == "heading":
            if (b.level or 2) <= 2:
                sec += 1
                b.id = f"section-{sec:03d}"
            else:
                sub += 1
                b.id = f"subsection-{sub:03d}"
        elif b.kind == "paragraph":
            para += 1
            b.id = f"paragraph-{para:03d}"
    return blocks


def render_html_with_ids(blocks: list[Block]) -> str:
    """The ID-bearing HTML fragment sent to the media planner. Headings +
    paragraphs carry their assigned `id`; other blocks render without one."""
    from services.markdown_html import _parse_blocks, _render_block_html

    out: list[str] = []
    for b in blocks:
        if b.kind == "heading" and b.id:
            lvl = b.level or 2
            m = _HEADING_RE.match(b.text.strip())
            inner = _inline(m.group(2).strip()) if m else _inline(b.heading_text or "")
            out.append(f'<h{lvl} id="{b.id}">{inner}</h{lvl}>')
        elif b.kind == "paragraph" and b.id:
            inner = _inline(" ".join(line.strip() for line in b.text.split("\n")).strip())
            out.append(f'<p id="{b.id}">{inner}</p>')
        elif b.kind == "html":
            # Already-valid HTML from our own pipeline (e.g. the Sources Cited
            # <ol>) — pass through verbatim so the planner sees real markup, not
            # an entity-escaped copy.
            out.append(b.text)
        else:
            # Reuse the shared renderer for lists/tables/blockquote/hr.
            rendered = "\n".join(_render_block_html(x) for x in _parse_blocks(b.text))
            out.append(rendered or b.text)
    return "\n".join(p for p in out if p)


@dataclass
class IdIndex:
    """The authoritative index of valid IDs for validating model placements."""

    anchor_ids: set[str] = field(default_factory=set)       # all heading + paragraph ids
    section_ids: set[str] = field(default_factory=set)      # heading ids only
    id_to_index: dict[str, int] = field(default_factory=dict)   # id → block position
    paragraph_section: dict[str, str] = field(default_factory=dict)  # paragraph id → enclosing heading id


def build_id_index(blocks: list[Block]) -> IdIndex:
    """Valid IDs + paragraph→enclosing-section containment (nearest preceding
    heading of level ≤ the paragraph's section). Used to reject any placement
    whose anchor_id/section_id isn't real."""
    idx = IdIndex()
    current_section: str | None = None
    for pos, b in enumerate(blocks):
        if b.id:
            idx.anchor_ids.add(b.id)
            idx.id_to_index[b.id] = pos
        if b.kind == "heading" and b.id:
            idx.section_ids.add(b.id)
            current_section = b.id
        elif b.kind == "paragraph" and b.id and current_section:
            idx.paragraph_section[b.id] = current_section
    return idx


def _excerpt_occurrence_index(markdown: str, excerpt: str, occurrence: int) -> int | None:
    """Char offset (into the RAW markdown) of the Nth (1-based) occurrence of
    `excerpt`, tolerating whitespace differences — the plan copies excerpts from
    a whitespace-normalized view, while the raw paragraph may wrap across lines.
    Matching runs on the raw text with a whitespace-flexible pattern, so the
    returned offset is always valid for line mapping. None when absent."""
    tokens = [re.escape(t) for t in (excerpt or "").split()]
    if not tokens:
        return None
    pattern = re.compile(r"\s+".join(tokens))
    want = max(1, int(occurrence or 1))
    for n, m in enumerate(pattern.finditer(markdown), start=1):
        if n == want:
            return m.start()
    return None


def resolve_placement(
    placement: dict, blocks: list[Block], idx: IdIndex, markdown: str
) -> int | None:
    """Resolve a placement to a target block index, in the app's strict order:
    anchor_id → section_id → fallback_excerpt. Returns None when none resolve
    (the caller skips insertion and logs — never a fuzzy/nearby guess)."""
    anchor_id = (placement.get("anchor_id") or "").strip()
    if anchor_id and anchor_id in idx.id_to_index:
        return idx.id_to_index[anchor_id]

    section_id = (placement.get("section_id") or "").strip()
    if section_id and section_id in idx.id_to_index:
        # Insert after the last paragraph of the section (not right after the
        # heading) unless the plan explicitly anchored on the heading.
        sec_pos = idx.id_to_index[section_id]
        last = sec_pos
        for pos in range(sec_pos + 1, len(blocks)):
            if blocks[pos].kind == "heading":
                break
            if blocks[pos].kind == "paragraph":
                last = pos
        return last

    excerpt = (placement.get("fallback_excerpt") or "").strip()
    if excerpt:
        try:
            occ = int(placement.get("fallback_excerpt_occurrence") or 1)
        except (TypeError, ValueError):
            occ = 1
        char_off = _excerpt_occurrence_index(markdown, excerpt, occ)
        if char_off is not None:
            # Map the char offset to the block whose span contains that line.
            line_no = markdown[:char_off].count("\n")
            for pos, b in enumerate(blocks):
                if b.start <= line_no < b.end:
                    return pos
    return None


def figure_markdown(*, media_id: str, src: str, alt: str, caption: str | None, css_class: str) -> str:
    """A raw-HTML `<figure>` block (Astro renders HTML inside Markdown). Carries
    `data-media-id` for idempotent re-insertion. Alt/caption are attribute- and
    text-escaped by the caller-facing `_esc`."""
    cap = f"\n  <figcaption>{_esc(caption)}</figcaption>" if caption else ""
    return (
        f'<figure class="{css_class}" data-media-id="{_esc_attr(media_id)}">\n'
        f'  <img src="{_esc_attr(src)}" alt="{_esc_attr(alt)}" loading="lazy" />{cap}\n'
        f'</figure>'
    )


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_attr(text: str) -> str:
    return _esc(text).replace('"', "&quot;")


@dataclass
class ResolvedFigure:
    block_index: int
    position: str    # 'after' | 'before'
    media_id: str
    markup: str


def insert_figures(markdown: str, blocks: list[Block], figures: list[ResolvedFigure]) -> str:
    """Splice `<figure>` blocks into the Markdown at resolved block boundaries,
    preserving the original text verbatim. Idempotent: a figure whose
    `data-media-id` is already present is skipped (supports retries/republish).
    Figures are applied bottom-up so earlier line offsets stay valid."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # Idempotency: drop figures already present by data-media-id.
    todo = [f for f in figures if f"data-media-id=\"{_esc_attr(f.media_id)}\"" not in markdown]
    # Insert from the highest line index down so splices don't shift later ones.
    # Ties (two figures at the same block) break on the ORIGINAL list index,
    # reversed: inserting at the same line index stacks later-inserted text
    # first, so processing the later figure first preserves document order.
    for _, fig in sorted(
        enumerate(todo),
        key=lambda t: (blocks[t[1].block_index].end, t[0]),
        reverse=True,
    ):
        b = blocks[fig.block_index]
        at = b.start if fig.position == "before" else b.end
        block_text = ["", fig.markup, ""]
        lines[at:at] = block_text
    return "\n".join(lines)


def section_text(blocks: list[Block], pos: int) -> str:
    """The text of the section containing block `pos` (nearest preceding heading
    through the next heading) — grounding for a replacement image. Pure."""
    if not blocks:
        return ""
    pos = max(0, min(pos, len(blocks) - 1))
    start = pos
    while start > 0 and blocks[start].kind != "heading":
        start -= 1
    parts: list[str] = []
    if blocks[start].kind == "heading" and blocks[start].heading_text:
        parts.append(blocks[start].heading_text)
    for b in blocks[start + 1:]:
        if b.kind == "heading":
            break
        if b.kind in ("paragraph", "list"):
            parts.append(b.text)
    return re.sub(r"\s+", " ", "\n".join(p for p in parts if p)).strip()[:1800]


def unique_webp(stem: str, existing_paths, base: str, slug: str) -> str:
    """A `.webp` filename derived from `stem`, deduped against already-committed
    repo paths (`<base>/<slug>/<name>`). Pure."""
    stem = (stem or "image")[:60].strip("-") or "image"
    fn = f"{stem}.webp"
    n = 2
    while f"{base}/{slug}/{fn}" in existing_paths:
        fn = f"{stem}-{n}.webp"
        n += 1
    return fn


def word_count(markdown: str) -> int:
    """Readable-word count over the article body (app-owned, never trusted from
    the model). Strips HTML tags + Markdown marks first."""
    text = re.sub(r"<[^>]+>", " ", markdown or "")
    text = re.sub(r"[*_`#>|]", " ", text)
    return len(_WORD_RE.findall(text))


def inline_budget(words: int) -> int:
    """floor(words / 1000), capped at 2 — the spec's inline-visual allowance."""
    return max(0, min(2, words // 1000))
