"""Tests for the sibling internal-links prompt block (`main._internal_links_block`)
and the request-model field it reads — the nlp-api half of the service × location
matrix's silo linking (platform-api plans the links, verifies them, and appends
any the writer dropped)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402

LINKS = [
    {"anchor": "Roof restoration in Hawthorn", "url": "https://fcr.com.au/roof-restoration-hawthorn/", "relation": "same_location_other_service"},
    {"anchor": "Tile roof restoration in Melbourne", "url": "https://fcr.com.au/tile-roof-restoration-melbourne/", "relation": "same_service_other_location"},
]


def test_block_renders_every_link_with_its_relation():
    block = main._internal_links_block(LINKS)
    assert block.startswith("\nINTERNAL LINKS")
    assert "Roof restoration in Hawthorn → https://fcr.com.au/roof-restoration-hawthorn/  (another service in this location)" in block
    assert "Tile roof restoration in Melbourne → https://fcr.com.au/tile-roof-restoration-melbourne/  (this service in a nearby location)" in block
    assert "Never place these in the H1" in block


def test_block_empty_when_no_links():
    assert main._internal_links_block(None) == ""
    assert main._internal_links_block([]) == ""
    assert main._internal_links_block([{"anchor": "x", "url": ""}, "junk"]) == ""


def test_block_caps_and_tolerates_unknown_relation_and_missing_anchor():
    many = [{"anchor": f"a{i}", "url": f"/p{i}/", "relation": "weird"} for i in range(20)]
    block = main._internal_links_block(many)
    assert block.count("→") == main._INTERNAL_LINKS_MAX
    assert "(a related page)" in block
    assert "- /only-url/ → /only-url/" in main._internal_links_block([{"url": "/only-url/"}])


def test_request_models_accept_internal_links():
    gen = main.GeneratePageRequest(
        keyword="roof restoration Hawthorn", location="Melbourne,Victoria,Australia",
        business_name="FCR", gbp_category="Roofing contractor", address="1 St", internal_links=LINKS,
    )
    assert gen.internal_links == LINKS
    reopt = main.ReoptimizePageRequest(
        keyword="k", location="l", deficiencies=[], business_name="b", gbp_category="c", internal_links=LINKS,
    )
    assert reopt.internal_links == LINKS
    # Default stays None so every existing caller is untouched.
    assert main.GeneratePageRequest(
        keyword="k", location="l", business_name="b", gbp_category="c", address="a",
    ).internal_links is None
