"""Unit tests for the LABS-style HTML report's pure helpers
(services/brand_report_html): range aggregation, health score, lead valuation,
and the rendered document's key structure."""

from services.brand_report_html import (
    aggregate_range,
    build_lead_valuation,
    health_score,
    render_html,
    score_color,
    score_label,
)


def _row(kid, engine, found, status="completed", conf=0.9, comps=None):
    return {
        "keyword_id": kid, "engine": engine, "status": status,
        "mention_found": found, "confidence_score": conf,
        "competitor_results": comps,
    }


LABELS = {"k1": "emergency plumber sydney", "k2": "roof restoration"}


def test_health_score_formula():
    assert health_score(None, None) is None
    assert health_score(50, 0.8) == round(50 * 0.7 + 0.8 * 30)  # 59
    assert health_score(100, 1.0) == 100
    assert health_score(0, 0.0) == 0


def test_score_bands():
    assert score_label(75) == "Healthy Visibility"
    assert score_label(45) == "Partial Visibility"
    assert score_label(10) == "Critically Invisible"
    assert score_color(75) != score_color(45) != score_color(10)


def test_aggregate_range_counts_and_pcts():
    rows = [
        _row("k1", "chatgpt", True),
        _row("k1", "claude", False),
        _row("k1", "gemini", True, comps=[
            {"name": "Acme", "found": True}, {"name": "FlowFix", "found": False},
        ]),
        _row("k2", "chatgpt", False),
        _row("k2", "claude", False, status="failed"),  # ignored
    ]
    data = aggregate_range(rows, LABELS)
    t = data["totals"]
    assert t["scans"] == 4 and t["mentions"] == 2
    assert t["visibility_pct"] == 50.0
    assert t["health_score"] == health_score(50.0, 0.9)

    engines = {e["engine"]: e for e in data["engines"]}
    assert engines["chatgpt"]["scans"] == 2 and engines["chatgpt"]["mentions"] == 1
    assert engines["claude"]["scans"] == 1  # the failed row didn't count
    assert "google_ai_mode" not in engines  # zero-scan engines omitted

    kws = {k["keyword"]: k for k in data["keywords"]}
    assert kws["emergency plumber sydney"]["scans"] == 3
    assert kws["emergency plumber sydney"]["pct"] == round(100 * 2 / 3, 1)

    comps = {c["name"]: c for c in data["competitors"]}
    assert comps["Acme"]["mentions"] == 1 and comps["FlowFix"]["mentions"] == 0


def test_lead_valuation_math_and_ordering():
    stats = [
        {"keyword": "A", "scans": 4, "mentions": 4},   # no gap → $0
        {"keyword": "B", "scans": 4, "mentions": 2},   # 50% gap
        {"keyword": "C", "scans": 2, "mentions": 0},   # 100% gap
        {"keyword": "D", "scans": 2, "mentions": 1},   # no market data → skipped
    ]
    market = {
        "a": {"search_volume": 1000, "cpc": 2.0},
        "b": {"search_volume": 880, "cpc": 8.2},
        "c": {"search_volume": 320, "cpc": 11.75},
    }
    v = build_lead_valuation(stats, market)
    assert v is not None
    assert v["total"] == round(880 * 8.2 * 0.5 + 320 * 11.75)  # 3608 + 3760
    assert [r["keyword"] for r in v["rows"]] == ["C", "B", "A"]  # cost-desc
    assert v["monthly_searches"] == 2200

    assert build_lead_valuation(stats, {}) is None  # no market data at all


def test_render_html_structure():
    rows = [_row("k1", "chatgpt", True, comps=[{"name": "Acme", "found": True}])]
    data = aggregate_range(rows, LABELS)
    html = render_html(
        client={"name": "Sydney <Emergency> Plumbing", "website_url": "https://sep.example",
                "gbp": {"address": "1 Pipe St", "gbp_rating": 4.8, "gbp_review_count": 41}},
        agency_name="Amazing Rankings",
        date_range_label="Jun 01, 2026 – Jul 01, 2026",
        tracked_keywords=[{"keyword": "emergency plumber sydney", "category": None, "is_active": True}],
        data=data,
        valuation={"total": 3608, "avg_cpc": 8.2, "monthly_searches": 880, "gap_pct": 50,
                   "rows": [{"keyword": "b", "volume": 880, "cpc": 8.2, "gap": 0.5, "cost": 3608}]},
        generated_on="Jul 06, 2026",
    )
    # standalone doc + print CSS
    assert html.startswith("<!DOCTYPE html>") and "@media print" in html
    # section order markers
    for marker in ("AI Visibility Report", "Business Profile", "Global Health Score",
                   "Performance by AI Engine", "Keyword Performance",
                   "Competitor Benchmarking", "Opportunity Cost", "Report generated on"):
        assert marker in html, marker
    # white-label agency name + escaped client name (no raw angle brackets)
    assert "Amazing Rankings" in html
    assert "Sydney &lt;Emergency&gt; Plumbing" in html
    assert "<Emergency>" not in html
    # headings escape exactly once (regression: '&' passed pre-escaped double-escaped)
    assert "Business Profile &amp; Tracked Keywords" in html
    assert "&amp;amp;" not in html
    # "(You)" row present and highlighted before competitors
    assert "(You)" in html


def test_render_html_empty_range():
    data = aggregate_range([], LABELS)
    html = render_html(
        client={"name": "Acme", "website_url": None, "gbp": {}},
        agency_name="Amazing Rankings", date_range_label="range",
        tracked_keywords=[], data=data, valuation=None, generated_on="today",
    )
    assert "No completed scans in this range" in html
    # empty-range report omits the data tables entirely
    assert "Performance by AI Engine" not in html
