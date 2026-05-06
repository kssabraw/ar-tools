"""Per-zone term usage analyzer.

Computes which SIE-recommended related keywords + entities actually appear in
each zone of the produced article (Title, H1, Subheadings, Body) and extracts
the most frequent quadgrams (4-word phrases) per zone for an at-a-glance
read on what the article is "about" lexically.

Pure function - no LLM calls. Output is attached to the writer response so
the frontend can render a usage table below the article body.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional


# Zones we report on. The order here drives the frontend's display order.
ZONES: tuple[str, ...] = ("title", "h1", "subheadings", "body")


# Common English stopwords. Kept narrow on purpose - we only use them to
# filter quadgrams that are entirely "the of and to in", which carry no
# topical signal. Anything more aggressive risks killing real phrases like
# "in the box" that are meaningful in context.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by",
    "for", "from", "has", "have", "he", "her", "his", "i",
    "in", "is", "it", "its", "of", "on", "or", "she", "so",
    "such", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "to", "was",
    "we", "were", "will", "with", "you", "your",
})

# Citation marker pattern - strip these from body text before quadgram
# extraction so {{cit_005}} doesn't pollute phrases. The Sources Cited
# module replaces them with <sup><a> tags before publication, but the
# raw writer.article body still carries the {{cit_N}} form.
_MARKER_RE = re.compile(r"\{\{cit_\d+\}\}")

# Word tokenizer - keep alphanumerics, intra-word apostrophes (don't,
# brand's), and intra-word hyphens (well-known). Strip everything else.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")


@dataclass
class TermCount:
    """One term's occurrence count in a single zone."""
    term: str
    count: int
    # entity_category is set only when the term came from SIE with
    # is_entity=True; None for plain related-keyword terms.
    entity_category: Optional[str] = None

    def to_dict(self) -> dict:
        out: dict = {"term": self.term, "count": self.count}
        if self.entity_category:
            out["entity_category"] = self.entity_category
        return out


@dataclass
class QuadgramCount:
    phrase: str
    count: int

    def to_dict(self) -> dict:
        return {"phrase": self.phrase, "count": self.count}


@dataclass
class ZoneUsage:
    related_keywords: list[TermCount]
    entities: list[TermCount]
    quadgrams: list[QuadgramCount]

    def to_dict(self) -> dict:
        return {
            "related_keywords": [t.to_dict() for t in self.related_keywords],
            "entities": [t.to_dict() for t in self.entities],
            "quadgrams": [q.to_dict() for q in self.quadgrams],
        }


# ----------------------------------------------------------------------
# Zone text extraction
# ----------------------------------------------------------------------

def _strip_markers(text: str) -> str:
    return _MARKER_RE.sub("", text or "")


def _zone_texts(
    *,
    title: str,
    h1: str,
    article: list[dict],
) -> dict[str, str]:
    """Return one concatenated text blob per zone, ready for term counting.

    `article` is the writer's `article[]` list (each entry has level, type,
    heading, body). Content/FAQ/conclusion bodies feed the body zone;
    H2/H3 headings (any type, except H1) feed the subheadings zone.
    """
    subheading_parts: list[str] = []
    body_parts: list[str] = []

    for s in article or []:
        if not isinstance(s, dict):
            continue
        level = s.get("level")
        type_ = s.get("type")
        heading = s.get("heading") or ""
        body = s.get("body") or ""

        if level in ("H2", "H3") and heading:
            # Subheadings include H2/H3 headings of every type:
            # content, faq-header, faq-question, sources-cited-header.
            subheading_parts.append(heading)

        # Body collects anything that's actual prose. Skip H1 (covered by
        # the explicit `h1` arg), and skip sources-cited-body which is
        # raw HTML (would pollute quadgrams).
        if type_ in (
            "content", "intro", "conclusion", "faq-question", "h1-enrichment"
        ) and body:
            body_parts.append(body)

    return {
        "title": (title or "").strip(),
        "h1": (h1 or "").strip(),
        "subheadings": "\n".join(subheading_parts),
        "body": _strip_markers("\n".join(body_parts)),
    }


# ----------------------------------------------------------------------
# Counting helpers
# ----------------------------------------------------------------------

def _count_term_in_text(term: str, text: str) -> int:
    """Case-insensitive, whole-word-ish substring count.

    For multi-word terms we use a simple `\\b` regex to avoid matching
    inside a longer word. For single tokens, same behavior.
    """
    if not term or not text:
        return 0
    pattern = re.compile(
        r"\b" + re.escape(term) + r"\b",
        re.IGNORECASE,
    )
    return len(pattern.findall(text))


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text or "")]


def _quadgrams(text: str, *, top_n: int = 8) -> list[QuadgramCount]:
    """Top-N most-frequent 4-word phrases in the text, excluding phrases
    composed entirely of stopwords."""
    tokens = _tokenize(text)
    if len(tokens) < 4:
        return []
    counter: Counter = Counter()
    for i in range(len(tokens) - 3):
        window = tokens[i : i + 4]
        if all(w in _STOPWORDS for w in window):
            continue
        counter[" ".join(window)] += 1
    # Show even single-occurrence quadgrams in title/h1/subheadings
    # (they're short zones), but cap to top_n.
    return [
        QuadgramCount(phrase=phrase, count=count)
        for phrase, count in counter.most_common(top_n)
    ]


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def compute_term_usage_by_zone(
    *,
    title: str,
    h1: str,
    article: list[dict],
    sie_terms_required: list[dict],
    sie_terms_exploratory: list[dict],
) -> dict[str, dict]:
    """Compute per-zone term usage for the produced article.

    Returns a dict keyed by zone name (`title`, `h1`, `subheadings`,
    `body`), each value being the `ZoneUsage.to_dict()` shape.

    Related keywords + entities are sourced from SIE (required +
    exploratory). Only terms with at least one occurrence in the zone
    are returned, sorted by count desc (then alphabetically). Entities
    are split out from plain related keywords by `is_entity=True`.

    Quadgrams are derived from the zone's own text - top 8 by frequency,
    stopword-only phrases excluded.
    """
    zones = _zone_texts(title=title, h1=h1, article=article)

    # Combine SIE term lists (de-duped by lowercased term) + tag entities.
    all_sie: dict[str, dict] = {}
    for src in (sie_terms_required, sie_terms_exploratory):
        for entry in src or []:
            if not isinstance(entry, dict):
                continue
            term = (entry.get("term") or "").strip()
            if not term:
                continue
            key = term.lower()
            if key not in all_sie:
                all_sie[key] = entry

    out: dict[str, dict] = {}
    for zone_name in ZONES:
        zone_text = zones.get(zone_name, "")
        related: list[TermCount] = []
        entities: list[TermCount] = []
        for entry in all_sie.values():
            term = (entry.get("term") or "").strip()
            if not term:
                continue
            count = _count_term_in_text(term, zone_text)
            if count == 0:
                continue
            tc = TermCount(
                term=term,
                count=count,
                entity_category=(
                    entry.get("entity_category") if entry.get("is_entity") else None
                ),
            )
            if entry.get("is_entity"):
                entities.append(tc)
            else:
                related.append(tc)

        related.sort(key=lambda t: (-t.count, t.term.lower()))
        entities.sort(key=lambda t: (-t.count, t.term.lower()))

        usage = ZoneUsage(
            related_keywords=related,
            entities=entities,
            quadgrams=_quadgrams(zone_text),
        )
        out[zone_name] = usage.to_dict()

    return out
