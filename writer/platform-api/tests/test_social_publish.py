"""Unit tests for the social publish path's pure helpers (no DB / network)."""

from services.social import publish

FB = {"platform": "facebook", "char_limit": 63206, "max_images": 10, "requires_image": False}
IG = {"platform": "instagram", "char_limit": 2200, "max_images": 10, "requires_image": True}
X = {"platform": "twitter", "char_limit": 280, "max_images": 4, "requires_image": False}
PIN = {"platform": "pinterest", "char_limit": 500, "max_images": 1, "requires_image": True}


def test_validate_facebook_text_ok():
    v = publish.validate_post("facebook", "Hello from our shop!", [], FB)
    assert v["hard"] == [] and v["warnings"] == []


def test_validate_empty_post_blocked():
    v = publish.validate_post("facebook", "   ", [], FB)
    assert "empty_post" in v["hard"]
    # an image alone is enough (no copy) on a platform that doesn't require text
    v2 = publish.validate_post("facebook", "", ["https://img/a.jpg"], FB)
    assert v2["hard"] == []


def test_validate_over_char_limit():
    v = publish.validate_post("twitter", "x" * 281, [], X)
    assert any(h.startswith("over_char_limit") for h in v["hard"])
    assert publish.validate_post("twitter", "x" * 280, [], X)["hard"] == []


def test_validate_instagram_requires_image():
    assert "image_required" in publish.validate_post("instagram", "nice caption", [], IG)["hard"]
    assert publish.validate_post("instagram", "nice caption", ["https://img/a.jpg"], IG)["hard"] == []


def test_validate_too_many_images():
    urls = [f"https://img/{i}.jpg" for i in range(2)]
    assert any(h.startswith("too_many_images") for h in publish.validate_post("pinterest", "c", urls, PIN)["hard"])


def test_validate_x_link_warning():
    v = publish.validate_post("twitter", "see https://example.com", [], X)
    assert v["hard"] == []
    assert "x_link_post_50_credits" in v["warnings"]
    # no scheme => no warning
    assert publish.validate_post("twitter", "no link", [], X)["warnings"] == []


def test_validate_unknown_platform_minimal():
    # no spec => only the empty-post check applies
    assert publish.validate_post("mastodon", "hi", [], None)["hard"] == []
    assert "empty_post" in publish.validate_post("mastodon", "", [], None)["hard"]


def test_estimate_cost_usd():
    # X link = 50 credits, plain X = 5, others = 1
    assert publish.estimate_cost_usd("twitter", "buy at https://x.co", 0.01) == 0.5
    assert publish.estimate_cost_usd("twitter", "no link", 0.01) == 0.05
    assert publish.estimate_cost_usd("facebook", "anything", 0.01) == 0.01
