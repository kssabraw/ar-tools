"""Unit tests for the strategist -> content-plan seed bridge.

The bridge is a one-shot copy: it turns the client's latest topic-strategist
plan into the site-owned `content_plan` that `website_plan.content_plan_pillars`
then parses. The two things worth pinning are that the copy is faithful (each
strategist cluster becomes one post, keeping its brief) and that the inferred
`format` matches the reference's planner triggers.
"""

from __future__ import annotations

from services import website_content_plan as wcp
from services import website_plan as wp


class TestInferFormat:
    def test_vs_titles_are_comparisons(self):
        assert wcp.infer_format("Tile vs shingle roofs") == "comparison"
        assert wcp.infer_format("Metal versus asphalt") == "comparison"

    def test_enumerated_titles_are_listicles(self):
        assert wcp.infer_format("5 best roof coatings") == "listicle"
        assert wcp.infer_format("Types of roof damage") == "listicle"
        assert wcp.infer_format("Ways to extend a roof's life") == "listicle"

    def test_everything_else_is_the_default_evergreen_cluster_post(self):
        assert wcp.infer_format("How roof inspections work") == wp.DEFAULT_POST_FORMAT

    def test_news_and_local_geo_are_never_inferred(self):
        # Both need a plan-time decision the title cannot carry: news is
        # non-evergreen, local-geo is a geo-site format.
        assert wcp.infer_format("Roofing news this week") not in {"news", "local_geo"}


class TestPlanToContentPlan:
    STRATEGIST = {
        "assessment": "Own the roof-maintenance topic.",
        "pillars": [
            {
                "pillar": "Roof Maintenance",
                "rationale": "core topic",
                "clusters": [
                    {
                        "title": "How often to inspect a roof",
                        "buyer_problem": "owners don't know cadence",
                        "search_intent": "informational",
                        "funnel_stage": "TOFU",
                        "target_keywords": ["roof inspection frequency", "inspect roof"],
                        "questions": ["How often?"],
                    },
                    {"title": "5 signs of roof damage", "target_keywords": ["signs of roof damage"]},
                ],
            }
        ],
    }

    def test_maps_pillars_and_clusters_to_posts(self):
        cp = wcp.plan_to_content_plan(self.STRATEGIST)
        assert len(cp["pillars"]) == 1
        pillar = cp["pillars"][0]
        assert pillar["title"] == "Roof Maintenance"
        assert pillar["slug"] == "roof-maintenance"
        assert [p["title"] for p in pillar["posts"]] == [
            "How often to inspect a roof",
            "5 signs of roof damage",
        ]

    def test_first_target_keyword_becomes_the_post_keyword(self):
        cp = wcp.plan_to_content_plan(self.STRATEGIST)
        first = cp["pillars"][0]["posts"][0]
        assert first["keyword"] == "roof inspection frequency"
        assert first["buyer_problem"] == "owners don't know cadence"
        assert first["funnel_stage"] == "TOFU"

    def test_format_is_inferred_per_post(self):
        cp = wcp.plan_to_content_plan(self.STRATEGIST)
        posts = cp["pillars"][0]["posts"]
        assert posts[0]["format"] == wp.DEFAULT_POST_FORMAT
        assert posts[1]["format"] == "listicle"

    def test_the_output_is_what_the_planner_parses(self):
        # The seed and the planner must agree on the shape; feed the mapper's
        # output straight into the planner and expect a full plan.
        cp = wcp.plan_to_content_plan(self.STRATEGIST)
        pillars = wp.content_plan_pillars(cp)
        assert len(pillars) == 1
        assert len(pillars[0].posts) == 2

    def test_empty_and_blank_entries_are_dropped_not_raised(self):
        plan = {"pillars": [
            {"pillar": "", "clusters": [{"title": "x"}]},
            {"pillar": "Real", "clusters": [{"title": ""}, {"title": "Kept"}]},
            {"pillar": "Emptyless", "clusters": []},
        ]}
        cp = wcp.plan_to_content_plan(plan)
        assert [p["title"] for p in cp["pillars"]] == ["Real"]
        assert [p["title"] for p in cp["pillars"][0]["posts"]] == ["Kept"]

    def test_a_plan_with_no_usable_pillars_is_empty(self):
        assert wcp.plan_to_content_plan({"pillars": []}) == {"pillars": []}
        assert wcp.plan_to_content_plan(None) == {"pillars": []}


class TestPlanSummary:
    def test_counts_pillars_posts_and_hubs(self):
        cp = {"pillars": [
            {"title": "Big", "slug": "big", "posts": [
                {"title": f"P{i}", "format": "informational_cluster"} for i in range(5)
            ]},
            {"title": "Small", "slug": "small", "posts": [
                {"title": "Only", "format": "informational_cluster"}
            ]},
        ]}
        summary = wcp.plan_summary(cp)
        assert summary == {"pillars": 2, "posts": 6, "hubs": 1}
