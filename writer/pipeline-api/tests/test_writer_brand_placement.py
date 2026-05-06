"""Step 3.6 - Brand & ICP placement plan.

Regression tests for the bug where every section punted on the brand
mention ("let another section carry it") and the article shipped with
zero brand mentions and no ICP callout. The plan deterministically
pre-allocates exactly one H2 for each, so per-section coordination
isn't required.
"""

from __future__ import annotations

from models.writer import BrandVoiceCard
from modules.writer.brand_placement import (
    BrandPlacementPlan,
    H2PlacementDirective,
    brand_mention_present,
    build_brand_placement_plan,
)


def _h2(order: int, text: str) -> dict:
    return {"order": order, "level": "H2", "type": "content", "text": text}


def _h3(order: int, text: str) -> dict:
    return {"order": order, "level": "H3", "type": "content", "text": text}


def test_no_brand_card_returns_empty_plan():
    structure = [_h2(1, "Pricing"), _h2(2, "Optimize")]
    plan = build_brand_placement_plan(structure, None)
    assert plan.brand_anchor_order is None
    assert plan.icp_anchor_order is None
    assert plan.directives == {}


def test_empty_card_returns_empty_plan():
    structure = [_h2(1, "Pricing")]
    plan = build_brand_placement_plan(structure, BrandVoiceCard())
    assert plan.brand_anchor_order is None
    assert plan.icp_anchor_order is None


def test_no_content_h2s_returns_empty_plan():
    plan = build_brand_placement_plan(
        [{"order": 1, "level": "H1", "type": "content", "text": "Title"}],
        BrandVoiceCard(brand_name="Ubiquitous"),
    )
    assert plan.brand_anchor_order is None


def test_brand_anchor_picks_best_service_match():
    """Token overlap with `client_services` drives brand anchor choice."""
    structure = [
        _h2(1, "Pricing strategy basics"),
        _h2(2, "Creator content amplification on TikTok Shop"),
        _h2(3, "Returns and refunds"),
    ]
    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        client_services=["creator content marketing", "paid amplification"],
    )
    plan = build_brand_placement_plan(structure, card)
    # H2 #2 shares 3 tokens with the services ("creator", "content",
    # "amplification"); the others share zero or one.
    assert plan.brand_anchor_order == 2


def test_brand_anchor_falls_back_to_first_h2_when_no_overlap():
    structure = [_h2(1, "Pricing"), _h2(2, "Optimize"), _h2(3, "Returns")]
    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        client_services=["unrelated service"],
    )
    plan = build_brand_placement_plan(structure, card)
    assert plan.brand_anchor_order == 1


def test_icp_anchor_picks_best_pain_point_match_and_records_hook():
    structure = [
        _h2(1, "Pricing"),
        _h2(2, "Reduce returns and refund rates"),
        _h2(3, "Optimize listings"),
    ]
    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        audience_pain_points=["high refund rates eating margin"],
    )
    plan = build_brand_placement_plan(structure, card)
    # Brand falls back to first H2; ICP should pick H2 #2 (matches
    # "refund rates"), not collide with brand anchor.
    assert plan.brand_anchor_order == 1
    assert plan.icp_anchor_order == 2
    assert plan.icp_hook_phrase == "high refund rates eating margin"


def test_icp_anchor_avoids_collision_with_brand_anchor():
    """If the best-scoring section for ICP is also the brand anchor,
    pick the next-best for ICP so they're variety-distributed."""
    structure = [
        _h2(1, "Creator content for refund reduction"),
        _h2(2, "Pricing"),
    ]
    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        client_services=["creator content"],
        audience_pain_points=["refund reduction"],
    )
    plan = build_brand_placement_plan(structure, card)
    # Both signals best-match H2 #1. ICP must avoid the collision and
    # take H2 #2 instead.
    assert plan.brand_anchor_order == 1
    assert plan.icp_anchor_order == 2


def test_icp_falls_back_to_first_non_brand_h2_when_no_audience_match():
    structure = [_h2(1, "Pricing"), _h2(2, "Optimize"), _h2(3, "Returns")]
    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        client_services=["pricing strategy"],
        audience_verticals=["totally unrelated vertical"],
    )
    plan = build_brand_placement_plan(structure, card)
    assert plan.brand_anchor_order == 1  # service match
    assert plan.icp_anchor_order == 2    # first non-brand H2 (no overlap)


def test_directives_force_non_anchor_sections_to_skip_brand():
    """Every non-anchor H2 must get must_not_mention_brand=True so
    sections can't punt the mention into themselves either."""
    structure = [_h2(1, "A"), _h2(2, "B"), _h2(3, "C")]
    card = BrandVoiceCard(brand_name="Ubiquitous")
    plan = build_brand_placement_plan(structure, card)
    anchor = plan.brand_anchor_order
    for order in (1, 2, 3):
        d = plan.for_order(order)
        if order == anchor:
            assert d.must_mention_brand is True
            assert d.must_not_mention_brand is False
        else:
            assert d.must_mention_brand is False
            assert d.must_not_mention_brand is True


def test_for_order_returns_empty_directive_for_unknown_order():
    plan = build_brand_placement_plan([_h2(1, "A")], BrandVoiceCard(brand_name="X"))
    d = plan.for_order(999)
    assert d.must_mention_brand is False
    assert d.must_not_mention_brand is False
    assert d.icp_callout_hook is None


def test_no_brand_name_but_has_audience_still_assigns_icp_only():
    """Audience-only configurations (no brand name) should still surface
    an ICP callout - the soft signals shouldn't be silently dropped."""
    structure = [_h2(1, "Returns"), _h2(2, "Pricing")]
    card = BrandVoiceCard(audience_pain_points=["return rate"])
    plan = build_brand_placement_plan(structure, card)
    assert plan.brand_anchor_order is None
    assert plan.icp_anchor_order == 1
    assert plan.icp_hook_phrase == "return rate"
    # No brand_name → no must_mention/must_not_mention flags should be
    # set anywhere (we'd be telling sections about a brand that doesn't
    # exist).
    for order in (1, 2):
        d = plan.for_order(order)
        assert d.must_mention_brand is False
        assert d.must_not_mention_brand is False


def test_section_prompt_emits_must_mention_when_directive_is_anchor():
    """Section prompt must include the hard MUST-mention directive
    when the H2 is the brand anchor - not the old soft fallback."""
    from modules.writer.sections import _build_section_user_prompt

    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        client_services=["creator marketing"],
    )
    directive = H2PlacementDirective(must_mention_brand=True)
    prompt = _build_section_user_prompt(
        keyword="kw",
        intent="informational",
        h2_item={"order": 1, "text": "Pricing"},
        h3_items=[],
        section_budgets={1: 200},
        required_terms=[],
        excluded_terms=[],
        avoid_terms=[],
        forbidden_terms=[],
        citations=[],
        brand_voice_card=card,
        is_authority_gap_section=False,
        placement_directive=directive,
    )
    assert "REQUIRED" in prompt
    assert "MUST mention Ubiquitous EXACTLY ONCE" in prompt
    # Soft fallback language must be absent - that's the bug we're fixing.
    assert "let another carry it" not in prompt
    assert "1–2 times" not in prompt and "1-2 times" not in prompt


def test_section_prompt_emits_do_not_mention_when_directive_is_non_anchor():
    """Non-anchor sections must be told NOT to mention the brand -
    the bug had every section punting under the soft 'let another carry
    it' instruction, so we have to actively suppress mentions outside
    the anchor."""
    from modules.writer.sections import _build_section_user_prompt

    card = BrandVoiceCard(brand_name="Ubiquitous")
    directive = H2PlacementDirective(must_not_mention_brand=True)
    prompt = _build_section_user_prompt(
        keyword="kw",
        intent="informational",
        h2_item={"order": 1, "text": "Pricing"},
        h3_items=[],
        section_budgets={1: 200},
        required_terms=[],
        excluded_terms=[],
        avoid_terms=[],
        forbidden_terms=[],
        citations=[],
        brand_voice_card=card,
        is_authority_gap_section=False,
        placement_directive=directive,
    )
    assert "DO NOT mention Ubiquitous" in prompt


def test_section_prompt_emits_icp_callout_with_hook():
    from modules.writer.sections import _build_section_user_prompt

    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        audience_pain_points=["margin erosion from refunds"],
    )
    directive = H2PlacementDirective(
        must_not_mention_brand=True,
        icp_callout_hook="margin erosion from refunds",
    )
    prompt = _build_section_user_prompt(
        keyword="kw",
        intent="informational",
        h2_item={"order": 1, "text": "Returns"},
        h3_items=[],
        section_budgets={1: 200},
        required_terms=[],
        excluded_terms=[],
        avoid_terms=[],
        forbidden_terms=[],
        citations=[],
        brand_voice_card=card,
        is_authority_gap_section=False,
        placement_directive=directive,
    )
    assert "ICP_CALLOUT (REQUIRED)" in prompt
    assert "margin erosion from refunds" in prompt


def test_section_prompt_keeps_soft_fallback_when_no_directive_passed():
    """Backward-compat: callers that don't pass a directive still get
    the original soft language, so the new module is purely additive."""
    from modules.writer.sections import _build_section_user_prompt

    card = BrandVoiceCard(brand_name="Ubiquitous")
    prompt = _build_section_user_prompt(
        keyword="kw",
        intent="informational",
        h2_item={"order": 1, "text": "Pricing"},
        h3_items=[],
        section_budgets={1: 200},
        required_terms=[],
        excluded_terms=[],
        avoid_terms=[],
        forbidden_terms=[],
        citations=[],
        brand_voice_card=card,
        is_authority_gap_section=False,
        # placement_directive omitted - exercises the fallback branch.
    )
    assert "1–2 times" in prompt or "1-2 times" in prompt
    assert "let another carry" in prompt


def test_plan_records_anchor_heading_text():
    """The heading text is the unambiguous editor reference; the
    pre-resequence `order` is meaningless after pipeline.py:632
    renumbers every section to its final position."""
    structure = [_h2(1, "Pricing"), _h2(2, "Returns")]
    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        client_services=["pricing strategy"],
        audience_pain_points=["return rate"],
    )
    plan = build_brand_placement_plan(structure, card)
    assert plan.brand_anchor_text == "Pricing"
    assert plan.icp_anchor_text == "Returns"


def test_plan_text_fields_none_when_no_anchor():
    structure = [_h2(1, "Pricing")]
    plan = build_brand_placement_plan(structure, None)
    assert plan.brand_anchor_text is None
    assert plan.icp_anchor_text is None


def test_brand_mention_present_positive_match():
    assert brand_mention_present(
        "At Ubiquitous we run creator marketing.",
        "Ubiquitous",
    )


def test_brand_mention_present_word_boundary_blocks_substring():
    """A brand named "Net" must NOT match 'internet'. Without word
    boundaries the verifier would report success on a body that never
    actually mentioned the brand."""
    assert not brand_mention_present(
        "We use the internet for outreach.",
        "Net",
    )


def test_brand_mention_present_case_insensitive():
    assert brand_mention_present("UBIQUITOUS leads the space.", "Ubiquitous")
    assert brand_mention_present("ubiquitous leads.", "Ubiquitous")


def test_brand_mention_present_empty_inputs():
    assert not brand_mention_present("", "Ubiquitous")
    assert not brand_mention_present("something", "")
    assert not brand_mention_present("", "")


def test_brand_mention_present_escapes_regex_special_chars():
    """Brand names with regex metacharacters (e.g. 'Foo+Bar', 'A.B
    Inc.') must be escaped before the boundary check, otherwise the
    pattern explodes or matches the wrong thing."""
    assert brand_mention_present("We partner with Foo+Bar.", "Foo+Bar")
    assert brand_mention_present("Hired by A.B Inc.", "A.B Inc.")


def test_user_failure_layout_assigns_a_brand_anchor():
    """The article that shipped with zero brand mentions had three
    body H2s and a populated brand voice card. The plan should produce
    exactly one brand anchor and one ICP anchor across that layout."""
    structure = [
        _h2(1, "Set Smarter Pricing and Discount Tactics"),
        _h3(2, "Shop Score Affects ROI More Than Ad Spend"),
        _h2(3, "Optimize Product Listings to Convert Impulse Traffic"),
        _h2(4, "Reduce Returns and Refund Rates"),
        _h3(5, "Live-commerce in Southeast Asia"),
        _h3(6, "Cold-start Trust Problem"),
    ]
    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        client_services=["creator marketing", "paid amplification"],
        audience_pain_points=["margin erosion from refunds and returns"],
        audience_verticals=["TikTok Shop", "Beauty", "Health & Wellness"],
    )
    plan = build_brand_placement_plan(structure, card)

    # Exactly one brand anchor and one ICP anchor.
    assert plan.brand_anchor_order is not None
    assert plan.icp_anchor_order is not None
    assert plan.brand_anchor_order != plan.icp_anchor_order

    # Anchors must be content H2s, not H3s.
    h2_orders = {1, 3, 4}
    assert plan.brand_anchor_order in h2_orders
    assert plan.icp_anchor_order in h2_orders

    # ICP should land on the Returns H2 (token overlap with "refunds and
    # returns") and the hook phrase should be the matched pain point.
    assert plan.icp_anchor_order == 4
    assert plan.icp_hook_phrase == "margin erosion from refunds and returns"
