"""Step 0.5 — Heading-structure sanitizer.

Runs immediately after `_validate_inputs` in the writer pipeline.
Cleans up two structural drift modes that have been observed in real
briefs:

1. **Duplicate H2 headings.** Briefs occasionally produce two body H2s
   with identical (case-folded, whitespace-normalized) heading text.
   The writer used to faithfully call `write_h2_group` once per
   duplicate, generating divergent prose for each — the article then
   shipped with two near-identical sections under the same heading,
   confusing readers and starving the brand-placement plan (which
   counted the duplicates as separate anchor candidates).

2. **FAQ-as-content body H2.** Briefs occasionally emit an H2 with
   `type="content"` whose heading text is "Frequently Asked Questions"
   (or a close variant). The writer rendered it as a body section,
   then later appended the actual FAQ block (`type="faq-header"` plus
   `type="faq-question"` items) — and the conclusion landed *between*
   the two, because conclusion is appended after body sections but
   before the FAQ block. Filtering FAQ-like body H2s out fixes the
   "conclusion in the middle of the FAQs" rendering bug.

The sanitizer is conservative:
- It keeps the FIRST occurrence of a duplicate H2 (and its H3 children).
- It drops the duplicate H2 along with everything between it and the
  next surviving H2 — H3s under the duplicate are dropped too. We
  prefer "lossy and predictable" over "smart-reparenting and
  unpredictable" — editors can review the drop log if they want the
  dropped H3s back.
- Non-content items (H1, faq-header, faq-question, conclusion,
  h1-enrichment) pass through untouched.

Returns the cleaned heading_structure plus a `SanitizationLog`
detailing what was dropped, so writer metadata can surface the action
to editors.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Matches an H2 heading whose entire (normalized) text reads as a
# variant of "Frequently Asked Questions" / "FAQs" / "Q&A". We require
# a full-string match so an H2 like "Frequently Asked Questions About
# Pricing" — which is a legitimate body section — is NOT dropped.
_FAQ_LIKE_H2_RE = re.compile(
    r"^(frequently asked questions?|faqs?|q ?(?:&|and) ?a)$",
    re.IGNORECASE,
)


@dataclass
class SanitizationLog:
    """Per-run record of what the sanitizer dropped. Empty lists are
    the no-op steady state and surface as such in writer metadata."""

    duplicate_h2s_dropped: list[dict[str, Any]] = field(default_factory=list)
    faq_like_h2s_dropped: list[dict[str, Any]] = field(default_factory=list)
    h3_children_dropped: list[dict[str, Any]] = field(default_factory=list)


def _normalize_heading(text: str) -> str:
    """Lowercase, collapse internal whitespace, strip surrounding
    whitespace and trailing punctuation. Used for duplicate detection
    only — the kept H2's original casing/punctuation passes through to
    the section writer untouched."""
    norm = (text or "").strip().lower()
    norm = re.sub(r"\s+", " ", norm)
    norm = norm.rstrip(".,;:!?—–-").rstrip()
    return norm


def sanitize_heading_structure(
    heading_structure: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], SanitizationLog]:
    """Return `(cleaned_heading_structure, log)`.

    Walks `heading_structure` in `order`. For each entry:
      - H2 content + FAQ-like text → drop, log under `faq_like_h2s_dropped`
        (and drop all subsequent H3 entries until the next surviving H2).
      - H2 content + already-seen normalized text → drop, log under
        `duplicate_h2s_dropped` (and drop all subsequent H3 entries
        until the next surviving H2).
      - H2 content + first occurrence of normalized text → keep.
      - Anything else (H1, faq-header, faq-question, conclusion,
        h1-enrichment, H3 under a kept H2) → keep.

    The cleaned list preserves the original `order` values (no
    renumbering) so downstream lookups by `order` continue to work.
    Resequencing happens later in pipeline.py after assembly.
    """
    if not isinstance(heading_structure, list):
        return list(heading_structure or []), SanitizationLog()

    sorted_items = sorted(
        [h for h in heading_structure if isinstance(h, dict)],
        key=lambda h: h.get("order", 0),
    )

    log = SanitizationLog()
    seen_normalized: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    # `dropping_under_h2` flips True when we drop a body H2; subsequent
    # H3s with `type="content"` are dropped along with it until we hit
    # another H2 (kept or dropped) or a non-content item that ends the
    # body block (faq-header, conclusion).
    dropping_under_h2 = False

    for item in sorted_items:
        level = item.get("level")
        item_type = item.get("type")

        # End-of-body markers reset the drop flag — H3 questions under
        # a faq-header are not "children of a dropped body H2".
        if item_type in {"faq-header", "faq-question", "conclusion"}:
            dropping_under_h2 = False
            cleaned.append(item)
            continue

        if level == "H2" and item_type == "content":
            text = (item.get("text") or "").strip()
            normalized = _normalize_heading(text)

            if _FAQ_LIKE_H2_RE.match(normalized):
                log.faq_like_h2s_dropped.append({
                    "order": item.get("order"),
                    "text": text,
                })
                logger.warning(
                    "writer.sanitizer.faq_like_h2_dropped",
                    extra={"order": item.get("order"), "text": text[:120]},
                )
                dropping_under_h2 = True
                continue

            if normalized and normalized in seen_normalized:
                log.duplicate_h2s_dropped.append({
                    "order": item.get("order"),
                    "text": text,
                })
                logger.warning(
                    "writer.sanitizer.duplicate_h2_dropped",
                    extra={"order": item.get("order"), "text": text[:120]},
                )
                dropping_under_h2 = True
                continue

            if normalized:
                seen_normalized.add(normalized)
            dropping_under_h2 = False
            cleaned.append(item)
            continue

        if level == "H3" and item_type == "content":
            if dropping_under_h2:
                log.h3_children_dropped.append({
                    "order": item.get("order"),
                    "text": (item.get("text") or "").strip(),
                })
                logger.info(
                    "writer.sanitizer.h3_under_dropped_h2",
                    extra={"order": item.get("order")},
                )
                continue
            cleaned.append(item)
            continue

        # H1, h1-enrichment, anything else — pass through untouched.
        cleaned.append(item)

    if log.duplicate_h2s_dropped or log.faq_like_h2s_dropped:
        logger.info(
            "writer.sanitizer.complete",
            extra={
                "duplicate_h2s": len(log.duplicate_h2s_dropped),
                "faq_like_h2s": len(log.faq_like_h2s_dropped),
                "h3_children_dropped": len(log.h3_children_dropped),
                "kept_count": len(cleaned),
                "input_count": len(sorted_items),
            },
        )

    return cleaned, log
