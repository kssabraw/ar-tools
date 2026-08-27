"""Deterministic 'length fit' engine for Local SEO / service pages.

Local pages were running 2–3× longer than the competitor SERP. The cause is
structural: generation is driven by a fixed 12-section template with absolute
per-section word counts and an explicit "information gain — cover every topic
competitors cover, then add more" mandate, and nothing in the pipeline ever
measured or budgeted against the actual SERP length.

This module closes that gap deterministically (no LLM, no extra tokens):

  1. It measures the competitor SERP's average body-content length.
  2. It sets a target of SERP average + 20% (owner-chosen — a local page may
     reasonably out-cover a thin SERP, but not by 2–3×).
  3. It scores how well a generated page fits that target, so the target both
     steers generation (as a budget in the prompt) and is enforced by the
     scoring / auto-reoptimization loop.

Body length is measured with `content_word_count` on BOTH sides — the competitor
pages and the generated page — so the comparison is symmetric. It counts the
readable body content (paragraphs, list items, table cells, and other prose)
after stripping site chrome (nav/header/footer/aside/forms) and headings, so a
page whose content lives in lists or tables is measured at its true length, not
just its ``<p>`` prose. A pure regex/bs4 module, unit-testable in isolation,
mirroring ``blog_structure.py``.
"""
from __future__ import annotations

import os
from typing import List, Optional

from bs4 import BeautifulSoup

# A competitor page that scraped to near-nothing is a failed/thin scrape, not a
# real length signal — exclude it so it can't drag the average (and target) down.
_MIN_VALID_WORDS = 100

# SERP average + 20%: the owner-chosen target band.
OVERAGE_MULTIPLIER = 1.20

# Absolute floor on the length target (owner-chosen). The target drives length_fit
# scoring AND the writer's word budget AND the scaling of the reference-page
# layout; on a thin / low-signal SERP, SERP-avg + 20% can be so small that a
# multi-section reference layout gets squeezed to nonsense. The floor only ever
# RAISES a real (avg-derived) target — it never manufactures one from a SERP that
# produced no usable average (that stays None, i.e. length is not graded).
MIN_TARGET_WORDS = int(os.environ.get("LENGTH_MIN_TARGET_WORDS", "900"))

# Full credit while the page sits between the SERP average and slightly above
# target; penalties ramp up outside the band. Over-length (the disease we are
# fixing) and under-length both cost, on their own slopes.
_LOWER_OK = 1.0 / OVERAGE_MULTIPLIER   # ratio at which the page ≈ the SERP average
_UPPER_OK = 1.10                       # ratio at which the page ≈ target + 10%
_UNDER_SLOPE = 250.0                   # points lost per unit of ratio below the band
_OVER_SLOPE = 150.0                    # points lost per unit of ratio above the band

# Site chrome + headings are removed before counting body content, so nav menus,
# footers, sidebars, and forms don't inflate the measure and headings (short,
# structural) don't pad the prose count. Everything else a reader sees —
# paragraphs, list items, table cells, blockquotes, div/span prose — is counted.
_CHROME_TAGS = (
    "script", "style", "noscript", "template", "iframe", "svg",
    "nav", "header", "footer", "aside", "form",
)
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def content_word_count(html: str) -> int:
    """Readable body-content word count: everything a reader sees minus site
    chrome (nav/header/footer/aside/forms), headings, and scripts/styles.
    Counts prose, list items, and table cells — not just ``<p>`` — so a page
    whose content lives in lists or tables is measured at its true length. Used
    symmetrically for competitor pages and the generated page, so the comparison
    is fair."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(list(_CHROME_TAGS) + list(_HEADING_TAGS)):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return len(text.split())


def competitor_avg_words(page_htmls: List[str]) -> Optional[float]:
    """Average per-competitor-page body-content word count across the SERP,
    dropping thin/failed scrapes. Returns ``None`` when fewer than 2 valid pages
    remain (no reliable target — callers then skip length budgeting/scoring).
    Measures each page with `content_word_count`, identical to the generated
    page, so the two sides are directly comparable."""
    counts = [content_word_count(h) for h in (page_htmls or [])]
    valid = [c for c in counts if c >= _MIN_VALID_WORDS]
    if len(valid) < 2:
        return None
    return sum(valid) / len(valid)


def word_target(avg_words: Optional[float]) -> Optional[int]:
    """SERP average + 20%, floored at ``MIN_TARGET_WORDS``. ``None`` when there is
    no average (a SERP that yielded no usable competitor length → length is not
    graded and the reference layout is not scaled). The floor only raises a real,
    low target; it never invents one from a missing average."""
    if not avg_words or avg_words <= 0:
        return None
    return max(int(round(avg_words * OVERAGE_MULTIPLIER)), MIN_TARGET_WORDS)


def is_over_length(engine: Optional[dict], min_ratio: float = 1.0) -> bool:
    """True when a length_fit engine result shows the page OVER the SERP target
    by at least ``min_ratio`` (page_words >= target_words * min_ratio). Used to
    decide whether a generated/live page earns a length-trim pass; under-length
    never triggers a trim (that would ask the writer to pad). ``min_ratio`` lets
    a caller require a LARGE overage before spending an extra rewrite pass — the
    generation budget prompt keeps most pages near target, so the trim should be
    a rare safety net, not a routine step. Default 1.0 = any overage."""
    e = engine or {}
    if not e.get("measured"):
        return False
    target = e.get("target_words") or 0
    return bool(target) and e.get("page_words", 0) > target * min_ratio


def compute_length_fit(page_html: str, target_words: Optional[int]) -> Optional[dict]:
    """Deterministically score a page's body length against the SERP target
    (SERP average + 20%). Returns the engine-dict shape used by the composite:
    ``{score, issues, recommendations, ...}`` — or ``None`` when length can't be
    measured (no SERP target, or no body prose on the page). Callers OMIT the
    engine on ``None`` so the composite renormalizes over the engines it can
    measure, never distorting a score it can't. Over-length and under-length
    both produce a concrete "cut ~N words" / "add ~N words" recommendation so the
    auto-reoptimization loop is steered, not just penalized."""
    if not target_words or target_words <= 0:
        return None

    words = content_word_count(page_html)
    if words <= 0:
        return None

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
