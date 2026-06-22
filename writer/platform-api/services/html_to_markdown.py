"""Minimal HTML → Markdown converter (stdlib only).

Scoped to the clean <article> markup the Local SEO generator emits (headings,
paragraphs, lists, links, bold/italic, blockquote, tables, hr) so a generated
page can be published to a Google Doc via the same Apps Script webhook the blog
writer uses (which expects Markdown `content`). Not a general-purpose converter —
unknown tags degrade to their text content.
"""

from __future__ import annotations

from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "section", "article", "header", "ul", "ol", "blockquote", "table", "tr"}
_SKIP_TAGS = {"script", "style", "head", "title", "noscript"}


class _MarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []      # finished block strings
        self.buf: list[str] = []        # current inline buffer
        self.list_stack: list[dict] = []  # [{type: ul|ol, n: int}]
        self.list_lines: list[str] = []   # accumulated item lines for the current top-level list
        self.skip_depth = 0
        self.heading: str | None = None
        self.in_blockquote = False
        self.href: str | None = None
        # table state
        self.in_table = False
        self.rows: list[list[str]] = []
        self.cur_row: list[str] | None = None
        self.cur_cell: list[str] | None = None
        self.header_row = False
        self.had_header = False

    # ── helpers ───────────────────────────────────────────────────────────
    def _flush_block(self, prefix: str = "") -> None:
        text = "".join(self.buf).strip()
        self.buf = []
        if text:
            self.parts.append(prefix + text)

    def _emit(self, s: str) -> None:
        if self.cur_cell is not None:
            self.cur_cell.append(s)
        else:
            self.buf.append(s)

    # ── tags ──────────────────────────────────────────────────────────────
    def handle_starttag(self, tag: str, attrs):
        if tag in _SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush_block()
            self.heading = "#" * int(tag[1]) + " "
        elif tag == "p":
            self._flush_block()
        elif tag == "br":
            self._emit("  \n")
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "a":
            self.href = dict(attrs).get("href")
            self._emit("[")
        elif tag == "ul":
            self._flush_block()
            self.list_stack.append({"type": "ul", "n": 0})
        elif tag == "ol":
            self._flush_block()
            self.list_stack.append({"type": "ol", "n": 0})
        elif tag == "li":
            self._flush_block()
        elif tag == "blockquote":
            self._flush_block()
            self.in_blockquote = True
        elif tag == "hr":
            self._flush_block()
            self.parts.append("---")
        elif tag == "table":
            self._flush_block()
            self.in_table = True
            self.rows = []
            self.had_header = False
        elif tag == "tr" and self.in_table:
            self.cur_row = []
            self.header_row = False
        elif tag in ("td", "th") and self.in_table:
            self.cur_cell = []
            if tag == "th":
                self.header_row = True

    def handle_endtag(self, tag: str):
        if tag in _SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush_block(self.heading or "")
            self.heading = None
        elif tag == "p":
            self._flush_block("> " if self.in_blockquote else "")
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "a":
            self._emit(f"]({self.href or ''})")
            self.href = None
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            if not self.list_stack and self.list_lines:
                # Emit the whole (possibly nested) list as ONE block so items stay
                # on consecutive lines — blank lines between items break the list.
                self.parts.append("\n".join(self.list_lines))
                self.list_lines = []
        elif tag == "li":
            text = "".join(self.buf).strip()
            self.buf = []
            if text:
                depth = max(0, len(self.list_stack) - 1)
                indent = "  " * depth
                top = self.list_stack[-1] if self.list_stack else {"type": "ul", "n": 0}
                if top["type"] == "ol":
                    top["n"] += 1
                    self.list_lines.append(f"{indent}{top['n']}. {text}")
                else:
                    self.list_lines.append(f"{indent}- {text}")
        elif tag == "blockquote":
            self.in_blockquote = False
        elif tag in ("td", "th") and self.in_table:
            cell = "".join(self.cur_cell or []).strip().replace("\n", " ").replace("|", "\\|")
            if self.cur_row is not None:
                self.cur_row.append(cell)
            self.cur_cell = None
        elif tag == "tr" and self.in_table:
            if self.cur_row:
                self.rows.append(self.cur_row)
                if self.header_row and not self.had_header:
                    self.rows.append(["---"] * len(self.cur_row))  # md header separator
                    self.had_header = True
            self.cur_row = None
        elif tag == "table":
            self._render_table()
            self.in_table = False

    def handle_data(self, data: str):
        if self.skip_depth or not data:
            return
        # Collapse internal whitespace but keep single spaces between inline runs.
        text = " ".join(data.split())
        if not text:
            return
        # preserve a leading/trailing space if the original had one (inline flow)
        if data[:1].isspace():
            text = " " + text
        if data[-1:].isspace():
            text = text + " "
        self._emit(text)

    def _render_table(self) -> None:
        if not self.rows:
            return
        # One block, rows on consecutive lines — blank lines break a markdown table.
        lines = ["| " + " | ".join(row) + " |" for row in self.rows]
        self.parts.append("\n".join(lines))

    def result(self) -> str:
        self._flush_block()
        # Join blocks with blank lines; collapse 3+ newlines to 2.
        md = "\n\n".join(p for p in self.parts if p is not None)
        while "\n\n\n" in md:
            md = md.replace("\n\n\n", "\n\n")
        return md.strip()


def html_to_markdown(html: str) -> str:
    """Convert the generator's article HTML to Markdown for Google Docs publish."""
    if not html or not html.strip():
        return ""
    parser = _MarkdownParser()
    parser.feed(html)
    parser.close()
    return parser.result()
