"""Unit tests for the fallback-aware length target + the trim-pass helpers in
`main.py` (the deterministic half of the length-control fixes).

Background: when the SERP analysis failed at generate time (a provider outage),
`serp_word_target` was absent, so the writer got NO word budget, length_fit was
omitted and no trim ran — pages shipped at 3,000+ words with length neither
budgeted nor graded. These helpers let platform-api hand nlp a fallback target
that flows through the budget line, length_fit and the trim decision, and give
the trim pass an explicit "this is a cut" override (the shared reoptimize system
prompt is add-oriented and forbids removing elements). Pure + offline.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def _page(n_words: int) -> str:
    return "<article><section><h1>T</h1><p>" + " ".join(["word"] * n_words) + "</p></section></article>"


# ── _resolve_length_target ──────────────────────────────────────────────────

def test_serp_target_wins_over_fallback():
    assert main._resolve_length_target({"serp_word_target": 1300}, 1200) == 1300


def test_fallback_used_when_analysis_has_no_target():
    assert main._resolve_length_target(None, 1200) == 1200
    assert main._resolve_length_target({}, 1200) == 1200
    assert main._resolve_length_target({"serp_word_target": None}, 1200) == 1200


def test_no_target_when_neither_exists():
    assert main._resolve_length_target(None, None) is None
    assert main._resolve_length_target({"serp_word_target": 0}, 0) is None


# ── _length_budget_line ─────────────────────────────────────────────────────

def test_budget_line_from_serp_names_the_serp_average():
    line = main._length_budget_line({"serp_word_target": 1571, "serp_avg_word_count": 1309})
    assert "~1571 words" in line
    assert "competitor SERP average ~1309" in line


def test_budget_line_from_fallback_is_honest_about_its_basis():
    line = main._length_budget_line(None, 1200)
    assert "~1200 words" in line
    assert "no competitor SERP could be measured" in line
    assert "AUTHORITATIVE" in line


def test_budget_line_empty_without_any_target():
    assert main._length_budget_line(None) == ""
    assert main._length_budget_line({"related_keywords": {}}, None) == ""


# ── _compute_length_fit with a fallback ─────────────────────────────────────

def test_length_fit_grades_against_fallback_target():
    engine = main._compute_length_fit(_page(2400), None, 1200)
    assert engine is not None and engine["measured"]
    assert engine["target_words"] == 1200
    assert engine["page_words"] == 2400
    assert engine["score"] < 50


def test_length_fit_omitted_without_any_target():
    assert main._compute_length_fit(_page(2400), None, None) is None


# ── _length_trim_deficiency ─────────────────────────────────────────────────

def _scores_and_defs(page_words: int, target: int):
    engine = {"measured": True, "page_words": page_words, "target_words": target,
              "score": 10.0, "issues": ["over"], "recommendations": ["cut"]}
    scores = {"length_fit": engine, "organic_ranking": {"score": 80}}
    defs = [{"engine_key": "length_fit", "engine": "Length Fit", "score": 10.0,
             "issues": ["over"], "recommendations": ["cut"]},
            {"engine_key": "organic_ranking", "engine": "Organic", "score": 60}]
    return scores, defs


def test_trim_deficiency_returned_when_over_by_ratio():
    scores, defs = _scores_and_defs(2720, 1627)  # 67% over
    out = main._length_trim_deficiency(scores, defs, 1.4)
    assert out is not None and out["engine_key"] == "length_fit"


def test_trim_deficiency_none_under_ratio():
    scores, defs = _scores_and_defs(1537, 1232)  # 25% over — below the 40% trigger
    assert main._length_trim_deficiency(scores, defs, 1.4) is None


def test_trim_deficiency_none_when_under_length_or_unmeasured():
    scores, defs = _scores_and_defs(800, 1200)
    assert main._length_trim_deficiency(scores, defs, 1.0) is None
    assert main._length_trim_deficiency(None, None, 1.0) is None
    assert main._length_trim_deficiency({"length_fit": {"measured": False}}, defs, 1.0) is None


# ── _length_trim_block ──────────────────────────────────────────────────────

def test_trim_block_names_the_cut_and_lifts_the_no_remove_rule():
    block = main._length_trim_block({"measured": True, "page_words": 2852, "target_words": 1571})
    assert "LENGTH TRIM OVERRIDE" in block
    assert "~1281 words" in block          # 2852 − 1571
    assert "HARD CEILING: 1650" in block    # 1571 × 1.05
    assert "MAY delete" in block
    assert "NEVER remove" in block         # required structure still protected
    assert "Do NOT add" in block


def test_trim_block_empty_when_not_over_or_unmeasured():
    assert main._length_trim_block(None) == ""
    assert main._length_trim_block({"measured": False}) == ""
    assert main._length_trim_block({"measured": True, "page_words": 1000, "target_words": 1200}) == ""


# ── request-model contract ──────────────────────────────────────────────────

def test_request_models_accept_the_fallback_field():
    g = main.GeneratePageRequest(
        keyword="k", location="Melbourne,Victoria,Australia", business_name="B",
        gbp_category="Roofer", address="1 St", length_target=1200,
    )
    assert g.length_target == 1200
    r = main.ReoptimizePageRequest(
        keyword="k", location="Melbourne,Victoria,Australia", existing_page_html="<p>x</p>",
        deficiencies=[], business_name="B", gbp_category="Roofer",
    )
    assert r.length_target is None
