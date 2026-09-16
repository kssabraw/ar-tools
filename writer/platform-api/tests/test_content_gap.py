"""Unit tests for the Content Gap Analyzer pure core.

Covers the win/gap verdict (§2.1 three-valued AIO axis), AIO citation helpers,
competitor-set resolution (§6 "both" union), page-signal extraction, and the
build_onpage_diff assembler (§4). No I/O.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services import content_gap as cg


# ===========================================================================
# compute_verdict — the §2.1 matrix (three-valued AIO axis)
# ===========================================================================
def test_verdict_top10_no_aio_is_win():
    assert cg.compute_verdict(3, aio_present=False, in_aio=False) == "win"


def test_verdict_top10_aio_cited_is_win():
    assert cg.compute_verdict(5, aio_present=True, in_aio=True) == "win"


def test_verdict_top10_aio_present_not_cited_is_aio_gap():
    assert cg.compute_verdict(2, aio_present=True, in_aio=False) == "aio_gap"


def test_verdict_not_ranking_no_aio_is_organic_gap():
    assert cg.compute_verdict(None, aio_present=False, in_aio=False) == "organic_gap"
    assert cg.compute_verdict(25, aio_present=False, in_aio=False) == "organic_gap"


def test_verdict_in_aio_only_is_organic_gap():
    # Cited in AIO but not top-10 organic ("not ranking").
    assert cg.compute_verdict(None, aio_present=True, in_aio=True) == "organic_gap"


def test_verdict_not_ranking_aio_present_not_cited_is_full_gap():
    assert cg.compute_verdict(None, aio_present=True, in_aio=False) == "full_gap"
    assert cg.compute_verdict(18, aio_present=True, in_aio=False) == "full_gap"


def test_verdict_boundary_position_10_is_top10():
    assert cg.compute_verdict(10, aio_present=False, in_aio=False) == "win"
    assert cg.compute_verdict(11, aio_present=False, in_aio=False) == "organic_gap"


def test_is_gap():
    assert cg.is_gap("win") is False
    for v in ("aio_gap", "organic_gap", "full_gap"):
        assert cg.is_gap(v) is True


# ===========================================================================
# AIO citation helpers
# ===========================================================================
def test_client_cited_in_aio_matches_www_and_scheme():
    sources = [
        {"domain": "competitor.com", "url": "https://competitor.com/x"},
        {"domain": "www.client.com", "url": "https://www.client.com/page"},
    ]
    assert cg.client_cited_in_aio(sources, "client.com") is True
    assert cg.client_cited_in_aio(sources, "https://client.com") is True
    assert cg.client_cited_in_aio(sources, "notthere.com") is False


def test_client_cited_in_aio_empty():
    assert cg.client_cited_in_aio([], "client.com") is False
    assert cg.client_cited_in_aio([{"domain": "x.com"}], "") is False


def test_aio_gap_sources_excludes_client_and_dedupes():
    sources = [
        {"domain": "a.com", "url": "https://a.com/1", "title": "A"},
        {"domain": "a.com", "url": "https://a.com/2", "title": "A2"},
        {"domain": "www.client.com", "url": "https://client.com", "title": "C"},
        {"domain": "b.com", "url": "https://b.com", "title": "B"},
    ]
    got = cg.aio_gap_sources(sources, "client.com")
    assert [g["domain"] for g in got] == ["a.com", "b.com"]


# ===========================================================================
# resolve_competitors — the §6 union, capped, strongest-first
# ===========================================================================
def _organic(*pairs):
    return [{"position": p, "domain": d, "url": f"https://{d}/x"} for p, d in pairs]


def test_resolve_competitors_above_client():
    organic = _organic((1, "a.com"), (2, "client.com"), (3, "b.com"), (4, "c.com"))
    got = cg.resolve_competitors(organic, client_position=2, registry_domains=set(), client_domain="client.com")
    # Only a.com ranks above position 2; the client is excluded.
    assert [c["domain"] for c in got] == ["a.com"]


def test_resolve_competitors_client_not_ranking_uses_all_top10():
    organic = _organic((1, "a.com"), (2, "b.com"), (3, "c.com"))
    got = cg.resolve_competitors(organic, client_position=None, registry_domains=set(), client_domain="client.com")
    assert [c["domain"] for c in got] == ["a.com", "b.com", "c.com"]


def test_resolve_competitors_includes_registered_below_client():
    organic = _organic((1, "a.com"), (2, "client.com"), (5, "rival.com"))
    # rival.com ranks below the client but is a registered competitor in the SERP.
    got = cg.resolve_competitors(
        organic, client_position=2, registry_domains={"rival.com"}, client_domain="client.com"
    )
    domains = [c["domain"] for c in got]
    assert "a.com" in domains and "rival.com" in domains
    rival = next(c for c in got if c["domain"] == "rival.com")
    assert rival["registered"] is True
    # Positioned competitor (a.com pos 1) sorts before rival (pos 5).
    assert domains[0] == "a.com"


def test_resolve_competitors_excludes_is_client_row_when_domain_blank():
    # Client with no website_url → client_domain="" can't identify the client by
    # domain; the snapshot's is_client flag must still exclude its own row.
    organic = [
        {"position": 1, "domain": "a.com", "url": "https://a.com/x"},
        {"position": 2, "domain": "client.com", "url": "https://client.com/p", "is_client": True},
    ]
    got = cg.resolve_competitors(organic, client_position=2, registry_domains=set(), client_domain="")
    assert [c["domain"] for c in got] == ["a.com"]


def test_resolve_competitors_dedupes_and_caps():
    organic = _organic((1, "a.com"), (2, "a.com"), (3, "b.com"), (4, "c.com"), (5, "d.com"))
    got = cg.resolve_competitors(
        organic, client_position=None, registry_domains=set(), client_domain="client.com", max_competitors=3
    )
    assert [c["domain"] for c in got] == ["a.com", "b.com", "c.com"]
    # deduped: a.com appears once, keeping its best position
    assert next(c for c in got if c["domain"] == "a.com")["position"] == 1


# ===========================================================================
# page_signals_from_html
# ===========================================================================
_HTML = """
<html><head>
  <title>Best Roof Repair in Denver</title>
  <meta name="description" content="Top-rated roof repair.">
  <script type="application/ld+json">{"@type": "FAQPage", "mainEntity": []}</script>
</head><body><article>
  <h1>Roof Repair</h1>
  <h2>How much does roof repair cost?</h2>
  <p>It depends on the damage and materials used here.</p>
  <h2>Our Process</h2>
  <ul><li>Inspect</li><li>Quote</li></ul>
  <h2>Frequently Asked Questions</h2>
  <p>Contact us today for a free quote.</p>
</article></body></html>
"""


def test_page_signals_extraction():
    sig = cg.page_signals_from_html(_HTML, url="https://client.com/roof")
    assert sig["available"] is True
    assert sig["title"] == "Best Roof Repair in Denver"
    assert sig["meta_description"] == "Top-rated roof repair."
    assert "FAQPage" in sig["schema_types"]
    assert sig["heading_count"] == 3
    assert "how much does roof repair cost?" in sig["headings"]
    assert "list" in sig["block_types"]
    assert sig["elements"]["has_lists"] is True
    assert sig["word_count"] > 0


def test_page_signals_empty_html():
    sig = cg.page_signals_from_html("")
    assert sig["available"] is True
    assert sig["headings"] == []
    assert sig["title"] is None


# ===========================================================================
# build_onpage_diff
# ===========================================================================
def _sig(headings=None, wc=0, elements=None, schema=None, title=None, meta=None, domain=None, available=True):
    return {
        "available": available,
        "domain": domain,
        "url": f"https://{domain}/x" if domain else None,
        "title": title,
        "meta_description": meta,
        "word_count": wc,
        "headings": headings or [],
        "heading_count": len(headings or []),
        "block_types": [],
        "schema_types": schema or [],
        "elements": {k: False for k in cg._ELEMENT_LABELS} | (elements or {}),
    }


def test_onpage_diff_subtopic_and_word_gap():
    client = _sig(headings=["intro"], wc=500, title="Client", meta="m", domain="client.com")
    comps = [
        _sig(headings=["intro", "pricing", "faq"], wc=1500, elements={"has_faq": True}, schema=["FAQPage"], title="A", meta="ma", domain="a.com"),
        _sig(headings=["pricing", "warranty"], wc=1300, elements={"has_faq": True}, title="B", domain="b.com"),
    ]
    diff = cg.build_onpage_diff(client, comps)
    assert diff["client_available"] is True
    assert diff["competitors_compared"] == 2
    # "pricing" is covered by both competitors and missing from the client → top gap.
    top = diff["subtopic_gap"][0]
    assert top["heading"] == "pricing"
    assert sorted(top["covered_by"]) == ["a.com", "b.com"]
    # word count: client 500 vs median(1500,1300)=1400 → delta -900
    assert diff["word_count"]["competitor_median"] == 1400
    assert diff["word_count"]["delta"] == -900
    # element gap: both have FAQ, client lacks it
    faq = next(e for e in diff["element_gap"] if e["element"] == "has_faq")
    assert faq["count"] == 2
    # schema gap: FAQPage from a.com only
    assert diff["schema_gap"][0]["schema"] == "FAQPage"


def test_onpage_diff_client_covers_subtopic_excludes_it():
    client = _sig(headings=["intro", "pricing"], wc=1000, domain="client.com")
    comps = [_sig(headings=["intro", "pricing"], wc=1000, domain="a.com")]
    diff = cg.build_onpage_diff(client, comps)
    assert diff["subtopic_gap"] == []  # client already covers everything


def test_onpage_diff_client_unavailable():
    client = {"available": False}
    comps = [_sig(headings=["pricing"], wc=1200, elements={"has_faq": True}, domain="a.com")]
    diff = cg.build_onpage_diff(client, comps)
    assert diff["client_available"] is False
    # competitor coverage still surfaces; client column is None, not "has zero"
    assert diff["word_count"]["client"] is None
    assert diff["word_count"]["delta"] is None
    assert diff["subtopic_gap"][0]["heading"] == "pricing"
    assert any(e["element"] == "has_faq" for e in diff["element_gap"])


def test_onpage_diff_counts_unavailable_competitors():
    client = _sig(headings=["intro"], domain="client.com")
    comps = [_sig(headings=["pricing"], domain="a.com"), {"available": False, "domain": "b.com"}]
    diff = cg.build_onpage_diff(client, comps)
    assert diff["competitors_compared"] == 1
    assert diff["competitors_unavailable"] == 1


def test_onpage_diff_no_competitors():
    client = _sig(headings=["intro"], wc=500, domain="client.com")
    diff = cg.build_onpage_diff(client, [])
    assert diff["competitors_compared"] == 0
    assert diff["subtopic_gap"] == []
    assert diff["word_count"]["competitor_median"] == 0


# ===========================================================================
# _snapshot_fresh
# ===========================================================================
def test_snapshot_fresh_window():
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    recent = (now - timedelta(days=10)).isoformat()
    stale = (now - timedelta(days=40)).isoformat()
    assert cg._snapshot_fresh(recent, 30, now=now) is True
    assert cg._snapshot_fresh(stale, 30, now=now) is False
    assert cg._snapshot_fresh(None, 30, now=now) is False
    assert cg._snapshot_fresh("garbage", 30, now=now) is False


# ===========================================================================
# Phase 1 pure helpers
# ===========================================================================
def test_estimate_deep_calls():
    # 2 nlp + 1 bulk + (n+1) ranked + (n+1) scrapes
    assert cg.estimate_deep_calls(0) == 5
    assert cg.estimate_deep_calls(5) == 15
    # page-traffic off drops the (n+1) ranked_keywords calls
    assert cg.estimate_deep_calls(5, page_traffic=False) == 9
    assert cg.estimate_deep_calls(-3) == 5  # negative coerced to 0


def test_norm_url():
    assert cg._norm_url("https://www.A.com/Path/") == "a.com/path"
    assert cg._norm_url("http://a.com/x#frag") == "a.com/x"
    assert cg._norm_url("https://a.com/p?x=1") == "a.com/p?x=1"  # query kept
    assert cg._norm_url("") == ""
    assert cg._norm_url(None) == ""


def test_estimate_page_traffic_matches_target_url_only():
    rows = [
        {"url": "https://a.com/x", "position": 2, "volume": 1000},
        {"url": "https://a.com/other", "position": 1, "volume": 9999},  # different page
    ]
    # only the /x row counts: 1000 × CTR(2)=0.155 = 155.0; www + trailing slash tolerated
    assert cg.estimate_page_traffic(rows, "https://www.a.com/x/") == 155.0


def test_estimate_page_traffic_no_match_is_none_not_zero():
    rows = [{"url": "https://a.com/x", "position": 2, "volume": 1000}]
    assert cg.estimate_page_traffic(rows, "https://a.com/nowhere") is None
    assert cg.estimate_page_traffic([], "https://a.com/x") is None
    assert cg.estimate_page_traffic(rows, None) is None


def test_estimate_page_traffic_skips_volumeless_rows():
    rows = [
        {"url": "https://a.com/x", "position": 2, "volume": None},
        {"url": "https://a.com/x", "position": 3, "volume": 500},
    ]
    # only the second row contributes: 500 × CTR(3)=0.105 = 52.5
    assert cg.estimate_page_traffic(rows, "https://a.com/x") == 52.5


def test_build_authority_gap_medians_and_deltas():
    client = {"page_rd": 5, "page_ur": 10, "domain_rd": 100, "dr": 200}
    comps = [
        {"domain": "a.com", "page_rd": 50, "page_ur": 40, "domain_rd": 800, "dr": 600},
        {"domain": "b.com", "page_rd": 30, "page_ur": 35, "domain_rd": 500, "dr": 400},
    ]
    g = cg.build_authority_gap(client, comps)
    assert g["competitor_page_rd_median"] == 40
    assert g["competitor_domain_rd_median"] == 650
    assert g["competitor_dr_median"] == 500
    # positive delta = competitors ahead (client must gain this much)
    assert g["page_rd_gap"] == 35
    assert g["domain_rd_gap"] == 550
    assert g["dr_gap"] == 300
    assert "DataForSEO" in g["caveat"]


def test_build_authority_gap_client_none_and_missing_metrics():
    comps = [{"domain": "a.com", "page_rd": None, "domain_rd": 500, "dr": 600}]
    g = cg.build_authority_gap(None, comps)
    assert g["client"] is None
    # median over the one competitor with a value; deltas None without a client side
    assert g["competitor_domain_rd_median"] == 500
    assert g["page_rd_gap"] is None
    assert g["dr_gap"] is None
    assert g["competitor_page_rd_median"] is None  # no competitor page_rd values


def test_assemble_authority_from_snapshot_rows():
    result_rows = [
        {"position": 2, "url": "https://client.com/roof", "domain": "client.com", "is_client": True, "referring_domains": 5, "url_rating": 10},
        {"position": 1, "url": "https://a.com/x", "domain": "a.com", "referring_domains": 50, "url_rating": 40},
        {"position": 3, "url": "https://b.com/y", "domain": "b.com", "referring_domains": 30, "url_rating": 35},
    ]
    domain_rows = [
        {"domain": "client.com", "is_client": True, "domain_rating": 200, "referring_domains": 100},
        {"domain": "a.com", "domain_rating": 600, "referring_domains": 800},
        {"domain": "b.com", "domain_rating": 400, "referring_domains": 500},
    ]
    competitors = [
        {"domain": "a.com", "url": "https://a.com/x", "position": 1},
        {"domain": "b.com", "url": "https://www.b.com/y/", "position": 3},  # url-normalized match
    ]
    g = cg.assemble_authority("client.com", competitors, result_rows, domain_rows)
    assert g["client"] == {"page_rd": 5, "page_ur": 10, "domain_rd": 100, "dr": 200}
    a = next(c for c in g["competitors"] if c["domain"] == "a.com")
    assert (a["page_rd"], a["page_ur"], a["domain_rd"], a["dr"]) == (50, 40, 800, 600)
    b = next(c for c in g["competitors"] if c["domain"] == "b.com")
    assert (b["page_rd"], b["domain_rd"]) == (30, 500)  # matched despite www/slash
    assert g["dr_gap"] == 300  # median(600,400)=500 - client 200


def test_assemble_authority_client_not_ranking_uses_domain_row():
    # client absent from result rows (not ranking) — still gets domain-level RD/DR
    result_rows = [{"position": 1, "url": "https://a.com/x", "domain": "a.com", "referring_domains": 50}]
    domain_rows = [
        {"domain": "client.com", "is_client": True, "domain_rating": 150, "referring_domains": 60},
        {"domain": "a.com", "domain_rating": 600, "referring_domains": 800},
    ]
    g = cg.assemble_authority("client.com", [{"domain": "a.com", "url": "https://a.com/x"}], result_rows, domain_rows)
    assert g["client"]["page_rd"] is None  # no client page row
    assert g["client"]["dr"] == 150         # domain row still found via is_client


def test_build_site_traffic_gap():
    traffic = {"client.com": 100.0, "a.com": 500.0, "b.com": 300.0}
    g = cg.build_site_traffic_gap(traffic, "client.com", ["a.com", "b.com"])
    assert g["client"] == 100.0
    assert g["competitor_median"] == 400.0
    assert g["delta"] == 300.0
    assert g["basis"] == "estimated (DataForSEO)"


def test_build_page_traffic_gap_labelled_modeled():
    g = cg.build_page_traffic_gap(
        6.5, [{"domain": "a.com", "url": "u", "estimate": 155.0}, {"domain": "b.com", "url": "v", "estimate": 48.8}]
    )
    assert g["basis"] == "estimated (modeled)"
    assert g["client"] == 6.5
    assert g["competitor_median"] == 101.9
    assert g["delta"] == 95.4


def test_build_entity_gap_maps_serp_and_filters_client_deficiencies():
    serp = [
        {"name": "Shingle", "entity_type": "THING", "page_spread": 3, "page_spread_pct": 0.6, "recommended_mentions": 4, "wiki_link": "http://w"},
    ]
    defs = [
        {"engine": "Entity establishment", "engine_key": "entity_establishment", "score": 40, "issues": ["x"]},
        {"engine": "Organic ranking", "engine_key": "organic_ranking", "score": 70},
        {"engine": "serp_signal_coverage", "score": 55},  # matched via `engine` when engine_key absent
    ]
    g = cg.build_entity_gap(serp, defs)
    assert g["serp_entities"][0]["name"] == "Shingle"
    assert g["serp_entities"][0]["type"] == "THING"
    assert g["serp_entity_count"] == 1
    keys = {d.get("engine_key") or d.get("engine") for d in g["client_deficiencies"]}
    assert keys == {"entity_establishment", "serp_signal_coverage"}  # organic_ranking dropped


# ===========================================================================
# _reserve — fail-closed budget meter
# ===========================================================================
class _FakeSB:
    def __init__(self, data):
        self._data = data

    def rpc(self, name, params):
        return self

    def execute(self):
        return SimpleNamespace(data=self._data)


def test_reserve_confirmed_true(monkeypatch):
    monkeypatch.setattr(cg.settings, "content_gap_daily_call_budget", 500)
    monkeypatch.setattr(cg, "get_supabase", lambda: _FakeSB(True))
    assert cg._reserve(10) is True


def test_reserve_over_cap_false(monkeypatch):
    monkeypatch.setattr(cg.settings, "content_gap_daily_call_budget", 500)
    monkeypatch.setattr(cg, "get_supabase", lambda: _FakeSB(False))
    assert cg._reserve(10) is False


def test_reserve_cap_zero_disables_guard(monkeypatch):
    monkeypatch.setattr(cg.settings, "content_gap_daily_call_budget", 0)
    monkeypatch.setattr(cg, "get_supabase", lambda: (_ for _ in ()).throw(AssertionError("must not query")))
    assert cg._reserve(10) is True  # guard off → allow without touching the DB


def test_reserve_fail_closed_on_exception(monkeypatch):
    class Boom:
        def rpc(self, *a, **k):
            raise RuntimeError("db down")

    monkeypatch.setattr(cg.settings, "content_gap_daily_call_budget", 500)
    monkeypatch.setattr(cg, "get_supabase", lambda: Boom())
    # fail-CLOSED: an accounting error blocks the spend (unlike domain_intel)
    assert cg._reserve(10) is False


# ===========================================================================
# _deep_dimensions — the full deep pass (externals mocked)
# ===========================================================================
async def test_deep_dimensions_assembles_all(monkeypatch):
    async def fake_post_nlp(path, payload, timeout=90.0):
        if path == "/analyze":
            return {
                "google_entities": [
                    {"name": "Shingle", "entity_type": "THING", "page_spread": 3, "recommended_mentions": 4, "wiki_link": "http://w"},
                ]
            }
        if path == "/score-page":
            assert payload["page_url"] == "https://client.com/roof"
            assert payload["serp_analysis"] is not None  # /analyze reused, not recomputed
            return {
                "composite_score": 62.0,
                "composite_status": "needs_work",
                "engine_scores": {"entity_establishment": 40},
                "deficiencies": [
                    {"engine": "Entity", "engine_key": "entity_establishment", "score": 40, "issues": ["missing"]},
                    {"engine": "Organic", "engine_key": "organic_ranking", "score": 70},
                ],
            }
        return None

    async def fake_bulk(targets, location_code=None):
        assert "client.com" in targets and "a.com" in targets
        return {"client.com": 100.0, "a.com": 500.0, "b.com": 300.0}, 0.01

    async def fake_ranked(domain, location_code=None, **kw):
        data = {
            "a.com": [{"url": "https://a.com/x", "position": 2, "volume": 1000}],
            "b.com": [{"url": "https://b.com/y", "position": 5, "volume": 800}],
            "client.com": [{"url": "https://client.com/roof", "position": 15, "volume": 500}],
        }
        return data.get(domain, []), 0.01

    async def fake_scrape(url):
        if not url:
            return {"available": False}
        return {
            "available": True, "url": url, "title": "T", "meta_description": "m", "word_count": 1000,
            "headings": ["intro"], "heading_count": 1, "block_types": [], "schema_types": [],
            "elements": {k: False for k in cg._ELEMENT_LABELS},
        }

    monkeypatch.setattr(cg, "_post_nlp", fake_post_nlp)
    monkeypatch.setattr(cg.dataforseo_labs, "fetch_bulk_traffic", fake_bulk)
    monkeypatch.setattr(cg.dataforseo_labs, "fetch_ranked_keywords", fake_ranked)
    monkeypatch.setattr(cg, "_scrape_signals", fake_scrape)

    competitors = [
        {"domain": "a.com", "url": "https://a.com/x", "position": 1},
        {"domain": "b.com", "url": "https://b.com/y", "position": 3},
    ]
    result_rows = [
        {"position": 1, "url": "https://a.com/x", "domain": "a.com", "referring_domains": 50, "url_rating": 40},
        {"position": 3, "url": "https://b.com/y", "domain": "b.com", "referring_domains": 30, "url_rating": 35},
    ]
    domain_rows = [
        {"domain": "client.com", "is_client": True, "domain_rating": 200, "referring_domains": 100},
        {"domain": "a.com", "domain_rating": 600, "referring_domains": 800},
        {"domain": "b.com", "domain_rating": 400, "referring_domains": 500},
    ]

    gap, onpage_diff = await cg._deep_dimensions(
        keyword="roof repair",
        client_url="https://client.com/roof",
        client_domain="client.com",
        business={"business_name": "C", "gbp_category": "Roofer", "address": "A"},
        competitors=competitors,
        result_rows=result_rows,
        domain_rows=domain_rows,
        aio_present=True,
        aio_sources=[{"domain": "a.com"}, {"domain": "client.com"}],
        location_code=2840,
        entity_provider=None,
        page_traffic_enabled=True,
    )

    assert gap["dimensions_unavailable"] == []
    # authority
    assert gap["authority"]["competitor_dr_median"] == 500
    # aio citation gap (a.com cited, client cited too → only a.com surfaces)
    assert [s["domain"] for s in gap["aio_citation"]["cited_sources_not_client"]] == ["a.com"]
    # entities: serp side mapped, client deficiencies filtered to entity engine
    assert gap["entities"]["serp_entities"][0]["name"] == "Shingle"
    assert [d["engine_key"] for d in gap["entities"]["client_deficiencies"]] == ["entity_establishment"]
    # onpage score
    assert gap["onpage_score"]["composite_score"] == 62.0
    # site traffic: median(500,300)=400 vs client 100 → delta 300
    assert gap["site_traffic"]["delta"] == 300.0
    # page traffic (modeled): a=1000×0.155=155, b=800×0.061=48.8, client=500×0.013=6.5
    assert gap["page_traffic"]["client"] == 6.5
    a_est = next(c for c in gap["page_traffic"]["competitors"] if c["domain"] == "a.com")["estimate"]
    assert a_est == 155.0
    # on-page diff assembled over 2 scraped competitors
    assert onpage_diff["competitors_compared"] == 2


async def test_deep_dimensions_degrades_when_nlp_and_client_url_missing(monkeypatch):
    async def fail_nlp(path, payload, timeout=90.0):
        return None  # nlp unavailable

    async def fake_bulk(targets, location_code=None):
        return {}, 0.0

    async def fake_scrape(url):
        return {"available": False}

    monkeypatch.setattr(cg, "_post_nlp", fail_nlp)
    monkeypatch.setattr(cg.dataforseo_labs, "fetch_bulk_traffic", fake_bulk)
    monkeypatch.setattr(cg, "_scrape_signals", fake_scrape)

    gap, onpage_diff = await cg._deep_dimensions(
        keyword="kw",
        client_url=None,  # client not ranking, no canonical
        client_domain="client.com",
        business={"business_name": "C", "gbp_category": "", "address": ""},
        competitors=[],
        result_rows=[],
        domain_rows=[{"domain": "client.com", "is_client": True, "domain_rating": 100}],
        aio_present=False,
        aio_sources=[],
        location_code=None,
        entity_provider=None,
        page_traffic_enabled=False,  # off → no ranked_keywords calls
    )
    # /analyze failed AND no client URL → both entity sources unavailable
    assert "serp_entities" in gap["dimensions_unavailable"]
    assert "onpage_score_no_client_url" in gap["dimensions_unavailable"]
    assert "entities" not in gap  # neither side produced anything
    assert "aio_citation" not in gap  # no AIO on this SERP
    # authority still assembled from the domain row (free)
    assert gap["authority"]["client"]["dr"] == 100
    # on-page diff still returns (client unavailable, no competitors)
    assert onpage_diff["client_available"] is False


# ===========================================================================
# Phase 2 — estimate_max_calls (pure preflight ceiling, §8)
# ===========================================================================
def test_estimate_max_calls_scales_per_keyword():
    per_kw = cg.estimate_deep_calls(5, True)
    assert cg.estimate_max_calls(4, 5, True) == 4 * per_kw


def test_estimate_max_calls_zero_keywords_is_zero():
    assert cg.estimate_max_calls(0, 5, True) == 0


def test_estimate_max_calls_page_traffic_off_is_cheaper():
    on = cg.estimate_max_calls(3, 5, True)
    off = cg.estimate_max_calls(3, 5, False)
    assert off < on


def test_estimate_max_calls_clamps_negatives():
    assert cg.estimate_max_calls(-2, -1, True) == 0


# ===========================================================================
# Phase 2 — build_run_csv_rows (pure export flattening, §8/§9)
# ===========================================================================
def test_build_run_csv_rows_full_row():
    keywords = [
        {
            "keyword": "roof repair",
            "page_url": "https://c.com/roof",
            "verdict": "full_gap",
            "client_position": None,
            "aio_present": True,
            "in_aio": False,
            "competitors": [{"domain": "a.com", "position": 1}, {"domain": "b.com", "position": 2}],
            "gap": {
                "authority": {"page_rd_gap": 12.0, "domain_rd_gap": 40.0, "dr_gap": 5.0},
                "dimensions_unavailable": ["site_traffic"],
            },
            "onpage_diff": {"word_count": {"client": 500, "competitor_median": 900, "delta": -400}},
        }
    ]
    rows = cg.build_run_csv_rows(keywords)
    assert len(rows) == 1
    row = dict(zip(cg.CSV_HEADERS, rows[0]))
    assert row["keyword"] == "roof repair"
    assert row["verdict"] == "full_gap"
    assert row["competitor_count"] == 2
    assert row["top_competitor"] == "a.com"
    assert row["page_rd_gap"] == 12.0
    assert row["dr_gap"] == 5.0
    assert row["word_count_delta"] == -400
    assert row["dimensions_unavailable"] == "site_traffic"


def test_build_run_csv_rows_win_with_no_gap_payload():
    # A win short-circuits the deep pass, so gap/onpage_diff/competitors are null.
    keywords = [
        {
            "keyword": "brand term",
            "page_url": None,
            "verdict": "win",
            "client_position": 1,
            "aio_present": False,
            "in_aio": False,
            "competitors": None,
            "gap": None,
            "onpage_diff": None,
        }
    ]
    rows = cg.build_run_csv_rows(keywords)
    row = dict(zip(cg.CSV_HEADERS, rows[0]))
    assert row["verdict"] == "win"
    assert row["competitor_count"] == 0
    assert row["top_competitor"] == ""
    assert row["page_rd_gap"] is None
    assert row["word_count_delta"] is None
    assert row["dimensions_unavailable"] == ""


def test_build_run_csv_rows_empty():
    assert cg.build_run_csv_rows([]) == []


def test_csv_headers_stable():
    # The export contract the frontend + downstream consumers read.
    assert cg.CSV_HEADERS[0] == "keyword"
    assert "verdict" in cg.CSV_HEADERS
    assert len(cg.CSV_HEADERS) == 13
