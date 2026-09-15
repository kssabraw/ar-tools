"""Unit tests for the Brand Guide deterministic extraction core (Phase 0).

Everything here is pure — no network, no Pillow, no numpy — so the census,
clustering, two-tier hex merge, type-scale, font ranking and logo ranking are
exercised against hand-built fixtures: a small inline-CSS "site" (the CSS-only
palette path + fonts/type/logos) and synthetic screenshot pixel-count tables
(the pixel-primary path + the CSS-hex snap). The numbers asserted are ones the
fixtures state by construction — a check, not a restatement of whatever the
code happened to emit.
"""

from __future__ import annotations

import pytest

from services import brand_guide_extract as bg

# --------------------------------------------------------------------------
# A tiny fixture "site". Brand navy declared many times, an orange accent, and
# three NEAR-DUPLICATE off-whites (to prove clustering folds them). A near-
# transparent overlay (must be dropped) and a stray incidental colour (below the
# share floor). Fonts: Inter primary + Merriweather secondary, plus a Google
# Fonts href. A believable type scale. Logo signals: og:image, a logo-hinted
# header <img>, and a favicon.
# --------------------------------------------------------------------------
FIXTURE_HTML = """
<!doctype html><html><head>
  <meta property="og:image" content="https://acme.example/social-card.png">
  <link rel="icon" href="/favicon.ico">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=Merriweather&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Inter', sans-serif; font-size: 16px; color: #222222; background: #ffffff; }
    h1 { font-family: 'Merriweather', serif; font-size: 3rem; font-weight: 700; color: #1a2b6d; }
    h2 { font-size: 32px; font-weight: 700; }
    h3 { font-size: 24px; }
    .lead { font-size: 16px; }
    .cap { font-size: 12px; }
    .btn { background-color: #e94f37; border-radius: 8px; padding: 12px 24px; }
    .card { background: #f7f7f7; border-radius: 8px; gap: 16px; }
    .panel { background: #f8f8f8; }
    .well { background: #f6f6f6; }
    .overlay { background: rgba(0,0,0,0.08); }
    .fleck { color: #00ff88; }
  </style>
</head><body>
  <header>
    <a href="/"><img src="/assets/acme-logo.svg" alt="Acme logo" class="site-logo"></a>
    <nav><a href="/pricing" style="color:#1a2b6d; font-family:Inter, sans-serif">Pricing</a></nav>
  </header>
  <main><h1 style="color:#1a2b6d">Welcome</h1></main>
</body></html>
"""


class TestColorParsing:
    def test_hex_long_and_short(self):
        assert bg.parse_color("#1a2b6d") == ((26, 43, 109), 1.0)
        assert bg.parse_color("#FFF") == ((255, 255, 255), 1.0)

    def test_hex_with_alpha(self):
        rgb, alpha = bg.parse_color("#1a2b6d80")
        assert rgb == (26, 43, 109)
        assert 0.49 < alpha < 0.51

    def test_rgb_and_rgba(self):
        assert bg.parse_color("rgb(26, 43, 109)") == ((26, 43, 109), 1.0)
        rgb, alpha = bg.parse_color("rgba(255, 255, 255, 0.05)")
        assert rgb == (255, 255, 255)
        assert alpha == pytest.approx(0.05)

    def test_modern_space_slash_syntax(self):
        rgb, alpha = bg.parse_color("rgb(12 34 56 / 50%)")
        assert rgb == (12, 34, 56)
        assert alpha == pytest.approx(0.5)

    def test_hsl_primary_red(self):
        assert bg.parse_color("hsl(0, 100%, 50%)") == ((255, 0, 0), 1.0)

    def test_unparseable_returns_none(self):
        assert bg.parse_color("oklch(0.5 0.1 180)") is None
        assert bg.parse_color("rebeccapurple") is None
        assert bg.parse_color("") is None


class TestColorConversion:
    def test_rgb_to_hex(self):
        assert bg.rgb_to_hex((26, 43, 109)) == "#1a2b6d"

    def test_hsl_roundtrip_shape(self):
        h, s, light = bg.rgb_to_hsl((255, 0, 0))
        assert h == 0 and s == 100 and light == 50

    def test_cmyk_pure_black_no_divzero(self):
        assert bg.rgb_to_cmyk((0, 0, 0)) == (0, 0, 0, 100)

    def test_cmyk_pure_red(self):
        assert bg.rgb_to_cmyk((255, 0, 0)) == (0, 100, 100, 0)

    def test_distance_symmetry_and_zero(self):
        assert bg.color_distance((10, 20, 30), (10, 20, 30)) == 0
        assert bg.color_distance((0, 0, 0), (0, 0, 255)) == pytest.approx(255)


class TestClustering:
    def test_near_duplicates_fold_into_one_representative(self):
        # Three off-whites within tolerance collapse; the heaviest is the rep.
        weighted = [((247, 247, 247), 50), ((248, 248, 248), 30), ((246, 246, 246), 20)]
        swatches = bg.cluster_colors(weighted, tolerance=bg.DEFAULT_CLUSTER_TOLERANCE)
        assert len(swatches) == 1
        assert swatches[0].member_count == 3
        assert swatches[0].rgb == (247, 247, 247)  # heaviest = representative
        assert swatches[0].share == pytest.approx(1.0)

    def test_distinct_hues_stay_separate(self):
        weighted = [((26, 43, 109), 60), ((233, 79, 55), 40)]
        swatches = bg.cluster_colors(weighted)
        assert len(swatches) == 2
        assert swatches[0].rgb == (26, 43, 109)  # sorted by share desc
        assert swatches[0].share == pytest.approx(0.6)

    def test_zero_and_negative_weights_dropped(self):
        assert bg.cluster_colors([((1, 2, 3), 0), ((4, 5, 6), -2)]) == []


class TestColorCensusTwoTier:
    def test_pixel_primary_snaps_to_declared_hex(self):
        # A pixel colour a hair off the declared navy snaps to the exact CSS hex.
        decls = [("color", "#1a2b6d")]
        pixels = [((25, 44, 110), 800), ((255, 255, 255), 200)]
        swatches, source = bg.build_color_census(
            pixel_counts=pixels, css_declarations_list=decls
        )
        assert source == "pixel"
        navy = swatches[0]
        assert navy.source == "both"
        assert navy.css_hex == "#1a2b6d"
        assert navy.hex == "#1a2b6d"  # reported number is the exact declared one
        assert navy.rgb == (26, 43, 109)

    def test_pixel_without_css_match_keeps_sampled_hex(self):
        pixels = [((25, 44, 110), 800)]
        swatches, source = bg.build_color_census(
            pixel_counts=pixels, css_declarations_list=[("color", "#e94f37")]
        )
        assert source == "pixel"
        assert swatches[0].source == "pixel"
        assert swatches[0].css_hex is None
        assert swatches[0].hex == "#192c6e"  # the pixel-sampled value

    def test_css_only_fallback_when_no_pixels(self):
        decls = bg.css_declarations(FIXTURE_HTML)
        swatches, source = bg.build_color_census(css_declarations_list=decls)
        assert source == "css"
        assert all(s.source == "css" for s in swatches)
        hexes = {s.hex for s in swatches}
        assert "#1a2b6d" in hexes  # brand navy (declared 3×)
        assert "#e94f37" in hexes  # accent

    def test_transparent_overlay_dropped(self):
        # The fixture's rgba(0,0,0,0.08) overlay is below the alpha floor.
        decls = bg.css_declarations(FIXTURE_HTML)
        swatches, _ = bg.build_color_census(css_declarations_list=decls)
        assert all(s.rgb != (0, 0, 0) for s in swatches)

    def test_min_share_floor_drops_incidental(self):
        pixels = [((26, 43, 109), 9990), ((0, 255, 136), 10)]  # 0.1% fleck
        swatches, _ = bg.build_color_census(pixel_counts=pixels, min_share=0.02)
        assert len(swatches) == 1
        assert swatches[0].rgb == (26, 43, 109)

    def test_no_signal_returns_none_source(self):
        swatches, source = bg.build_color_census()
        assert swatches == []
        assert source == "none"


class TestTypeScale:
    def test_scale_is_descending_and_rem_normalised(self):
        decls = bg.css_declarations(FIXTURE_HTML)
        scale = bg.derive_type_scale(decls)
        pxs = [step.px for step in scale]
        assert pxs == sorted(pxs, reverse=True)
        assert 48.0 in pxs   # 3rem → 48px
        assert 16.0 in pxs
        assert 12.0 in pxs

    def test_body_size_is_the_most_frequent_step(self):
        decls = bg.css_declarations(FIXTURE_HTML)
        scale = bg.derive_type_scale(decls)
        top_count = max(scale, key=lambda s: s.count)
        assert top_count.px == 16.0  # declared on body + .lead

    def test_near_equal_sizes_snap_together(self):
        scale = bg.derive_type_scale([("font-size", "15.98px"), ("font-size", "16px")])
        assert len(scale) == 1
        assert scale[0].px == 16.0
        assert scale[0].count == 2

    def test_percent_and_viewport_units_ignored(self):
        assert bg.derive_type_scale([("font-size", "120%"), ("font-size", "5vw")]) == []


class TestFonts:
    def test_first_family_ranked_and_google_flagged(self):
        decls = bg.css_declarations(FIXTURE_HTML)
        gfonts = bg.google_font_families(FIXTURE_HTML)
        fonts = bg.rank_font_families(decls, gfonts)
        names = [f.name for f in fonts]
        assert "Inter" in names
        assert "Merriweather" in names
        assert all(name not in names for name in ("sans-serif", "serif"))
        inter = next(f for f in fonts if f.name == "Inter")
        assert inter.google is True

    def test_google_href_families_parsed(self):
        assert bg.google_font_families(FIXTURE_HTML) == ["Inter", "Merriweather"]

    def test_generic_only_stack_yields_no_family(self):
        assert bg.rank_font_families([("font-family", "sans-serif")]) == []


class TestLogoCandidates:
    def test_ranked_og_image_first_favicon_last(self):
        cands = bg.logo_candidates_from_html(FIXTURE_HTML, base_url="https://acme.example")
        assert cands, "expected at least one candidate"
        assert cands[0].source == "og_image"
        assert cands[0].url == "https://acme.example/social-card.png"
        sources = [c.source for c in cands]
        assert "img_logo" in sources          # the logo-hinted header <img>
        assert sources[-1] == "favicon"

    def test_relative_urls_resolved_against_base(self):
        cands = bg.logo_candidates_from_html(FIXTURE_HTML, base_url="https://acme.example/")
        img = next(c for c in cands if c.source == "img_logo")
        assert img.url == "https://acme.example/assets/acme-logo.svg"

    def test_protocol_relative_and_absolute_kept(self):
        html = '<meta property="og:image" content="//cdn.x/y.png">'
        cands = bg.logo_candidates_from_html(html, base_url="https://acme.example")
        assert cands[0].url == "https://cdn.x/y.png"


class TestExtractVisualCensus:
    def test_css_only_capture_produces_full_census(self):
        census = bg.extract_visual_census(FIXTURE_HTML, base_url="https://acme.example")
        assert not census.is_empty
        assert census.palette_source == "css"
        assert census.colors and census.fonts and census.type_scale
        assert census.logo_candidates
        # honest note that dominance is declaration frequency, not pixel area
        assert any("CSS declarations only" in n for n in census.notes)

    def test_pixel_capture_marks_palette_source_pixel(self):
        pixels = [((26, 43, 109), 700), ((233, 79, 55), 200), ((255, 255, 255), 100)]
        census = bg.extract_visual_census(
            FIXTURE_HTML, pixel_counts=pixels, base_url="https://acme.example"
        )
        assert census.palette_source == "pixel"
        # navy snapped to the declared hex
        navy = census.colors[0]
        assert navy.source == "both"
        assert navy.css_hex == "#1a2b6d"

    def test_empty_html_degrades_without_raising(self):
        census = bg.extract_visual_census("")
        assert census.is_empty
        assert census.palette_source == "none"
        assert census.notes  # explains what was missing

    def test_as_dict_is_json_shaped(self):
        census = bg.extract_visual_census(FIXTURE_HTML, base_url="https://acme.example")
        d = census.as_dict()
        assert set(d) >= {"colors", "fonts", "type_scale", "logo_candidates", "palette_source"}
        assert isinstance(d["colors"][0]["rgb"], list)  # tuples serialised to lists
        assert isinstance(d["colors"][0]["share"], float)


# --------------------------------------------------------------------------
# Phase-0 spike findings folded into the capture layer. Fixtures mirror the
# actual leaks measured on live client sites in the D4 spike.
# --------------------------------------------------------------------------
class TestFontJunkDropped:
    """Finding 1: Elementor `var(--…)` + Wix `wfont_<hash>` leak as families."""

    def test_elementor_var_family_dropped(self):
        # FreightOptics: var(--ui)/var(--host)/var( --e-global-typography-…-font-family )
        decls = [
            ("font-family", "Host Grotesk, sans-serif"),
            ("font-family", "var(--ui)"),
            ("font-family", "var(--host)"),
            ("font-family", "var( --e-global-typography-text-font-family )"),
            ("font-family", "Inter, system-ui"),
        ]
        names = [f.name for f in bg.rank_font_families(decls)]
        assert "Host Grotesk" in names and "Inter" in names
        assert not any(n.startswith("var(") for n in names)

    def test_wix_wfont_hash_dropped_but_real_aliases_kept(self):
        # Sealbeach CoLabs: wfont_3f9260_<32hex> IDs alongside real Wix aliases.
        decls = [
            ("font-family", "wfont_3f9260_763c7b8a6d994b3e81f4796950e90e13,sans-serif"),
            ("font-family", "futura-lt-w01-light"),
            ("font-family", "proxima-n-w01-reg"),
            ("font-family", "helvetica-w01-roman"),
        ]
        names = [f.name for f in bg.rank_font_families(decls)]
        assert "futura-lt-w01-light" in names        # real alias survives
        assert "proxima-n-w01-reg" in names
        assert not any(n.startswith("wfont_") for n in names)
        assert not any(f.name for f in bg.rank_font_families(decls) if "763c7b8a" in f.name)

    def test_bare_first_family_helper(self):
        assert bg._first_family("var(--ui)") is None
        assert bg._first_family("wfont_3f9260_4ead16c8356b4536a4538ccdfe940616") is None
        assert bg._first_family("Host Grotesk, sans-serif") == "Host Grotesk"
        assert bg._first_family("futura-lt-w01-light") == "futura-lt-w01-light"


class TestLogoChromeDownRanked:
    """Finding 2: consent-banner / customer-logo chrome out-ranking the brand."""

    UMH = """
      <meta property="og:image" content="https://umh.com/wp-content/uploads/UMH_logo-o.png">
      <header>
        <img src="https://cdn-cookieyes.com/assets/images/poweredbtcky.svg" class="logo">
        <img src="https://umh.com/wp-content/uploads/UMH_header_logo.svg" alt="UMH logo">
      </header>
    """

    def test_cookieyes_never_outranks_real_logo(self):
        cands = bg.logo_candidates_from_html(self.UMH, base_url="https://umh.com")
        # Real brand marks lead; the cookie-consent SVG sinks below them.
        top_urls = [c.url for c in cands[:2]]
        assert "https://umh.com/wp-content/uploads/UMH_logo-o.png" in top_urls
        assert "https://umh.com/wp-content/uploads/UMH_header_logo.svg" in top_urls
        cky = next(c for c in cands if "cookieyes" in c.url)
        assert cky.score < 0 and "down-ranked" in cky.note
        assert cky is cands[-1]  # last, never a suggestion

    def test_customer_logo_demoted_below_site_logo(self):
        html = """
          <header>
            <img src="/wp-content/uploads/freightoptics-site-logo-480.png" class="logo">
            <img src="/wp-content/uploads/freightoptics-customer-logo-park-west.png" alt="customer logo">
          </header>
        """
        cands = bg.logo_candidates_from_html(html, base_url="https://www.freightoptics.com")
        site = next(c for c in cands if "site-logo" in c.url)
        cust = next(c for c in cands if "customer-logo" in c.url)
        assert site.score > cust.score
        assert cands[0].url.endswith("freightoptics-site-logo-480.png")

    def test_wixstatic_asset_host_not_penalised(self):
        # A client's OWN logo on a Wix/WordPress CDN must NOT be treated as chrome.
        html = '<header><img src="https://static.wixstatic.com/media/abc~mv2.png" class="logo"></header>'
        cands = bg.logo_candidates_from_html(html, base_url="https://x.example")
        assert cands and cands[0].score >= 70 and "down-ranked" not in cands[0].note


class TestDiscoverKeyPages:
    NAV = """
      <nav>
        <a href="/">Home</a>
        <a href="/services/roof-repair">Services</a>
        <a href="/products">Shop</a>
        <a href="/about-us">About</a>
        <a href="/contact">Contact</a>
        <a href="https://facebook.com/x">Follow us</a>
        <a href="/brochure.pdf">Download</a>
        <a href="#top">Back to top</a>
        <a href="mailto:a@b.com">Email</a>
      </nav>
    """

    def test_picks_one_service_and_one_about(self):
        pages = bg.discover_key_pages(self.NAV, base_url="https://acme.example")
        assert pages == [
            "https://acme.example/services/roof-repair",
            "https://acme.example/about-us",
        ]

    def test_excludes_homepage_assets_fragments_offhost(self):
        pages = bg.discover_key_pages(self.NAV, base_url="https://acme.example")
        joined = " ".join(pages)
        assert "facebook.com" not in joined  # off-host
        assert ".pdf" not in joined          # asset
        assert "#" not in joined             # fragment
        assert "mailto" not in joined
        assert all(u.rstrip("/") != "https://acme.example" for u in pages)

    def test_limit_and_empty_degrade(self):
        assert bg.discover_key_pages(self.NAV, base_url="https://acme.example", limit=1) == [
            "https://acme.example/services/roof-repair"
        ]
        assert bg.discover_key_pages("<nav><a href='/'>Home</a></nav>", base_url="https://acme.example") == []
        assert bg.discover_key_pages("", base_url="https://acme.example") == []
