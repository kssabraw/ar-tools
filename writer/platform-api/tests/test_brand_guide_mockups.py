"""Unit tests for the Brand Guide Generator Phase-5 Applications / mockups layer.

Pure palette resolution + the five in-context mockup builders + the section
assembly + its degrade path. No network, no LLM — the whole module is deterministic
assembly over the stored `synthesized` / `visual_census` shapes + the render
context (PRD §5.2 / §5.4). Mirrors the render-layer tests.
"""

from __future__ import annotations

from services import brand_guide_mockups as M


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _guide(**over) -> dict:
    g = {
        "id": "guide-1",
        "client_id": "client-1",
        "version": 2,
        "visual_census": {
            "colors": [
                {"hex": "#0f172a", "rgb": [15, 23, 42], "share": 0.55, "source": "both"},
                {"hex": "#6366f1", "rgb": [99, 102, 241], "share": 0.12, "source": "pixel"},
            ],
            "fonts": [
                {"name": "Inter", "count": 12, "google": True},
                {"name": "Georgia", "count": 3, "google": False},
            ],
        },
        "synthesized": {
            "tagline": "Roofs done right.",
            "color": {
                "swatches": [
                    {"hex": "#0f172a", "name": "Midnight", "role": "primary", "share": 0.55},
                    {"hex": "#6366f1", "name": "Signal Violet", "role": "accent", "share": 0.12},
                ],
            },
            "voice_examples": {"headline": "Your roof, handled.", "cta": "Get a free quote", "product_blurb": "Fast, local, licensed."},
            "boilerplate": {"short": "Acme Roofing fixes roofs since 1998."},
        },
    }
    g.update(over)
    return g


def _ctx(**over) -> dict:
    c = {"name": "Acme Roofing", "website": "https://acme.com", "phone": "(555) 010-1234", "address": "12 Main St, Springfield"}
    c.update(over)
    return c


# ---------------------------------------------------------------------------
# Palette resolution
# ---------------------------------------------------------------------------
class TestResolvePalette:
    def test_from_synthesized_roles(self):
        pal = M.resolve_palette(_guide())
        assert pal["primary"] == "#0f172a"      # role=primary wins regardless of luminance
        assert pal["accent"] == "#6366f1"        # role=accent
        assert pal["on_primary"] == "#ffffff"    # readable ink on the dark primary
        assert pal["heading_font"] == "Inter"
        assert pal["body_font"] == "Georgia"

    def test_falls_back_to_census_when_no_swatches(self):
        g = _guide(synthesized={"tagline": "x"})  # no color.swatches
        g["visual_census"]["colors"] = [{"hex": "#c8102e", "rgb": [200, 16, 46], "share": 0.6}]
        pal = M.resolve_palette(g)
        assert pal["primary"] == "#c8102e"

    def test_skips_not_brand_swatches(self):
        g = _guide()
        g["synthesized"]["color"]["swatches"] = [
            {"hex": "#111111", "role": "primary", "not_brand": True},
            {"hex": "#c8102e", "role": "accent"},
        ]
        pal = M.resolve_palette(g)
        # The not-brand primary is skipped; the accent becomes the primary.
        assert pal["primary"] == "#c8102e"

    def test_no_palette_returns_empty(self):
        g = {"visual_census": {"colors": []}, "synthesized": {}}
        assert M.resolve_palette(g) == {}

    def test_ink_and_paper_defaults_when_no_extremes(self):
        # An all-light palette (nothing dark, nothing near-white) → safe defaults.
        g = {"visual_census": {"colors": [{"hex": "#cfcfcf"}, {"hex": "#bbbbbb"}]}, "synthesized": {}}
        pal = M.resolve_palette(g)
        assert pal["ink"] == "#0f172a"   # darkest is still light → safe slate ink
        assert pal["paper"] == "#ffffff"  # nothing near-white → white paper


# ---------------------------------------------------------------------------
# Section assembly
# ---------------------------------------------------------------------------
class TestBuildSection:
    def test_all_five_mockups_and_tokens_present(self):
        html = M.build_applications_section(_guide(), _ctx(), logo_src="data:image/png;base64,AAAA")
        assert "<h2>Applications</h2>" in html
        for caption in ("Website hero", "Social post", "Business card", "Letterhead", "Product label"):
            assert caption in html
        # Brand tokens + copy present.
        assert "#0f172a" in html and "#6366f1" in html
        assert "Your roof, handled." in html      # headline
        assert "Get a free quote" in html          # CTA
        assert "Roofs done right." in html          # tagline
        assert "Acme Roofing" in html               # business name
        # Real contact + logo image.
        assert "(555) 010-1234" in html and "acme.com" in html
        assert "data:image/png;base64,AAAA" in html

    def test_omitted_when_no_palette(self):
        assert M.build_applications_section({"visual_census": {}, "synthesized": {}}, _ctx()) == ""

    def test_cta_falls_back_to_generic_label(self):
        g = _guide()
        g["synthesized"]["voice_examples"] = {"headline": "Hi"}  # no cta
        html = M.build_applications_section(g, _ctx())
        assert "Learn more" in html

    def test_wordmark_when_no_logo(self):
        html = M.build_applications_section(_guide(), _ctx(), logo_src=None)
        assert "<img" not in html                   # no logo image
        assert "Acme Roofing" in html               # text wordmark stands in

    def test_contact_lines_omitted_when_absent(self):
        html = M.build_applications_section(_guide(), _ctx(phone="", address=""))
        assert "(555) 010-1234" not in html
        assert "Main St" not in html

    def test_letterhead_placeholder_when_no_boilerplate(self):
        g = _guide()
        g["synthesized"]["boilerplate"] = {}
        html = M.build_applications_section(g, _ctx())
        assert "Letterhead" in html                 # still renders (inert placeholder rules)

    def test_escapes_untrusted_copy(self):
        g = _guide()
        g["synthesized"]["tagline"] = "<script>x</script>"
        html = M.build_applications_section(g, _ctx(name="A & B <Co>"))
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "A &amp; B &lt;Co&gt;" in html

    def test_profile_independent(self):
        # The mockups take no profile arg — identical for internal + client (§4.7).
        a = M.build_applications_section(_guide(), _ctx(), logo_src="d")
        b = M.build_applications_section(_guide(), _ctx(), logo_src="d")
        assert a == b


# ---------------------------------------------------------------------------
# Determinism guarantee (PRD §5.2)
# ---------------------------------------------------------------------------
def test_no_llm_dependency():
    import inspect

    src = inspect.getsource(M)
    assert "report_llm" not in src
    assert "anthropic" not in src.lower()


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
class TestHelpers:
    def test_readable_on_dark_is_white(self):
        assert M._readable_on("#0f172a") == "#ffffff"

    def test_readable_on_light_is_ink(self):
        assert M._readable_on("#ffffff") == M._INK

    def test_display_url_strips_scheme(self):
        assert M._display_url("https://acme.com/") == "acme.com"
        assert M._display_url("http://x.io/path/") == "x.io/path"

    def test_hex_rgb_parses_short_and_long(self):
        assert M._hex_rgb("#fff") == (255, 255, 255)
        assert M._hex_rgb("#6366f1") == (99, 102, 241)
        assert M._hex_rgb("nope") is None

    def test_font_css_names_family_with_fallback(self):
        assert M._font_css("Inter") == "'Inter', sans-serif"
        assert M._font_css("") == "sans-serif"
