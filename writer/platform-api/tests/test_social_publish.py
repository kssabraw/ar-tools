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


def test_validate_reel_requires_one_video_no_images():
    # A Reel is video-only: exactly one video, no images.
    assert publish.validate_post("instagram", "cap", vid("https://v/a.mp4"), IG, fmt="reel")["hard"] == []
    # no video (only an image) → blocked, and images aren't allowed on a Reel
    v = publish.validate_post("instagram", "cap", img("https://i/a.jpg"), IG, fmt="reel")
    assert any(h.startswith("reel_requires_one_video") for h in v["hard"])
    assert any(h.startswith("reel_no_images") for h in v["hard"])
    # an image alongside a video is still rejected
    v2 = publish.validate_post("facebook", "cap", vid("https://v/a.mp4") + img("https://i/a.jpg"), FB, fmt="reel")
    assert any(h.startswith("reel_no_images") for h in v2["hard"])
    # zero media → needs a video (works for Facebook too, whose spec.requires_image is False)
    assert any(h.startswith("reel_requires_one_video")
               for h in publish.validate_post("facebook", "cap", [], FB, fmt="reel")["hard"])


def test_validate_story_media_required_caption_ignored():
    # A Story needs media but no caption: a caption-less Story with media is fine.
    assert publish.validate_post("instagram", "", img("https://i/a.jpg"), IG, fmt="story")["hard"] == []
    assert publish.validate_post("facebook", "", vid("https://v/a.mp4"), FB, fmt="story")["hard"] == []
    # a caption-less Story is NEVER an empty_post
    assert "empty_post" not in publish.validate_post("instagram", "", img("https://i/a.jpg"), IG, fmt="story")["hard"]
    # no media → blocked, even for Facebook (spec.requires_image is False)
    assert "story_requires_media" in publish.validate_post("facebook", "", [], FB, fmt="story")["hard"]
    # a supplied caption is advisory only (dropped at publish), never a hard block
    v = publish.validate_post("instagram", "this caption is dropped", img("https://i/a.jpg"), IG, fmt="story")
    assert v["hard"] == [] and "story_caption_ignored" in v["warnings"]


def test_validate_story_ignores_char_limit():
    # A long "caption" on a Story never over_char_limits (it's dropped anyway).
    v = publish.validate_post("instagram", "x" * 5000, img("https://i/a.jpg"), IG, fmt="story")
    assert not any(h.startswith("over_char_limit") for h in v["hard"])


def test_validate_feed_default_unchanged():
    assert publish.validate_post("facebook", "hi", [], FB)["hard"] == []
    assert publish.validate_post("facebook", "hi", [], FB, fmt="feed")["hard"] == []


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


def test_publish_job_isolation_gate_fails_post_before_platform(monkeypatch):
    """The authoritative isolation gate at publish time: a re-check failure fails
    the post and NEVER reaches the platform (no budget reserve, no adapter.post)."""
    import asyncio

    from services import notifications
    from services.social import budget

    monkeypatch.setattr(
        publish, "get_post",
        lambda pid: {"id": pid, "platform": "facebook", "account_id": "foreign-acct",
                     "draft_id": None, "status": "scheduled"},
    )
    monkeypatch.setattr(
        publish, "_assert_account_allowed",
        lambda *a, **k: (_ for _ in ()).throw(
            HTTPException(status_code=403, detail="social_account_not_in_client_profile")
        ),
    )

    def _no_reserve(*a, **k):
        raise AssertionError("budget.reserve must not be called after an isolation failure")

    def _no_post(*a, **k):
        raise AssertionError("the platform must never be reached for a foreign account")

    monkeypatch.setattr(budget, "reserve", _no_reserve)
    monkeypatch.setattr(publish, "get_adapter", lambda *a, **k: type("A", (), {"post": _no_post})())

    updates: list[dict] = []
    emitted: list[str] = []
    monkeypatch.setattr(notifications, "emit", lambda *a, **k: emitted.append(a[1] if len(a) > 1 else ""))

    class _Q:
        def __init__(self, tbl):
            self.tbl = tbl

        def update(self, fields):
            if self.tbl == "social_posts":
                updates.append(fields)
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            class _R:
                data: list = []
            return _R()

    monkeypatch.setattr(publish, "_sb", lambda: type("SB", (), {"table": lambda self, t: _Q(t)})())

    asyncio.run(publish.run_publish_job({"id": "job-1", "payload": {"post_id": "p1", "client_id": "c1"}}))

    assert updates, "the post should have been marked failed"
    assert updates[-1]["status"] == "failed"
    assert updates[-1]["status_detail"] == "social_account_not_in_client_profile"
    assert "social_post_failed" in emitted
