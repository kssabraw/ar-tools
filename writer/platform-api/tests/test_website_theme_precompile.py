"""Unit tests for the theme compiler's deterministic pass.

Most run against the **real Claude Design export** in
`docs/reference/claude-design-export/`, because the format is a small custom DSL
with no spec other than that file and a generated runtime. A hand-written
fixture would test my reading of the format rather than the format.

The numbers asserted below (accent colour 21×, six screens, the
`{cat,title,read,photo}` contract) are the ones the export's own README
independently records — which is what makes them a check rather than a
restatement of whatever the code happened to produce.
"""

from __future__ import annotations

import pathlib

import pytest

from services import website_theme_precompile as pc

FIXTURES = pathlib.Path(__file__).resolve().parents[3] / "docs" / "reference" / "claude-design-export"


@pytest.fixture(scope="module")
def design() -> str:
    return (FIXTURES / "healthnotes.dc.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def canvas() -> str:
    return (FIXTURES / "Health Site Directions.dc.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def result(design: str) -> pc.Precompiled:
    return pc.precompile(design)


class TestCanvasDetection:
    def test_the_canvas_doc_is_recognised(self, canvas):
        # It holds several design *options* per turn. Compiling it would build a
        # theme out of a mood board.
        assert pc.is_canvas_doc(canvas) is True
        assert pc.looks_like_design(canvas) is False

    def test_the_design_is_not_mistaken_for_one(self, design):
        assert pc.is_canvas_doc(design) is False
        assert pc.looks_like_design(design) is True

    def test_a_zip_with_one_design_and_one_canvas_needs_no_question(self, design, canvas):
        chosen, designs, canvases = pc.pick_design({"a.dc.html": design, "b.dc.html": canvas})
        assert chosen == "a.dc.html"
        assert designs == ["a.dc.html"]
        assert canvases == ["b.dc.html"]

    def test_two_designs_refuse_to_choose(self, design):
        # Picking one silently produces a theme nobody designed.
        chosen, designs, _ = pc.pick_design({"a.dc.html": design, "b.dc.html": design})
        assert chosen is None
        assert designs == ["a.dc.html", "b.dc.html"]

    def test_a_canvas_only_zip_yields_no_design(self, canvas):
        chosen, designs, canvases = pc.pick_design({"only.dc.html": canvas})
        assert chosen is None and designs == [] and canvases == ["only.dc.html"]

    def test_compiling_a_canvas_doc_fails_loudly(self, canvas):
        with pytest.raises(pc.PrecompileError, match="design_doc_is_canvas"):
            pc.precompile(canvas)


class TestScreens:
    def test_one_file_yields_the_whole_page_set(self, result):
        # The property the compiler design rests on: six sc-if branches are six
        # pages, not "first page = layout, rest = section sources".
        assert result.screen_keys == ["home", "topics", "article", "about", "privacy", "contact"]

    def test_every_screen_has_markup(self, result):
        assert all(not s.is_empty for s in result.screens)

    def test_chrome_is_what_sits_outside_every_branch(self, result):
        # The header and footer each screen shares — this is what becomes the
        # layout rather than being duplicated into six templates.
        assert "<header" in result.chrome_html
        assert "<sc-if" not in result.chrome_html

    def test_flag_names_become_page_keys(self):
        assert pc.screen_key("isHome") == "home"
        assert pc.screen_key("isBlogPost") == "blog_post"
        assert pc.screen_key("weird") == "weird"

    def test_nested_branches_close_on_the_right_tag(self):
        # A non-greedy regex would close the outer branch on the inner one's tag
        # and silently truncate a page.
        html = (
            '<x-dc><sc-if value="{{ isHome }}">outer'
            '<sc-if value="{{ isInner }}">inner</sc-if>tail</sc-if></x-dc>'
        )
        screens, _ = pc.split_screens(html)
        assert screens[0].key == "home"
        assert "inner" in screens[0].html and screens[0].html.rstrip().endswith("tail")

    def test_an_unclosed_branch_is_an_error_not_a_guess(self):
        with pytest.raises(pc.PrecompileError, match="unclosed_sc-if"):
            pc.split_screens('<sc-if value="{{ isHome }}">never closed')

    def test_a_file_with_no_screens_fails(self):
        with pytest.raises(pc.PrecompileError, match="no_screens_found"):
            pc.precompile("<x-dc><div>nothing routed</div></x-dc>")

    def test_an_empty_file_fails(self):
        with pytest.raises(pc.PrecompileError, match="empty_design_file"):
            pc.precompile("   ")


class TestCollections:
    def test_the_sample_arrays_are_read_as_a_schema(self, result):
        # `{cat, title, read, photo}` is the design stating which frontmatter it
        # renders. The shape is the contract; the rows are thrown away.
        names = {c.name: c for c in result.collections}
        assert set(names) == {"latest", "catList", "related"}
        assert names["latest"].fields == ("cat", "title", "read", "photo")
        assert names["latest"].alias == "a"

    def test_the_preview_count_is_kept_as_a_hint_only(self, result):
        names = {c.name: c for c in result.collections}
        assert names["latest"].hint_count == 3
        assert names["catList"].hint_count == 6

    def test_no_sample_row_content_survives(self, result):
        # The rows are placeholder copy about intermittent fasting; a theme that
        # shipped them would ship somebody else's article titles.
        blob = repr(result.collections)
        assert "intermittent fasting" not in blob
        assert "Nutrition" not in blob

    def test_handlers_are_not_content_fields(self):
        # `open` is prototype navigation riding along in the sample row.
        script = 'const rows = [ { title:"x", open } ];'
        [collection] = pc.parse_collections(
            '<sc-for list="{{ rows }}" as="r">{{ r.title }}</sc-for>', script,
        )
        assert collection.fields == ("title",)

    def test_template_only_fields_are_still_captured(self):
        # A field the array omits but the template renders is still real.
        script = 'const rows = [ { title:"x" } ];'
        [collection] = pc.parse_collections(
            '<sc-for list="{{ rows }}" as="r">{{ r.title }}{{ r.subtitle }}</sc-for>', script,
        )
        assert collection.fields == ("title", "subtitle")


class TestImagery:
    def test_the_hero_placeholders_are_found_per_screen(self, result):
        heroes = [s for s in result.image_slots if s.is_hero]
        assert {s.screen for s in heroes} == {"home", "article"}

    def test_card_labels_come_from_the_sample_arrays(self, result):
        # They live in the script, not the markup — a screen-only scan finds the
        # heroes and misses every thumbnail.
        cards = [s for s in result.image_slots if s.collection]
        assert {s.collection for s in cards} == {"latest"}
        assert any("dumbbells" in s.label for s in cards)

    def test_all_five_placeholders_are_captured(self, result):
        # The count the export's README independently records.
        assert len(result.image_slots) == 5

    def test_html_entities_are_decoded(self, result):
        assert any("clock & plate" in s.label for s in result.image_slots)

    def test_the_prompt_seed_drops_the_framing_words(self):
        assert pc.ImageSlot("hero photo: plated balanced meal").prompt_seed == "plated balanced meal"
        assert pc.ImageSlot("photo: dumbbells").prompt_seed == "dumbbells"

    def test_non_image_bracketed_text_is_not_an_image(self):
        slots = pc.harvest_image_slots([pc.Screen("home", "isHome", "[ 3 ] and [ note: a caveat ]")])
        assert slots == []


class TestTokenCensus:
    def test_the_accent_is_the_most_used_colour(self, result):
        # 21 occurrences, the figure the README records — this is the value that
        # deserves to become a token.
        top = dict(result.tokens.colors)
        assert top["oklch(0.5 0.1 180)"] == 21
        assert top["#e3e9e6"] == 18

    def test_colours_are_matched_in_shorthand_properties(self):
        # `border-bottom:1px solid #e3e9e6` has no colour *property* to key on.
        census = pc.census_styles('<div style="border-bottom:1px solid #abcdef"></div>')
        assert census.colors == [("#abcdef", 1)]

    def test_the_global_stylesheet_contributes(self):
        # The body and link colours appear once each in the helmet's <style>; an
        # inline-only census would rank the two most load-bearing values last.
        census = pc.census_styles("", global_css="body{color:#17211e}a{color:#ff0000}")
        assert dict(census.colors) == {"#17211e": 1, "#ff0000": 1}

    def test_one_colour_counts_once_however_it_is_written(self):
        census = pc.census_styles('<div style="color:#ABCDEF"></div><p style="color:#abcdef"></p>')
        assert census.colors == [("#abcdef", 2)]

    def test_type_and_shape_are_censused(self, result):
        assert result.tokens.font_families[0][0].startswith("'Space Grotesk'")
        assert dict(result.tokens.font_sizes)["13px"] == 21
        assert dict(result.tokens.radii)["999px"] == 13

    def test_zero_spacing_is_not_a_spacing_token(self):
        census = pc.census_styles('<div style="padding:0;gap:12px"></div>')
        assert census.spacing == [("12px", 1)]

    def test_an_unstyled_document_yields_an_empty_census(self):
        assert pc.census_styles("<div>plain</div>").is_empty


class TestFontsAndRoutes:
    def test_google_font_families_are_extracted_for_self_hosting(self, result):
        # Captured here so the theme can self-host them; the <link> itself is
        # dropped, because the compiled theme must make no external request.
        assert result.fonts == ["Space Grotesk", "Libre Franklin"]

    def test_prototype_handlers_become_routes(self, result):
        assert result.routes["goHome"] == "/"
        assert result.routes["goTopics"] == "/topics/"
        assert result.routes["goContact"] == "/contact/"

    def test_the_global_css_is_lifted(self, result):
        assert "box-sizing" in result.global_css


class TestResidue:
    def test_the_raw_export_is_full_of_dsl(self, result):
        # The pre-pass measures; it does not clean. This is the "before".
        assert "sc-for" in pc.residue(result.screens[0].html)

    def test_stripping_removes_the_scaffolding(self, result):
        cleaned = pc.strip_prototype_markup(result.screens[0].html)
        assert "onClick=" not in cleaned
        assert "hint-placeholder-" not in cleaned

    def test_clean_output_reports_nothing(self):
        # The compiler's post-check: an sc-if or a {{ }} surviving into a theme
        # is prototype scaffolding rendered to a real visitor.
        assert pc.residue('<div class="hero"><h1>Real markup</h1></div>') == []

    @pytest.mark.parametrize(
        "markup,expected",
        [
            ('<sc-if value="{{ x }}">', "sc-if"),
            ("<sc-for list=\"{{ y }}\" as=\"z\">", "sc-for"),
            ("<p>{{ title }}</p>", "interpolation"),
            ('<div style-hover="color:red">', "style-hover"),
        ],
    )
    def test_each_kind_of_residue_is_named(self, markup, expected):
        assert expected in pc.residue(markup)


class TestLayoutSelection:
    """The layout manifest — which house-component variant each screen renders.

    Deterministic like the token pass: the hero image's side is read from the
    screen's own DOM order, and only ever moved between the sides the template
    implements — never to a value that could break a build.
    """

    def test_hero_after_heading_is_right(self):
        html = '<section><h1>We fix roofs</h1><div>[hero photo: a roof]</div></section>'
        assert pc.hero_image_position(html) == "right"

    def test_hero_before_heading_is_left(self):
        html = '<section><div>[hero photo: a roof]</div><h1>We fix roofs</h1></section>'
        assert pc.hero_image_position(html) == "left"

    def test_no_hero_image_is_none(self):
        # A text-only screen: the compiler omits it so the resolver's default
        # (show a generated hero on the right) applies — the compiler moves an
        # image, it never suppresses one.
        html = '<section><h1>About us</h1><p>Prose only.</p></section>'
        assert pc.hero_image_position(html) is None

    def test_non_hero_thumbnail_does_not_count_as_a_hero(self):
        # A card thumbnail is not a banner; only a hero-labelled slot decides the
        # hero layout.
        html = '<section><div>[photo: a small card thumbnail]</div><h1>Topics</h1></section>'
        assert pc.hero_image_position(html) is None

    def test_hero_with_no_heading_defaults_to_right(self):
        html = '<section><div>[hero photo: a roof]</div></section>'
        assert pc.hero_image_position(html) == "right"

    def test_clamp_rejects_anything_off_the_whitelist(self):
        assert pc._clamp_hero_image("sideways") is None
        assert pc._clamp_hero_image(None) is None
        for good in pc.HERO_IMAGE_POSITIONS:
            assert pc._clamp_hero_image(good) == good

    def test_manifest_over_the_real_export(self, result):
        # The reference export's home and article carry hero photos that sit
        # after their headings; the other four screens carry none.
        manifest = pc.build_layout_manifest(result)
        assert manifest["version"] == pc.LAYOUT_MANIFEST_VERSION
        assert set(manifest["screens"]) == {"home", "article"}
        assert manifest["screens"]["home"]["hero"]["image"] == "right"
        assert manifest["screens"]["article"]["hero"]["image"] == "right"

    def test_manifest_only_names_implemented_variants(self, result):
        # Every value the compiler emits must be one the template can render, or
        # the site ships a layout that does not exist.
        manifest = pc.build_layout_manifest(result)
        for sel in manifest["screens"].values():
            assert sel["hero"]["image"] in pc.HERO_IMAGE_POSITIONS


class TestCardGridDensity:
    """Card-grid column density — a theme-wide trait read from the design's own
    declared `grid-template-columns`. Only symmetric grids count; an asymmetric
    value is a content split, not a card row."""

    def test_symmetric_grid_gives_its_track_count(self):
        assert pc._grid_column_count("1fr 1fr 1fr") == 3
        assert pc._grid_column_count("1fr 1fr") == 2

    def test_repeat_form_is_read(self):
        assert pc._grid_column_count("repeat(4, 1fr)") == 4

    def test_asymmetric_split_is_not_a_card_grid(self):
        # A media/content split, not a row of equal cards.
        assert pc._grid_column_count("1.35fr 1fr") is None
        assert pc._grid_column_count("2fr 1fr") is None

    def test_out_of_range_track_counts_are_ignored(self):
        assert pc._grid_column_count("1fr") is None
        assert pc._grid_column_count("1fr 1fr 1fr 1fr 1fr") is None
        assert pc._grid_column_count("repeat(8, 1fr)") is None

    def test_dominant_count_wins(self):
        pre = pc.Precompiled(
            screens=[
                pc.Screen(key="a", flag="isA", html='<div style="grid-template-columns:1fr 1fr 1fr"></div>'),
                pc.Screen(key="b", flag="isB", html='<div style="grid-template-columns:1fr 1fr 1fr"></div>'),
                pc.Screen(key="c", flag="isC", html='<div style="grid-template-columns:1fr 1fr"></div>'),
            ]
        )
        assert pc.card_grid_columns(pre) == 3

    def test_no_grid_declares_nothing(self):
        pre = pc.Precompiled(screens=[pc.Screen(key="a", flag="isA", html="<div>no grid here</div>")])
        assert pc.card_grid_columns(pre) is None

    def test_clamp_rejects_off_whitelist(self):
        assert pc._clamp_columns(7) is None
        assert pc._clamp_columns(None) is None
        for good in pc.CARD_COLUMN_CHOICES:
            assert pc._clamp_columns(good) == good

    def test_manifest_carries_card_columns_over_the_real_export(self, result):
        # The reference export's card grids are predominantly three-up.
        manifest = pc.build_layout_manifest(result)
        assert manifest["components"]["cardColumns"] == 3

    def test_manifest_omits_components_when_undeclared(self):
        pre = pc.Precompiled(screens=[pc.Screen(key="home", flag="isHome", html="<div>prose</div>")])
        manifest = pc.build_layout_manifest(pre)
        # No card grid measured → no components block → the grids keep their own min.
        assert "components" not in manifest
