"""Regression tests for SIE Layer-1 chrome stripping (modules/sie/zones.py).

Guards the crash where a nested role-bearing element, decomposed as part of an
outer role-bearing ancestor, is later revisited in the same `find_all` loop with
its `attrs` already nulled to None — producing
`AttributeError: 'NoneType' object has no attribute 'get'` and a 500 from /sie.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from modules.sie.zones import _layer1_strip_chrome, extract_zones


def test_nested_role_elements_do_not_crash_strip():
    # Outer role=navigation contains an inner role=banner. Decomposing the outer
    # leaves the inner (still in the materialized list) decomposed with attrs=None.
    html = (
        "<html><body>"
        '<div role="navigation"><span role="banner">nav junk</span></div>'
        "<main><p>Real body content that is clearly long enough to keep.</p></main>"
        "</body></html>"
    )
    soup = BeautifulSoup(html, "html.parser")
    _layer1_strip_chrome(soup)  # must not raise
    # Both role-bearing chrome elements are gone; the real content survives.
    assert soup.find_all(attrs={"role": True}) == []
    assert "Real body content" in soup.get_text()


def test_extract_zones_survives_nested_role_chrome():
    html = (
        "<html><head><title>T</title></head><body>"
        '<div role="navigation"><nav role="banner"><a href="/">home</a></nav></div>'
        "<main><h1>Heading</h1>"
        "<p>Real body content that is clearly long enough to keep around.</p>"
        "</main></body></html>"
    )
    zones = extract_zones("http://example.com", html)
    assert zones is not None
    assert zones.h1 == ["Heading"]
    assert any("Real body content" in p for p in zones.paragraphs)
