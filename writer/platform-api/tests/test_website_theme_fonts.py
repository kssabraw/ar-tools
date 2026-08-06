"""Unit tests for self-hosting a theme's fonts.

The stylesheet fixture below is a trimmed copy of what Google actually returns
for `Space Grotesk`, including the per-subset comments the parser keys on — the
subset name exists nowhere else in the response, which is the whole reason this
is a text scan rather than a CSS parse.
"""

from __future__ import annotations

import pytest

from services import website_theme_fonts as fonts

GOOGLE_CSS = """
/* vietnamese */
@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url(https://fonts.gstatic.com/s/spacegrotesk/v22/vi-400.woff2) format('woff2');
  unicode-range: U+0102-0103, U+0110-0111;
}
/* latin-ext */
@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url(https://fonts.gstatic.com/s/spacegrotesk/v22/lx-400.woff2) format('woff2');
  unicode-range: U+0100-02BA, U+1E00-1E9F;
}
/* latin */
@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url(https://fonts.gstatic.com/s/spacegrotesk/v22/la-400.woff2) format('woff2');
  unicode-range: U+0000-00FF, U+0131;
}
/* latin */
@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url(https://fonts.gstatic.com/s/spacegrotesk/v22/la-700.woff2) format('woff2');
  unicode-range: U+0000-00FF, U+0131;
}
"""


class TestFamilyName:
    def test_the_family_is_taken_off_the_front_of_the_stack(self):
        assert fonts.family_name("'Space Grotesk',sans-serif") == "Space Grotesk"
        assert fonts.family_name('"Libre Franklin", Georgia, serif') == "Libre Franklin"

    def test_a_generic_stack_is_not_a_downloadable_family(self):
        # Asking a CDN for a font named `sans-serif` returns a 400 for the whole
        # request, taking any real family in the same call with it.
        assert fonts.family_name("sans-serif") is None
        assert fonts.family_name("ui-sans-serif, system-ui") is None

    def test_an_empty_stack_yields_nothing(self):
        assert fonts.family_name("  ") is None


class TestWantedWeights:
    def test_the_weights_come_from_the_design(self):
        # A design that sets 500 and 800 gets 500 and 800 — fetching a stock
        # 400/700 pair would leave both of its real weights synthesised.
        assert fonts.wanted_weights([("500", 9), ("800", 2)]) == (400, 500, 800)

    def test_keyword_weights_are_understood(self):
        assert fonts.wanted_weights([("bold", 4)]) == (400, 700)

    def test_a_design_that_never_states_a_weight_gets_the_default_pair(self):
        assert fonts.wanted_weights([]) == fonts.FALLBACK_WEIGHTS

    def test_off_scale_weights_are_snapped(self):
        # Google serves hundreds only; an off-scale axis value 404s the whole
        # stylesheet rather than just that weight.
        assert fonts.wanted_weights([("450", 1)]) == (400, 500)

    def test_nonsense_is_ignored_rather_than_requested(self):
        assert fonts.wanted_weights([("inherit", 3), ("1200", 1)]) == fonts.FALLBACK_WEIGHTS

    def test_a_headings_only_census_still_gets_a_text_weight(self):
        # Inline font-weight tends to appear on headings, so a census can easily
        # see 700 and nothing else — shipping no 400 face would leave body copy
        # browser-synthesised.
        assert 400 in fonts.wanted_weights([("700", 12)])


class TestParsing:
    def test_faces_are_read_with_their_subset(self):
        faces = fonts.parse_font_faces(GOOGLE_CSS)
        assert {(f.weight, f.subset) for f in faces} == {
            (400, "latin"), (400, "latin-ext"), (700, "latin")
        }

    def test_scripts_the_sites_do_not_publish_in_are_dropped(self):
        # unicode-range means a browser downloads only what a page uses, so the
        # cost of dropping Vietnamese is a fallback on a stray character — and
        # the saving is real bytes in every repo.
        assert all(f.subset != "vietnamese" for f in fonts.parse_font_faces(GOOGLE_CSS))

    def test_the_unicode_range_survives(self):
        # Without it the browser downloads every face for every page.
        face = fonts.parse_font_faces(GOOGLE_CSS)[0]
        assert face.unicode_range.startswith("U+")

    def test_filenames_are_distinct_per_weight_and_subset(self):
        names = {f.filename for f in fonts.parse_font_faces(GOOGLE_CSS)}
        assert names == {
            "space-grotesk-400-latin.woff2",
            "space-grotesk-400-latin-ext.woff2",
            "space-grotesk-700-latin.woff2",
        }

    def test_an_empty_stylesheet_yields_no_faces(self):
        assert fonts.parse_font_faces("") == []


# Both families in the reference design are variable fonts: Google serves ONE
# file per subset and declares a @font-face per requested weight against it.
VARIABLE_CSS = """
/* latin */
@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 400;
  src: url(https://fonts.gstatic.com/s/spacegrotesk/v22/var-latin.woff2) format('woff2');
}
/* latin */
@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 700;
  src: url(https://fonts.gstatic.com/s/spacegrotesk/v22/var-latin.woff2) format('woff2');
}
"""


class TestVariableFonts:
    """The bug the built output hid.

    Naming by weight downloaded one variable file three times under three names.
    The site still rendered — the bundler dedupes by content hash — so nothing
    complained while every site repo carried triplicate binaries.
    """

    def test_weights_sharing_a_file_get_one_name(self):
        names = fonts.resolve_filenames(fonts.parse_font_faces(VARIABLE_CSS))
        assert list(names.values()) == ["space-grotesk-latin.woff2"]

    def test_the_shared_name_carries_no_weight(self):
        # It is not a weight-400 file; calling it one is a lie a later reader
        # would act on.
        [name] = set(fonts.resolve_filenames(fonts.parse_font_faces(VARIABLE_CSS)).values())
        assert "400" not in name and "700" not in name

    def test_a_static_family_keeps_its_per_weight_names(self):
        # There the files genuinely differ, so dropping the weight would collide
        # two different fonts onto one path.
        names = fonts.resolve_filenames(fonts.parse_font_faces(GOOGLE_CSS))
        assert "space-grotesk-700-latin.woff2" in names.values()

    def test_both_weights_still_declare_a_face(self):
        # Deduplicating the download must not deduplicate the CSS — the browser
        # needs to be told the file covers 700 as well.
        css = fonts.render_font_faces(fonts.parse_font_faces(VARIABLE_CSS))
        assert css.count("@font-face") == 2
        assert css.count("space-grotesk-latin.woff2") == 2

    @pytest.mark.asyncio
    async def test_the_file_is_downloaded_once(self, monkeypatch):
        calls: list[str] = []

        class FakeResponse:
            def __init__(self, status, text="", content=b""):
                self.status_code, self.text, self.content = status, text, content

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                calls.append(url)
                if "googleapis" in url:
                    return FakeResponse(200, text=VARIABLE_CSS)
                return FakeResponse(200, content=b"woff2-bytes")

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        _css, files = await fonts.fetch_font_bundle(["Space Grotesk"], [400, 700])

        assert list(files) == ["fonts/space-grotesk-latin.woff2"]
        assert len([c for c in calls if "gstatic" in c]) == 1


class TestRendering:
    def test_the_css_points_at_committed_files_not_a_cdn(self):
        # The point of self-hosting: a generated site makes no third-party
        # request, so it cannot be slowed or broken by one.
        css = fonts.render_font_faces(fonts.parse_font_faces(GOOGLE_CSS))
        assert "https://" not in css
        assert "src: url('./fonts/space-grotesk-700-latin.woff2') format('woff2');" in css

    def test_swap_is_declared(self):
        # Without it the text is invisible until the font arrives.
        assert "font-display: swap;" in fonts.render_font_faces(fonts.parse_font_faces(GOOGLE_CSS))

    def test_no_faces_renders_nothing_rather_than_an_empty_rule(self):
        assert fonts.render_font_faces([]) == ""


class TestCssUrl:
    def test_weights_are_requested_in_one_call(self):
        url = fonts.css_url("Space Grotesk", [700, 400])
        assert url.endswith("family=Space+Grotesk:wght@400;700&display=swap")


class TestBundle:
    @pytest.mark.asyncio
    async def test_a_download_failure_drops_that_face_not_the_bundle(self, monkeypatch):
        class FakeResponse:
            def __init__(self, status, text="", content=b""):
                self.status_code, self.text, self.content = status, text, content

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                if "googleapis" in url:
                    return FakeResponse(200, text=GOOGLE_CSS)
                if "la-700" in url:
                    raise RuntimeError("cdn down")
                return FakeResponse(200, content=b"woff2-bytes")

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        css, files = await fonts.fetch_font_bundle(["Space Grotesk"], [400, 700])

        # The two that downloaded are hosted; the one that failed is absent from
        # BOTH the files and the CSS — a @font-face pointing at a file we did
        # not commit is a 404 on every page load.
        assert set(files) == {
            "fonts/space-grotesk-400-latin.woff2",
            "fonts/space-grotesk-400-latin-ext.woff2",
        }
        assert "700" not in css

    @pytest.mark.asyncio
    async def test_an_unreachable_cdn_yields_an_empty_bundle(self, monkeypatch):
        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                raise RuntimeError("no network")

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        css, files = await fonts.fetch_font_bundle(["Space Grotesk"])
        # Never raises: a font CDN outage must not fail a theme compile.
        assert (css, files) == ("", {})
