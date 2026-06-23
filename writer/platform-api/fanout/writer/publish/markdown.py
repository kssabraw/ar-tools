"""Article → Astro-content Markdown (pure). Builds a Markdown file with YAML frontmatter for
an Astro content collection: the leading H1 is lifted into the `title` so the layout renders
it (no doubled heading), and the body keeps the writer's injected internal links. Each repo
designs its own layout/schema; we emit a portable, minimal frontmatter set."""

from __future__ import annotations

import re
from datetime import date


def _yaml_quote(value: str) -> str:
    """Double-quote + escape a scalar for YAML frontmatter."""
    return '"' + (value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _split_title(markdown: str) -> tuple[str | None, str]:
    """Pull a leading `# Title` off the body (so it isn't rendered twice under the layout).
    Returns (title_or_None, body_without_that_h1). Only strips a single leading H1."""
    lines = (markdown or "").splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        m = re.match(r"^#\s+(.+?)\s*$", lines[i])
        if m:
            rest = lines[i + 1:]
            while rest and not rest[0].strip():     # drop the blank line after the H1
                rest = rest[1:]
            return m.group(1).strip(), "\n".join(rest)
    return None, markdown


def _derive_description(body: str, fallback: str = "") -> str:
    """First real paragraph of prose (skipping headings / lists / blank lines), trimmed to
    ~160 chars on a word boundary — a reasonable meta description default."""
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-", "*", ">", "|", "`")):
            continue
        text = re.sub(r"[*_`#\[\]()]", "", line)            # strip inline md marks
        text = re.sub(r"\]\([^)]*\)", "", text)
        if len(text) <= 160:
            return text
        cut = text[:160].rsplit(" ", 1)[0]
        return cut + "…"
    return fallback


def build_astro_markdown(
    *, article_markdown: str, title: str, slug: str, silo: str,
    description: str | None = None, pub_date: date | None = None, extra: dict | None = None,
) -> str:
    """Astro content-collection Markdown: YAML frontmatter (title/description/pubDate/slug/silo/
    draft) + the article body (leading H1 lifted into the title). `extra` adds/overrides
    frontmatter scalars for a repo whose schema wants more fields."""
    h1, body = _split_title(article_markdown)
    final_title = title or h1 or slug
    desc = description or _derive_description(body, fallback=final_title)
    when = (pub_date or date.today()).isoformat()

    fm: dict[str, str] = {
        "title": _yaml_quote(final_title),
        "description": _yaml_quote(desc),
        "pubDate": when,
        "slug": _yaml_quote(slug),
        "silo": _yaml_quote(silo),
        "draft": "false",
    }
    for k, v in (extra or {}).items():
        fm[k] = _yaml_quote(v) if isinstance(v, str) else str(v)

    lines = ["---", *(f"{k}: {v}" for k, v in fm.items()), "---", "", body.strip(), ""]
    return "\n".join(lines)
