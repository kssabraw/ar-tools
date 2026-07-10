"""Unit tests for services.rank_summary.build_rank_summary — the pure
whole-tracker narrative for the Rankings Overview tab."""

from services.rank_summary import build_rank_summary


def _kw(keyword, *, status="stable", today_rank=None, avg_7=None, avg_30=None,
        clicks_30d=0, impressions_30d=0):
    return {
        "keyword": keyword, "status": status, "today_rank": today_rank,
        "avg_7": avg_7, "avg_30": avg_30, "clicks_30d": clicks_30d,
        "impressions_30d": impressions_30d,
    }


def test_empty_tracker():
    out = build_rank_summary([], client_name="Acme")
    assert out["headline"] == "No keywords tracked yet"
    assert "Acme" in out["narrative"]
    assert out["stats"]["keyword_count"] == 0


def test_counts_page_one_striking_and_avg_position():
    kws = [
        _kw("a", today_rank=3),    # page 1
        _kw("b", today_rank=8),    # page 1
        _kw("c", today_rank=15),   # striking distance (4–20)
        _kw("d", today_rank=45),   # neither
    ]
    out = build_rank_summary(kws, striking_min=4, striking_max=20)
    s = out["stats"]
    assert s["keyword_count"] == 4
    assert s["page_one"] == 2
    assert s["striking"] == 2          # #8 and #15 both fall in 4–20
    assert s["avg_position"] == round((3 + 8 + 15 + 45) / 4, 1)
    assert "4 keywords" in out["narrative"] and "on page 1" in out["narrative"]


def test_named_movers_by_thirty_day_trend():
    kws = [
        # avg_30 12 -> avg_7 4 = improved by 8
        _kw("emergency plumber", status="climbing", avg_7=4, avg_30=12, today_rank=4),
        # avg_30 12 -> avg_7 18 = dropped by 6
        _kw("blocked drain", status="dropping", avg_7=18, avg_30=12, today_rank=18),
        _kw("steady", status="stable", avg_7=5, avg_30=5, today_rank=5),
    ]
    out = build_rank_summary(kws)
    assert out["top_gainer"]["keyword"] == "emergency plumber"
    assert out["top_gainer"]["delta"] == 8.0
    assert out["top_gainer"]["position"] == 4
    assert out["top_decliner"]["keyword"] == "blocked drain"
    assert out["top_decliner"]["delta"] == -6.0
    assert out["stats"]["climbing"] == 1 and out["stats"]["dropping"] == 1
    assert "biggest gain" in out["narrative"] and "emergency plumber" in out["narrative"]


def test_deindex_risk_and_gsc_metrics():
    kws = [
        _kw("a", status="deindex_risk", avg_30=None),
        _kw("b", today_rank=5, clicks_30d=100, impressions_30d=4000),
    ]
    out = build_rank_summary(kws, gsc_connected=True)
    assert out["stats"]["at_risk"] == 1
    assert "deindex risk" in out["narrative"]
    assert "100 clicks and 4,000 impressions" in out["narrative"]


def test_gsc_metrics_hidden_when_not_connected():
    kws = [_kw("a", today_rank=5, clicks_30d=100, impressions_30d=4000)]
    out = build_rank_summary(kws, gsc_connected=False)
    assert "impressions" not in out["narrative"]


def test_no_positions_yet():
    kws = [_kw("a", status="no_data"), _kw("b", status="no_data")]
    out = build_rank_summary(kws)
    assert "awaiting their first ranking data" in out["narrative"]
    assert out["stats"]["avg_position"] is None
