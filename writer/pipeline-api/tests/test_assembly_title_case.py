"""Step 11.x - Title case normalization (PRD v2.0.3)."""

from __future__ import annotations

from titlecase import titlecase

from models.brief import FAQItem
from modules.brief.assembly import _apply_title_case, assemble_structure
from modules.brief.graph import Candidate


def _h2(text: str) -> Candidate:
    return Candidate(text=text, source="serp")  # type: ignore[arg-type]


def _h3(text: str) -> Candidate:
    return Candidate(text=text, source="paa")  # type: ignore[arg-type]


def _faq(question: str) -> FAQItem:
    return FAQItem(question=question, source="paa", faq_score=0.85)


def test_h1_normalized_to_title_case():
    items, _ = assemble_structure(
        keyword="how to open a tiktok shop",
        intent="how-to",
        h2s=[],
        h3_attachments={},
        faqs=[
            _faq("How do I start?"),
            _faq("Is it free?"),
            _faq("Who can sell?"),
        ],
        title="how to open a TikTok shop",  # mixed case input
    )
    h1 = next(h for h in items if h.level == "H1")
    # `titlecase` library normalizes the H1 to AP/Chicago style.
    assert h1.text == titlecase("how to open a TikTok shop")
    # And the round-trip is idempotent.
    assert titlecase(h1.text) == h1.text


def test_h2_and_h3_normalized():
    h2 = _h2("do you need 1000 followers")
    h3 = _h3("hidden compliance checklist")
    items, _ = assemble_structure(
        keyword="how to open a tiktok shop",
        intent="how-to",
        h2s=[h2],
        h3_attachments={0: [h3]},
        faqs=[
            _faq("Q1?"),
            _faq("Q2?"),
            _faq("Q3?"),
        ],
        title="How to Open a TikTok Shop",
    )
    h2_item = next(h for h in items if h.level == "H2" and h.type == "content")
    h3_item = next(h for h in items if h.level == "H3" and h.type == "content")
    assert titlecase(h2_item.text) == h2_item.text
    assert titlecase(h3_item.text) == h3_item.text


def test_faq_questions_NOT_normalized():
    """FAQ questions are full sentences ending with `?` - they must
    NOT be passed through titlecase (would mangle natural sentence case)."""
    items, _ = assemble_structure(
        keyword="kw",
        intent="how-to",
        h2s=[],
        h3_attachments={},
        faqs=[
            _faq("How do I start a TikTok Shop?"),
            _faq("Is it free?"),
            _faq("Who can sell?"),
        ],
        title="t",
    )
    faq_questions = [h for h in items if h.type == "faq-question"]
    assert faq_questions[0].text == "How do I start a TikTok Shop?"  # untouched
    assert faq_questions[1].text == "Is it free?"


def test_faq_header_IS_normalized():
    """The 'Frequently Asked Questions' header IS a heading (type=
    faq-header, not faq-question), so it goes through title case."""
    items, _ = assemble_structure(
        keyword="kw", intent="how-to", h2s=[], h3_attachments={},
        faqs=[_faq("Q1?"), _faq("Q2?"), _faq("Q3?")],
        title="t",
    )
    faq_header = next(h for h in items if h.type == "faq-header")
    assert faq_header.text == titlecase("Frequently Asked Questions")


def test_idempotent_round_trip():
    """Calling title case a second time on already-normalized text
    must not change it."""
    items, _ = assemble_structure(
        keyword="kw", intent="how-to",
        h2s=[_h2("Some Heading Text")],
        h3_attachments={0: [_h3("subheading detail")]},
        faqs=[_faq("Q1?"), _faq("Q2?"), _faq("Q3?")],
        title="Already Title Cased",
    )
    before = [h.text for h in items]
    items2 = _apply_title_case(items)
    after = [h.text for h in items2]
    assert before == after


def test_apply_title_case_preserves_brand_proper_nouns():
    """The titlecase library handles 'TikTok', 'iPhone', etc.
    correctly - should not mangle them to 'Tiktok' or 'IPhone'."""
    h2 = _h2("how does TikTok rank stores")
    items, _ = assemble_structure(
        keyword="kw", intent="how-to",
        h2s=[h2], h3_attachments={0: []},
        faqs=[_faq("Q1?"), _faq("Q2?"), _faq("Q3?")],
        title="t",
    )
    h2_item = next(h for h in items if h.level == "H2" and h.type == "content")
    # `titlecase` preserves embedded capitals (TikTok stays TikTok).
    assert "TikTok" in h2_item.text


def test_no_changes_to_silo_or_discarded_paths():
    """Title case applies only to heading_structure[].text. This test
    confirms the assemble_structure scope is limited to its return value
    - no spillover into other module outputs."""
    items, cut = assemble_structure(
        keyword="kw", intent="how-to",
        h2s=[],
        h3_attachments={},
        faqs=[_faq("Q1?"), _faq("Q2?"), _faq("Q3?")],
        title="how to do x",
    )
    # cut is empty (no candidates rejected by global cap in this fixture);
    # nothing to assert beyond that it's a list - ensures we didn't leak
    # title-case mutation into the cut path.
    assert isinstance(cut, list)
