"""Step 0.5 — Heading-structure sanitizer.

Regression tests for the structural drift modes observed in the user's
TikTok Shop article:
- Duplicate body H2s rendered as two near-identical sections.
- An H2 with type="content" and heading "Frequently Asked Questions"
  rendered as a body section, pushing the conclusion BETWEEN that
  fake FAQ block and the real one.
"""

from __future__ import annotations

from modules.writer.heading_sanitizer import (
    SanitizationLog,
    sanitize_heading_structure,
)


def _h1(o, t="Title"): return {"order": o, "level": "H1", "type": "content", "text": t}
def _h2(o, t): return {"order": o, "level": "H2", "type": "content", "text": t}
def _h3(o, t): return {"order": o, "level": "H3", "type": "content", "text": t}
def _faq_header(o, t="Frequently Asked Questions"): return {"order": o, "level": "H2", "type": "faq-header", "text": t}
def _faq_q(o, t): return {"order": o, "level": "H3", "type": "faq-question", "text": t}


def test_empty_input_returns_empty():
    cleaned, log = sanitize_heading_structure([])
    assert cleaned == []
    assert log.duplicate_h2s_dropped == []
    assert log.faq_like_h2s_dropped == []


def test_clean_structure_passes_through_untouched():
    structure = [
        _h1(1),
        _h2(2, "Pricing"),
        _h3(3, "Sub-section"),
        _h2(4, "Returns"),
        _faq_header(5),
        _faq_q(6, "Question?"),
    ]
    cleaned, log = sanitize_heading_structure(structure)
    assert cleaned == structure
    assert log.duplicate_h2s_dropped == []
    assert log.faq_like_h2s_dropped == []
    assert log.h3_children_dropped == []


def test_drops_duplicate_h2_with_identical_text():
    """The user's TikTok Shop article had this exact pattern: two H2s
    with the heading 'Test Limited-time Discounts and Bundles Against
    Base Price Cuts to Lift ROI' appearing back-to-back."""
    structure = [
        _h2(1, "Margin Audit"),
        _h2(2, "Test Limited-time Discounts and Bundles Against Base Price Cuts to Lift ROI"),
        _h3(3, "Hotel Revenue Management"),
        _h2(4, "Test Limited-time Discounts and Bundles Against Base Price Cuts to Lift ROI"),
        _h3(5, "Hotel Revenue Management duplicate"),
        _h3(6, "Shop Performance Score"),
    ]
    cleaned, log = sanitize_heading_structure(structure)
    cleaned_orders = [c.get("order") for c in cleaned]
    # Order 4 (duplicate H2) and orders 5, 6 (its children) all dropped.
    assert cleaned_orders == [1, 2, 3]
    assert len(log.duplicate_h2s_dropped) == 1
    assert log.duplicate_h2s_dropped[0]["order"] == 4
    assert len(log.h3_children_dropped) == 2
    assert {h["order"] for h in log.h3_children_dropped} == {5, 6}


def test_drops_faq_like_content_h2_and_its_children():
    """The user's article also had an H2 with type='content' and text
    'Frequently Asked Questions' — the writer rendered it BEFORE the
    conclusion while the real faq-header block ended up AFTER."""
    structure = [
        _h2(1, "Pricing"),
        _h2(2, "Frequently Asked Questions"),  # FAQ-as-content body H2
        _h3(3, "What about refunds?"),
        _faq_header(4),
        _faq_q(5, "Real FAQ?"),
    ]
    cleaned, log = sanitize_heading_structure(structure)
    cleaned_orders = [c.get("order") for c in cleaned]
    # FAQ-as-content H2 (order 2) and its H3 child (order 3) dropped;
    # the real faq-header + faq-question pass through untouched.
    assert cleaned_orders == [1, 4, 5]
    assert len(log.faq_like_h2s_dropped) == 1
    assert log.faq_like_h2s_dropped[0]["order"] == 2
    assert len(log.h3_children_dropped) == 1
    assert log.h3_children_dropped[0]["order"] == 3


def test_faq_like_match_variants():
    """Tolerate common variants: FAQs, FAQ, Q&A, Q and A, case drift."""
    for text in [
        "FAQs",
        "FAQ",
        "Frequently Asked Question",   # singular
        "FREQUENTLY ASKED QUESTIONS",
        "  frequently asked questions  ",
        "Q&A",
        "Q & A",
        "Q and A",
    ]:
        structure = [_h2(1, "Body"), _h2(2, text)]
        cleaned, log = sanitize_heading_structure(structure)
        assert len(log.faq_like_h2s_dropped) == 1, f"failed to drop {text!r}"


def test_faq_substring_in_legitimate_heading_is_kept():
    """An H2 like 'Frequently Asked Questions About Pricing' is a
    legitimate body section, not a FAQ block. The pattern requires a
    full-string match so substrings stay in."""
    structure = [
        _h2(1, "Pricing"),
        _h2(2, "Frequently Asked Questions About Pricing"),
    ]
    cleaned, log = sanitize_heading_structure(structure)
    assert len(cleaned) == 2
    assert log.faq_like_h2s_dropped == []


def test_dedup_normalizes_case_whitespace_and_trailing_punctuation():
    """Brief drift can produce 'Reduce Returns' and 'reduce returns:'
    as two separate H2 entries — they should collapse to one."""
    structure = [
        _h2(1, "Reduce Returns"),
        _h2(2, "  reduce returns:  "),
        _h2(3, "REDUCE RETURNS!"),
    ]
    cleaned, log = sanitize_heading_structure(structure)
    cleaned_orders = [c.get("order") for c in cleaned]
    assert cleaned_orders == [1]
    assert len(log.duplicate_h2s_dropped) == 2


def test_kept_h2_preserves_original_casing_and_punctuation():
    """Normalization is for *detection only* — the H2 that survives
    keeps its original text so the section writer's prompt and the
    rendered article match the brief's intended phrasing."""
    structure = [
        _h2(1, "Reduce Returns:  "),
        _h2(2, "reduce returns"),
    ]
    cleaned, _ = sanitize_heading_structure(structure)
    assert cleaned[0]["text"] == "Reduce Returns:  "  # untouched


def test_orders_are_preserved_no_renumbering():
    """Downstream code looks up section_budgets / placement plan by
    `order`. The sanitizer must NOT renumber surviving entries — only
    pipeline.py:632 does that, after assembly."""
    structure = [
        _h2(1, "A"),
        _h2(5, "B"),  # gap in orders
        _h2(7, "A"),  # duplicate of 1
    ]
    cleaned, _ = sanitize_heading_structure(structure)
    cleaned_orders = [c.get("order") for c in cleaned]
    assert cleaned_orders == [1, 5]


def test_faq_header_block_resets_drop_flag():
    """When a FAQ-as-content body H2 is dropped, the drop-flag must
    reset on the next non-content marker (faq-header / conclusion) so
    H3 questions under the real FAQ block aren't accidentally dropped."""
    structure = [
        _h2(1, "Frequently Asked Questions"),  # dropped
        _h3(2, "Body H3 under dropped H2"),     # dropped along with H2
        _faq_header(3),                         # resets drop flag
        _faq_q(4, "Real Q1"),
        _faq_q(5, "Real Q2"),
    ]
    cleaned, log = sanitize_heading_structure(structure)
    cleaned_orders = [c.get("order") for c in cleaned]
    assert cleaned_orders == [3, 4, 5]
    assert log.h3_children_dropped[0]["order"] == 2  # only the body H3
    assert len(log.h3_children_dropped) == 1


def test_conclusion_resets_drop_flag():
    structure = [
        _h2(1, "Dropped H2"),
        _h2(2, "Dropped H2"),  # duplicate → dropped
        _h3(3, "Body H3 under dropped"),  # dropped
        {"order": 4, "level": "H2", "type": "conclusion", "text": "Conclusion"},
        _h3(5, "H3 after conclusion — not under a dropped H2"),
    ]
    cleaned, log = sanitize_heading_structure(structure)
    # Conclusion resets flag; the H3 after conclusion isn't dropped.
    assert any(c.get("order") == 5 for c in cleaned)


def test_user_failure_layout_produces_clean_structure():
    """End-to-end on the exact pattern from the user's TikTok Shop
    article. Expected outcome: one Margin Audit H2, one Test Limited-
    time H2 with one Hotel Revenue child, the real faq-header + 3
    faq-questions. The duplicate Test Limited-time H2 and its
    children, plus the FAQ-as-content body H2 and its child question,
    are all dropped."""
    structure = [
        _h1(0, "How to Increase ROI"),
        _h2(1, "Start With a Full Margin Audit"),
        _h2(2, "Test Limited-time Discounts"),
        _h3(3, "Hotel Revenue Management"),
        _h2(4, "Test Limited-time Discounts"),                # duplicate
        _h3(5, "Hotel Revenue Management duplicate"),         # under duplicate
        _h3(6, "Shop Performance Score"),                     # under duplicate
        _h2(7, "Frequently Asked Questions"),                 # FAQ-as-content
        _h3(8, "Best Strategies sub-question"),               # under FAQ-as-content
        {"order": 9, "level": "H2", "type": "conclusion", "text": "Conclusion"},
        _faq_header(10),
        _faq_q(11, "Real Q1"),
        _faq_q(12, "Real Q2"),
        _faq_q(13, "Real Q3"),
    ]
    cleaned, log = sanitize_heading_structure(structure)
    kept_orders = [c.get("order") for c in cleaned]
    # H1, Margin Audit, Test Limited-time, Hotel Revenue (kept group),
    # conclusion, faq-header, 3 faq-questions.
    assert kept_orders == [0, 1, 2, 3, 9, 10, 11, 12, 13]
    assert len(log.duplicate_h2s_dropped) == 1
    assert log.duplicate_h2s_dropped[0]["order"] == 4
    assert len(log.faq_like_h2s_dropped) == 1
    assert log.faq_like_h2s_dropped[0]["order"] == 7
    # Three H3s dropped: orders 5, 6 (under duplicate), 8 (under faq-like).
    assert {h["order"] for h in log.h3_children_dropped} == {5, 6, 8}


def test_non_dict_entries_are_filtered():
    """Defensive: a malformed brief that put a string in
    heading_structure must not crash the sanitizer."""
    structure = [_h2(1, "A"), "not a dict", None, 42, _h2(2, "B")]
    cleaned, log = sanitize_heading_structure(structure)
    assert [c.get("order") for c in cleaned] == [1, 2]


def test_non_list_input_returns_empty():
    cleaned, log = sanitize_heading_structure(None)  # type: ignore[arg-type]
    assert cleaned == []
    assert isinstance(log, SanitizationLog)
