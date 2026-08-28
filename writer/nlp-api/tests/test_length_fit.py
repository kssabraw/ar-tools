"""Unit tests for the deterministic length-fit engine.

Pure + offline — bs4 only, no network, no Anthropic. Covers the content-aware
word count (prose + lists + tables, chrome-stripped), the competitor average,
the SERP-avg-+20% target, the length_fit scoring curve, the over-length helper,
and the None-when-unmeasurable contract (so callers omit the engine and the
composite renormalizes instead of taking a neutral placeholder).
Run with `pytest writer/nlp-api/tests/` or `python -m pytest`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import length_fit as lf  # noqa: E402


def _page(n_words: int) -> str:
    """An HTML fragment whose body content is exactly n_words words."""
    return "<article><h2>Heading not counted</h2><p>" + " ".join(["word"] * n_words) + "</p></article>"


# ── content_word_count ───────────────────────────────────────────────────────

def test_content_count_includes_lists_and_tables_excludes_chrome_and_headings():
    html = (
        "<nav>Home About Contact Services Areas Reviews</nav>"
        "<header>logo tagline phone</header>"
        "<article><h1>Big Heading Words Here Ignored</h1>"
        "<p>one two three</p>"
        "<ul><li>four five</li><li>six seven</li></ul>"
        "<table><tr><td>eight nine</td><td>ten</td></tr></table></article>"
        "<footer>footer nav words here too plenty</footer>"
        "<aside>related links sidebar chrome</aside>"
    )
    # counted: p(3) + li(2+2) + td(2+1) = 10; headings/nav/header/footer/aside excluded.
    assert lf.content_word_count(html) == 10


def test_content_count_handles_none_and_empty():
    assert lf.content_word_count(None) == 0
    assert lf.content_word_count("") == 0
    assert lf.content_word_count("<nav>only chrome here</nav>") == 0


# ── competitor_avg_words (now takes raw page HTML) ───────────────────────────

def test_competitor_avg_drops_thin_scrapes():
    good_a = "<article><p>" + " ".join(["w"] * 800) + "</p></article>"
    good_b = "<article><p>" + " ".join(["w"] * 1200) + "</p></article>"
    thin = "<article><p>too thin</p></article>"
    assert lf.competitor_avg_words([good_a, good_b, thin]) == 1000.0


def test_competitor_avg_needs_two_valid_pages():
    one_good = "<article><p>" + " ".join(["w"] * 900) + "</p></article>"
    assert lf.competitor_avg_words([one_good]) is None
    assert lf.competitor_avg_words(["<p>thin</p>", "<p>also thin</p>"]) is None
    assert lf.competitor_avg_words([]) is None


def test_word_target_is_avg_plus_20_percent():
    assert lf.word_target(1000.0) == 1200
    assert lf.word_target(None) is None
    assert lf.word_target(0) is None


def test_word_target_floors_thin_serps_but_never_invents_one():
    # A real but low average is raised to the floor so a multi-section reference
    # layout isn't squeezed to nonsense; a healthy average is unaffected.
    assert lf.MIN_TARGET_WORDS == 900
    assert lf.word_target(500.0) == 900       # 500*1.2 = 600 -> floored to 900
    assert lf.word_target(750.0) == 900       # 750*1.2 = 900 -> exactly the floor
    assert lf.word_target(800.0) == 960       # 800*1.2 = 960 -> above the floor, unchanged
    # the floor never manufactures a target where there is no SERP average
    assert lf.word_target(None) is None
    assert lf.word_target(0) is None


# ── is_over_length ───────────────────────────────────────────────────────────

def test_is_over_length():
    assert lf.is_over_length({"measured": True, "page_words": 2000, "target_words": 1200}) is True
    assert lf.is_over_length({"measured": True, "page_words": 900, "target_words": 1200}) is False  # under
    assert lf.is_over_length({"measured": True, "page_words": 1200, "target_words": 1200}) is False  # equal
    assert lf.is_over_length({"measured": False, "page_words": 9999, "target_words": 1200}) is False
    assert lf.is_over_length(None) is False


def test_is_over_length_min_ratio_gates_small_overages():
    # min_ratio=1.4 (the generate-page safety-net threshold): only a >40% overage
    # spends the extra trim pass. A 25% over page is left to the score + bulk gate.
    eng_25 = {"measured": True, "page_words": 1500, "target_words": 1200}   # 25% over
    eng_60 = {"measured": True, "page_words": 1920, "target_words": 1200}   # 60% over
    assert lf.is_over_length(eng_25, 1.4) is False
    assert lf.is_over_length(eng_60, 1.4) is True
    # exactly at the ratio boundary is not "over" it (strict >)
    assert lf.is_over_length({"measured": True, "page_words": 1680, "target_words": 1200}, 1.4) is False
    # default (1.0) still flags any real overage
    assert lf.is_over_length(eng_25) is True


# ── compute_length_fit scoring curve ─────────────────────────────────────────

def test_on_target_scores_100():
    target = 1200  # SERP avg 1000 + 20%
    assert lf.compute_length_fit(_page(1200), target)["score"] == 100.0
    assert lf.compute_length_fit(_page(1050), target)["score"] == 100.0  # ~SERP average
    assert lf.compute_length_fit(_page(1300), target)["score"] == 100.0  # target +10%


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


# ── None-when-unmeasurable (so callers omit it and the composite renormalizes) ─

def test_no_target_returns_none():
    for target in (None, 0):
        assert lf.compute_length_fit(_page(4000), target) is None


def test_no_body_prose_returns_none():
    assert lf.compute_length_fit("<article><h2>Only a heading</h2></article>", 1200) is None
    assert lf.compute_length_fit("<nav>only chrome</nav>", 1200) is None
