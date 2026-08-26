"""Unit tests for the theme compile.

The load-bearing test here is that the model cannot invent a colour. Everything
else about the compile degrades gracefully; a hallucinated brand colour would
ship as a client's identity, so `validate_roles` is the one place a wrong answer
must become a failure rather than a theme.
"""

from __future__ import annotations

import io
import pathlib
import zipfile

import pytest

from services import website_theme as wt
from services import website_theme_precompile as pc

FIXTURES = pathlib.Path(__file__).resolve().parents[3] / "docs" / "reference" / "claude-design-export"

# The assignment a correct model call produces for the reference export — every
# value copied from the census.
GOOD = {
    "colors": {
        "accent": "oklch(0.5 0.1 180)",
        "accent_hover": "oklch(0.42 0.1 180)",
        "bg": "#fbfcfb",
        "surface": "#fff",
        "surface_muted": "#f2f5f3",
        "text": "#17211e",
        "text_muted": "#54635d",
        "text_subtle": "#7b8a84",
        "border": "#e3e9e6",
        "border_strong": "#dbe3df",
    },
    "font_display": "'Space Grotesk',sans-serif",
    "font_body": "'Libre Franklin',sans-serif",
    "notes": "Editorial, cool-teal accent on near-white.",
}


@pytest.fixture(scope="module")
def design() -> str:
    return (FIXTURES / "healthnotes.dc.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pre(design: str) -> pc.Precompiled:
    return pc.precompile(design)


class TestUploadIngest:
    def test_a_bare_html_file_is_accepted(self, design):
        files = wt.read_upload(design.encode("utf-8"))
        assert list(files) == ["design.dc.html"]

    def test_a_zip_yields_its_html_members(self, design):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("healthnotes.dc.html", design)
            archive.writestr("support.js", "// the runtime we compile away from")
            archive.writestr(".thumbnail", b"\x00webp")
        files = wt.read_upload(buf.getvalue())
        # The runtime and the thumbnail are not designs; shipping the runtime
        # would defeat the point of compiling.
        assert list(files) == ["healthnotes.dc.html"]

    def test_macos_resource_forks_are_skipped(self, design):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("__MACOSX/._x.dc.html", "junk")
            archive.writestr("real.dc.html", design)
        assert list(wt.read_upload(buf.getvalue())) == ["real.dc.html"]

    def test_an_empty_upload_fails_clearly(self):
        with pytest.raises(wt.ThemeError, match="empty_upload"):
            wt.read_upload(b"")

    def test_a_zip_with_no_html_fails_clearly(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("notes.txt", "nothing here")
        with pytest.raises(wt.ThemeError, match="no_html_in_upload"):
            wt.read_upload(buf.getvalue())

    def test_a_corrupt_zip_fails_clearly(self):
        with pytest.raises(wt.ThemeError, match="bad_zip"):
            wt.read_upload(b"PK\x03\x04 not really a zip")


class TestValidation:
    """The model may name; it may not invent."""

    def test_a_correct_assignment_validates(self, pre):
        tokens = wt.validate_roles(GOOD, pre)
        assert tokens.colors["accent"] == "oklch(0.5 0.1 180)"
        assert tokens.font_body == "'Libre Franklin',sans-serif"

    def test_a_colour_the_design_never_had_is_refused(self, pre):
        # The whole point. A plausible-looking teal that was never measured
        # would otherwise ship as the client's brand colour.
        bad = {**GOOD, "colors": {**GOOD["colors"], "accent": "#00a3a3"}}
        with pytest.raises(wt.ThemeError, match="token_not_measured:accent"):
            wt.validate_roles(bad, pre)

    def test_a_nudged_colour_is_refused(self, pre):
        # "Close enough" is exactly the failure mode — one digit off is a
        # different brand colour.
        bad = {**GOOD, "colors": {**GOOD["colors"], "border": "#e3e9e7"}}
        with pytest.raises(wt.ThemeError, match="token_not_measured:border"):
            wt.validate_roles(bad, pre)

    def test_case_and_spacing_differences_are_tolerated(self, pre):
        # The census normalises, so the same colour written differently is the
        # same colour — this must not fail.
        ok = {**GOOD, "colors": {**GOOD["colors"], "text": "#17211E"}}
        assert wt.validate_roles(ok, pre).colors["text"] == "#17211e"

    def test_a_missing_role_is_an_error_not_a_default(self, pre):
        # Silently defaulting one produces a theme that is *partly* the design,
        # which is harder to notice than one that is plainly wrong.
        bad = {**GOOD, "colors": {k: v for k, v in GOOD["colors"].items() if k != "surface"}}
        with pytest.raises(wt.ThemeError, match="token_role_missing:surface"):
            wt.validate_roles(bad, pre)

    def test_an_unmeasured_font_is_refused(self, pre):
        bad = {**GOOD, "font_body": "'Helvetica Neue',sans-serif"}
        with pytest.raises(wt.ThemeError, match="token_not_measured:font_body"):
            wt.validate_roles(bad, pre)

    def test_a_design_with_no_measurable_font_fails_rather_than_letting_one_through(self):
        # Fonts used to be checked only `if families` — so the single case where
        # the model has nothing to copy from was the one case it could invent
        # freely. Colours never had that escape; now neither do fonts.
        bare = pc.Precompiled(tokens=pc.TokenCensus(colors=[("#000", 1)]))
        assigned = {**GOOD, "colors": {r: "#000" for r in wt.COLOR_ROLES}}
        with pytest.raises(wt.ThemeError, match="no_fonts_measured"):
            wt.validate_roles(assigned, bare)

    def test_an_empty_response_fails_rather_than_producing_a_blank_theme(self, pre):
        with pytest.raises(wt.ThemeError, match="token_role_missing"):
            wt.validate_roles({}, pre)


class TestCensusPrompt:
    def test_the_model_sees_measurements_not_markup(self, pre):
        prompt = wt.build_census_prompt(pre)
        assert "oklch(0.5 0.1 180) — 21" in prompt
        # Handing it the design's HTML would invite redesigning rather than
        # naming.
        assert "<div" not in prompt and "sc-if" not in prompt

    def test_the_global_stylesheet_is_shown_as_evidence(self, pre):
        # body{} and a{} are where a design states its background, ink and link
        # colours outright.
        assert "GLOBAL STYLESHEET" in wt.build_census_prompt(pre)

    def test_every_role_is_described(self, pre):
        prompt = wt.build_census_prompt(pre)
        for role in wt.COLOR_ROLES:
            assert role in prompt


class TestRenderedCss:
    def test_every_emitted_colour_was_measured(self, pre):
        # The guarantee restated at the output: nothing in the file is a value
        # the design did not contain.
        css = wt.render_tokens_css(wt.validate_roles(GOOD, pre), pre)
        measured = {v for v, _ in pre.tokens.colors}
        for line in css.splitlines():
            if line.strip().startswith("--color-") and "color-mix" not in line:
                value = line.split(":", 1)[1].strip().rstrip(";")
                assert value in measured, value

    def test_the_pill_radius_does_not_hijack_the_scale(self, pre):
        # 999px is the most common radius in the reference design. Letting it
        # into the scale makes every large-radius card a lozenge.
        css = wt.render_tokens_css(wt.validate_roles(GOOD, pre), pre)
        assert "--radius-lg: 999px;" not in css
        assert "--radius-pill: 999px;" in css

    def test_the_type_scale_comes_from_the_design(self, pre):
        css = wt.render_tokens_css(wt.validate_roles(GOOD, pre), pre)
        measured = {v for v, _ in pre.tokens.font_sizes}
        for line in css.splitlines():
            if line.strip().startswith("--text-"):
                assert line.split(":", 1)[1].strip().rstrip(";") in measured

    def test_a_design_with_too_few_steps_falls_back_to_the_house_scale(self):
        thin = pc.Precompiled(tokens=pc.TokenCensus(font_sizes=[("14px", 3)]))
        tokens = wt.ThemeTokens(colors={r: "#000" for r in wt.COLOR_ROLES}, font_display="a", font_body="b")
        css = wt.render_tokens_css(tokens, thin)
        # Inventing six steps around one measured size would be fabrication.
        assert "--text-base: 1rem;" in css

    def test_the_file_warns_against_hand_editing(self, pre):
        # The next compile overwrites it, so an edit here is silently lost.
        css = wt.render_tokens_css(wt.validate_roles(GOOD, pre), pre)
        assert "do not hand-edit" in css


class TestThemeRecord:
    def test_the_measurements_are_kept_for_the_later_phase(self, pre):
        # Re-measuring later would mean re-uploading a design the user has moved
        # on from.
        record = wt.theme_record(pre, wt.validate_roles(GOOD, pre))
        assert record["screens"] == ["home", "topics", "article", "about", "privacy", "contact"]
        assert {c["name"] for c in record["collections"]} == {"latest", "catList", "related"}

    def test_image_slots_carry_their_prompt_seeds(self, pre):
        record = wt.theme_record(pre, wt.validate_roles(GOOD, pre))
        seeds = {s["promptSeed"] for s in record["imageSlots"]}
        assert "plated balanced meal" in seeds
        assert "dumbbells" in seeds

    def test_no_sample_copy_is_stored(self, pre):
        record = wt.theme_record(pre, wt.validate_roles(GOOD, pre))
        assert "intermittent fasting" not in str(record)


class TestCompileErrors:
    """Every one of these fails before the LLM call, so no test here spends money."""

    @pytest.mark.asyncio
    async def test_a_canvas_only_upload_says_so(self):
        canvas = (FIXTURES / "Health Site Directions.dc.html").read_text(encoding="utf-8")
        with pytest.raises(wt.ThemeError, match="upload_is_canvas_only"):
            await wt.compile_design(canvas.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_two_designs_ask_rather_than_guess(self, design):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("a.dc.html", design)
            archive.writestr("b.dc.html", design)
        with pytest.raises(wt.ThemeError, match="multiple_designs:a.dc.html,b.dc.html"):
            await wt.compile_design(buf.getvalue())

    @pytest.mark.asyncio
    async def test_an_upload_with_no_design_says_so(self):
        with pytest.raises(wt.ThemeError, match="no_design_in_upload"):
            await wt.compile_design(b"<html><body>just a web page</body></html>")


class TestCompileWiring:
    """The compile end to end, with the two external calls stubbed."""

    @pytest.mark.asyncio
    async def test_the_compile_emits_tokens_and_the_fonts_it_hosted(self, monkeypatch, design):
        async def fake_assign(pre):
            return wt.validate_roles(GOOD, pre)

        async def fake_fonts(families, weights, **kwargs):
            # The families come from the design's own <link>, not from a guess.
            assert list(families) == ["Space Grotesk", "Libre Franklin"]
            return "@font-face{font-family:'Space Grotesk';}", {
                "fonts/space-grotesk-400-latin.woff2": b"woff2"
            }

        monkeypatch.setattr(wt, "assign_roles", fake_assign)
        monkeypatch.setattr(wt.fonts, "fetch_font_bundle", fake_fonts)

        files, record, _pre = await wt.compile_design(design.encode("utf-8"))
        # layouts.json is always emitted alongside tokens.css (the layout manifest).
        assert set(files) == {"tokens.css", "layouts.json", "fonts/space-grotesk-400-latin.woff2"}
        # The @font-face block must precede :root, or the family it declares is
        # named by a variable nothing has loaded yet.
        css = files["tokens.css"].decode()
        assert css.index("@font-face") < css.index(":root")
        assert record["selfHostedFonts"] == 1

    @pytest.mark.asyncio
    async def test_a_font_cdn_outage_does_not_fail_the_compile(self, monkeypatch, design):
        async def fake_assign(pre):
            return wt.validate_roles(GOOD, pre)

        async def no_fonts(families, weights, **kwargs):
            return "", {}

        monkeypatch.setattr(wt, "assign_roles", fake_assign)
        monkeypatch.setattr(wt.fonts, "fetch_font_bundle", no_fonts)

        files, record, _pre = await wt.compile_design(design.encode("utf-8"))
        # Degrades to naming the families — the behaviour before self-hosting
        # existed — rather than refusing to produce a theme.
        assert set(files) == {"tokens.css", "layouts.json"}
        assert record["selfHostedFonts"] == 0
        assert record["webFonts"] == ["Space Grotesk", "Libre Franklin"]


class TestUploadNaming:
    def test_a_path_cannot_escape_the_theme_folder(self):
        assert wt.safe_upload_name("../../etc/passwd") == "passwd"
        assert "/" not in wt.safe_upload_name("a/b/c.dc.html")

    def test_the_extension_survives(self):
        assert wt.safe_upload_name("Health Notes.dc.html") == "Health-Notes.dc.html"

    def test_a_missing_name_still_yields_one(self):
        assert wt.safe_upload_name(None) == "design"


class TestRepoFiles:
    def test_files_land_under_the_only_theme_directory(self, monkeypatch):
        # The template's contract: src/theme/ is the whole theme surface, so a
        # swap that wrote anywhere else would be a template change too.
        monkeypatch.setattr(
            wt, "load_built", lambda tid, names: {n: b"x" for n in names}
        )
        files = wt.theme_files_for_repo(
            {"id": "t1", "source_kind": "upload",
             "tokens": {"builtFiles": ["tokens.css", "fonts/a.woff2"]}}
        )
        assert set(files) == {"src/theme/tokens.css", "src/theme/fonts/a.woff2"}

    def test_the_house_theme_commits_nothing(self):
        # It already ships in the template; committing a copy is a no-op commit
        # and a pointless deploy.
        assert wt.theme_files_for_repo({"id": "t", "source_kind": "default"}) == {}

    def test_a_theme_that_never_compiled_commits_nothing(self):
        assert wt.theme_files_for_repo({"id": "t", "source_kind": "upload", "tokens": {}}) == {}
