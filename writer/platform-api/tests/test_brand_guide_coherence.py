"""Unit tests for the Phase-2 coherence check + WCAG contrast (pure).

Both are the deterministic core the LLM narrates but never computes (PRD §5.2):
the contrast pairings feed the Color section's accessible-pairings rows, and the
coherence flags are the audit payoff (feel vs execution). No network, no config
beyond import.
"""

from __future__ import annotations

from services import brand_guide_coherence as C


# ---------------------------------------------------------------------------
# WCAG contrast (pure math)
# ---------------------------------------------------------------------------
class TestContrast:
    def test_black_white_is_21(self):
        assert C.wcag_contrast((0, 0, 0), (255, 255, 255)) == 21.0

    def test_order_independent(self):
        assert C.wcag_contrast((26, 43, 109), (255, 255, 255)) == C.wcag_contrast((255, 255, 255), (26, 43, 109))

    def test_same_color_is_1(self):
        assert C.wcag_contrast((123, 45, 67), (123, 45, 67)) == 1.0

    def test_levels(self):
        assert C.contrast_level(21.0) == "AAA"
        assert C.contrast_level(7.0) == "AAA"
        assert C.contrast_level(4.5) == "AA"
        assert C.contrast_level(3.0) == "AA Large"
        assert C.contrast_level(2.9) == "fail"

    def test_navy_is_high_contrast_on_white(self):
        ratio = C.wcag_contrast((26, 43, 109), (255, 255, 255))
        assert ratio > 7  # dark navy → AAA on white


class TestContrastPairings:
    def test_picks_the_more_legible_text_color(self):
        colors = [
            {"hex": "#1a2b6d", "rgb": [26, 43, 109]},   # dark → white text
            {"hex": "#f2f2f2", "rgb": [242, 242, 242]},  # light → black text
        ]
        pairings = C.contrast_pairings(colors)
        assert pairings[0]["background"] == "#1a2b6d" and pairings[0]["text"] == "#ffffff"
        assert pairings[0]["passes_body"] is True
        assert pairings[1]["background"] == "#f2f2f2" and pairings[1]["text"] == "#000000"

    def test_optimal_text_always_clears_aa_body(self):
        # Choosing the better of white/black text is guaranteed to clear AA body
        # (the crossover minimum is ~4.58:1 > 4.5), so passes_body holds even for a
        # mid gray — the invariant `contrast_pairings` relies on.
        pairings = C.contrast_pairings([{"hex": "#808080", "rgb": [128, 128, 128]}])
        assert pairings[0]["passes_body"] is True
        assert pairings[0]["ratio"] >= 4.5

    def test_limit_and_bad_rows(self):
        colors = [{"hex": f"#{i:02x}0000", "rgb": [i, 0, 0]} for i in range(10)]
        colors.append({"hex": "#bad", "rgb": "nope"})  # unparseable → skipped
        assert len(C.contrast_pairings(colors, limit=3)) == 3


# ---------------------------------------------------------------------------
# Coherence flags (census vs vibe cross-check)
# ---------------------------------------------------------------------------
def _neutral(n: int) -> list[dict]:
    return [{"hex": f"#{80 + i:02x}{80 + i:02x}{80 + i:02x}", "rgb": [128, 128, 128], "hsl": [0, 3, 50]} for i in range(n)]


def _hued(n: int) -> list[dict]:
    return [{"hex": f"#{i}00000", "rgb": [200, i * 10, 0], "hsl": [20, 80, 50]} for i in range(n)]


class TestCoherenceFlags:
    def test_clean_census_no_flags(self):
        census = {
            "colors": [{"hex": "#1a2b6d", "rgb": [26, 43, 109], "hsl": [230, 61, 26]},
                       {"hex": "#e63946", "rgb": [230, 57, 70], "hsl": [355, 78, 56]}],
            "fonts": [{"name": "Inter", "count": 12}],
            "type_scale": [{"px": 48}, {"px": 16}],
        }
        assert C.build_coherence_flags(census, None) == []

    def test_neutral_sprawl_flag(self):
        census = {"colors": _neutral(5), "fonts": [], "type_scale": []}
        flags = C.build_coherence_flags(census, None)
        codes = {f["code"] for f in flags}
        assert "neutral_sprawl" in codes
        nf = next(f for f in flags if f["code"] == "neutral_sprawl")
        assert nf["evidence"]["neutral_count"] == 5 and nf["section"] == "color"

    def test_palette_and_type_and_font_sprawl(self):
        census = {
            "colors": _hued(8),
            "fonts": [{"name": "A", "count": 3}, {"name": "B", "count": 2}, {"name": "C", "count": 1}],
            "type_scale": [{"px": p} for p in range(9)],
        }
        codes = {f["code"] for f in C.build_coherence_flags(census, None)}
        assert {"palette_sprawl", "type_scale_sprawl", "font_sprawl"} <= codes

    def test_google_only_font_not_counted_as_overuse(self):
        # count == 0 (declared only via an external class) is not evidence of overuse.
        census = {"colors": [], "type_scale": [],
                  "fonts": [{"name": "A", "count": 5}, {"name": "B", "count": 0}, {"name": "C", "count": 0}]}
        assert not any(f["code"] == "font_sprawl" for f in C.build_coherence_flags(census, None))

    def test_vibe_execution_gap_headline(self):
        census = {"colors": _neutral(5), "fonts": [], "type_scale": []}
        vibe = {"mood_axes": {"budget_premium": 80}}
        flags = C.build_coherence_flags(census, vibe)
        gap = [f for f in flags if f["code"] == "vibe_execution_gap"]
        assert gap and gap[0]["evidence"]["feel"] == "premium"
        assert "premium" in gap[0]["title"]

    def test_no_vibe_gap_without_vibe_read(self):
        census = {"colors": _neutral(5), "fonts": [], "type_scale": []}
        assert not any(f["code"] == "vibe_execution_gap" for f in C.build_coherence_flags(census, None))

    def test_minimal_vibe_triggers_gap(self):
        census = {"colors": _hued(8), "fonts": [], "type_scale": []}
        vibe = {"mood_axes": {"minimal_maximal": 20}}
        gap = [f for f in C.build_coherence_flags(census, vibe) if f["code"] == "vibe_execution_gap"]
        assert gap and gap[0]["evidence"]["feel"] == "minimal"

    def test_flags_sorted_gap_first(self):
        census = {"colors": _neutral(5), "fonts": [], "type_scale": []}
        flags = C.build_coherence_flags(census, {"mood_axes": {"budget_premium": 90}})
        assert all(f["severity"] == "gap" for f in flags)  # all our flags are gaps

    def test_tolerates_garbage_shapes(self):
        assert C.build_coherence_flags(None, None) == []
        assert C.build_coherence_flags({"colors": ["x", {"hsl": "bad"}]}, "nope") == []
