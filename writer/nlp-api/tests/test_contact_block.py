"""Unit tests for the deterministic Contact / Find-Us block on local landing
pages (`main._build_contact_block` + `main._inject_contact_block`).

Covers the four local-landing elements that are injected rather than
LLM-authored: NAP (Name/Address/Phone), the address-keyed GBP map embed, the
driving-directions link, and the contact form — plus the graceful degradation
when an address is missing and the idempotent, article-aware injection. Pure +
offline — no network, no Anthropic. Run with `pytest writer/nlp-api/tests/`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


NAME = "Acme Plumbing"
ADDR = "123 Main St, Anaheim, CA 92805"
PHONE = "(714) 555-0199"


def test_full_block_has_all_four_elements():
    block = main._build_contact_block(NAME, ADDR, PHONE)
    # NAP
    assert NAME in block
    assert ADDR in block
    assert PHONE in block
    assert 'href="tel:7145550199"' in block  # canonical digits, leading 1 not present
    # GBP map embed — address-keyed iframe
    assert "<iframe" in block
    assert "google.com/maps?q=" in block
    assert "output=embed" in block
    assert "Acme+Plumbing" in block  # name+address url-encoded into the query
    # Driving directions
    assert "maps/dir/?api=1&destination=" in block
    assert "Get driving directions" in block
    # Form fill
    assert "<form" in block
    assert 'type="submit"' in block
    # Sentinel id for idempotency
    assert f'id="{main._CONTACT_BLOCK_ID}"' in block


def test_no_address_drops_map_and_directions_keeps_nap_and_form():
    block = main._build_contact_block(NAME, address=None, phone=PHONE)
    assert NAME in block
    assert PHONE in block
    assert "<iframe" not in block          # no address → no embed
    assert "maps/dir/" not in block        # no address → no directions
    assert "<form" in block                # form always present
    assert 'href="tel:7145550199"' in block


def test_no_phone_omits_phone_line():
    block = main._build_contact_block(NAME, ADDR, phone=None)
    assert ADDR in block
    assert "<iframe" in block              # address present → embed present
    assert "tel:" not in block             # no phone → no tel link
    assert 'class="nap-phone"' not in block


def test_no_business_name_returns_empty():
    assert main._build_contact_block("", ADDR, PHONE) == ""
    assert main._build_contact_block("   ", ADDR, PHONE) == ""


def test_business_name_is_html_escaped():
    block = main._build_contact_block("Bob & Sons <Plumbing>", ADDR, PHONE)
    assert "Bob &amp; Sons &lt;Plumbing&gt;" in block
    assert "<Plumbing>" not in block


def test_eleven_digit_phone_strips_leading_one():
    block = main._build_contact_block(NAME, ADDR, "1-714-555-0199")
    assert 'href="tel:7145550199"' in block


def test_inject_inserts_before_closing_article():
    html = "<article><section id='intro'><h1>Hi</h1></section></article>"
    out = main._inject_contact_block(html, NAME, ADDR, PHONE)
    assert out.count(f'id="{main._CONTACT_BLOCK_ID}"') == 1
    # Block sits inside the article (before the final </article>).
    assert out.index(main._CONTACT_BLOCK_ID) < out.rindex("</article>")


def test_inject_appends_when_no_article_wrapper():
    html = "<section id='intro'><h1>Hi</h1></section>"
    out = main._inject_contact_block(html, NAME, ADDR, PHONE)
    assert f'id="{main._CONTACT_BLOCK_ID}"' in out
    assert out.index("id='intro'") < out.index(main._CONTACT_BLOCK_ID)


def test_inject_is_idempotent():
    html = "<article><section id='intro'></section></article>"
    once = main._inject_contact_block(html, NAME, ADDR, PHONE)
    twice = main._inject_contact_block(once, NAME, ADDR, PHONE)
    assert once == twice
    assert twice.count(f'id="{main._CONTACT_BLOCK_ID}"') == 1


def test_inject_no_business_name_leaves_page_unchanged():
    html = "<article><section id='intro'></section></article>"
    assert main._inject_contact_block(html, "", ADDR, PHONE) == html


def test_inject_empty_html_returns_empty():
    assert main._inject_contact_block("", NAME, ADDR, PHONE) == ""
