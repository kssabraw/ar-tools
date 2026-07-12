"""Unit tests for the Domain Intelligence pure core.

Covers the DataForSEO Labs response parsers (services.dataforseo_labs) and the
gap/scoring/overview math (services.domain_intel). No I/O.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services import dataforseo_labs as labs
from services import domain_intel as di


# ===========================================================================
# dataforseo_labs — pure helpers
# ===========================================================================
def test_domain_of_and_rank_to_rating():
    assert labs.domain_of("https://www.Example.com/path") == "example.com"
    assert labs.domain_of("example.com") == "example.com"
    assert labs.domain_of(None) is None
    assert labs.rank_to_rating(824) == 82.4
    assert labs.rank_to_rating(None) is None
    assert labs.rank_to_rating("bad") is None


def test_chunk_splits_at_size():
    assert labs.chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert labs.chunk([], 3) == []


def _ranked_body(items):
    return {"tasks": [{"status_code": 20000, "cost": 0.02,
                       "result": [{"items": items}]}]}


def test_parse_ranked_keywords_extracts_nested_fields():
    body = _ranked_body([
        {
            "keyword_data": {
                "keyword": "roof repair sydney",
                "keyword_info": {"search_volume": 1300, "cpc": 8.5},
                "keyword_properties": {"keyword_difficulty": 34},
                "search_intent_info": {"main_intent": "commercial"},
            },
            "ranked_serp_element": {"serp_item": {"rank_absolute": 4, "url": "https://x.com/roof"}},
        },
        {"not_a_dict": True},                       # skipped
        {"keyword_data": {"keyword_info": {}}},     # no keyword → skipped
    ])
    rows = labs.parse_ranked_keywords(body)
    assert len(rows) == 1
    r = rows[0]
    assert r["keyword"] == "roof repair sydney"
    assert r["position"] == 4
    assert r["url"] == "https://x.com/roof"
    assert r["volume"] == 1300
    assert r["cpc_usd"] == 8.5
    assert r["keyword_difficulty"] == 34.0
    assert r["search_intent"] == "commercial"
    assert labs.cost_of(body) == 0.02


def test_parse_domain_rank_overview_reads_organic_metrics():
    body = {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"metrics": {"organic": {"etv": 5123.4, "count": 812, "pos_1": 40}}}
    ]}]}]}
    out = labs.parse_domain_rank_overview(body)
    assert out["organic_traffic_est"] == 5123.4
    assert out["ranked_keyword_count"] == 812
    assert out["organic_pos_1"] == 40


def test_parse_competitors_domain_normalizes_and_reads_metrics():
    body = {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"domain": "https://www.Rival.com", "avg_position": 7.2, "intersections": 55,
         "metrics": {"organic": {"count": 300, "etv": 900.0}}},
        {"nope": 1},
    ]}]}]}
    out = labs.parse_competitors_domain(body)
    assert len(out) == 1
    assert out[0]["domain"] == "rival.com"
    assert out[0]["intersections"] == 55
    assert out[0]["organic_keywords"] == 300


def test_parse_raises_on_task_error():
    body = {"tasks": [{"status_code": 40001, "status_message": "boom", "result": []}]}
    try:
        labs.parse_ranked_keywords(body)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "boom" in str(exc)


# ===========================================================================
# domain_intel — scoring & classification
# ===========================================================================
def test_enrich_est_value_uses_ctr_curve():
    rows = [{"keyword": "k", "position": 1, "volume": 1000, "cpc_usd": 2.0}]
    out = di.enrich_est_value(rows)
    # position 1 CTR 0.281 × 1000 × 2.0
    assert out[0]["est_value"] == round(1000 * 0.281 * 2.0, 2)
    # missing inputs → None, original untouched
    assert di.enrich_est_value([{"keyword": "k"}])[0]["est_value"] is None


def test_opportunity_score_monotonicity():
    base = di.opportunity_score(1000, 5.0, 30, 4, "weak")
    assert base > 0
    # more volume → higher
    assert di.opportunity_score(2000, 5.0, 30, 4, "weak") > base
    # higher KD (harder) → lower
    assert di.opportunity_score(1000, 5.0, 70, 4, "weak") < base
    # competitor in top 3 (proven) → higher than deeper
    assert di.opportunity_score(1000, 5.0, 30, 2, "weak") > base
    # zero value → zero score
    assert di.opportunity_score(0, 5.0, 30, 4, "weak") == 0.0


def test_classify_gap():
    kw = dict(competitor_max_position=10, client_min_position=20)
    # competitor too deep → not a gap
    assert di.classify_gap(None, 15, **kw) is None
    # client absent, competitor top-10 → missing
    assert di.classify_gap(None, 5, **kw) == "missing"
    # client ranks poorly (>20) → weak
    assert di.classify_gap(35, 5, **kw) == "weak"
    # client already ranks well → not a gap
    assert di.classify_gap(8, 5, **kw) is None


def test_compute_keyword_gap_filters_and_sorts():
    competitor = [
        {"keyword": "roof repair", "position": 3, "volume": 2000, "cpc_usd": 9.0, "keyword_difficulty": 30},
        {"keyword": "roof restoration", "position": 5, "volume": 800, "cpc_usd": 6.0, "keyword_difficulty": 40},
        {"keyword": "low volume", "position": 2, "volume": 3, "cpc_usd": 5.0, "keyword_difficulty": 10},  # < min_volume
        {"keyword": "deep", "position": 40, "volume": 5000, "cpc_usd": 9.0},  # competitor too deep
        {"keyword": "client owns", "position": 4, "volume": 999, "cpc_usd": 9.0},  # client ranks #2
    ]
    client = [{"keyword": "client owns", "position": 2}, {"keyword": "roof restoration", "position": 40}]
    gaps = di.compute_keyword_gap(
        competitor, client, "rival.com",
        competitor_max_position=10, client_min_position=20, min_volume=10,
    )
    kws = [g["keyword"] for g in gaps]
    assert "roof repair" in kws and "roof restoration" in kws
    assert "low volume" not in kws and "deep" not in kws and "client owns" not in kws
    # roof repair is 'missing' (client absent); roof restoration is 'weak'
    by_kw = {g["keyword"]: g for g in gaps}
    assert by_kw["roof repair"]["gap_type"] == "missing"
    assert by_kw["roof restoration"]["gap_type"] == "weak"
    assert by_kw["roof restoration"]["client_position"] == 40
    # sorted by opportunity_score desc
    assert gaps == sorted(gaps, key=lambda g: g["opportunity_score"], reverse=True)


def test_merge_keyword_gaps_keeps_best_per_keyword():
    a = [{"keyword": "K", "opportunity_score": 10.0, "competitor_domain": "a.com"}]
    b = [{"keyword": "k", "opportunity_score": 25.0, "competitor_domain": "b.com"},
         {"keyword": "other", "opportunity_score": 5.0}]
    merged = di.merge_keyword_gaps([a, b])
    by = {g["keyword"].lower(): g for g in merged}
    assert by["k"]["opportunity_score"] == 25.0            # higher wins
    assert by["k"]["competitor_domain"] == "b.com"
    assert len(merged) == 2
    assert merged[0]["opportunity_score"] == 25.0          # sorted desc


def test_compute_link_gap_excludes_client_domains():
    competitor_referring = {
        "rival.com": [
            {"domain": "https://directory.com", "rank": 500, "backlinks": 3},
            {"domain": "shared.com", "rank": 700, "backlinks": 1},  # client already has
        ],
        "rival2.com": [
            {"domain": "directory.com", "rank": 520, "backlinks": 9},  # also links rival2
        ],
    }
    client_referring = ["shared.com", "www.owned.com"]
    out = di.compute_link_gap(competitor_referring, client_referring)
    doms = {r["referring_domain"] for r in out}
    assert "directory.com" in doms
    assert "shared.com" not in doms
    dr = next(r for r in out if r["referring_domain"] == "directory.com")
    assert dr["linking_to"] == ["rival.com", "rival2.com"]     # both, sorted
    assert dr["referring_domain_rank"] == 520                   # strongest observed
    assert dr["backlink_count"] == 9                            # highest observed


def test_build_overview_merges_and_falls_back():
    out = di.build_overview(
        {"organic_traffic_est": None, "ranked_keyword_count": 400, "traffic_value_est": 12.0},
        bulk_traffic=999.0,
        backlink_summary={"rank": 62.0, "referring_domains": 240},
    )
    assert out["organic_traffic_est"] == 999.0     # fell back to bulk estimate
    assert out["ranked_keyword_count"] == 400
    assert out["dr"] == 62.0
    assert out["rd"] == 240


def test_gap_alert_digest(monkeypatch):
    monkeypatch.setattr(di.settings, "domain_intel_gap_alert_min", 3)
    gaps = [
        {"keyword": "roof repair", "volume": 2000},
        {"keyword": "roof restoration", "volume": 800},
        {"keyword": "gutter cleaning", "volume": 300},
        {"keyword": "old one", "volume": 100},
    ]
    # 3 newly-opened (prev has "old one") → clears threshold of 3
    d = di.gap_alert_digest({"old one"}, gaps)
    assert d is not None
    assert d["count"] == 3
    assert "roof repair" in d["summary"] and "new competitor keyword gaps" in d["title"]
    # only 2 newly-opened → below threshold → None
    assert di.gap_alert_digest({"roof restoration", "gutter cleaning", "old one"}, gaps) is None
    # empty prev, all new, clears threshold
    assert di.gap_alert_digest(set(), gaps)["count"] == 4


def test_build_domain_intel_actions():
    from services import reopt_planner as rp
    gaps = [
        {"keyword": "roof repair", "competitor_domain": "rival.com", "competitor_position": 3,
         "client_position": None, "volume": 2000, "opportunity_score": 500},
        {"keyword": "roof restoration", "competitor_domain": "rival.com", "competitor_position": 5,
         "client_position": 34, "volume": 800, "opportunity_score": 200},
    ]
    actions = rp.build_domain_intel_actions("c1", gaps)
    assert len(actions) == 2
    a = actions[0]
    assert a["kind"] == "keyword_gap" and a["source"] == "organic"
    assert a["keyword"] == "roof repair"
    assert "rival.com" in a["diagnosis"] and "you don't rank" in a["diagnosis"]
    assert a["cta_path"] == "clients/c1/domain-intel"
    # the deeper-position gap names the client's current rank
    assert "you rank #34" in actions[1]["diagnosis"]
    # empty → no actions (additive: unchanged plan behavior)
    assert rp.build_domain_intel_actions("c1", []) == []


def test_summarize_plan_counts_keyword_gap():
    from services import reopt_planner as rp
    actions = [{"kind": "keyword_gap", "severity": "info"}]
    out = rp.summarize_plan(actions)
    assert "1 other opportunity" in out["summary"]
    assert out["severity"] == "info"


def test_is_snapshot_fresh(monkeypatch):
    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(di.settings, "domain_intel_cache_hours", 24)
    assert di.is_snapshot_fresh((now - timedelta(hours=5)).isoformat(), now=now) is True
    assert di.is_snapshot_fresh((now - timedelta(hours=30)).isoformat(), now=now) is False
    assert di.is_snapshot_fresh(None, now=now) is False
    monkeypatch.setattr(di.settings, "domain_intel_cache_hours", 0)
    assert di.is_snapshot_fresh((now - timedelta(hours=1)).isoformat(), now=now) is False


# ── Labs location-code coercion (ops fix 2026-07-12) ─────────────────────────
def test_labs_location_code_coerces_city_codes():
    from services import dataforseo_labs as labs

    # Country codes (2000 + ISO-3166 numeric) pass through.
    assert labs.labs_location_code(2840) == 2840   # US
    assert labs.labs_location_code(2036) == 2036   # AU
    # City-level codes (what clients carry in rank_tracking_location_code —
    # these took out 60% of keyword_gap runs) coerce to the default country.
    assert labs.labs_location_code(1000567) == 2840
    assert labs.labs_location_code(1015027) == 2840
    # Missing / garbage → default, never an invalid Labs call.
    assert labs.labs_location_code(None) == 2840
    assert labs.labs_location_code("not-a-code") == 2840
    # _loc threads the coercion into every Labs payload.
    assert labs._loc(1000567, None)["location_code"] == 2840
    assert labs._loc(2840, "en")["location_code"] == 2840
