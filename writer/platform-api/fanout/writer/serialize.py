"""Markdown + HTML serialization (M14 slice 3, PRD §5.19) — pure, deterministic.

Functions of `(article[], citations)` only; inputs are never mutated. In our
`no_citations` path there are no `{{cit_N}}` markers and no Sources section, but the
marker substitution + unknown-id fallback are implemented per §5.19.5 for completeness.
"""

from __future__ import annotations

import html
import re

from .models import ArticleItem
from .validators import CITATION_MARKER_RE

_MARKER_N = re.compile(r"\{\{cit_0*([0-9]+)\}\}")


def _md_markers(text: str, known: set[int]) -> str:
    def repl(m: re.Match) -> str:
        n = int(m.group(1))
        return f"[^{n}]" if n in known else m.group(0)   # unknown -> verbatim (§5.19.5)
    return _MARKER_N.sub(repl, text)


def _html_markers(text: str, known: set[int]) -> str:
    def repl(m: re.Match) -> str:
        n = int(m.group(1))
        if n in known:
            return f'<sup><a href="#cite-{n}">{n}</a></sup>'
        return f"<span>{html.escape(m.group(0))}</span>"   # unknown -> span (§5.19.5)
    return _MARKER_N.sub(repl, text)


def _known_ids(citations: list[dict] | None) -> set[int]:
    ids: set[int] = set()
    for c in citations or []:
        m = re.match(r"cit_0*([0-9]+)$", str(c.get("citation_id", "")))
        if m:
            ids.add(int(m.group(1)))
    return ids


def to_markdown(article: list[ArticleItem], citations: list[dict] | None = None) -> str:
    """GFM serialization (§5.19.2). `[^N]` footnotes + a Sources section only when
    citations are present (never in our no_citations path)."""
    if not article:
        return ""
    known = _known_ids(citations)
    lines: list[str] = []
    for it in article:
        body = _md_markers(it.body or "", known)
        if it.level == "H1":
            lines.append(f"# {it.heading or body}\n")
        elif it.level == "H2":
            lines.append(f"## {it.heading or body}\n")
        elif it.level == "H3":
            lines.append(f"### {it.heading or body}\n")
        else:
            if it.heading:    # e.g. Key Takeaways block carries a heading + bullet body
                lines.append(f"## {it.heading}\n")
            if body:
                lines.append(f"{body}\n")
    if known:
        lines.append("## Sources\n")
        for c in citations or []:
            m = re.match(r"cit_0*([0-9]+)$", str(c.get("citation_id", "")))
            if m:
                lines.append(f"[^{int(m.group(1))}]: {c.get('title', '')} — {c.get('url', '')}")
    return "\n".join(lines).rstrip() + "\n"


def to_html(article: list[ArticleItem], citations: list[dict] | None = None) -> str:
    """Semantic HTML5 fragment (§5.19.3). Text is HTML-escaped; markers substituted after."""
    if not article:
        return ""
    known = _known_ids(citations)
    lines: list[str] = []
    for it in article:
        if it.level == "H1":
            lines.append(f"<h1>{html.escape(it.heading or it.body)}</h1>")
        elif it.level == "H2":
            lines.append(f"<h2>{html.escape(it.heading or it.body)}</h2>")
        elif it.level == "H3":
            lines.append(f"<h3>{html.escape(it.heading or it.body)}</h3>")
        else:
            if it.heading:
                lines.append(f"<h2>{html.escape(it.heading)}</h2>")
            if it.body:
                lines.append(f"<p>{_html_markers(html.escape(it.body), known)}</p>")
    if known:
        lines.append("<h2>Sources</h2>")
        items = []
        for c in citations or []:
            m = re.match(r"cit_0*([0-9]+)$", str(c.get("citation_id", "")))
            if m:
                items.append(
                    f'<li id="cite-{int(m.group(1))}">'
                    f'<a href="{html.escape(str(c.get("url", "")))}">'
                    f'{html.escape(str(c.get("title", "")))}</a></li>'
                )
        lines.append("<ol>" + "".join(items) + "</ol>")
    return "\n".join(lines)


def plain_text(article: list[ArticleItem]) -> str:
    """Round-trip helper (§5.19.4): the recoverable plain-text body, markers stripped."""
    parts = [CITATION_MARKER_RE.sub("", (it.heading or it.body or "")).strip() for it in article]
    return "\n".join(p for p in parts if p)
