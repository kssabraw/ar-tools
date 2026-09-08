"""Unit tests for the social AI image renderer's pure helpers (no network/DB)."""

import base64

from services import nano_banana
from services.social import image


def test_resolve_aspect_ratio_verticals():
    for p in ("instagram", "facebook", "youtube", "pinterest", "twitter"):
        assert image.resolve_aspect_ratio(p, "reel") == "9:16"
        assert image.resolve_aspect_ratio(p, "story") == "9:16"


def test_resolve_aspect_ratio_per_platform_feed():
    assert image.resolve_aspect_ratio("pinterest", "feed") == "2:3"
    assert image.resolve_aspect_ratio("instagram", "feed") == "4:5"
    assert image.resolve_aspect_ratio("twitter", "feed") == "16:9"
    assert image.resolve_aspect_ratio("x", "feed") == "16:9"
    assert image.resolve_aspect_ratio("youtube", "feed") == "16:9"
    assert image.resolve_aspect_ratio("facebook", "feed") == "1:1"
    assert image.resolve_aspect_ratio("mastodon", "feed") == "1:1"  # default


def test_resolve_aspect_ratio_always_gemini_supported():
    for p in ("instagram", "facebook", "youtube", "pinterest", "twitter", "x", "linkedin", "threads", ""):
        for f in ("feed", "reel", "story", "", "pin"):
            assert image.resolve_aspect_ratio(p, f) in image.GEMINI_ASPECT_RATIOS


def test_ext_for_mime():
    assert image.ext_for_mime("image/png") == "png"
    assert image.ext_for_mime("image/jpeg") == "jpg"
    assert image.ext_for_mime("image/webp") == "webp"
    assert image.ext_for_mime("image/png; charset=x") == "png"
    assert image.ext_for_mime("") == "png"          # default
    assert image.ext_for_mime("image/heic") == "png"  # unknown → default


def test_build_image_prompt_default_style_and_brand():
    out = image.build_image_prompt("a golden retriever on a porch", {"name": "Acme Roofing"}, None)
    assert "Acme Roofing" in out
    assert "golden retriever on a porch" in out
    assert "watermark" in out.lower()  # default style guidance present


def test_build_image_prompt_template_substitution_suppresses_default_style():
    out = image.build_image_prompt(
        "a burst pipe under a sink",
        {"name": "Acme"},
        "Flat vector illustration, blue palette. Scene: {description}",
    )
    assert "Flat vector illustration" in out
    assert "burst pipe under a sink" in out
    assert "watermark" not in out.lower()  # client's template drives the look, no default


def test_build_image_prompt_template_append_when_no_placeholder():
    out = image.build_image_prompt("a sink", {"name": "Acme"}, "Minimalist studio photo.")
    assert "Minimalist studio photo." in out and "a sink" in out


def test_build_image_prompt_handles_missing_client_and_empty():
    # No client name, and the description carries through with default style added.
    out = image.build_image_prompt("a red door", None, None)
    assert "a red door" in out and "watermark" in out.lower()
    assert "On-brand social media image for" not in out  # no name → no brand line
    # Empty description still yields a string (no crash), not None.
    assert isinstance(image.build_image_prompt("", None, None), str)


def _resp(mime: str, raw: bytes) -> dict:
    return {"candidates": [{"content": {"parts": [
        {"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode()}}
    ]}}]}


def test_extract_image_returns_bytes_and_mime():
    out = nano_banana.extract_image(_resp("image/png", b"PNGDATA"))
    assert out == (b"PNGDATA", "image/png")
    # back-compat helper still returns just bytes
    assert nano_banana.extract_image_bytes(_resp("image/jpeg", b"JPG")) == b"JPG"


def test_extract_image_none_when_no_image():
    assert nano_banana.extract_image({"candidates": [{"content": {"parts": [{"text": "sorry"}]}}]}) is None
    assert nano_banana.extract_image({}) is None
