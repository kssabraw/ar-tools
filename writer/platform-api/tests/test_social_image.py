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


def test_select_image_model_flash_on_routes_to_flash():
    out = image.select_image_model(
        use_flash=True, flash_model="gemini-3.1-flash-image", flash_cost=0.101,
        pro_model="gemini-3-pro-image-preview", pro_cost=0.134,
    )
    assert out == ("gemini-3.1-flash-image", 0.101)


def test_select_image_model_flash_off_falls_back_to_pro():
    out = image.select_image_model(
        use_flash=False, flash_model="gemini-3.1-flash-image", flash_cost=0.101,
        pro_model="gemini-3-pro-image-preview", pro_cost=0.134,
    )
    assert out == ("gemini-3-pro-image-preview", 0.134)


def test_select_image_model_blank_flash_model_falls_back_to_pro():
    # A misconfigured/empty flash model id can never route away from a real model.
    for bad in ("", "   ", None):
        out = image.select_image_model(
            use_flash=True, flash_model=bad, flash_cost=0.101,
            pro_model="gemini-3-pro-image-preview", pro_cost=0.134,
        )
        assert out == ("gemini-3-pro-image-preview", 0.134)


def test_select_image_model_strips_flash_model_whitespace():
    out = image.select_image_model(
        use_flash=True, flash_model="  gemini-3.1-flash-image  ", flash_cost=0.101,
        pro_model="gemini-3-pro-image-preview", pro_cost=0.134,
    )
    assert out == ("gemini-3.1-flash-image", 0.101)


def test_select_image_model_default_config_routes_to_flash():
    # The shipped defaults (queue #5 ON) route every social image to Nano Banana 2.
    from config import settings

    assert settings.social_image_use_flash is True
    model, cost = image.select_image_model(
        use_flash=settings.social_image_use_flash,
        flash_model=settings.social_image_flash_model,
        flash_cost=float(settings.social_image_flash_cost_usd),
        pro_model=settings.nano_banana_pro_model,
        pro_cost=float(settings.social_image_cost_usd),
    )
    assert model == settings.social_image_flash_model
    assert cost == float(settings.social_image_flash_cost_usd)
    # Cheaper than the Pro fallback — the whole point of the mixed path.
    assert cost < float(settings.social_image_cost_usd)


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
