"""Parsers and source extractors for SERP/Reddit/LLM responses.

Step 1 — turn DataForSEO SERP items into heading candidates and SERP feature flags.
Step 2 — turn Reddit threads, PAA blocks, and LLM response bodies into
         heading/FAQ candidates.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from models.brief import IntentSignals

from .sanitization import sanitize_heading

BOILERPLATE_PATTERNS = [
    r"^contact us$",
    r"^about( the)? author$",
    r"^related posts?$",
    r"^share this( post)?$",
    r"^subscribe( now)?$",
    r"^sign up( now)?$",
    r"^advertisement$",
    r"^you may also like$",
    r"^leave a (reply|comment)$",
    r"^table of contents$",
    r"^references?$",
    r"^bibliography$",
    r"^author bio$",
    r"^trending (now|posts?)$",
    r"^popular posts?$",
]
BOILERPLATE_REGEX = re.compile("|".join(BOILERPLATE_PATTERNS), re.IGNORECASE)


def is_boilerplate(text: str) -> bool:
    return bool(BOILERPLATE_REGEX.match(text.strip()))


def normalize_text(text: str) -> str:
    """Lowercase + strip punctuation for fuzzy matching. Preserves nothing for output."""
    text = re.sub(r"[^\w\s]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def levenshtein_ratio(a: str, b: str) -> float:
    """Normalized Levenshtein distance (0 = identical, 1 = completely different).

    Used for fuzzy dedup with threshold 0.15 per spec §4.
    """
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0

    rows = len(a) + 1
    cols = len(b) + 1
    matrix = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        matrix[i][0] = i
    for j in range(cols):
        matrix[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            matrix[i][j] = min(
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost,
            )
    distance = matrix[-1][-1]
    return distance / max(len(a), len(b))


def _add_sanitized(
    bucket: list[dict],
    raw_text: str,
    *,
    level: str,
    position: int,
    url: str,
    source: str,
) -> None:
    """Apply CQ PRD R2 sanitization at intake. Stash both clean + raw text.

    `raw_text` is preserved on the candidate so the brief output's
    discarded_headings can show what was actually scraped.
    """
    raw = (raw_text or "").strip()
    if not raw or is_boilerplate(raw):
        return
    cleaned = sanitize_heading(raw, source_url=url)
    if cleaned is None:
        # Sanitization rejected (S9 too short, S10 non-descriptive, or stripped to empty)
        bucket.append({
            "text": raw,
            "raw_text": raw,
            "level": level,
            "position": position,
            "url": url,
            "source": source,
            "sanitization_discarded": True,
        })
        return
    bucket.append({
        "text": cleaned,
        "raw_text": raw,
        "level": level,
        "position": position,
        "url": url,
        "source": source,
        "sanitization_discarded": False,
    })


def parse_serp(items: list[dict[str, Any]]) -> tuple[list[dict], IntentSignals, list[str], list[str]]:
    """Step 1 — extract headings (H1/H2/H3) from organic results, and SERP signals.

    Returns:
        headings: list of {text, raw_text, level, position, url, source, sanitization_discarded}
        intent_signals: IntentSignals
        paa_questions: list of PAA question strings (sanitized; ones rejected by S9/S10 dropped)
        organic_titles: list of organic result titles (used by intent classifier)
    """
    headings: list[dict] = []
    paa_questions: list[str] = []
    titles: list[str] = []

    signals = IntentSignals()

    for item in items:
        item_type = item.get("type")

        if item_type == "people_also_ask":
            for paa_item in item.get("items") or []:
                q = paa_item.get("title")
                if not q:
                    continue
                cleaned = sanitize_heading(q.strip(), source_url=None)
                if cleaned:
                    paa_questions.append(cleaned)
            continue

        if item_type == "shopping" or item_type == "shopping_serp":
            signals.shopping_box = True
            continue

        if item_type == "carousel" and "shopping" in (item.get("rectangle") or {}).get("name", "").lower():
            signals.shopping_box = True
            continue

        if item_type == "top_stories":
            signals.news_box = True
            continue

        if item_type == "local_pack" or item_type == "map":
            signals.local_pack = True
            continue

        if item_type == "featured_snippet":
            signals.featured_snippet = True

        if item_type == "table" and item.get("table"):
            signals.comparison_tables = True

        if item_type != "organic":
            continue

        position = item.get("rank_absolute") or item.get("rank_group") or 0
        url = item.get("url") or ""
        title = item.get("title") or ""
        if title and not is_boilerplate(title):
            titles.append(title.strip())
            # Title doubles as an H1 candidate
            if len(title.split()) >= 3:
                _add_sanitized(headings, title, level="H1", position=position, url=url, source="serp")

        # Some DataForSEO responses include `extended_snippet` or item-level
        # `highlighted_text`. We don't have direct H2/H3 access from the
        # standard SERP API; the Brief Generator gets them via title/snippet
        # parsing here, plus PAA, autocomplete, suggestions, and LLM fan-out.
        snippet = item.get("description") or ""
        for line in snippet.splitlines():
            line = line.strip(" •-—:")
            if line.endswith(":") and 3 <= len(line.split()) <= 12 and not is_boilerplate(line):
                _add_sanitized(
                    headings, line.rstrip(":"),
                    level="H2", position=position, url=url, source="serp",
                )

    return headings, signals, paa_questions, titles


def parse_reddit(items: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Step 2B — return (post_titles, comment_texts).

    DataForSEO SERP results don't include comments; we only have titles +
    descriptions from the search results page. Pulling actual thread
    comments would require ScrapeOwl or the Reddit API — out of scope here.
    For v1 we treat the description as comment-equivalent text.
    """
    titles: list[str] = []
    comment_like: list[str] = []
    for item in items:
        title = (item.get("title") or "").strip()
        if title:
            titles.append(title)
        desc = (item.get("description") or "").strip()
        if desc:
            comment_like.append(desc)
    return titles, comment_like


def aggregate_serp_stats(headings: list[dict]) -> dict[str, dict]:
    """Compute serp_frequency, avg_serp_position, and source URLs keyed by normalized text.

    Headings flagged with `sanitization_discarded` are excluded — they were
    sanitized to nothing meaningful and don't enter the SERP stats pool.
    The pre-sanitization raw text is preserved on the representative entry
    so downstream `discarded_headings` records can show the original artifact.
    """
    by_norm: dict[str, list[dict]] = defaultdict(list)
    for h in headings:
        if h.get("sanitization_discarded"):
            continue
        by_norm[normalize_text(h["text"])].append(h)

    stats: dict[str, dict] = {}
    for norm, group in by_norm.items():
        positions = [h["position"] for h in group if h.get("position")]
        urls = [h["url"] for h in group if h.get("url")]
        stats[norm] = {
            "serp_frequency": len(group),
            "avg_serp_position": (sum(positions) / len(positions)) if positions else None,
            "representative_text": group[0]["text"],
            "representative_level": group[0].get("level", "H2"),
            "raw_text": group[0].get("raw_text"),
            "source_urls": urls,
        }
    return stats


def sanitization_discards(headings: list[dict]) -> list[dict]:
    """Return SERP headings whose sanitization rejected them (S9 / S10).

    Used by the pipeline to populate `discarded_headings` with R2 reasons.
    """
    return [h for h in headings if h.get("sanitization_discarded")]
