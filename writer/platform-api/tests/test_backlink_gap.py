"""Unit tests for services.backlink_gap — domain normalization + link-gap logic."""

from __future__ import annotations

from services import backlink_gap as bg


def test_registrable_domain_strips_scheme_www_path_port():
    assert bg.registrable_domain("https://www.Example.com/path?q=1") == "example.com"
    assert bg.registrable_domain("competitor.com") == "competitor.com"
    assert bg.registrable_domain("http://sub.foo.co:8080/") == "sub.foo.co"
    assert bg.registrable_domain(None) is None
    assert bg.registrable_domain("") is None


def test_compute_link_gap_finds_domains_linking_to_multiple_competitors():
    client_rd = {"already.com"}
    competitor_rd = {
        "rivalA.com": {"news.com", "blog.com", "already.com"},
        "rivalB.com": {"news.com", "blog.com"},
        "rivalC.com": {"news.com", "directory.com"},
    }
    gaps = bg.compute_link_gap(client_rd, competitor_rd, min_competitors=2)
    by_domain = {g["referring_domain"]: g["competitors_linking"] for g in gaps}
    assert by_domain == {"news.com": 3, "blog.com": 2}   # already.com excluded (client has it); directory.com only 1
    assert gaps[0]["referring_domain"] == "news.com"      # sorted by count desc


def test_compute_link_gap_respects_min_competitors():
    gaps = bg.compute_link_gap(set(), {"a.com": {"x.com"}, "b.com": {"y.com"}}, min_competitors=2)
    assert gaps == []   # no referring domain links to 2+ competitors


def test_build_result_shape():
    r = bg.build_result("client.com", {"c.com"}, {"r.com": {"x.com", "y.com"}}, 1)
    assert r["client_domain"] == "client.com"
    assert r["client_referring_domains"] == 1
    assert r["competitors_analyzed"] == 1
    assert r["gap_count"] == 2
