"""Regression tests for the SIE ScrapeOwl client (modules/sie/scraper.py).

Guards the crash where ScrapeOwl answered a 200 whose ``html``/``body`` field was
a *dict* (a structured element/error payload) rather than a string. The old code
(``data.get("html") or data.get("body") or ""``) let that dict through as
``ScrapeResult.html`` with ``success=True``, and it reached
``extract_zones()``'s ``html.strip()`` — raising
``AttributeError: 'dict' object has no attribute 'strip'`` and 500-ing the whole
``/sie`` call, which the run-level auto-retry then cycled on for over an hour.
"""

from __future__ import annotations

from modules.sie.scraper import _extract_html


def test_extract_html_returns_string_body():
    assert _extract_html({"html": "<html><body>real</body></html>"}) == (
        "<html><body>real</body></html>"
    )


def test_extract_html_falls_back_to_body_key():
    assert _extract_html({"body": "<p>fallback</p>"}) == "<p>fallback</p>"


def test_extract_html_prefers_html_over_body():
    assert _extract_html({"html": "<h1>a</h1>", "body": "<h1>b</h1>"}) == "<h1>a</h1>"


def test_extract_html_dict_value_is_dropped():
    # The exact production incident: ScrapeOwl returned a dict under "html".
    assert _extract_html({"html": {"error": "blocked"}}) == ""


def test_extract_html_uses_body_when_html_is_a_dict():
    # A non-string html must not shadow a perfectly good string body.
    assert _extract_html({"html": {"x": 1}, "body": "<p>ok</p>"}) == "<p>ok</p>"


def test_extract_html_none_and_empty_and_missing():
    assert _extract_html({"html": None}) == ""
    assert _extract_html({"html": ""}) == ""
    assert _extract_html({}) == ""


def test_extract_html_non_string_scalars_dropped():
    assert _extract_html({"html": 12345}) == ""
    assert _extract_html({"html": ["<p>list</p>"]}) == ""
