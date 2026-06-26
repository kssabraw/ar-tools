"""Unit tests for services.target_cities — pure helpers.

The network resolver (resolve_target_cities) needs geocoding/Overpass and isn't
exercised here; the slug/name + area parsing helpers are.
"""

from __future__ import annotations

from services import target_cities as tc


def test_parse_area():
    assert tc._parse_area("Sydney,New South Wales,Australia") == ("Sydney", "New South Wales", "Australia")
    assert tc._parse_area("London,United Kingdom") == ("London", "", "United Kingdom")
    assert tc._parse_area("Austin") == ("Austin", "", "")
    assert tc._parse_area("") == ("", "", "")


def test_slug_to_name():
    assert tc._slug_to_name("inner-west") == "Inner West"
    assert tc._slug_to_name("los_angeles") == "Los Angeles"
    assert tc._slug_to_name("parramatta") == "Parramatta"


def test_website_candidate_names_dedupes_and_titlecases():
    urls = [
        "https://acme.com/parramatta/",
        "https://acme.com/service-areas/inner-west/",
        "https://acme.com/PARRAMATTA/",  # dup (case-insensitive)
        "https://acme.com/",
    ]
    names = tc.website_candidate_names(urls)
    # Order: first-seen; segments include 'Service Areas' before 'Inner West'.
    assert "Parramatta" in names
    assert "Inner West" in names
    assert "Service Areas" in names
    # case-insensitive dedupe — Parramatta appears once
    assert names.count("Parramatta") == 1
