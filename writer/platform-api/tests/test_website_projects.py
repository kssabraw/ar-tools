"""Unit tests for the project / case-study assembler.

The load-bearing rule: the structured facts pass through untouched and the prose
is whatever was supplied or narrated — the writer invents nothing, so these tests
assert the SHAPE and the pass-through, not any generated content.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services import website_projects as wp


PROJECT = {
    "headline": "Emergency Oak Removal in Anaheim",
    "location": "Anaheim, CA",
    "stats": [
        {"label": "Tree height", "value": "60 ft"},
        {"label": "Completed in", "value": "1 day"},
        {"label": "", "value": "dropped — no label"},
    ],
    "challenge": "A 60-foot oak split in a storm over the garage.",
    "work": "Rigged the canopy down in sections.",
    "outcome": "Down and cleaned in one day, zero damage.",
    "testimonial_quote": "They saved our garage.",
    "testimonial_author": "M. Reyes",
    "photos": [
        {"url": "https://ex.com/a.jpg", "alt": "before", "caption": "Leaning"},
        {"url": "", "alt": "dropped — no url"},
    ],
    "service_slug": "tree-removal",
    "service_name": "Tree Removal",
    "location_slug": "anaheim",
    "location_name": "Anaheim",
}


class TestBuildProjectContent:
    def test_structured_facts_pass_through(self):
        c = wp.build_project_content(PROJECT)
        s = c["frontmatter"]["sections"]
        # Stats/photos with an empty required side are dropped.
        assert s["stats"] == [{"label": "Tree height", "value": "60 ft"},
                              {"label": "Completed in", "value": "1 day"}]
        assert s["photos"] == [{"url": "https://ex.com/a.jpg", "alt": "before", "caption": "Leaning"}]
        assert s["geo"] == "Anaheim, CA"
        assert s["testimonial"] == {"quote": "They saved our garage.", "author": "M. Reyes"}
        assert s["links"] == [
            {"href": "/tree-removal/", "title": "Tree Removal"},
            {"href": "/anaheim/", "title": "Anaheim"},
        ]

    def test_title_and_hero_from_first_photo(self):
        c = wp.build_project_content(PROJECT)
        assert c["title"] == "Emergency Oak Removal in Anaheim"
        assert c["frontmatter"]["heroImage"] == "https://ex.com/a.jpg"

    def test_body_uses_supplied_prose_when_not_narrated(self):
        body = wp.build_project_content(PROJECT)["body"]
        assert "## The challenge" in body and "storm over the garage" in body
        assert "## What we did" in body and "## The result" in body

    def test_narrated_prose_overrides_supplied_notes(self):
        narrated = {"challenge": "Rewritten challenge.", "work": "", "outcome": "Rewritten result."}
        body = wp.build_project_content(PROJECT, narrated)["body"]
        assert "Rewritten challenge." in body
        # An empty narrated field falls back to the operator's supplied text.
        assert "Rigged the canopy" in body
        assert "Rewritten result." in body

    def test_meta_description_comes_from_the_outcome(self):
        assert "one day" in wp.build_project_content(PROJECT)["description"]

    def test_a_stats_and_photos_only_project_still_builds(self):
        bare = {"headline": "Job", "stats": [{"label": "x", "value": "1"}],
                "photos": [{"url": "https://e/x.jpg"}]}
        c = wp.build_project_content(bare)
        assert c["title"] == "Job"
        assert c["body"] == ""  # no prose supplied
        assert c["frontmatter"]["sections"]["stats"]

    def test_empty_project_is_harmless(self):
        c = wp.build_project_content({})
        assert c["title"] == "Project"
        assert c["body"] == ""
        assert c["frontmatter"]["sections"] == {}


@pytest.mark.asyncio
class TestNarrateProject:
    """Narration is a best-effort enhancement, never a gate: no prose → no call;
    any failure → None so the caller uses the operator's raw text verbatim."""

    async def test_no_prose_skips_the_call_entirely(self, monkeypatch):
        called = AsyncMock()
        monkeypatch.setattr(wp.report_llm, "run_forced_tool", called)
        out = await wp.narrate_project(
            {"headline": "Job", "stats": [{"label": "x", "value": "1"}]}, client={}
        )
        assert out is None
        called.assert_not_called()

    async def test_llm_failure_degrades_to_none(self, monkeypatch):
        monkeypatch.setattr(
            wp.report_llm, "run_forced_tool",
            AsyncMock(side_effect=RuntimeError("report_no_tool_use")),
        )
        out = await wp.narrate_project({"challenge": "It leaked."}, client={})
        assert out is None  # caller falls back to the raw supplied text

    async def test_success_returns_cleaned_three_sections(self, monkeypatch):
        monkeypatch.setattr(
            wp.report_llm, "run_forced_tool",
            AsyncMock(return_value={"challenge": "  A storm. ", "work": "We fixed it.",
                                    "outcome": "No leaks.", "stray": "ignored"}),
        )
        out = await wp.narrate_project({"challenge": "storm", "work": "fix", "outcome": "ok"}, client={})
        assert out == {"challenge": "A storm.", "work": "We fixed it.", "outcome": "No leaks."}

    async def test_non_dict_tool_output_degrades_to_none(self, monkeypatch):
        monkeypatch.setattr(wp.report_llm, "run_forced_tool", AsyncMock(return_value="oops"))
        out = await wp.narrate_project({"work": "did a thing"}, client={})
        assert out is None
