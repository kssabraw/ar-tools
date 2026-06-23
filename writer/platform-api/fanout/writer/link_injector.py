"""Deterministic internal-link injection (M15 slice 1, handoff §9.5).

The Writer PRD (§1.3) explicitly excludes internal linking; M6 already computed the link
graph (`site_architecture.architecture_json`: up / lateral / down, no orphans / no
dangling). This module injects those links into the finished article — same philosophy as
M6 ("the LLM writes the prose, code wires the graph"), same contract pattern as `{{cit_N}}`.

Runs after the Writer returns, BEFORE serialization (`serialize.py` is pure over
`article[]`, so the job re-serializes after injection). Pure — targets/URLs are resolved by
the caller (the activation slice) from the architecture graph + slugs + `site_base_url`.

Rules (§9.5):
- For each target, wrap the FIRST prose occurrence of one of its anchor phrases (primary
  keyword → supporting keywords → title) as `[match](absolute-url)`; one link per target;
  never inside a heading, an existing link, or a code span.
- A **pillar** renders an "In This Guide" list of its children instead of inlining many.
- **Fallback:** any unmatched target drops into a "Related Articles" list before the
  conclusion — so the M6 link contract holds regardless of the prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import ArticleItem

# Spans that must never receive an injected link: an existing [text](url) link or `code`.
_LINK_OR_CODE = re.compile(r"\[[^\]]*\]\([^)]*\)|`[^`]*`")
_BODY_TYPES = ("content", "intro", "h1-enrichment")   # prose items eligible for inline links


@dataclass
class LinkTarget:
    url: str                                  # absolute target URL
    anchors: list[str] = field(default_factory=list)   # priority-ordered phrases to match
    title: str = ""                           # display title (Related / In-this-guide list)


@dataclass
class InjectionResult:
    article: list[ArticleItem]
    linked: list[str] = field(default_factory=list)        # urls linked inline / in-guide
    related: list[LinkTarget] = field(default_factory=list)  # unmatched -> Related list


def _wrap_first(text: str, anchor: str, url: str) -> tuple[str, bool]:
    """Wrap the first whole-phrase occurrence of `anchor` in `text` as a markdown link,
    skipping any existing link/code spans. Returns `(new_text, wrapped?)`."""
    if not anchor.strip():
        return text, False
    pat = re.compile(rf"(?<!\w){re.escape(anchor.strip())}(?!\w)", re.IGNORECASE)

    def sub_once(seg: str) -> tuple[str, bool]:
        m = pat.search(seg)
        if not m:
            return seg, False
        s, e = m.span()
        return f"{seg[:s]}[{seg[s:e]}]({url}){seg[e:]}", True

    out: list[str] = []
    pos = 0
    wrapped = False
    for m in _LINK_OR_CODE.finditer(text):
        seg = text[pos:m.start()]
        if not wrapped:
            seg, wrapped = sub_once(seg)
        out.append(seg)
        out.append(m.group(0))          # keep the existing link/code verbatim
        pos = m.end()
    tail = text[pos:]
    if not wrapped:
        tail, wrapped = sub_once(tail)
    out.append(tail)
    return "".join(out), wrapped


def _bullet_list(targets: list[LinkTarget]) -> str:
    return "\n".join(f"- [{t.title or t.url}]({t.url})" for t in targets)


def inject_links(
    article: list[ArticleItem], targets: list[LinkTarget], *, is_pillar: bool = False,
) -> InjectionResult:
    """Inject internal links into a copy of `article` (input not mutated)."""
    items = [it.model_copy(deep=True) for it in article]
    linked: set[str] = set()

    # A pillar links DOWN to all its children via an "In This Guide" list (don't inline
    # dozens of links); supporting articles inline up/lateral links into the prose.
    if is_pillar:
        if targets:
            guide = ArticleItem(level="H2", type="content", heading="In This Guide")
            body = ArticleItem(level="none", type="content", body=_bullet_list(targets))
            insert_at = next((i for i, it in enumerate(items)
                              if it.type in ("intro", "key-takeaways")), 1) + 1
            items[insert_at:insert_at] = [guide, body]
            linked = {t.url for t in targets}
        return _renumber(InjectionResult(article=items, linked=list(linked), related=[]))

    for target in targets:
        if target.url in linked:
            continue
        matched = False
        for anchor in [*target.anchors, target.title]:
            for it in items:
                if it.level != "none" or it.type not in _BODY_TYPES:
                    continue
                new_body, ok = _wrap_first(it.body, anchor, target.url)
                if ok:
                    it.body, matched = new_body, True
                    linked.add(target.url)
                    break
            if matched:
                break

    related = [t for t in targets if t.url not in linked]
    if related:
        rel_h2 = ArticleItem(level="H2", type="content", heading="Related Articles")
        rel_body = ArticleItem(level="none", type="content", body=_bullet_list(related))
        concl = next((i for i, it in enumerate(items) if it.type == "conclusion"), None)
        at = concl if concl is not None else len(items)
        items[at:at] = [rel_h2, rel_body]

    return _renumber(InjectionResult(article=items, linked=list(linked), related=related))


def _renumber(result: InjectionResult) -> InjectionResult:
    for i, it in enumerate(result.article, start=1):
        it.order = i
    return result
