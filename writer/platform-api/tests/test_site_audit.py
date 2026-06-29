"""Unit tests for services.site_audit — pure parse + scoring."""

from __future__ import annotations

from services import site_audit as sa


def test_parse_page_maps_checks_to_issues():
    page = {"url": "https://x.com/a", "status_code": 200,
            "checks": {"no_title": True, "no_h1_tag": True, "large_page_size": True}}
    issues = sa.parse_page(page)
    assert {i["type"] for i in issues} == {"missing_title", "missing_h1", "page_weight"}
    assert all(i["url"] == "https://x.com/a" for i in issues)


def test_parse_page_status_code_marks_broken():
    issues = sa.parse_page({"url": "u", "status_code": 404, "checks": {}})
    assert issues == [{"type": "broken_page", "severity": "high", "url": "u", "detail": "HTTP 404"}]


def test_parse_page_does_not_double_count_broken():
    issues = sa.parse_page({"url": "u", "status_code": 500, "checks": {"is_5xx_code": True}})
    assert sum(1 for i in issues if i["type"] == "broken_page") == 1


def test_score_clean_pages_is_100():
    assert sa.score_issues([], 5) == 100


def test_score_drops_with_severe_issues():
    assert sa.score_issues([{"severity": "high"}] * 3, 1) < 100


def test_build_result_aggregates_counts_and_score():
    pages = [
        {"url": "a", "status_code": 200, "checks": {"no_title": True}},      # high
        {"url": "b", "status_code": 200, "checks": {"no_image_alt": True}},  # low
    ]
    r = sa.build_result(pages)
    assert r["pages_scanned"] == 2
    assert r["issue_count"] == 2
    assert r["counts_by_severity"] == {"high": 1, "medium": 0, "low": 1}
    assert 0 <= r["score"] <= 100
