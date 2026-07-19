"""Minimal Markdown → HTML converter for WordPress publishing.

The Blog Writer's article sections are Markdown prose; the WordPress REST API's
`content` field expects HTML (it does not render Markdown). Rather than pull in a
new dependency, this converts the constructs our generation pipeline actually
emits — ATX headings, paragraphs, unordered/ordered lists, blockquotes,
horizontal rules, and inline bold/italic/links/code. Anything unrecognized is
passed through as paragraph text (HTML-escaped), so unexpected input degrades to
readable prose rather than breaking.

Service/location pages and Local SEO pages already carry their own HTML
rendering, so this is only used for the blog path.
"""

from __future__ import annotations

import re

# Inline patterns, applied in order. Images before links (they share the
# `[...](...)` shape), links before the emphasis passes so their bracketed text
# isn't mangled; code spans are extracted before emphasis so `**literal**`
# inside backticks survives.
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((https?://[^\s)]+)\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<![\*\w])\*([^*\n]+)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+)`")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_UL_RE = re.compile(r"^[-*+]\s+(.*)$")
_OL_RE = re.compile(r"^\d+[.)]\s+(.*)$")
_HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
# A GitHub-flavored-Markdown table delimiter row, e.g. "| --- | :--: | --: |".
# Requires at least two cells (one internal pipe) so a lone "---" stays an <hr>.
_TABLE_DELIM_RE = re.compile(r"^\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?$")
# A line that opens a block-level HTML element we pass through verbatim (used by
# the illustration layer, which interleaves <figure>/<svg> blocks into the body).
_RAW_BLOCK_RE = re.compile(r"^<(figure|svg|div|img|table)\b", re.IGNORECASE)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _inline(text: str) -> str:
    """Render inline Markdown to HTML on a single line of already-trimmed text."""
    # Pull code spans out first so their contents are escaped but not emphasised.
    placeholders: list[str] = []

    def _stash_code(match: re.Match) -> str:
        placeholders.append(f"<code>{_escape(match.group(1))}</code>")
        return f"\x00{len(placeholders) - 1}\x00"

    text = _CODE_RE.sub(_stash_code, text)
    text = _escape(text)
    text = _IMAGE_RE.sub(
        lambda m: f'<img src="{m.group(2)}" alt="{m.group(1)}" />',
        text,
    )
    text = _LINK_RE.sub(
        lambda m: f'<a href="{m.group(2)}" rel="noopener" target="_blank">{m.group(1)}</a>',
        text,
    )
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    # Restore code spans.
    text = re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text)
    return text


def _split_table_row(line: str) -> list[str]:
    """Split a Markdown table row into trimmed cells, dropping the outer pipes."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _table_alignments(delim_line: str) -> list[str | None]:
    """Per-column text-align from a delimiter row's colons (:--- / :--: / ---:)."""
    aligns: list[str | None] = []
    for cell in _split_table_row(delim_line):
        left, right = cell.startswith(":"), cell.endswith(":")
        aligns.append("center" if left and right else "right" if right else "left" if left else None)
    return aligns


def _render_table(lines: list[str], start: int) -> tuple[str, int]:
    """Render a GFM table starting at `start` (header row; start+1 is the
    delimiter). Returns (html, index_after_table)."""
    header = _split_table_row(lines[start])
    aligns = _table_alignments(lines[start + 1])
    cols = len(header)

    def cell(tag: str, raw: str, idx: int) -> str:
        align = aligns[idx] if idx < len(aligns) else None
        style = f' style="text-align:{align}"' if align else ""
        return f"<{tag}{style}>{_inline(raw)}</{tag}>"

    parts = ["<table>", "<thead>", "<tr>"]
    parts += [cell("th", h, i) for i, h in enumerate(header)]
    parts += ["</tr>", "</thead>", "<tbody>"]

    j = start + 2
    while j < len(lines) and lines[j].strip() and "|" in lines[j]:
        row = _split_table_row(lines[j])
        parts.append("<tr>")
        parts += [cell("td", row[i] if i < len(row) else "", i) for i in range(cols)]
        parts.append("</tr>")
        j += 1

    parts += ["</tbody>", "</table>"]
    return "\n".join(parts), j


def _is_table_start(lines: list[str], i: int) -> bool:
    """A table is a row line immediately followed by a delimiter row."""
    return (
        i + 1 < len(lines)
        and "|" in lines[i]
        and bool(_TABLE_DELIM_RE.match(lines[i + 1].strip()))
    )


def _parse_blocks(markdown: str) -> list[dict]:
    """Parse Markdown into an ordered list of block dicts. Inline formatting is
    already rendered to HTML in each block's text. The two renderers below turn
    these into either semantic HTML (Google Docs) or Gutenberg block markup
    (WordPress) without re-parsing.

    Block shapes: {type: heading, level, html} | {type: paragraph, html} |
    {type: list, ordered, items[]} | {type: blockquote, html} | {type: hr} |
    {type: table, html} (inner <table>…</table>, identical for both renderers).
    """
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[dict] = []
    paragraph: list[str] = []
    cur_list: dict | None = None

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append({"type": "paragraph", "html": _inline(" ".join(paragraph).strip())})
            paragraph.clear()

    def close_list() -> None:
        nonlocal cur_list
        if cur_list:
            blocks.append(cur_list)
            cur_list = None

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if not stripped:
            flush_paragraph()
            close_list()
            i += 1
            continue

        # Raw block-level HTML (e.g. an interleaved <figure>/<svg> illustration):
        # pass the line through verbatim rather than escaping it as prose.
        if _RAW_BLOCK_RE.match(stripped):
            flush_paragraph()
            close_list()
            blocks.append({"type": "raw", "html": lines[i].rstrip()})
            i += 1
            continue

        # Tables span multiple lines (header + delimiter + rows); detected with
        # look-ahead and consumed as a block.
        if _is_table_start(lines, i):
            flush_paragraph()
            close_list()
            table_html, i = _render_table(lines, i)
            blocks.append({"type": "table", "html": table_html})
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_paragraph()
            close_list()
            blocks.append({
                "type": "heading",
                "level": len(heading.group(1)),
                "html": _inline(heading.group(2).strip()),
            })
            i += 1
            continue

        if _HR_RE.match(stripped):
            flush_paragraph()
            close_list()
            blocks.append({"type": "hr"})
            i += 1
            continue

        ul = _UL_RE.match(stripped)
        ol = _OL_RE.match(stripped)
        if ul or ol:
            flush_paragraph()
            ordered = bool(ol)
            if cur_list is None or cur_list["ordered"] != ordered:
                close_list()
                cur_list = {"type": "list", "ordered": ordered, "items": []}
            cur_list["items"].append(_inline((ul or ol).group(1).strip()))
            i += 1
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            close_list()
            blocks.append({"type": "blockquote", "html": _inline(stripped[1:].strip())})
            i += 1
            continue

        # Plain text line — accumulate into the current paragraph.
        close_list()
        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    close_list()
    return blocks


def _render_block_html(b: dict) -> str:
    t = b["type"]
    if t == "heading":
        return f'<h{b["level"]}>{b["html"]}</h{b["level"]}>'
    if t == "paragraph":
        return f'<p>{b["html"]}</p>'
    if t == "hr":
        return "<hr />"
    if t == "blockquote":
        return f'<blockquote><p>{b["html"]}</p></blockquote>'
    if t == "table":
        return b["html"]
    if t == "raw":
        return b["html"]
    if t == "list":
        tag = "ol" if b["ordered"] else "ul"
        items = "\n".join(f"<li>{it}</li>" for it in b["items"])
        return f"<{tag}>\n{items}\n</{tag}>"
    return ""


def _render_block_gutenberg(b: dict) -> str:
    t = b["type"]
    if t == "heading":
        level = b["level"]
        # The Heading block defaults to <h2>; other levels carry a level attr.
        attr = "" if level == 2 else f' {{"level":{level}}}'
        return f'<!-- wp:heading{attr} -->\n<h{level}>{b["html"]}</h{level}>\n<!-- /wp:heading -->'
    if t == "paragraph":
        return f'<!-- wp:paragraph -->\n<p>{b["html"]}</p>\n<!-- /wp:paragraph -->'
    if t == "hr":
        return '<!-- wp:separator -->\n<hr class="wp-block-separator has-alpha-channel-opacity"/>\n<!-- /wp:separator -->'
    if t == "blockquote":
        return (
            '<!-- wp:quote -->\n'
            f'<blockquote class="wp-block-quote"><p>{b["html"]}</p></blockquote>\n'
            '<!-- /wp:quote -->'
        )
    if t == "table":
        return f'<!-- wp:table -->\n<figure class="wp-block-table">{b["html"]}</figure>\n<!-- /wp:table -->'
    if t == "raw":
        return f'<!-- wp:html -->\n{b["html"]}\n<!-- /wp:html -->'
    if t == "list":
        ordered = b["ordered"]
        tag = "ol" if ordered else "ul"
        attr = ' {"ordered":true}' if ordered else ""
        items = "\n".join(
            f"<!-- wp:list-item -->\n<li>{it}</li>\n<!-- /wp:list-item -->" for it in b["items"]
        )
        return f"<!-- wp:list{attr} -->\n<{tag}>\n{items}\n</{tag}>\n<!-- /wp:list -->"
    return ""


def markdown_to_html(markdown: str) -> str:
    """Convert Markdown to a semantic HTML fragment (headings, paragraphs, lists,
    tables, …). Used for the Google Docs path (the Apps Script imports it as a
    natively-formatted Doc) and as a fallback elsewhere."""
    if not markdown:
        return ""
    return "\n".join(_render_block_html(b) for b in _parse_blocks(markdown))


def markdown_to_gutenberg(markdown: str) -> str:
    """Convert Markdown to WordPress Gutenberg block markup (the same HTML wrapped
    in `<!-- wp:* -->` block delimiters) so a published post lands as native,
    individually-editable blocks rather than a single Classic/HTML block."""
    if not markdown:
        return ""
    return "\n\n".join(_render_block_gutenberg(b) for b in _parse_blocks(markdown))
