"""Deterministic 'length fit' engine for Local SEO / service pages.

Local pages were running 2–3× longer than the competitor SERP. The cause is
structural: generation is driven by a fixed 12-section template with absolute
per-section word counts and an explicit "information gain — cover every topic
competitors cover, then add more" mandate, and nothing in the pipeline ever
measured or budgeted against the actual SERP length.

This module closes that gap deterministically (no LLM, no extra tokens):

  1. It measures the competitor SERP's average body length.
  2. It sets a target of SERP average + 20% (owner-chosen — a local page may
     reasonably out-cover a thin SERP, but not by 2–3×).
  3. It scores how well a generated page fits that target, so the target both
     steers generation (as a budget in the prompt) and is enforced by the
     scoring / auto-reoptimization loop.

Body length is measured from ``<p>`` prose on BOTH sides — the competitor
"paragraphs" zone and the generated page — so the comparison is symmetric and
chrome-free (nav/footer text lives outside ``<p>``). A pure regex/bs4 module,
unit-testable in isolation, mirroring ``blog_structure.py``.
"""
from __future__ import annotations

from typing import List, Optional

from bs4 import BeautifulSoup

# A competitor page that scraped to near-nothing is a failed/thin scrape, not a
# real length signal — exclude it so it can't drag the average (and target) down.
_MIN_VALID_WORDS = 100

# SERP average + 20%: the owner-chosen target band.
OVERAGE_MULTIPLIER = 1.20

# Full credit while the page sits between the SERP average and slightly above
# target; penalties ramp up outside the band. Over-length (the disease we are
# fixing) and under-length both cost, on their own slopes.
_LOWER_OK = 1.0 / OVERAGE_MULTIPLIER   # ratio at which the page ≈ the SERP average
_UPPER_OK = 1.10                       # ratio at which the page ≈ target + 10%
_UNDER_SLOPE = 250.0                   # points lost per unit of ratio below the band
_OVER_SLOPE = 150.0                    # points lost per unit of ratio above the band

# Score used when no SERP length target is available (external-URL scoring, or an
# older analysis with no target). Kept ≥ the 80 deficiency threshold so an
# unmeasurable page never flags as a length deficiency, and near typical composite
# levels so it barely moves a score it genuinely cannot measure.
_NEUTRAL_SCORE = 85


def paragraph_word_count(html: str) -> int:
    """Words of visible ``<p>`` prose in an HTML fragment — chrome-free and
    symmetric with how competitor length is measured from the paragraphs zone."""
    soup = BeautifulSoup(html or "", "html.parser")
    text = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
    return len(text.split())


def competitor_avg_words(paragraph_zone_texts: List[str]) -> Optional[float]:
    """Average per-competitor-page ``<p>`` word count across the SERP, dropping
    thin/failed scrapes. Returns ``None`` when fewer than 2 valid pages remain
    (no reliable target — callers then skip length budgeting/scoring)."""
    counts = [len((t or "").split()) for t in (paragraph_zone_texts or [])]
    valid = [c for c in counts if c >= _MIN_VALID_WORDS]
    if len(valid) < 2:
        return None
    return sum(valid) / len(valid)


def word_target(avg_words: Optional[float]) -> Optional[int]:
    """SERP average + 20%, rounded. ``None`` when there is no average."""
    if not avg_words or avg_words <= 0:
        return None
    return int(round(avg_words * OVERAGE_MULTIPLIER))


def _neutral(reason: str) -> dict:
    return {
        "score": _NEUTRAL_SCORE,
        "issues": [],
        "recommendations": [],
        "measured": False,
        "reason": reason,
    }


def compute_length_fit(page_html: str, target_words: Optional[int]) -> dict:
    """Deterministically score a page's body length against the SERP target
    (SERP average + 20%). Returns the engine-dict shape used by the composite:
    ``{score, issues, recommendations, ...}``. Over-length and under-length both
    produce a concrete "cut ~N words" / "add ~N words" recommendation so the
    auto-reoptimization loop is steered, not just penalized."""
    if not target_words or target_words <= 0:
        return _neutral("No SERP length target available — length fit not measured.")

    words = paragraph_word_count(page_html)
    if words <= 0:
        return _neutral("No body prose detected — length fit not measured.")

    ratio = words / target_words
    if ratio < _LOWER_OK:
        score = max(0.0, 100.0 - (_LOWER_OK - ratio) * _UNDER_SLOPE)
    elif ratio > _UPPER_OK:
        score = max(0.0, 100.0 - (ratio - _UPPER_OK) * _OVER_SLOPE)
    else:
        score = 100.0
    score = round(score, 1)

    serp_avg = int(round(target_words / OVERAGE_MULTIPLIER))
    issues: List[str] = []
    recs: List[str] = []
    if ratio > _UPPER_OK:
        over = words - target_words
        pct = int(round((ratio - 1) * 100))
        issues.append(
            f"Page body is ~{words} words vs a target of ~{target_words} "
            f"(competitor SERP average ~{serp_avg} + 20%) — about {pct}% over."
        )
        recs.append(
            f"Cut ~{over} words. Tighten the Main Service Body first, merge overlapping "
            f"H2/H3 sections, and drop net-new topics competitors don't cover unless they "
            f"are essential to the answer. Do not pad to a number."
        )
    elif ratio < _LOWER_OK:
        short = target_words - words
        pct = int(round((1 - ratio) * 100))
        issues.append(
            f"Page body is ~{words} words vs a target of ~{target_words} "
            f"(competitor SERP average ~{serp_avg} + 20%) — about {pct}% under."
        )
        recs.append(
            f"Add ~{short} words of substantive, on-topic depth (competitor topic coverage, "
            f"service specifics, local detail) — never filler or fabricated facts."
        )

    return {
        "score": score,
        "issues": issues,
        "recommendations": recs,
        "measured": True,
        "page_words": words,
        "target_words": target_words,
        "serp_avg_words": serp_avg,
    }
