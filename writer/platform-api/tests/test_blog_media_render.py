"""Unit tests for the pure parts of blog_media.render (WebP normalization,
prompt simplification)."""
from services.blog_media.render import _ensure_webp, _simplify


def test_ensure_webp_passes_webp_through_unchanged():
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 rest-of-bytes"
    assert _ensure_webp(webp) is webp


def test_ensure_webp_returns_undecodable_bytes_unchanged():
    junk = b"not-an-image-at-all"
    assert _ensure_webp(junk) == junk


def test_simplify_keeps_subject_and_no_text_rule():
    out = _simplify("A rooftop scene at dawn. Wide angle. Lots of extra styling detail. More.")
    assert "A rooftop scene at dawn" in out
    assert "No readable words" in out
