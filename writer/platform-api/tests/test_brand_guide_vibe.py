"""Unit tests for the Brand Guide Generator Phase-1.5 aesthetic/vibe read.

The pure schema sanitize / mood-axis clamp / unevidenced-descriptor drop /
homepage-path lookup are exercised with no mocks; the vision call itself is
mocked (the PNG fit + the Anthropic tool_use), and the orchestrator's gate /
no-screenshot / download-miss skip paths run against monkeypatched IO. No
network, no Pillow, no deps beyond the platform-api requirements.
"""

from __future__ import annotations

import pytest

from config import settings
from services import brand_guide_vibe as V


# ---------------------------------------------------------------------------
# clamp_axis
# ---------------------------------------------------------------------------
class TestClampAxis:
    def test_int_in_range(self):
        assert V.clamp_axis(55) == 55

    def test_float_rounds(self):
        assert V.clamp_axis(72.6) == 73

    def test_numeric_string_coerced(self):
        assert V.clamp_axis("40") == 40

    def test_clamped_low_and_high(self):
        assert V.clamp_axis(-10) == 0
        assert V.clamp_axis(150) == 100

    def test_non_numeric_dropped(self):
        assert V.clamp_axis("very warm") is None
        assert V.clamp_axis(None) is None
        assert V.clamp_axis([1]) is None


# ---------------------------------------------------------------------------
# sanitize_vibe_read
# ---------------------------------------------------------------------------
class TestSanitize:
    def test_drops_unevidenced_descriptor(self):
        raw = {
            "aesthetic_descriptors": [
                {"descriptor": "clinical", "evidence": "near-black canvas, one violet accent"},
                {"descriptor": "futuristic", "evidence": ""},          # no evidence → dropped
                {"descriptor": "premium"},                              # no evidence key → dropped
            ],
            "mood_axes": {},
            "character": {},
        }
        out = V.sanitize_vibe_read(raw)
        descs = [d["descriptor"] for d in out["aesthetic_descriptors"]]
        assert descs == ["clinical"]

    def test_dedup_and_cap(self):
        raw = {
            "aesthetic_descriptors": [
                {"descriptor": f"adj{i}", "evidence": "ev"} for i in range(12)
            ] + [{"descriptor": "ADJ0", "evidence": "dup by case"}],
            "mood_axes": {},
            "character": {},
        }
        out = V.sanitize_vibe_read(raw)
        assert len(out["aesthetic_descriptors"]) == V._MAX_DESCRIPTORS
        # dedup is case-insensitive on descriptor
        lowered = [d["descriptor"].lower() for d in out["aesthetic_descriptors"]]
        assert len(lowered) == len(set(lowered))

    def test_axes_known_only_and_clamped(self):
        raw = {
            "aesthetic_descriptors": [{"descriptor": "bold", "evidence": "big type"}],
            "mood_axes": {
                "budget_premium": 130,          # clamps to 100
                "warm_cool": "cool-ish",         # non-numeric → dropped
                "made_up_axis": 50,              # unknown → dropped
                "playful_serious": 82,
            },
            "character": {},
        }
        out = V.sanitize_vibe_read(raw)
        assert out["mood_axes"] == {"budget_premium": 100, "playful_serious": 82}

    def test_character_known_only(self):
        raw = {
            "aesthetic_descriptors": [{"descriptor": "airy", "evidence": "whitespace"}],
            "mood_axes": {},
            "character": {
                "color_mood": "muted mono with a vivid accent",
                "spatial_density": "  ",             # blank → dropped
                "bogus_key": "ignored",              # unknown → dropped
            },
        }
        out = V.sanitize_vibe_read(raw)
        assert out["character"] == {"color_mood": "muted mono with a vivid accent"}

    def test_empty_returns_none(self):
        assert V.sanitize_vibe_read({"aesthetic_descriptors": [], "mood_axes": {}, "character": {}}) is None
        assert V.sanitize_vibe_read({"aesthetic_descriptors": [{"descriptor": "x"}]}) is None  # unevidenced-only

    def test_non_dict_returns_none(self):
        assert V.sanitize_vibe_read(None) is None
        assert V.sanitize_vibe_read("nope") is None

    def test_lengths_capped(self):
        raw = {
            "aesthetic_descriptors": [{"descriptor": "a" * 200, "evidence": "b" * 999}],
            "mood_axes": {},
            "character": {"type_personality": "c" * 999},
        }
        out = V.sanitize_vibe_read(raw)
        assert len(out["aesthetic_descriptors"][0]["descriptor"]) == V._DESCRIPTOR_LEN
        assert len(out["aesthetic_descriptors"][0]["evidence"]) == V._EVIDENCE_LEN
        assert len(out["character"]["type_personality"]) == V._CHARACTER_LEN


# ---------------------------------------------------------------------------
# homepage_screenshot_path
# ---------------------------------------------------------------------------
class TestHomepagePath:
    def test_finds_homepage(self):
        captured = {"pages": [
            {"role": "page-1", "screenshot_path": "x/page-1.png"},
            {"role": "homepage", "screenshot_path": "x/homepage.png"},
        ]}
        assert V.homepage_screenshot_path(captured) == "x/homepage.png"

    def test_none_when_homepage_has_no_path(self):
        captured = {"pages": [
            {"role": "homepage", "screenshot_path": None},
            {"role": "page-1", "screenshot_path": "x/page-1.png"},
        ]}
        # only the homepage is a valid palette/vibe source; a page-1 shot never fills in
        assert V.homepage_screenshot_path(captured) is None

    def test_none_on_non_dict_or_empty(self):
        assert V.homepage_screenshot_path(None) is None
        assert V.homepage_screenshot_path({"pages": []}) is None
        assert V.homepage_screenshot_path({}) is None


# ---------------------------------------------------------------------------
# run_vibe_read_from_png — fit + vision mocked
# ---------------------------------------------------------------------------
class TestRunFromPng:
    async def test_happy_path_adds_provenance(self, monkeypatch):
        monkeypatch.setattr("services.qa_visual._fit_image", lambda png: (b"IMG", "image/png"))

        async def _judge(image, media_type):
            return {
                "aesthetic_descriptors": [{"descriptor": "clinical", "evidence": "near-black canvas"}],
                "mood_axes": {"budget_premium": 80},
                "character": {"color_mood": "muted mono"},
            }

        monkeypatch.setattr(V, "_judge_vibe", _judge)
        vibe, note = await V.run_vibe_read_from_png(b"PNG")
        assert note == "vibe read captured"
        assert vibe["aesthetic_descriptors"][0]["descriptor"] == "clinical"
        assert vibe["model"] == settings.brand_guide_vibe_model
        assert vibe["methodology_note"] == V.METHODOLOGY_NOTE

    async def test_unfittable_image_skips(self, monkeypatch):
        monkeypatch.setattr("services.qa_visual._fit_image", lambda png: None)
        vibe, note = await V.run_vibe_read_from_png(b"PNG")
        assert vibe is None and "too large" in note

    async def test_judge_none_skips(self, monkeypatch):
        monkeypatch.setattr("services.qa_visual._fit_image", lambda png: (b"IMG", "image/png"))

        async def _judge(image, media_type):
            return None

        monkeypatch.setattr(V, "_judge_vibe", _judge)
        vibe, note = await V.run_vibe_read_from_png(b"PNG")
        assert vibe is None and "no read" in note

    async def test_empty_after_sanitize_skips(self, monkeypatch):
        monkeypatch.setattr("services.qa_visual._fit_image", lambda png: (b"IMG", "image/png"))

        async def _judge(image, media_type):
            return {"aesthetic_descriptors": [{"descriptor": "x"}], "mood_axes": {}, "character": {}}

        monkeypatch.setattr(V, "_judge_vibe", _judge)
        vibe, note = await V.run_vibe_read_from_png(b"PNG")
        assert vibe is None and "empty after sanitize" in note


# ---------------------------------------------------------------------------
# run_vibe_read_for_capture — the orchestrator gates
# ---------------------------------------------------------------------------
CAP = {"pages": [{"role": "homepage", "screenshot_path": "c/g/homepage.png"}]}


class TestOrchestrator:
    async def test_disabled_skips_without_io(self, monkeypatch):
        monkeypatch.setattr(settings, "brand_guide_enabled", True)
        monkeypatch.setattr(settings, "brand_guide_vibe_enabled", False)

        def _boom(_path):
            raise AssertionError("must not download when disabled")

        monkeypatch.setattr(V, "_download_screenshot", _boom)
        vibe, note = await V.run_vibe_read_for_capture(CAP)
        assert vibe is None and "disabled" in note

    async def test_module_flag_off_skips(self, monkeypatch):
        monkeypatch.setattr(settings, "brand_guide_enabled", False)
        monkeypatch.setattr(settings, "brand_guide_vibe_enabled", True)
        monkeypatch.setattr(V, "_download_screenshot", lambda _p: (_ for _ in ()).throw(AssertionError()))
        vibe, note = await V.run_vibe_read_for_capture(CAP)
        assert vibe is None and "disabled" in note

    async def test_no_homepage_screenshot_skips(self, monkeypatch):
        monkeypatch.setattr(settings, "brand_guide_enabled", True)
        monkeypatch.setattr(settings, "brand_guide_vibe_enabled", True)
        vibe, note = await V.run_vibe_read_for_capture({"pages": [{"role": "homepage", "screenshot_path": None}]})
        assert vibe is None and "CSS-only" in note

    async def test_download_miss_skips(self, monkeypatch):
        monkeypatch.setattr(settings, "brand_guide_enabled", True)
        monkeypatch.setattr(settings, "brand_guide_vibe_enabled", True)
        monkeypatch.setattr(V, "_download_screenshot", lambda _p: None)
        vibe, note = await V.run_vibe_read_for_capture(CAP)
        assert vibe is None and "could not be read from storage" in note

    async def test_happy_path_reads_from_bucket(self, monkeypatch):
        monkeypatch.setattr(settings, "brand_guide_enabled", True)
        monkeypatch.setattr(settings, "brand_guide_vibe_enabled", True)
        seen = {}

        def _dl(path):
            seen["path"] = path
            return b"PNGBYTES"

        async def _from_png(png):
            seen["png"] = png
            return {"aesthetic_descriptors": [{"descriptor": "bold", "evidence": "big"}]}, "vibe read captured"

        monkeypatch.setattr(V, "_download_screenshot", _dl)
        monkeypatch.setattr(V, "run_vibe_read_from_png", _from_png)
        vibe, note = await V.run_vibe_read_for_capture(CAP)
        assert seen["path"] == "c/g/homepage.png"     # read back from the bucket
        assert seen["png"] == b"PNGBYTES"
        assert vibe["aesthetic_descriptors"][0]["descriptor"] == "bold"

    async def test_in_memory_png_skips_bucket_download(self, monkeypatch):
        # The generate hot path passes the just-captured bytes → no bucket read.
        monkeypatch.setattr(settings, "brand_guide_enabled", True)
        monkeypatch.setattr(settings, "brand_guide_vibe_enabled", True)
        monkeypatch.setattr(V, "_download_screenshot", lambda _p: (_ for _ in ()).throw(AssertionError("no download")))
        seen = {}

        async def _from_png(png):
            seen["png"] = png
            return {"aesthetic_descriptors": [{"descriptor": "airy", "evidence": "space"}]}, "vibe read captured"

        monkeypatch.setattr(V, "run_vibe_read_from_png", _from_png)
        vibe, note = await V.run_vibe_read_for_capture(CAP, homepage_png=b"INMEM")
        assert seen["png"] == b"INMEM"                # used the in-memory bytes
        assert vibe["aesthetic_descriptors"][0]["descriptor"] == "airy"

    async def test_disabled_ignores_in_memory_png(self, monkeypatch):
        # the gate wins even when bytes are in hand — no vision call while dark
        monkeypatch.setattr(settings, "brand_guide_enabled", False)
        monkeypatch.setattr(settings, "brand_guide_vibe_enabled", True)
        monkeypatch.setattr(V, "run_vibe_read_from_png",
                            lambda png: (_ for _ in ()).throw(AssertionError("must not run")))
        vibe, note = await V.run_vibe_read_for_capture(CAP, homepage_png=b"INMEM")
        assert vibe is None and "disabled" in note


# ---------------------------------------------------------------------------
# Dependency sync-guard: the vibe read borrows qa_visual._fit_image (a private
# helper with no import-time cross-check). Lock it so a rename/removal in
# qa_visual breaks HERE, loudly, instead of at runtime on a real capture.
# ---------------------------------------------------------------------------
def test_fit_image_dependency_exists():
    from services.qa_visual import _fit_image

    assert callable(_fit_image)
