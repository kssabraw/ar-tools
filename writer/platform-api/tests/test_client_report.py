"""Unit tests for the Client Reporting pure builders (no network, no WeasyPrint)."""

from __future__ import annotations

from services import client_report as cr


# ---------------------------------------------------------------------------
# _rank_color
# ---------------------------------------------------------------------------
def test_rank_color_tiers():
    assert cr._rank_color(1) == "#16a34a"
    assert cr._rank_color(3) == "#16a34a"
    assert cr._rank_color(7) == "#84cc16"
    assert cr._rank_color(15) == "#f59e0b"
    assert cr._rank_color(40) == "#ef4444"
    assert cr._rank_color(None) == "#e5e7eb"
    assert cr._rank_color("x") == "#e5e7eb"


# ---------------------------------------------------------------------------
# svg_sparkline
# ---------------------------------------------------------------------------
def test_sparkline_needs_two_points():
    assert cr.svg_sparkline([]) == ""
    assert cr.svg_sparkline([5]) == ""
    assert cr.svg_sparkline([None, None]) == ""


def test_sparkline_renders_polyline_and_skips_none():
    out = cr.svg_sparkline([10, None, 6, 4])
    assert out.startswith("<svg") and "<polyline" in out
    assert out.count(",") >= 2  # 3 numeric points → coordinate pairs
    # improving series (ends lower than it starts) → green stroke
    assert "#16a34a" in out


def test_sparkline_declining_is_red():
    assert "#ef4444" in cr.svg_sparkline([2, 5, 9])


# ---------------------------------------------------------------------------
# svg_geogrid
# ---------------------------------------------------------------------------
def test_geogrid_empty_inputs():
    assert cr.svg_geogrid(None) == ""
    assert cr.svg_geogrid([]) == ""
    assert cr.svg_geogrid("nope") == ""


def test_geogrid_renders_cells_with_absent_color():
    out = cr.svg_geogrid([[1, None], [12, 30]])
    assert out.startswith("<svg")
    assert out.count("<rect") == 4
    assert "#16a34a" in out and "#e5e7eb" in out and "#ef4444" in out


# ---------------------------------------------------------------------------
# _weak_area_names (object / list / None tolerant)
# ---------------------------------------------------------------------------
def test_weak_area_names_object_and_list_and_none():
    obj = {"weak_areas": [{"city": "Port Melbourne"}, {"city": "Toorak"}, {"pins": 1}]}
    assert cr._weak_area_names(obj) == ["Port Melbourne", "Toorak"]
    assert cr._weak_area_names([{"city": "A"}, {"city": "A"}, {"city": "B"}]) == ["A", "B"]
    assert cr._weak_area_names(None) == []


# ---------------------------------------------------------------------------
# _fmt_pos
# ---------------------------------------------------------------------------
def test_fmt_pos():
    assert cr._fmt_pos(None) == "—"
    assert cr._fmt_pos(3) == "3"
    assert cr._fmt_pos(4.25) == "4.2"
    assert cr._fmt_pos("bad") == "—"


# ---------------------------------------------------------------------------
# build_report_html
# ---------------------------------------------------------------------------
def _data(**over):
    base = {
        "client": {"name": "Acme Plumbing", "website_url": "https://acme.com", "logo_url": None},
        "period": {"start": "2026-05-01", "end": "2026-05-31"},
        "section_status": {},
    }
    base.update(over)
    return base


def test_build_html_empty_has_no_data_notice():
    out = cr.build_report_html(_data())
    assert "Acme Plumbing" in out and "2026-05-01" in out
    assert "No report data is available" in out


def test_build_html_includes_present_sections():
    data = _data(
        organic={"keywords": [{"keyword": "emergency plumber", "current_rank": 4,
                               "avg_30d": 5.2, "sparkline": [6, 5, 4]}],
                 "summary": {"tracked": 1, "top10": 1, "improved": 1, "declined": 0}},
        gbp={"business_name": "Acme Plumbing", "address": "1 St", "rating": 4.8,
             "review_count": 120, "top_reviews": ["Great service"]},
    )
    out = cr.build_report_html(data)
    assert "Organic rankings" in out
    assert "emergency plumber" in out
    assert "Google Business Profile" in out
    assert "4.8" in out and "Great service" in out
    assert "No report data is available" not in out
    # escaping: a malicious review can't inject markup
    data["gbp"]["top_reviews"] = ["<script>x</script>"]
    assert "<script>x</script>" not in cr.build_report_html(data)
    assert "&lt;script&gt;" in cr.build_report_html(data)


# ---------------------------------------------------------------------------
# executive summary (Phase 4 — positive, owner-friendly, no health label)
# ---------------------------------------------------------------------------
def test_section_exec_empty_without_data():
    assert cr._section_exec(_data()) == ""


def test_section_exec_renders_positive_no_health_label_and_escapes():
    data = _data(exec={
        "headline": "Strong month — visibility <b>up</b> across the board.",
        "highlights": ["Impressions up 24% vs last month"],
        "focus_next": ["Expand the drains page to win more local searches"],
    })
    out = cr.build_report_html(data)
    assert "Executive summary" in out
    assert "Impressions up 24% vs last month" in out
    assert "focused on next" in out and "Expand the drains page" in out
    # no health label / score / risks wording
    assert "/100" not in out and "Risks" not in out
    # headline escaped
    assert "<b>up</b>" not in out and "&lt;b&gt;up&lt;/b&gt;" in out


def test_generate_exec_summary_no_key_returns_none(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert cr.generate_exec_summary("Acme", {"start": "x", "end": "y"}, {}, {}) is None


# ---------------------------------------------------------------------------
# build_comparisons (30 / 90 / since-start) + performance section
# ---------------------------------------------------------------------------
def _series_rows():
    """Daily rows over ~120 days: impressions climbing, rank improving."""
    from datetime import date as _d, timedelta as _td
    today = _d(2026, 6, 26)
    rows = []
    for i in range(120):  # oldest → newest
        day = today - _td(days=119 - i)
        rows.append({"date": day.isoformat(), "impressions": 100 + i, "clicks": None,
                     "gsc_position": 30 - (i * 0.1)})
    return rows, today


def test_build_comparisons_volume_and_rank():
    rows, today = _series_rows()
    comp = cr.build_comparisons(rows, today)
    assert comp is not None
    assert comp["impressions"]["current"] is not None
    # impressions trended up → all changes positive
    ch = comp["impressions"]["changes"]
    assert ch["30d"] > 0 and ch["90d"] > 0 and ch["start"] > 0
    # rank improved (position number fell) → positive "positions gained"
    assert comp["rank"]["changes_positions"]["start"] > 0
    # clicks were all None → omitted
    assert "clicks" not in comp


def test_build_comparisons_empty():
    assert cr.build_comparisons([], cr.date.today()) is None


def test_section_performance_renders_changes():
    rows, today = _series_rows()
    data = _data(organic={"comparisons": cr.build_comparisons(rows, today)})
    out = cr.build_report_html(data)
    assert "Performance highlights" in out
    assert "Impressions" in out and "Average ranking" in out
    assert "Since we started" in out
    assert "▲" in out  # positive change arrow


# ---------------------------------------------------------------------------
# AI visibility section (auto-populates once scans run)
# ---------------------------------------------------------------------------
def test_section_ai_visibility():
    assert cr._section_ai_visibility(_data()) == ""
    data = _data(ai_visibility={"engines": {"chatgpt": "3 of 5 answers", "perplexity": "1 of 5 answers"}})
    out = cr.build_report_html(data)
    assert "AI search visibility" in out
    assert "ChatGPT" in out and "3 of 5 answers" in out
