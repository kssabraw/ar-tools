"""Unit tests for deterministic charts (blog_media.charts): value/source
validation against the article, structural rules, and SVG rendering."""
from services.blog_media import charts as c


def _pt(label, value, display, quote, name="Xponent21", **extra):
    d = {"label": label, "value": value, "display_value": display,
         "source_quote": quote, "source_name": name, "derived": False}
    d.update(extra)
    return d


def _chart(ctype, pts, **over):
    ch = {"type": ctype, "series": [{"name": "s", "data": pts}], "title": "T", "source_name": "Xponent21"}
    ch.update(over)
    return ch


def _article(*quotes):
    return "Intro. " + " ".join(quotes) + " Outro."


# ── validation ───────────────────────────────────────────────────────────────


def test_valid_bar_passes():
    q1 = "AI Overviews now appear in 60.32% of U.S. queries"
    q2 = "The prior year figure stood at 25% of queries"
    ch = _chart("bar", [_pt("2026", 60.32, "60.32%", q1), _pt("2025", 25, "25%", q2)])
    ok, reason = c.validate_chart_spec(ch, article_text=_article(q1, q2), allow_derived=False)
    assert ok and reason is None


def test_source_quote_must_be_in_article():
    q1 = "AI Overviews now appear in 60.32% of U.S. queries"
    ch = _chart("bar", [_pt("a", 60.32, "60.32%", q1), _pt("b", 25, "25%", "a quote not present anywhere")])
    ok, reason = c.validate_chart_spec(ch, article_text=_article(q1), allow_derived=False)
    assert not ok and reason == "source_quote_not_in_article"


def test_value_must_appear_in_quote():
    q = "AI Overviews appear in most U.S. queries"  # no number
    ch = _chart("bar", [_pt("a", 60.32, "60.32%", q), _pt("b", 25, "25%", q)])
    ok, reason = c.validate_chart_spec(ch, article_text=_article(q), allow_derived=False)
    assert not ok and reason == "value_not_present_in_quote"


def test_line_needs_three_ordered_dated_points():
    q1, q2 = "value was 10 in jan", "value was 20 in feb"
    ch = _chart("line", [_pt("jan", 10, "10", q1, date="2026-01"), _pt("feb", 20, "20", q2, date="2026-02")])
    ok, reason = c.validate_chart_spec(ch, article_text=_article(q1, q2), allow_derived=False)
    assert not ok and reason == "line_needs_three_points"


def test_donut_must_total_100():
    q1, q2 = "share was 60 percent", "other share was 25 percent"
    ch = _chart("donut", [_pt("a", 60, "60%", q1), _pt("b", 25, "25%", q2)])
    ok, reason = c.validate_chart_spec(ch, article_text=_article(q1, q2), allow_derived=False)
    assert not ok and reason == "donut_values_do_not_total_100"


def test_donut_with_derived_remainder_ok_when_enabled():
    q1 = "AI Overviews now appear in 60.32% of U.S. queries"
    pts = [
        _pt("With AIO", 60.32, "60.32%", q1),
        {"label": "Without", "value": 39.68, "display_value": "39.68%", "derived": True,
         "formula": "100 - 60.32", "derivation_explanation": "remainder of the whole"},
    ]
    ch = _chart("donut", pts)
    ok, reason = c.validate_chart_spec(ch, article_text=_article(q1), allow_derived=True)
    assert ok, reason
    # same chart rejected when derivations disabled
    ok2, reason2 = c.validate_chart_spec(ch, article_text=_article(q1), allow_derived=False)
    assert not ok2 and reason2 == "derived_values_not_allowed"


def test_single_stat_requires_one_value():
    q = "AI Overviews now appear in 60.32% of U.S. queries"
    ch = _chart("single_stat", [_pt("a", 60.32, "60.32%", q), _pt("b", 25, "25%", q)])
    ok, reason = c.validate_chart_spec(ch, article_text=_article(q), allow_derived=False)
    assert not ok and reason == "single_stat_requires_one_value"


def test_unsupported_type_rejected():
    ok, reason = c.validate_chart_spec({"type": "pie", "series": []}, article_text="x", allow_derived=False)
    assert not ok and reason == "unsupported_type"


# ── rendering ────────────────────────────────────────────────────────────────


def _valid_bar():
    q1 = "AI Overviews now appear in 60.32% of U.S. queries"
    q2 = "The prior year figure stood at 25% of queries"
    return _chart("bar", [_pt("2026", 60.32, "60.32%", q1), _pt("2025", 25, "25%", q2)],
                  subtitle="Tracked U.S. queries")


def test_render_bar_svg_structure():
    svg = c.render_chart_svg(_valid_bar())
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "<rect" in svg and "Source: Xponent21" in svg and ">T<" in svg
    assert "60.32%" in svg


def test_render_line_has_polyline():
    q = ["v 10 jan", "v 20 feb", "v 30 mar"]
    ch = _chart("line", [
        _pt("jan", 10, "10", q[0], date="2026-01"),
        _pt("feb", 20, "20", q[1], date="2026-02"),
        _pt("mar", 30, "30", q[2], date="2026-03"),
    ])
    assert "<polyline" in c.render_chart_svg(ch)


def test_render_donut_has_path_and_legend():
    svg = c.render_chart_svg(_chart("donut", [
        {"label": "A", "value": 60, "display_value": "60%"},
        {"label": "B", "value": 40, "display_value": "40%"},
    ]))
    assert "<path" in svg and "A — 60%" in svg


def test_render_single_stat_big_number():
    svg = c.render_chart_svg(_chart("single_stat", [{"label": "queries", "value": 60.32, "display_value": "60.32%"}]))
    assert "60.32%" in svg and 'font-size="150"' in svg


def test_render_horizontal_bar_and_scatter():
    hbar = c.render_chart_svg(_chart("horizontal_bar", [
        {"label": "A", "value": 5, "display_value": "5"}, {"label": "B", "value": 9, "display_value": "9"}]))
    assert "<rect" in hbar
    scatter = c.render_chart_svg(_chart("scatter", [
        {"x": 1, "y": 2, "value": 2}, {"x": 3, "y": 4, "value": 4}]))
    assert "<circle" in scatter


def test_theme_colors_whitelisted_to_hex():
    evil = _chart("bar", [
        {"label": "A", "value": 5, "display_value": "5"},
        {"label": "B", "value": 9, "display_value": "9"},
    ], theme={"secondary_color": '#fff" onload="alert(1)', "primary_color": "#123abc"})
    svg = c.render_chart_svg(evil)
    assert "onload" not in svg           # injection neutralized → default color
    assert "#123abc" in svg or "#" in svg  # valid hex kept


def test_scatter_without_xy_rejected():
    q1, q2 = "value pair one is 2", "value pair two is 4"
    no_xy = _chart("scatter", [_pt("a", 2, "2", q1), _pt("b", 4, "4", q2)])
    ok, reason = c.validate_chart_spec(no_xy, article_text=_article(q1, q2), allow_derived=False)
    assert not ok and reason == "scatter_missing_xy"
    with_xy = _chart("scatter", [_pt("a", 2, "2", q1, x=1, y=2), _pt("b", 4, "4", q2, x=3, y=4)])
    ok2, _ = c.validate_chart_spec(with_xy, article_text=_article(q1, q2), allow_derived=False)
    assert ok2


def test_render_stacked_bar_multi_series_with_legend():
    ch = {
        "type": "stacked_bar", "title": "T", "source_name": "X",
        "series": [
            {"name": "Organic", "data": [{"label": "2025", "value": 30, "display_value": "30"},
                                          {"label": "2026", "value": 40, "display_value": "40"}]},
            {"name": "Paid", "data": [{"label": "2025", "value": 10, "display_value": "10"},
                                       {"label": "2026", "value": 20, "display_value": "20"}]},
        ],
    }
    svg = c.render_chart_svg(ch)
    assert svg.count("<rect") >= 5  # background + 4 stacked segments + legend chips
    assert "Organic" in svg and "Paid" in svg


def test_axis_labels_rendered_when_provided():
    ch = _valid_bar()
    ch["x_axis"] = {"label": "Year", "type": "category"}
    ch["y_axis"] = {"label": "Share", "unit": "%", "start_at_zero": True}
    svg = c.render_chart_svg(ch)
    assert ">Year<" in svg
    assert "Share (%)" in svg and "rotate(-90" in svg
