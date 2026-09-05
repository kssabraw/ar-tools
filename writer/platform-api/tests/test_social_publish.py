"""Unit tests for the social publish path's pure helpers (no DB / network)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from services.social import publish

FB = {"platform": "facebook", "char_limit": 63206, "max_images": 10, "requires_image": False}
IG = {"platform": "instagram", "char_limit": 2200, "max_images": 10, "requires_image": True}
X = {"platform": "twitter", "char_limit": 280, "max_images": 4, "requires_image": False}
PIN = {"platform": "pinterest", "char_limit": 500, "max_images": 1, "requires_image": True}


def img(*urls):
    return [{"type": "image", "url": u} for u in urls]


def vid(*urls):
    return [{"type": "video", "url": u} for u in urls]


def test_build_media():
    assert publish.build_media(["a", "b"], ["v"]) == [
        {"type": "image", "url": "a"}, {"type": "image", "url": "b"}, {"type": "video", "url": "v"}
    ]
    assert publish.build_media(None, None) == []
    assert publish.build_media(["", "a"], None) == [{"type": "image", "url": "a"}]  # drops empties


def test_validate_facebook_text_ok():
    v = publish.validate_post("facebook", "Hello from our shop!", [], FB)
    assert v["hard"] == [] and v["warnings"] == []


def test_validate_empty_post_blocked():
    assert "empty_post" in publish.validate_post("facebook", "   ", [], FB)["hard"]
    assert publish.validate_post("facebook", "", img("https://img/a.jpg"), FB)["hard"] == []


def test_validate_over_char_limit():
    assert any(h.startswith("over_char_limit") for h in publish.validate_post("twitter", "x" * 281, [], X)["hard"])
    assert publish.validate_post("twitter", "x" * 280, [], X)["hard"] == []


def test_validate_instagram_requires_media():
    assert "media_required" in publish.validate_post("instagram", "caption", [], IG)["hard"]
    # an image OR a video satisfies IG's media requirement (video => Reel)
    assert publish.validate_post("instagram", "caption", img("https://i/a.jpg"), IG)["hard"] == []
    assert publish.validate_post("instagram", "caption", vid("https://v/a.mp4"), IG)["hard"] == []


def test_validate_too_many_images_and_videos():
    assert any(h.startswith("too_many_images") for h in publish.validate_post("pinterest", "c", img("a", "b"), PIN)["hard"])
    assert any(h.startswith("too_many_videos") for h in publish.validate_post("facebook", "c", vid("a", "b"), FB)["hard"])


def test_validate_x_link_warning():
    v = publish.validate_post("twitter", "see https://example.com", [], X)
    assert v["hard"] == [] and "x_link_post_50_credits" in v["warnings"]
    assert publish.validate_post("twitter", "no link", [], X)["warnings"] == []


def test_validate_unknown_platform_minimal():
    assert publish.validate_post("mastodon", "hi", [], None)["hard"] == []
    assert "empty_post" in publish.validate_post("mastodon", "", [], None)["hard"]


def test_estimate_cost_usd():
    assert publish.estimate_cost_usd("twitter", "buy at https://x.co", 0.01) == 0.5
    assert publish.estimate_cost_usd("twitter", "no link", 0.01) == 0.05
    assert publish.estimate_cost_usd("facebook", "anything", 0.01) == 0.01


def test_ensure_future_iso():
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    out = publish._ensure_future_iso(now + timedelta(hours=1), now)
    assert out.startswith("2026-09-05T13:00")
    # naive datetime treated as UTC
    naive = datetime(2026, 9, 5, 13, 0)
    assert publish._ensure_future_iso(naive, now).startswith("2026-09-05T13:00")
    with pytest.raises(HTTPException):
        publish._ensure_future_iso(now - timedelta(minutes=1), now)
