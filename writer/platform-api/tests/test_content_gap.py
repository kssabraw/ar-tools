"""Unit tests for the Content Gap Analyzer pure core.

Covers the win/gap verdict (§2.1 three-valued AIO axis), AIO citation helpers,
competitor-set resolution (§6 "both" union), page-signal extraction, and the
build_onpage_diff assembler (§4). No I/O.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
