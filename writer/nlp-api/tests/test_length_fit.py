"""Unit tests for the deterministic length-fit engine.

Pure + offline — bs4 only, no network, no Anthropic. Covers the competitor
average, the SERP-avg-+20% target, and the length_fit scoring curve
(over-length penalized, under-length penalized, on-target = 100, and the
neutral degrade when no target is available).
Run with `pytest writer/nlp-api/tests/` or `python -m pytest`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import length_fit as lf  # noqa: E402


def _page(n_words: int) -> str:
    """An HTML fragment whose <p> prose is exactly n_words words."""
    return "<article><h2>Heading not counted</h2><p>" + " ".join(["word"] * n_words) + "</p></article>"


# ── competitor_avg_words ─────────────────────────────────────────────────────

def test_competitor_avg_drops_thin_scrapes():
    # Two real pages (800, 1200) + one failed/thin scrape (10 words) → avg of the
    # two valid pages only.
    texts = [" ".join(["w"] * 800), " ".join(["w"] * 1200), "too thin"]
    assert lf.competitor_avg_words(texts) == 1000.0


def test_competitor_avg_needs_two_valid_pages():
    assert lf.competitor_avg_words([" ".join(["w"] * 900)]) is None
    assert lf.competitor_avg_words(["thin", "also thin"]) is None
    assert lf.competitor_avg_words([]) is None


def test_word_target_is_avg_plus_20_percent():
    assert lf.word_target(1000.0) == 1200
    assert lf.word_target(None) is None
    assert lf.word_target(0) is None


# ── paragraph_word_count ─────────────────────────────────────────────────────

def test_paragraph_word_count_ignores_headings_and_chrome():
    html = (
        "<nav>Home About Contact Services Areas</nav>"
        "<article><h1>Big Heading Words Here</h1>"
        "<p>one two three four five</p>"
        "<ul><li>list item not counted</li></ul>"
        "<footer>footer nav words here too</footer></article>"
    )
    # Only the <p> prose counts.
    assert lf.paragraph_word_count(html) == 5


# ── compute_length_fit scoring curve ─────────────────────────────────────────

def test_on_target_scores_100():
    target = 1200  # SERP avg 1000 + 20%
    assert lf.compute_length_fit(_page(1200), target)["score"] == 100.0
    # Anywhere from ~the SERP average (1000) up to target+10% (1320) is full credit.
    assert lf.compute_length_fit(_page(1050), target)["score"] == 100.0
    assert lf.compute_length_fit(_page(1300), target)["score"] == 100.0


def test_over_length_is_penalized_and_recommends_cutting():
    target = 1200
    res = lf.compute_length_fit(_page(2600), target)  # ~2.2x, the reported disease
    assert res["measured"] is True
    assert res["score"] < 60
    assert res["page_words"] == 2600
    assert res["issues"] and "over" in res["issues"][0].lower()
    assert res["recommendations"] and "cut" in res["recommendations"][0].lower()


def test_more_over_scores_lower_monotonic():
    target = 1200
    s13 = lf.compute_length_fit(_page(1560), target)["score"]   # 30% over
    s20 = lf.compute_length_fit(_page(2400), target)["score"]   # 2x target
    assert s13 > s20
    assert lf.compute_length_fit(_page(3600), target)["score"] == 0.0  # 3x → floored


def test_under_length_is_penalized_and_recommends_adding():
    target = 1200
    res = lf.compute_length_fit(_page(600), target)  # well under the SERP average
    assert res["score"] < 100
    assert res["issues"] and "under" in res["issues"][0].lower()
    assert res["recommendations"] and "add" in res["recommendations"][0].lower()


# ── neutral degrade ──────────────────────────────────────────────────────────

def test_no_target_scores_neutral_and_never_flags_deficiency():
    for target in (None, 0):
        res = lf.compute_length_fit(_page(4000), target)
        assert res["measured"] is False
        # Neutral must sit at/above the 80 deficiency threshold so an unmeasurable
        # page never surfaces as a length deficiency.
        assert res["score"] >= 80
        assert res["issues"] == []


def test_no_body_prose_scores_neutral():
    res = lf.compute_length_fit("<article><h2>Only a heading</h2></article>", 1200)
    assert res["measured"] is False
    assert res["score"] >= 80
