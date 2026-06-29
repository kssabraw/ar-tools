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
# campaign-health executive summary (Phase 4)
# ---------------------------------------------------------------------------
def test_health_color():
    assert cr._health_color("Strong") == "#16a34a"
    assert cr._health_color("At risk") == "#ef4444"
    assert cr._health_color(None) == "#6366f1"


def test_section_health_empty_without_data():
    assert cr._section_health(_data()) == ""


def test_section_health_renders_and_escapes():
    data = _data(health={
        "overall_health": "Needs attention", "health_score": 62,
        "headline": "Rankings <b>steady</b> but local pack slipping.",
        "wins": ["Top-3 for emergency plumber"],
        "risks": ["Lost page 1 for blocked drains"],
        "next_steps": ["Reoptimize the drains page"],
    })
    out = cr.build_report_html(data)
    assert "Executive summary" in out
    assert "Needs attention · 62/100" in out
    assert "Top-3 for emergency plumber" in out and "Reoptimize the drains page" in out
    # the executive summary renders first (before Organic etc.)
    assert out.index("Executive summary") < out.index("No report data is available") \
        if "No report data is available" in out else True
    # headline is escaped
    assert "<b>steady</b>" not in out and "&lt;b&gt;steady&lt;/b&gt;" in out


def test_generate_health_narrative_no_key_returns_none(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert cr.generate_health_narrative("Acme", {"start": "x", "end": "y"}, {}, {}) is None
