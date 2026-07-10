"""Unit tests for services.lead_valuation — the headless volume × CPC ×
visibility-gap engine (UI removed 2026-07-10; engine kept for a future tool)."""

from services.lead_valuation import build_lead_valuation, keyword_visibility_stats

LABELS = {"k1": "emergency plumber", "k2": "roof repair"}


def _row(kid, found, *, status="completed", feature_present=True):
    return {"keyword_id": kid, "status": status, "mention_found": found,
            "feature_present": feature_present}


def test_visibility_stats_folds_and_excludes():
    rows = [
        _row("k1", True),
        _row("k1", False),
        _row("k1", False, status="failed"),           # not completed → excluded
        _row("k1", False, feature_present=False),     # AIO didn't fire → excluded
        _row("k2", True),
        _row("unknown", True),                        # removed keyword → excluded
    ]
    stats = {s["keyword"]: s for s in keyword_visibility_stats(rows, LABELS)}
    assert stats["emergency plumber"] == {"keyword": "emergency plumber", "scans": 2, "mentions": 1}
    assert stats["roof repair"]["scans"] == 1 and stats["roof repair"]["mentions"] == 1
    assert len(stats) == 2


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
    assert v["total"] == round(880 * 8.2 * 0.5 + 320 * 11.75)
    assert [r["keyword"] for r in v["rows"]] == ["C", "B", "A"]  # cost-desc
    assert v["monthly_searches"] == 2200


def test_lead_valuation_none_without_market_or_scans():
    stats = [{"keyword": "A", "scans": 2, "mentions": 1}]
    assert build_lead_valuation(stats, {}) is None
    assert build_lead_valuation([{"keyword": "A", "scans": 0, "mentions": 0}],
                                {"a": {"search_volume": 10, "cpc": 1.0}}) is None
