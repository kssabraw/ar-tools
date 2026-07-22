"""Unit tests for the pure illustration logic — density planning, chart integrity,
SVG rendering, and figure interleaving. No OpenAI/Supabase calls exercised."""

from services.illustration import (
    count_words,
    figure_html_image,
    interleave_figures,
    is_eligible_body_section,
    plan_body_count,
    render_bar_chart_svg,
    section_text,
    select_body_anchors,
    strip_html,
    verify_series_integrity,
)


def _sec(order, heading, body, type_=None):
    s = {"order": order, "heading": heading, "body": body}
    if type_:
        s["type"] = type_
    return s


# ── text helpers ─────────────────────────────────────────────────────────────
def test_strip_html_removes_tags_and_entities():
    assert strip_html("<p>Fix <strong>burst</strong> pipes &amp; drains</p>") == "Fix burst pipes & drains"


def test_count_words_across_sections():
    arts = [_sec(1, "Intro", "one two three"), _sec(2, "More", "<p>four five</p>")]
    # headings count too: Intro(1)+3 + More(1)+2 = 7
    assert count_words(arts) == 7


# ── eligibility ──────────────────────────────────────────────────────────────
def test_eligible_requires_heading_and_enough_prose():
    long_body = " ".join(["word"] * 50)
    assert is_eligible_body_section(_sec(1, "Why It Matters", long_body)) is True
    assert is_eligible_body_section(_sec(1, "Why It Matters", "too short")) is False
    assert is_eligible_body_section(_sec(1, "", long_body)) is False


def test_structural_sections_excluded():
    long_body = " ".join(["word"] * 50)
    assert is_eligible_body_section(_sec(9, "Key Takeaways", long_body)) is False
    assert is_eligible_body_section(_sec(9, "Sources Cited", long_body)) is False
    assert is_eligible_body_section(_sec(9, "Frequently Asked Questions", long_body)) is False
    assert is_eligible_body_section(_sec(9, "Conclusion", long_body)) is False
    assert is_eligible_body_section({"order": 9, "heading": "X", "body": long_body, "type": "cta"}) is False


# ── density (owner spec: 1/1000 words, cap 2, floor 1 for real posts) ─────────
def test_plan_body_count_anchors():
    assert plan_body_count(1000, 5) == 1     # 1,000 words -> 1 body (+hero = 2)
    assert plan_body_count(1500, 5) == 1
    assert plan_body_count(2000, 5) == 2
    assert plan_body_count(3000, 5) == 2     # hard cap 2 (total 3)
    assert plan_body_count(9000, 5) == 2


def test_plan_body_count_short_post_floored_to_one():
    assert plan_body_count(700, 3) == 1      # sub-1,000 still gets 1 body
    assert plan_body_count(200, 1) == 1


def test_plan_body_count_zero_when_no_eligible_sections():
    assert plan_body_count(5000, 0) == 0


def test_plan_body_count_capped_by_eligible_sections():
    assert plan_body_count(3000, 1) == 1     # only one place to put a visual


# ── anchor spread ────────────────────────────────────────────────────────────
def test_select_body_anchors_spreads_and_is_sorted():
    eligible = [_sec(o, f"H{o}", "x") for o in (2, 4, 6, 8, 10)]
    anchors = select_body_anchors(eligible, 2)
    assert len(anchors) == 2
    assert anchors == sorted(anchors)
    assert set(anchors).issubset({2, 4, 6, 8, 10})


def test_select_body_anchors_handles_more_than_available():
    eligible = [_sec(2, "A", "x")]
    assert select_body_anchors(eligible, 2) == [2]
    assert select_body_anchors([], 2) == []
    assert select_body_anchors(eligible, 0) == []


# ── chart integrity ──────────────────────────────────────────────────────────
def test_verify_series_integrity_accepts_grounded_values():
    text = "AEO drives 45% of clicks while SEO drives 30% and direct 25%."
    series = [{"label": "AEO", "value": 45}, {"label": "SEO", "value": 30}, {"label": "Direct", "value": 25}]
    assert verify_series_integrity(series, text) is True


def test_verify_series_integrity_rejects_invented_value():
    text = "AEO drives 45% of clicks while SEO drives 30%."
    series = [{"label": "AEO", "value": 45}, {"label": "SEO", "value": 31}]  # 31 not in text
    assert verify_series_integrity(series, text) is False


def test_verify_series_integrity_rejects_single_point_and_nonnumeric():
    assert verify_series_integrity([{"label": "A", "value": 45}], "45% here") is False
    assert verify_series_integrity([{"label": "A", "value": "n/a"}, {"label": "B", "value": 2}], "2 and stuff") is False


def test_verify_series_integrity_matches_comma_grouped_numbers():
    text = "The market grew to 1,200 accounts from 800 last year."
    series = [{"label": "This year", "value": 1200}, {"label": "Last year", "value": 800}]
    assert verify_series_integrity(series, text) is True


# ── SVG ──────────────────────────────────────────────────────────────────────
def test_render_bar_chart_svg_structure():
    svg = render_bar_chart_svg("Clicks by channel", [{"label": "AEO", "value": 45}, {"label": "SEO", "value": 30}], "%")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "Clicks by channel" in svg
    assert svg.count("<rect") == 2          # one bar per series point
    assert "45%" in svg and "30%" in svg


def test_render_bar_chart_svg_empty_series_returns_empty():
    assert render_bar_chart_svg("t", []) == ""


# ── interleave ───────────────────────────────────────────────────────────────
def test_interleave_inserts_figure_after_anchor():
    sections = [_sec(1, "Intro", "a"), _sec(2, "Body", "b"), _sec(3, "End", "c")]
    illus = {"items": [{"anchor_order": 2, "kind": "image", "url": "https://x/y.png", "alt": "y"}]}
    out = interleave_figures(sections, illus)
    orders_types = [(s.get("order"), s.get("type")) for s in out]
    # figure appears immediately after order-2 section
    assert orders_types == [(1, None), (2, None), (2, "figure"), (3, None)]
    fig = [s for s in out if s.get("type") == "figure"][0]
    assert "<figure" in fig["html"] and "https://x/y.png" in fig["html"]


def test_interleave_noop_without_illustrations():
    sections = [_sec(1, "Intro", "a")]
    assert interleave_figures(sections, None) == sections
    assert interleave_figures(sections, {"items": []}) == sections


def test_figure_html_image_escapes_and_wraps():
    html = figure_html_image("https://x/y.png", 'a "quote"', "cap")
    assert html.startswith("<figure") and "figcaption" in html
    assert "&quot;" in html  # alt is attribute-escaped


def test_section_text_joins_heading_and_body():
    assert section_text(_sec(1, "Why", "<p>Because reasons.</p>")) == "Why. Because reasons."
