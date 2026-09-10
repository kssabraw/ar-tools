"""Unit tests for the offers/specials and warranty/guarantee assemblers.

Both are structured, operator-supplied and INVENT-NOTHING: offers is pure
assembly (no LLM at all — offer terms are legal facts), warranty narrates only
its connective prose (promise + explainer), never its coverage terms. So these
tests assert the SHAPE and the pass-through, and that narration is a best-effort
enhancement that degrades to the raw supplied text.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services import website_offers as wo
from services import website_warranty as ww


OFFERS = {
    "intro": "Save on your first visit.",
    "offers": [
        {
            "title": "$50 off first service",
            "value": "Save $50",
            "terms": "New customers only",
            "expiry": "Dec 31, 2026",
            "cta_label": "Book now",
            "cta_href": "/contact-us/",
        },
        {"title": "", "value": "dropped — no title"},
    ],
    "financing": "0% for 12 months on approved credit.",
    "fine_print": "One offer per household.",
}


class TestBuildOffersContent:
    def test_offer_cards_pass_through_camelcased(self):
        s = wo.build_offers_content(OFFERS)["frontmatter"]["sections"]
        assert s["offers"] == [
            {
                "title": "$50 off first service",
                "value": "Save $50",
                "terms": "New customers only",
                "expiry": "Dec 31, 2026",
                "ctaLabel": "Book now",
                "ctaHref": "/contact-us/",
            }
        ]  # the title-less offer is dropped
        assert s["intro"] == "Save on your first visit."
        assert s["financing"] == "0% for 12 months on approved credit."
        assert s["finePrint"] == "One offer per household."

    def test_body_is_empty_and_title_defaults(self):
        c = wo.build_offers_content(OFFERS)
        assert c["body"] == ""  # an offers page is its cards, all in sections
        assert c["title"] == "Current Offers"

    def test_description_from_intro(self):
        assert wo.build_offers_content(OFFERS)["description"] == "Save on your first visit."

    def test_description_falls_back_to_first_offer(self):
        c = wo.build_offers_content({"offers": [{"title": "Free estimate", "value": "$0"}]})
        assert c["description"] == "Free estimate — $0"

    def test_empty_offers_is_harmless(self):
        c = wo.build_offers_content({})
        assert c["title"] == "Current Offers"
        assert c["body"] == ""
        assert c["frontmatter"]["sections"] == {}


WARRANTY = {
    "headline": "Our 10-year workmanship guarantee",
    "promise": "If our work fails, we fix it free.",
    "coverage": [
        {"item": "Workmanship", "detail": "All labor", "duration": "10 years"},
        {"item": "", "detail": "dropped — no item"},
    ],
    "claim_steps": ["Call us", "  ", "We inspect", "We repair"],
    "manufacturer_vs_workmanship": "The manufacturer covers the parts; we cover the install.",
    "faq": [
        {"q": "Is it transferable?", "a": "Yes, to the next owner."},
        {"q": "", "a": "dropped — no question"},
    ],
}


class TestBuildWarrantyContent:
    def test_structured_facts_pass_through(self):
        s = ww.build_warranty_content(WARRANTY)["frontmatter"]["sections"]
        assert s["coverage"] == [{"item": "Workmanship", "detail": "All labor", "duration": "10 years"}]
        assert s["claimSteps"] == ["Call us", "We inspect", "We repair"]  # blank step dropped
        assert s["faqItems"] == [{"q": "Is it transferable?", "a": "Yes, to the next owner."}]
        assert s["promise"] == "If our work fails, we fix it free."

    def test_body_carries_the_explainer_when_not_narrated(self):
        body = ww.build_warranty_content(WARRANTY)["body"]
        assert "## Manufacturer vs. workmanship" in body
        assert "covers the parts" in body

    def test_narrated_prose_overrides_supplied_notes(self):
        narrated = {"promise": "We stand behind every job.", "explainer": ""}
        c = ww.build_warranty_content(WARRANTY, narrated)
        assert c["frontmatter"]["sections"]["promise"] == "We stand behind every job."
        # An empty narrated explainer falls back to the operator's supplied text.
        assert "covers the parts" in c["body"]

    def test_title_and_description_default_and_from_promise(self):
        c = ww.build_warranty_content(WARRANTY)
        assert c["title"] == "Our 10-year workmanship guarantee"
        assert c["description"] == "If our work fails, we fix it free."

    def test_a_coverage_only_warranty_still_builds(self):
        c = ww.build_warranty_content({"coverage": [{"item": "Parts", "duration": "1 year"}]})
        assert c["title"] == "Our Guarantee"
        assert c["body"] == ""  # no promise/explainer prose supplied
        assert c["frontmatter"]["sections"]["coverage"]

    def test_empty_warranty_is_harmless(self):
        c = ww.build_warranty_content({})
        assert c["title"] == "Our Guarantee"
        assert c["body"] == ""
        assert c["frontmatter"]["sections"] == {}


@pytest.mark.asyncio
class TestNarrateWarranty:
    """Narration is best-effort: no prose → no call; any failure → None so the
    caller uses the operator's raw text verbatim. Coverage terms are never sent
    for rewriting — only the promise + explainer notes."""

    async def test_no_prose_skips_the_call_entirely(self, monkeypatch):
        called = AsyncMock()
        monkeypatch.setattr(ww.report_llm, "run_forced_tool", called)
        out = await ww.narrate_warranty(
            {"coverage": [{"item": "Parts", "duration": "1 year"}]}, client={}
        )
        assert out is None
        called.assert_not_called()

    async def test_llm_failure_degrades_to_none(self, monkeypatch):
        monkeypatch.setattr(
            ww.report_llm, "run_forced_tool",
            AsyncMock(side_effect=RuntimeError("report_no_tool_use")),
        )
        out = await ww.narrate_warranty({"promise": "We fix it."}, client={})
        assert out is None

    async def test_success_returns_cleaned_two_sections(self, monkeypatch):
        monkeypatch.setattr(
            ww.report_llm, "run_forced_tool",
            AsyncMock(return_value={"promise": "  We stand behind it. ",
                                    "explainer": "Parts vs. labor.", "stray": "ignored"}),
        )
        out = await ww.narrate_warranty({"promise": "we fix it"}, client={})
        assert out == {"promise": "We stand behind it.", "explainer": "Parts vs. labor."}

    async def test_non_dict_tool_output_degrades_to_none(self, monkeypatch):
        monkeypatch.setattr(ww.report_llm, "run_forced_tool", AsyncMock(return_value="oops"))
        out = await ww.narrate_warranty({"manufacturer_vs_workmanship": "parts vs labor"}, client={})
        assert out is None
