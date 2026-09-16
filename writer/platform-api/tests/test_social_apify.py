"""Unit tests for the Apify client's pure helpers + per-platform post parsers
(services/social/apify.py). No network — parsers/input-builders only."""

from services.social import apify


# ── actor id / handle helpers ────────────────────────────────────────────────

def test_actor_path_maps_slash_to_tilde():
    assert apify.actor_path("apify/instagram-scraper") == "apify~instagram-scraper"
    assert apify.actor_path("apify~instagram-scraper") == "apify~instagram-scraper"
    assert apify.actor_path("  apidojo/tweet-scraper ") == "apidojo~tweet-scraper"
    assert apify.actor_path("") == ""


def test_actor_for_platform_reads_settings(monkeypatch):
    monkeypatch.setattr(apify.settings, "social_apify_actor_instagram", "u/ig")
    monkeypatch.setattr(apify.settings, "social_apify_actor_twitter", "u/x")
    assert apify.actor_for_platform("instagram") == "u/ig"
    assert apify.actor_for_platform("twitter") == "u/x"
    assert apify.actor_for_platform("x") == "u/x"          # x aliases twitter
    assert apify.actor_for_platform("linkedin") == ""      # unmapped → blank
    assert apify.actor_for_platform("") == ""


def test_normalize_handle():
    assert apify.normalize_handle("@brand") == "brand"
    assert apify.normalize_handle("  brand ") == "brand"
    assert apify.normalize_handle("https://instagram.com/brand/") == "brand"
    assert apify.normalize_handle("www.facebook.com/BrandPage") == "BrandPage"
    assert apify.normalize_handle("") == ""


# ── input builders ───────────────────────────────────────────────────────────

def test_build_actor_input_per_platform_shapes():
    ig = apify.build_actor_input("instagram", "@brand", 30)
    assert ig["directUrls"] == ["https://www.instagram.com/brand/"]
    assert ig["resultsType"] == "posts" and ig["resultsLimit"] == 30

    fb = apify.build_actor_input("facebook", "BrandPage", 10)
    assert fb["startUrls"] == [{"url": "https://www.facebook.com/BrandPage"}]
    assert fb["resultsLimit"] == 10

    x = apify.build_actor_input("twitter", "@brand", 25)
    assert x["twitterHandles"] == ["brand"] and x["maxItems"] == 25

    yt = apify.build_actor_input("youtube", "brand", 15)
    assert yt["startUrls"] == [{"url": "https://www.youtube.com/@brand/videos"}]
    assert yt["maxResults"] == 15

    pin = apify.build_actor_input("pinterest", "brand", 20)
    assert pin["startUrls"] == [{"url": "https://www.pinterest.com/brand/"}]

    # max_items floored at 1
    assert apify.build_actor_input("instagram", "b", 0)["resultsLimit"] == 1


# ── number / timestamp coercion ──────────────────────────────────────────────

def test_to_int_variants():
    assert apify._to_int(None) == 0
    assert apify._to_int(1234) == 1234
    assert apify._to_int("1,234") == 1234
    assert apify._to_int("1.2K") == 1200
    assert apify._to_int("3M") == 3_000_000
    assert apify._to_int(True) == 0          # bools are not counts
    assert apify._to_int("garbage") == 0
    assert apify._to_int("") == 0


def test_parse_timestamp_formats():
    assert apify.parse_timestamp("2026-09-10T07:00:00Z").startswith("2026-09-10T07:00:00")
    assert apify.parse_timestamp("2026-09-10 07:00:00").startswith("2026-09-10T07:00:00")
    # epoch seconds
    assert apify.parse_timestamp(1757487600) is not None
    assert apify.parse_timestamp("1757487600") is not None
    # Twitter ctime
    assert apify.parse_timestamp("Wed Sep 10 07:00:00 +0000 2025") is not None
    assert apify.parse_timestamp("not a date") is None
    assert apify.parse_timestamp(None) is None
    assert apify.parse_timestamp("") is None


# ── per-platform parsers ──────────────────────────────────────────────────────

def test_parse_instagram_fields_and_media_type():
    raw = {
        "url": "https://instagram.com/p/1", "caption": "Big news!",
        "likesCount": 100, "commentsCount": 5, "videoViewCount": 900,
        "timestamp": "2026-09-01T00:00:00Z", "type": "Video", "productType": "clips",
    }
    p = apify.parse_instagram(raw)
    assert p["url"] == "https://instagram.com/p/1"
    assert p["caption"] == "Big news!"
    assert p["likes"] == 100 and p["comments"] == 5 and p["views"] == 900
    assert p["media_type"] == "video"
    # carousel via sidecar
    assert apify.parse_instagram({"url": "u", "type": "Sidecar"})["media_type"] == "carousel"
    assert apify.parse_instagram({"url": "u", "displayUrl": "x"})["media_type"] == "image"


def test_parse_facebook_nested_reaction_counts():
    raw = {
        "postUrl": "https://fb.com/1", "text": "Hello",
        "reactions": {"count": 42}, "commentsCount": 3, "shares": 7,
        "time": "2026-08-01", "video": {"url": "v"},
    }
    p = apify.parse_facebook(raw)
    assert p["url"] == "https://fb.com/1"
    assert p["likes"] == 42 and p["comments"] == 3 and p["shares"] == 7
    assert p["media_type"] == "video"


def test_parse_twitter_fields():
    raw = {
        "twitterUrl": "https://x.com/s/1", "fullText": "a tweet",
        "likeCount": 50, "replyCount": 2, "retweetCount": 9, "viewCount": 1000,
        "createdAt": "Wed Sep 10 07:00:00 +0000 2025",
        "extendedEntities": {"media": [{"type": "photo"}]},
    }
    p = apify.parse_twitter(raw)
    assert p["url"] == "https://x.com/s/1" and p["caption"] == "a tweet"
    assert p["likes"] == 50 and p["comments"] == 2 and p["shares"] == 9 and p["views"] == 1000
    assert p["media_type"] == "image"
    assert p["published_at"] is not None


def test_parse_youtube_title_is_caption_and_video_type():
    raw = {"url": "https://youtu.be/1", "title": "How we fixed it",
           "description": "long desc " * 100, "viewCount": 5000, "likes": 40,
           "commentsCount": 8, "date": "2026-07-01"}
    p = apify.parse_youtube(raw)
    assert p["caption"].startswith("How we fixed it")
    assert p["views"] == 5000 and p["media_type"] == "video"
    # description is truncated into the caption (title + <=400 chars)
    assert len(p["caption"]) <= len("How we fixed it") + 1 + 400


def test_parse_pinterest_saves_map_to_likes():
    raw = {"pinUrl": "https://pin.it/1", "title": "Pin", "repinCount": 30, "commentCount": 1}
    p = apify.parse_pinterest(raw)
    assert p["url"] == "https://pin.it/1" and p["likes"] == 30 and p["media_type"] == "image"


def test_parse_posts_dispatch_and_drops_urlless():
    items = [
        {"url": "https://instagram.com/p/1", "caption": "a", "type": "Image"},
        {"caption": "no url — dropped"},          # dropped (no url)
        "not a dict",                              # dropped
        {"url": "https://instagram.com/p/2", "caption": "b", "type": "Video"},
    ]
    out = apify.parse_posts("instagram", items)
    assert [p["url"] for p in out] == ["https://instagram.com/p/1", "https://instagram.com/p/2"]
    # unknown platform → no parser → empty
    assert apify.parse_posts("linkedin", items) == []
    assert apify.parse_posts("instagram", []) == []
