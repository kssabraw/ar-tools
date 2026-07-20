"""Unit tests for the pure blog-image generation core (services/image_generation).

Covers word counting, the body-image budget, plan parsing/coercion, prompt
authoring, repo-path + site-URL building, and markdown injection. No network:
the OpenAI render + LLM plan calls are never exercised here.
"""
from services import image_generation as ig
from services.image_generation import ImageSlot, Section


def _sections():
    return [
        Section(heading="Intro", body="Alpha beta gamma delta."),
        Section(heading="Costs and pricing", body="Plan A is $100 per month, Plan B is $250 per month."),
        Section(heading="Conclusion", body="Wrap up the discussion here."),
    ]


# ── word count + budget ──────────────────────────────────────────────────────


def test_count_words_counts_headings_and_body():
    secs = [Section(heading="Two words", body="three more words here")]  # 2 + 4 = 6
    assert ig.count_words(secs) == 6


def test_target_body_image_count_rounds_and_clamps():
    # 1500 words × 2/1000 = 3.0
    assert ig.target_body_image_count(1500, per_1000=2.0, minimum=0, maximum=6) == 3
    # 1200 × 2/1000 = 2.4 → 2
    assert ig.target_body_image_count(1200, per_1000=2.0, minimum=0, maximum=6) == 2
    # 1250 × 2/1000 = 2.5 → round-half-up → 3
    assert ig.target_body_image_count(1250, per_1000=2.0, minimum=0, maximum=6) == 3
    # clamp to max
    assert ig.target_body_image_count(9000, per_1000=2.0, minimum=0, maximum=6) == 6
    # clamp to min
    assert ig.target_body_image_count(50, per_1000=2.0, minimum=1, maximum=6) == 1


# ── repo paths + site URLs ───────────────────────────────────────────────────


def test_site_url_strips_public_prefix():
    assert ig.site_url_for_repo_path("public/images/blog/x/hero.png") == "/images/blog/x/hero.png"
    assert ig.site_url_for_repo_path("assets/blog/x/hero.png") == "/assets/blog/x/hero.png"
    assert ig.site_url_for_repo_path("/public/images/y/body-1.png") == "/images/y/body-1.png"


def test_build_slot_paths_hero_and_body():
    repo, site = ig.build_slot_paths("public/images/blog", "my-post", "hero", 0, "illustration")
    assert repo == "public/images/blog/my-post/hero.png"
    assert site == "/images/blog/my-post/hero.png"
    repo, site = ig.build_slot_paths("public/images/blog", "my-post", "body", 2, "chart")
    assert repo == "public/images/blog/my-post/chart-2.png"
    assert site == "/images/blog/my-post/chart-2.png"


def test_image_filename_by_role_and_kind():
    assert ig.image_filename("hero", 0, "illustration") == "hero.png"
    assert ig.image_filename("body", 1, "illustration") == "body-1.png"
    assert ig.image_filename("body", 3, "chart") == "chart-3.png"


# ── plan parsing / coercion ──────────────────────────────────────────────────


def test_parse_plan_happy_path():
    raw = {
        "hero": {"prompt": "A rooftop at dawn", "alt": "Rooftop"},
        "body": [
            {"after_section_index": 1, "kind": "chart", "prompt": "Bar chart: Plan A $100, Plan B $250", "alt": "Pricing"},
            {"after_section_index": 2, "kind": "illustration", "prompt": "A tidy checklist", "alt": "Checklist"},
        ],
    }
    slots = ig.parse_plan(
        raw, sections=_sections(), slug="post", n_body=2,
        style_suffix="STYLE", hero_size="1536x1024", body_size="1024x1024",
        base_path="public/images/blog",
    )
    assert len(slots) == 3
    hero = slots[0]
    assert hero.role == "hero" and hero.after_index == -1 and hero.size == "1536x1024"
    assert hero.repo_path == "public/images/blog/post/hero.png"
    assert "STYLE" in hero.prompt
    chart = slots[1]
    assert chart.role == "body" and chart.kind == "chart" and chart.after_index == 1
    assert chart.repo_path == "public/images/blog/post/chart-1.png"
    assert chart.anchor_heading == "Costs and pricing"
    # chart slots get the chart suffix, not the illustration style suffix
    assert "STYLE" not in chart.prompt


def test_parse_plan_clamps_index_and_caps_count():
    raw = {
        "hero": {"prompt": "H", "alt": "h"},
        "body": [
            {"after_section_index": 99, "kind": "illustration", "prompt": "one", "alt": "a"},
            {"after_section_index": -5, "kind": "illustration", "prompt": "two", "alt": "b"},
            {"after_section_index": 0, "kind": "illustration", "prompt": "three (dropped)", "alt": "c"},
        ],
    }
    slots = ig.parse_plan(
        raw, sections=_sections(), slug="p", n_body=2,
        style_suffix="S", hero_size="1536x1024", body_size="1024x1024",
        base_path="public/images/blog",
    )
    body = [s for s in slots if s.role == "body"]
    assert len(body) == 2  # capped at n_body
    assert body[0].after_index == 2  # 99 clamped to last section index
    assert body[1].after_index == 0  # -5 clamped to 0


def test_parse_plan_always_yields_a_hero_even_when_missing():
    slots = ig.parse_plan(
        {}, sections=_sections(), slug="p", n_body=0,
        style_suffix="S", hero_size="1536x1024", body_size="1024x1024",
        base_path="public/images/blog",
    )
    assert len(slots) == 1 and slots[0].role == "hero"


def test_parse_plan_skips_blank_body_prompts():
    raw = {"hero": {"prompt": "H", "alt": "h"}, "body": [{"after_section_index": 0, "kind": "illustration", "prompt": "  ", "alt": "x"}]}
    slots = ig.parse_plan(
        raw, sections=_sections(), slug="p", n_body=3,
        style_suffix="S", hero_size="1536x1024", body_size="1024x1024",
        base_path="public/images/blog",
    )
    assert [s.role for s in slots] == ["hero"]


def test_finalize_prompt_appends_suffix_once():
    assert ig.finalize_prompt("draw a cat", "STYLE").endswith("STYLE")
    once = ig.finalize_prompt("draw a cat\n\nSTYLE", "STYLE")
    assert once.count("STYLE") == 1


def test_safe_size_falls_back():
    assert ig._safe_size("1536x1024") == "1536x1024"
    assert ig._safe_size("999x999") == "1024x1024"


# ── markdown injection ───────────────────────────────────────────────────────


def _body_slot(after_index, position, url, alt="alt"):
    return ImageSlot(
        role="body", kind="illustration", position=position, after_index=after_index,
        alt=alt, prompt="p", size="1024x1024", repo_path="x", site_url=url,
    )


def test_render_markdown_injects_after_correct_section():
    secs = _sections()
    slots = [_body_slot(1, 1, "/images/blog/p/body-1.png", alt="Pricing chart")]
    md = ig.render_markdown_with_images(secs, slots)
    assert "## Costs and pricing" in md
    # image appears after the costs section body and before the Conclusion heading
    costs_idx = md.index("Plan A is $100")
    img_idx = md.index("![Pricing chart](/images/blog/p/body-1.png)")
    concl_idx = md.index("## Conclusion")
    assert costs_idx < img_idx < concl_idx


def test_render_markdown_no_images_is_plain():
    md = ig.render_markdown_with_images(_sections(), [])
    assert "![" not in md
    assert md.startswith("## Intro")


def test_render_markdown_orders_same_section_by_position():
    secs = _sections()
    slots = [
        _body_slot(0, 2, "/b2.png", alt="second"),
        _body_slot(0, 1, "/b1.png", alt="first"),
    ]
    md = ig.render_markdown_with_images(secs, slots)
    assert md.index("/b1.png") < md.index("/b2.png")


def test_render_markdown_sanitizes_alt_brackets():
    slots = [_body_slot(0, 1, "/b.png", alt="a [weird] alt")]
    md = ig.render_markdown_with_images(_sections(), slots)
    assert "![a weird alt](/b.png)" in md


def test_assemble_sections_orders_by_order_field():
    article = [
        {"heading": "Second", "body": "b", "order": 2},
        {"heading": "First", "body": "a", "order": 1},
    ]
    secs = ig.assemble_sections(article)
    assert [s.heading for s in secs] == ["First", "Second"]
