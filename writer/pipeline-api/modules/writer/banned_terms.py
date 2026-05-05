"""Step 4.4 — Post-hoc banned-term regex validation.

Per writer-module-v1_5-change-spec_2.md §4.4:
- Case-insensitive word-boundary regex from brand_voice_card.banned_terms
- Match in heading (h1/h2/h3) → CRITICAL: abort run, no retry
- Match in body / FAQ / intro / conclusion → RECOVERABLE: retry once
"""

from __future__ import annotations

import re
from typing import Optional


def build_banned_regex(banned_terms: list[str]) -> Optional[re.Pattern]:
    if not banned_terms:
        return None
    cleaned = [t.strip() for t in banned_terms if t and t.strip()]
    if not cleaned:
        return None
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in cleaned) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


def find_banned(text: str, regex: Optional[re.Pattern]) -> list[str]:
    """Returns list of matched terms (lower-cased, deduped)."""
    if regex is None or not text:
        return []
    matches = regex.findall(text)
    return sorted({m.lower() for m in matches})


class BannedTermLeakage(Exception):
    """Raised when post-hoc validation finds a banned term in a heading
    (critical, no retry) or in body content after retry."""

    def __init__(self, term: str, location: str, snippet: str):
        super().__init__(f"banned_term_leakage: '{term}' in {location}")
        self.term = term
        self.location = location
        self.snippet = snippet
