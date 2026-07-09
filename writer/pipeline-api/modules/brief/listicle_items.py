"""Step 11.6 - Listicle minimum ranked-item enforcement (Brief Generator).

A `ranked_items` (listicle) brief is supposed to present at least the intent
template's `min_h2_count` ranked H2s - one section per item (e.g. one per
product / vendor / tool). The core assembly pipeline selects ranked H2s from
the SERP / fanout heading pool and MMR-picks up to `max_h2_count`, but it never
PADS to reach `min_h2_count`. When the pool yields few ranked-shaped headings -
e.g. a "best X software" SERP whose per-tool headings ("Reveel", "Sifted", ...)
were dropped as bare entities by the relevance gate - the outline can land with
a single ranked item: a listicle in name only.

This pass runs AFTER `assemble_structure`, on the final `HeadingItem` list, so
the synthesized items don't have to survive the mid-pipeline transforms
(framing, authority-H2 displacement, the intent rewriter, parent-fit). When a
`ranked_items` outline has fewer than `min_h2_count` content H2s, it asks one
LLM call to NAME the real, well-known items the listicle should rank, appends
them as ranked H2 sections until the floor is met (capped at `max_h2_count`),
and renumbers the ranked items 1..N.

Honest-fallback by design: if the model can't name enough REAL items (or the
call fails), the outline is left short rather than padded with invented
entries - an honest 2-item listicle beats five fabricated products. This
mirrors the MMR philosophy (`mmr.py`: "DO NOT ... invent synthetic H2s"); the
escape hatch is listicle-only and grounded on a name-real-things-only prompt.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from titlecase import titlecase

from models.brief import HeadingItem

from .llm import claude_json

logger = logging.getLogger(__name__)


LLMJsonFn = Callable[..., Awaitable[Any]]

# Strips a leading list ordinal so a heading can be cleanly renumbered:
# "1. Foo" / "2) Foo" / "#3 Foo" / "4: Foo" -> "Foo". Deliberately does NOT
# strip a "Top N " prefix (that's a section label, not an item ordinal).
_LEADING_ORDINAL_RE = re.compile(r"^\s*#?\d+[\.\):]?\s+")

# FAQ block heading types - the ranked-item region ends where these begin.
_FAQ_TYPES = frozenset({"faq-header", "faq-question"})

# A listicle title may promise a count ("Top 10", "25 Best X", "10 Best X in
# 2026"). These locate that count so the ranked-item target and the title can
# be reconciled. `\d{1,3}` (1-99x) deliberately never matches a 4-digit year:
# "2026" has no word boundary between its inner digits, so `(\d{1,3})\b` can't
# grab a slice of it, and the leading/`top `/`best`-anchored contexts keep a
# year like "in 2026" from being read as a count.
_TITLE_COUNT_PATTERNS = [
    re.compile(r"^\s*(\d{1,3})\b"),                    # "10 Best X ..."
    re.compile(r"\btop\s+(\d{1,3})\b", re.IGNORECASE),   # "Top 10 ..."
    re.compile(r"\b(\d{1,3})\s+best\b", re.IGNORECASE),  # "the 10 best ..."
]


def _find_title_count(title: str):
    """Return the regex match locating the listicle count, or None."""
    text = title or ""
    for pat in _TITLE_COUNT_PATTERNS:
        m = pat.search(text)
        if m:
            return m
    return None


def extract_title_count(title: str) -> Optional[int]:
    """Return the count a listicle title promises ("Top 10" -> 10), or None.

    Never returns a 4-digit year (see `_TITLE_COUNT_PATTERNS`). Returns None
    for a zero or absent count.
    """
    m = _find_title_count(title)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def apply_title_count(title: str, count: int) -> str:
    """Rewrite the count token in a listicle title to `count` in place.

    Returns the title unchanged when it carries no count. Only the count
    token is replaced, so a year or other numbers in the title are untouched.
    """
    m = _find_title_count(title)
    if not m:
        return title
    start, end = m.start(1), m.end(1)
    return title[:start] + str(count) + title[end:]


@dataclass
class ListicleFillResult:
    """Outcome of `ensure_min_ranked_items` (for logging / observability)."""

    before_count: int = 0
    after_count: int = 0
    added: int = 0
    llm_called: bool = False
    llm_failed: bool = False
    fallback_short: bool = False  # LLM ran but couldn't name enough real items
    added_names: list[str] = field(default_factory=list)


def strip_leading_ordinal(text: str) -> str:
    """Remove a leading list ordinal ("1. ", "#3 ", "4) ") from a heading."""
    return _LEADING_ORDINAL_RE.sub("", text or "", count=1).strip()


def _content_h2_positions(structure: list[HeadingItem]) -> list[int]:
    return [
        i for i, h in enumerate(structure)
        if h.level == "H2" and h.type == "content"
    ]


def renumber_ranked_items(structure: list[HeadingItem]) -> None:
    """Renumber every content H2 as "1. ", "2. ", ... in document order.

    Idempotent: strips any existing leading ordinal first, so re-running
    produces the same result. Only touches content H2s (the ranked items);
    the H1, FAQ block, and any H3s are left alone.
    """
    for ordinal, pos in enumerate(_content_h2_positions(structure), start=1):
        base = strip_leading_ordinal(structure[pos].text)
        structure[pos].text = f"{ordinal}. {base}"


def _reindex_order(structure: list[HeadingItem]) -> None:
    """Reassign the positional `order` field to match list order (0-based),
    matching the answer-contract reindex convention in pipeline.py."""
    for idx, h in enumerate(structure):
        h.order = idx


def _normalize_name(text: str) -> str:
    """Lowercased key for de-duplicating item names against existing headings.
    Drops a leading ordinal and any trailing angle (text after the first
    colon / dash) so "1. Reveel: Audit Automation" keys as "reveel"."""
    base = strip_leading_ordinal(text).lower()
    # Split on the first ' - ' or ':' to isolate the item name from its angle.
    for sep in (":", " - ", " – ", " — "):
        if sep in base:
            base = base.split(sep, 1)[0]
            break
    return base.strip()


_SYSTEM = """You name the real, well-known items a "best of" ranked listicle should cover.

You are given a listicle's keyword, title, and scope. Return the specific, \
REAL, currently-existing named items (products, tools, brands, companies, \
services - whatever the listicle ranks) that a well-researched version of this \
article would rank.

Hard rules:
- Only REAL, verifiable, well-known items. Never invent or guess a name. If you \
are not confident an item genuinely exists and fits, leave it out.
- If you cannot name enough real items, return FEWER (even an empty list). A \
short honest list is required; a padded list with fabricated names is not.
- Do NOT repeat any item in the "already covered" list.
- Each item's "angle" is a short (<= 8 words) noun-phrase differentiator - what \
that item is best known for. No verbs, no marketing superlatives \
("best"/"top"/"leading"), no sentences.

Output strict JSON:
  {"items": [{"name": "Item Name", "angle": "short differentiator"}, ...]}

Return at most the requested number of items, most-relevant first."""


async def synthesize_item_names(
    *,
    keyword: str,
    title: str,
    scope_statement: str,
    count: int,
    existing_names: set[str],
    grounding: str = "",
    llm_json_fn: Optional[LLMJsonFn] = None,
    model: Optional[str] = None,
) -> list[dict[str, str]]:
    """One LLM call naming up to `count` real items for the listicle.

    Returns a list of {"name", "angle"} dicts, de-duplicated against
    `existing_names` and against each other. Returns [] on any failure or
    when the model declines to name real items (honest fallback).
    """
    if count <= 0:
        return []

    call = llm_json_fn or claude_json
    covered = sorted(n for n in existing_names if n)
    user = (
        f"Keyword: {keyword}\n"
        f"Title: {title}\n"
        f"Scope: {scope_statement}\n"
        f"Number of NEW items to name: {count}\n"
        f"Already covered (do not repeat): {covered or 'none'}\n"
    )
    if grounding.strip():
        user += (
            "\nContext already gathered for this article (may name real "
            "items - use only if genuinely relevant, never copy blindly):\n"
            f"{grounding.strip()[:2000]}\n"
        )

    try:
        response = await call(
            _SYSTEM, user, max_tokens=600, temperature=0, model=model,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort, never abort the brief
        logger.warning("brief.listicle.synthesize_failed: %s", exc)
        return []

    raw_items = response.get("items") if isinstance(response, dict) else None
    if not isinstance(raw_items, list):
        return []

    out: list[dict[str, str]] = []
    seen = set(existing_names)
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        key = _normalize_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        angle = (entry.get("angle") or "").strip()
        out.append({"name": name, "angle": angle})
        if len(out) >= count:
            break
    return out


def _build_heading(name: str, angle: str) -> HeadingItem:
    text = f"{name}: {angle}" if angle else name
    return HeadingItem(
        level="H2",
        text=titlecase(text),
        type="content",
        source="synthesized",
        exempt=True,
    )


async def ensure_min_ranked_items(
    *,
    structure: list[HeadingItem],
    keyword: str,
    title: str,
    scope_statement: str,
    min_count: int,
    max_count: int,
    grounding: str = "",
    llm_json_fn: Optional[LLMJsonFn] = None,
    model: Optional[str] = None,
) -> ListicleFillResult:
    """Ensure a ranked_items outline has >= `min_count` ranked content H2s.

    Mutates `structure` in place (appends ranked H2 sections before the FAQ
    block and renumbers the ranked items 1..N) and returns a
    `ListicleFillResult`. No-op (no LLM call) when the floor is already met.
    Honest-fallback: leaves the outline unchanged when the model can't name
    enough real items or the call fails.

    Caller is responsible for only invoking this for `ranked_items` intents.
    """
    positions = _content_h2_positions(structure)
    result = ListicleFillResult(before_count=len(positions), after_count=len(positions))

    need = min_count - len(positions)
    if need <= 0:
        return result  # floor already met - no LLM call

    room = max_count - len(positions)
    want = min(need, room) if room > 0 else 0
    if want <= 0:
        return result

    existing_names = {_normalize_name(structure[p].text) for p in positions}
    result.llm_called = True
    items = await synthesize_item_names(
        keyword=keyword,
        title=title,
        scope_statement=scope_statement,
        count=want,
        existing_names=existing_names,
        grounding=grounding,
        llm_json_fn=llm_json_fn,
        model=model,
    )
    if not items:
        # Honest fallback: an LLM failure OR a genuine "no real items to
        # name" both leave the short outline as-is rather than fabricate.
        result.fallback_short = True
        logger.info(
            "brief.listicle.short_accepted",
            extra={
                "keyword": keyword,
                "content_h2_count": len(positions),
                "min_h2_count": min_count,
            },
        )
        return result

    new_items = [_build_heading(it["name"], it["angle"]) for it in items]

    # Insert the ranked items at the end of the content region - right before
    # the FAQ block (assemble_structure emits [H1, content H2s (+H3s), FAQ];
    # the conclusion is writer-side, not in the brief structure).
    faq_start = next(
        (i for i, h in enumerate(structure) if h.type in _FAQ_TYPES),
        len(structure),
    )
    structure[faq_start:faq_start] = new_items

    renumber_ranked_items(structure)
    _reindex_order(structure)

    result.added = len(new_items)
    result.added_names = [it["name"] for it in items]
    result.after_count = len(_content_h2_positions(structure))
    logger.info(
        "brief.listicle.items_synthesized",
        extra={
            "keyword": keyword,
            "before": result.before_count,
            "after": result.after_count,
            "added": result.added,
            "names": result.added_names,
        },
    )
    return result
