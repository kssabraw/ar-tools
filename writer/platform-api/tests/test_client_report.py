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
    """Daily rows over ~120 days ending at period_end (a 30-day period): impressions
    climbing, rank improving. Returns (rows, period_start, period_end)."""
    from datetime import date as _d, timedelta as _td
    period_end = _d(2026, 6, 26)
    period_start = period_end - _td(days=30)
    rows = []
    for i in range(120):  # oldest → newest
        day = period_end - _td(days=119 - i)
        rows.append({"date": day.isoformat(), "impressions": 100 + i, "clicks": None,
                     "gsc_position": 30 - (i * 0.1)})
    return rows, period_start, period_end


def test_build_comparisons_period_over_period():
    rows, ps, pe = _series_rows()
    comp = cr.build_comparisons(rows, ps, pe)
    assert comp is not None
    # this period vs the previous same-length period, both present (enough history)
    assert comp["impressions"]["current"] > 0 and comp["impressions"]["previous"] is not None
    assert comp["impressions"]["change"] > 0            # impressions climbed
    assert comp["rank"]["change_positions"] > 0         # rank improved (position fell)
    assert "clicks" not in comp                         # all None → omitted


def test_build_comparisons_empty():
    from datetime import date as _d, timedelta as _td
    pe = _d(2026, 6, 26)
    assert cr.build_comparisons([], pe - _td(days=30), pe) is None


def test_build_comparisons_sources_volume_from_traffic_rows():
    """When traffic_rows is given, impressions/clicks come from it (property-level
    GSC), NOT from the per-keyword metric rows — which can be stale/zero. Rank still
    comes from the metric rows."""
    from datetime import date as _d, timedelta as _td
    pe = _d(2026, 6, 26)
    ps = pe - _td(days=30)
    metric, traffic = [], []
    for i in range(120):
        day = (pe - _td(days=119 - i)).isoformat()
        # per-keyword rows: rank present, traffic zeroed (the stale-feed case)
        metric.append({"date": day, "gsc_position": 30 - (i * 0.1), "impressions": 0, "clicks": 0})
        traffic.append({"date": day, "impressions": 100 + i, "clicks": 5 + i})
    comp = cr.build_comparisons(metric, ps, pe, traffic_rows=traffic)
    assert comp["impressions"]["current"] and comp["impressions"]["current"] > 0
    assert comp["clicks"]["current"] and comp["clicks"]["current"] > 0
    assert comp["rank"]["current"] is not None  # rank still from the metric series


def test_build_comparisons_suppresses_previous_without_coverage():
    """When the data doesn't span the previous period (a young campaign), the
    previous-period figure and change are suppressed — never a partial, misleading
    delta — and the KPI hero doesn't render off it."""
    from datetime import date as _d, timedelta as _td
    pe = _d(2026, 8, 10)
    ps = pe - _td(days=30)
    rows = [
        {"date": (pe - _td(days=37 - i)).isoformat(), "impressions": 1000 + i,
         "clicks": 10 + i, "gsc_position": 8.0}
        for i in range(38)  # data starts ~07-04, before ps(07-11) but not before prev period start
    ]
    comp = cr.build_comparisons(rows, ps, pe)
    assert comp["impressions"]["current"] is not None
    assert comp["impressions"]["previous"] is None
    assert comp["impressions"]["change"] is None
    assert comp["rank"]["previous"] is None
    kpi = cr._kpi_strip(_data(organic={"comparisons": comp, "summary": {"tracked": 5, "top10": 2}}))
    assert "Search visibility" not in kpi  # no hero off a non-comparable metric


def test_section_performance_renders_this_vs_previous():
    rows, ps, pe = _series_rows()
    data = _data(organic={"comparisons": cr.build_comparisons(rows, ps, pe)})
    out = cr.build_report_html(data)
    assert "Performance highlights" in out
    assert "This period" in out and "Previous period" in out and "Change" in out
    assert "Impressions" in out and "Average ranking" in out
    assert "▲" in out  # positive change arrow


def test_section_performance_omits_zero_volume_metric():
    """A volume metric whose current period is 0 (a GSC gap) is dropped rather than
    shown as a scary '0 ▼ -100%'; the ranking row still renders."""
    comp = {
        "impressions": {"current": 0, "previous": 100, "change": -100.0},
        "clicks": {"current": 0, "previous": 5, "change": None},
        "rank": {"current": 7.0, "previous": 8.0, "change_positions": 1.0},
    }
    out = cr._section_performance(_data(organic={"comparisons": comp}))
    assert "Performance highlights" in out
    assert "Average ranking" in out
    assert "Impressions" not in out and "Organic clicks" not in out
    assert "-100" not in out and "100%" not in out


def test_period_over_period_extras_render():
    """Maps presence, AI visibility, and goal movement each show a 'vs previous
    period' comparison."""
    # Maps local-pack presence delta
    geo = _data(geogrid={"keywords": [{"keyword": "x", "average_rank": 5, "top3_pins": 3,
                                        "total_pins": 10, "rank_grid": [[1]]}],
                         "presence_now": 19.0, "presence_prev": 14.0, "weak_areas": []})
    assert "up from 14%" in cr.build_report_html(geo)
    # AI visibility overall delta
    ai = _data(ai_visibility={"engines": {"chatgpt": "8 of 12 answers"},
                              "visibility_now": 71.0, "visibility_prev": 63.0, "keywords": []})
    assert "up from 63%" in cr.build_report_html(ai)
    # Goal movement since last period (clicks goal is date-aware)
    g = {"goal_type": "organic_clicks", "label": "Clicks", "status": "achieved",
         "progress_pct": 100.0, "current_value": 257, "previous_value": 129, "target_value": 40}
    html = cr._section_goals({"goals": {"goals": [g]}})
    assert "since last period" in html and "128" in html  # 257 - 129


# ---------------------------------------------------------------------------
# AI visibility section (auto-populates once scans run)
# ---------------------------------------------------------------------------
def test_section_ai_visibility():
    assert cr._section_ai_visibility(_data()) == ""
    data = _data(ai_visibility={"engines": {"chatgpt": "3 of 5 answers", "perplexity": "1 of 5 answers"}})
    out = cr.build_report_html(data)
    assert "AI search visibility" in out
    assert "ChatGPT" in out and "3 of 5 answers" in out


def test_section_ai_visibility_per_keyword_matrix():
    data = _data(ai_visibility={
        "engines": {"chatgpt": "2 of 2 answers"},
        "keywords": [
            {"keyword": "best managed IT services near me",
             "engines": {"chatgpt": True, "claude": True, "perplexity": False},
             "found_count": 2, "total": 3},
            {"keyword": "emergency it support downtown",
             "engines": {"chatgpt": False, "claude": False}, "found_count": 0, "total": 2},
        ],
    })
    out = cr.build_report_html(data)
    # per-query matrix present, with specific query text + a per-query score
    assert "Which AI tools recommend you" in out
    assert "best managed IT services near me" in out and "2/3" in out
    # engine chips labelled
    assert "ChatGPT" in out and "Perplexity" in out
    # the brand-invisible query is surfaced as a forward-looking opportunity
    assert "Room to grow" in out and "emergency it support downtown" in out


# ---------------------------------------------------------------------------
# _keyword_change (positions gained; positive = improved)
# ---------------------------------------------------------------------------
def test_keyword_change_from_averages_and_sparkline():
    # 30d avg 8, 7d avg 5 → improved by 3 positions
    assert cr._keyword_change({"avg_7": 5.0, "avg_30": 8.0}) == 3.0
    # no averages → first−last of sparkline (12 → 4 = +8 improvement)
    assert cr._keyword_change({"avg_7": None, "avg_30": None, "sparkline": [12, 9, 4]}) == 8.0
    # too little history → None
    assert cr._keyword_change({"sparkline": [4]}) is None


# ---------------------------------------------------------------------------
# organic section trims to top movers + Movement column
# ---------------------------------------------------------------------------
def test_section_organic_shows_top_movers_only():
    kws = [{"keyword": f"kw{i}", "current_rank": 5, "avg_30d": 5,
            "change": float(i), "sparkline": [9, 5]} for i in range(10)]
    data = _data(organic={"keywords": kws,
                          "summary": {"tracked": 10, "top10": 4, "improved": 6, "declined": 1}})
    out = cr.build_report_html(data)
    assert "Movement" in out
    # biggest gainer (kw9, change 9) shown; smallest non-mover trimmed
    assert "kw9" in out and "kw1<" not in out
    assert "remaining 5 are tracked" in out


def test_section_organic_leads_with_wins_not_lone_decliner():
    """Positive framing: feature the strongest rankings, never headline a keyword
    purely because it slipped, and no negative ('to watch') copy."""
    wins = [{"keyword": f"win{i}", "current_rank": r, "change": None, "sparkline": []}
            for i, r in enumerate([3, 4, 5, 8, 10])]
    decliner = {"keyword": "slipped kw", "current_rank": 12, "change": -2.0, "sparkline": [10, 12]}
    data = _data(organic={"keywords": wins + [decliner],
                          "summary": {"tracked": 40, "top10": 5, "improved": 0, "declined": 1}})
    out = cr.build_report_html(data)
    assert "win0" in out and "win4" in out          # strongest rankings featured
    assert "slipped kw" not in out                   # lone poor-ranked decliner not featured
    assert "to watch" not in out                     # no negative summary copy
    assert "ranking on page 1 of Google" in out


def test_section_organic_does_not_pad_with_decliner():
    """The real WheelHouse case: only 4 page-1 keywords, and the 5th-best rank is a
    mid-pack decliner. It must NOT be pulled into the table just to reach 5 rows."""
    kws = [{"keyword": "w1", "current_rank": 3, "change": None, "sparkline": []},
           {"keyword": "w2", "current_rank": 4, "change": None, "sparkline": []},
           {"keyword": "w3", "current_rank": 5, "change": None, "sparkline": []},
           {"keyword": "w4", "current_rank": 8, "change": None, "sparkline": []},
           {"keyword": "decliner kw", "current_rank": 12, "change": -2.0, "sparkline": [10, 12]}]
    data = _data(organic={"keywords": kws, "summary": {"tracked": 40, "top10": 4, "improved": 0, "declined": 1}})
    out = cr.build_report_html(data)
    assert "w1" in out and "w4" in out
    assert "decliner kw" not in out
    assert "-2 positions" not in out


def test_gbp_review_period_renders():
    """GBP section shows new reviews this vs last period, a rating climb, and
    recent-review highlights (positive framing)."""
    data = _data(gbp={
        "business_name": "WheelHouse IT", "address": "Fort Lauderdale",
        "rating": 4.6, "review_count": 84, "top_reviews": ["generic old review"],
        "review_period": {
            "reviews_this": 6, "reviews_prev": 4,
            "rating_now": 4.6, "rating_prev": 4.5,
            "highlights": ["Fantastic team, fixed our servers fast"],
        },
    })
    out = cr.build_report_html(data)
    assert "Google Business Profile" in out
    assert "gained" in out and "6" in out and "vs 4 the previous period" in out
    assert "up from 4.5★" in out
    assert "Recent reviews this period" in out and "Fantastic team" in out
    # the generic top-review list is dropped when we have this-period highlights
    assert "generic old review" not in out


def test_gbp_review_period_absent_degrades():
    # no review_period → section still renders with rating/reviews, no crash
    data = _data(gbp={"business_name": "X", "rating": 4.6, "review_count": 84,
                      "top_reviews": ["nice"], "review_period": None})
    out = cr.build_report_html(data)
    assert "Google Business Profile" in out and "nice" in out
    assert "gained" not in out


def test_positive_framing_reframes_weaknesses():
    # Maps weak areas → opportunity language
    geo = _data(geogrid={"keywords": [{"keyword": "x", "average_rank": 5, "top3_pins": 3,
                                        "total_pins": 10, "rank_grid": [[1]]}],
                         "weak_areas": ["Davie", "Plantation"]})
    out = cr.build_report_html(geo)
    assert "room to grow" in out.lower() and "Weakest" not in out
    # AI invisible-questions callout → forward-looking, not "isn't appearing yet"
    ai = _data(ai_visibility={"engines": {"chatgpt": "0 of 1 answers"},
                              "keywords": [{"keyword": "foo bar",
                                            "engines": {"chatgpt": False}, "found_count": 0, "total": 1}]})
    out2 = cr.build_report_html(ai)
    assert "Room to grow" in out2 and "isn’t appearing yet" not in out2


# ---------------------------------------------------------------------------
# Work delivered section
# ---------------------------------------------------------------------------
def test_section_work_delivered():
    assert cr._section_work_delivered(_data()) == ""
    data = _data(work_delivered={"counts": {"blog_post": 3, "local_seo_page": 2}, "total": 5})
    out = cr.build_report_html(data)
    assert "Work delivered this period" in out
    assert "Blog posts" in out and "Local SEO pages" in out


# ---------------------------------------------------------------------------
# At-a-glance KPI strip
# ---------------------------------------------------------------------------
def test_kpi_strip_renders_present_metrics():
    assert cr._kpi_strip(_data()) == ""
    data = _data(
        organic={"comparisons": {"impressions": {"current": 100, "previous": 80, "change": 24.0},
                                 "rank": {"current": 5, "previous": 8, "change_positions": 3.0}},
                 "summary": {"tracked": 12, "top10": 5}},
        work_delivered={"counts": {"blog_post": 4}, "total": 4},
    )
    out = cr._kpi_strip(data)
    assert "Search visibility" in out and "+24%" in out
    assert "Ranking gains" in out
    assert "On page 1 of Google" in out and "5" in out
    assert "Content delivered" in out


# ---------------------------------------------------------------------------
# White-label footer
# ---------------------------------------------------------------------------
def test_footer_is_white_labeled():
    out = cr.build_report_html(_data(agency_name="Amazing Rankings"))
    assert "Prepared by Amazing Rankings" in out
    assert "AR Tools" not in out


# ---------------------------------------------------------------------------
# Goal scorecard (client-facing) — _section_goals / _fmt_goal_value
# ---------------------------------------------------------------------------
def _goals(*gs):
    return {"goals": {"goals": list(gs)}}


def test_section_goals_renders_and_softens_status():
    data = _goals(
        {"goal_type": "keyword_position", "label": "Rank roof repair", "status": "behind",
         "progress_pct": 20.0, "current_value": 8, "target_value": 3, "due_date": "2026-12-31"},
    )
    html = cr._section_goals(data)
    assert "Progress toward your goals" in html
    assert "Rank roof repair" in html
    # client-facing softening: "behind" is never shown; "In progress" is.
    assert "In progress" in html and "BEHIND" not in html


def test_section_goals_shows_pace_marker():
    """The bar carries an 'expected by now' marker at elapsed%, so a short bar +
    a status label no longer look contradictory to a client."""
    data = _goals(
        {"goal_type": "maps_pack_presence", "label": "Local-pack presence", "status": "behind",
         "progress_pct": 5.0, "elapsed_pct": 19.0, "current_value": 11.5, "target_value": 25,
         "due_date": "2026-12-31"},
    )
    html = cr._section_goals(data)
    assert "gmark" in html and "left:19%" in html
    assert "In progress" in html  # softened 'behind'


def test_section_goals_drops_no_data_and_shows_achieved():
    data = _goals(
        {"goal_type": "organic_clicks", "label": "Clicks", "status": "achieved",
         "progress_pct": 100.0, "current_value": 900, "target_value": 800},
        {"goal_type": "maps_pack_presence", "label": "Maps", "status": "no_data",
         "current_value": None, "target_value": 50},
    )
    html = cr._section_goals(data)
    assert "Achieved" in html and "900 clicks/mo" in html
    assert "Maps" not in html          # no_data goal is dropped from the client report


def test_section_goals_empty_when_nothing_measurable():
    assert cr._section_goals(_goals()) == ""
    assert cr._section_goals({}) == ""


def test_fmt_goal_value_by_type():
    assert cr._fmt_goal_value("keyword_position", 3) == "position 3"
    assert cr._fmt_goal_value("ai_visibility", 40) == "40%"
    assert cr._fmt_goal_value("keyword_position", None) == "—"


# ---------------------------------------------------------------------------
# GA4 website-traffic section (Client Reporting Phase 2)
# ---------------------------------------------------------------------------
from datetime import date as _date  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402


def _fake_ga4_supabase(properties, daily):
    """Chainable supabase stub for _gather_ga4: ga4_properties + ga4_daily reads."""
    def table(name):
        t = MagicMock()
        for m in ("select", "eq", "gte", "order", "limit"):
            getattr(t, m).return_value = t
        t.execute.return_value = MagicMock(
            data=properties if name == "ga4_properties" else daily
        )
        return t

    sb = MagicMock()
    sb.table.side_effect = table
    return sb


_GA4_DAILY = [
    {"date": "2026-04-01", "sessions": 10, "total_users": 8, "screen_page_views": 20,
     "conversions": None, "channels": {"Direct": 10}},
    {"date": "2026-04-15", "sessions": 50, "total_users": 40, "screen_page_views": 100,
     "conversions": 1, "channels": {"Organic Search": 50}},
    {"date": "2026-05-15", "sessions": 100, "total_users": 70, "screen_page_views": 250,
     "conversions": 3, "channels": {"Organic Search": 60, "Direct": 40}},
    {"date": "2026-05-20", "sessions": 80, "total_users": 55, "screen_page_views": 180,
     "conversions": 2, "channels": {"Organic Search": 50, "Direct": 30}},
]


def test_gather_ga4_none_without_property():
    sb = _fake_ga4_supabase([], _GA4_DAILY)
    assert cr._gather_ga4(sb, "c1", _date(2026, 5, 1), _date(2026, 5, 31)) is None


def test_gather_ga4_none_without_data():
    sb = _fake_ga4_supabase([{"id": "p1"}], [])
    assert cr._gather_ga4(sb, "c1", _date(2026, 5, 1), _date(2026, 5, 31)) is None


def test_gather_ga4_computes_period_and_channels():
    sb = _fake_ga4_supabase([{"id": "p1"}], _GA4_DAILY)
    out = cr._gather_ga4(sb, "c1", _date(2026, 5, 1), _date(2026, 5, 31))
    assert out is not None
    # current sessions = 100 + 80 = 180; previous (04-01<d<=05-01) = 50
    assert out["sessions"]["current"] == 180
    assert out["sessions"]["previous"] == 50
    assert out["sessions"]["change"] == 260.0
    assert out["conversions"]["current"] == 5
    # channels aggregated over the report window, ranked, with share %
    names = [c["name"] for c in out["channels"]]
    assert names[0] == "Organic Search"  # 110 > 70
    organic = next(c for c in out["channels"] if c["name"] == "Organic Search")
    assert organic["sessions"] == 110
    assert organic["pct"] == 61  # round(110/180*100)


def test_section_ga4_empty_without_data():
    assert cr._section_ga4(_data()) == ""


def test_section_ga4_renders_visits_and_channels():
    data = _data(ga4={
        "sessions": {"current": 180, "previous": 50, "change": 260.0},
        "users": {"current": 125, "previous": 40, "change": 212.5},
        "conversions": {"current": 5, "previous": 1, "change": 400.0},
        "channels": [{"name": "Organic Search", "sessions": 110, "pct": 61},
                     {"name": "Direct", "sessions": 70, "pct": 39}],
    })
    html = cr._section_ga4(data)
    assert "Website traffic" in html
    assert "Website visits" in html and "180" in html
    assert "Organic Search" in html and "61%" in html


def test_section_ga4_omits_zero_current_metric():
    data = _data(ga4={"sessions": {"current": 0, "previous": 5, "change": -100.0}, "channels": []})
    assert cr._section_ga4(data) == ""


def test_build_html_includes_ga4_section():
    data = _data(ga4={"sessions": {"current": 180, "previous": 50, "change": 260.0}, "channels": []})
    assert "Website traffic" in cr.build_report_html(data)


def test_kpi_strip_includes_ga4_visits_on_gain():
    data = _data(ga4={"sessions": {"current": 180, "previous": 50, "change": 260.0}, "channels": []})
    html = cr._kpi_strip(data)
    assert "Website visits" in html


def test_kpi_strip_omits_ga4_visits_when_flat_or_down():
    data = _data(ga4={"sessions": {"current": 50, "previous": 80, "change": -37.5}, "channels": []})
    assert "Website visits" not in cr._kpi_strip(data)
