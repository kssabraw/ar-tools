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


def markdown_to_html(markdown: str) -> str:
    """Convert a Markdown string to an HTML fragment suitable for WP `content`."""
    if not markdown:
        return ""

    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    html: list[str] = []
    paragraph: list[str] = []
    list_type: str | None = None  # 'ul' | 'ol' | None

    def flush_paragraph() -> None:
        if paragraph:
            html.append(f"<p>{_inline(' '.join(paragraph).strip())}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            html.append(f"</{list_type}>")
            list_type = None

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if not stripped:
            flush_paragraph()
            close_list()
            i += 1
            continue

        # Tables span multiple lines (header + delimiter + rows), so they're
        # detected with look-ahead and consumed as a block.
        if _is_table_start(lines, i):
            flush_paragraph()
            close_list()
            table_html, i = _render_table(lines, i)
            html.append(table_html)
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            html.append(f"<h{level}>{_inline(heading.group(2).strip())}</h{level}>")
            i += 1
            continue

        if _HR_RE.match(stripped):
            flush_paragraph()
            close_list()
            html.append("<hr />")
            i += 1
            continue

        ul = _UL_RE.match(stripped)
        ol = _OL_RE.match(stripped)
        if ul or ol:
            flush_paragraph()
            want = "ul" if ul else "ol"
            if list_type != want:
                close_list()
                html.append(f"<{want}>")
                list_type = want
            item = (ul or ol).group(1).strip()
            html.append(f"<li>{_inline(item)}</li>")
            i += 1
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            close_list()
            html.append(f"<blockquote><p>{_inline(stripped[1:].strip())}</p></blockquote>")
            i += 1
            continue

        # Plain text line — accumulate into the current paragraph.
        close_list()
        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    close_list()
    return "\n".join(html)
