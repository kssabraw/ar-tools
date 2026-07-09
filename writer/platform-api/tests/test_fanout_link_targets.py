"""Client-inferred URL style + user extra link targets (fanout internal linking).

infer_url_style derives the site's real blog permalink pattern from the client
card's blog-post reference URL, so injected links match where WordPress will
actually publish (e.g. /blog/{slug}/) instead of the assumed per-silo
directories. build_extra_targets/merge_targets fold the user's up-to-3 money
pages into each article's links under the ≤5-outbound owner rule.
"""

import pytest

pytest.importorskip("pydantic")

from fanout.writer.link_injector import LinkTarget  # noqa: E402
from fanout.writer.link_targets import (  # noqa: E402
    MAX_OUTBOUND_LINKS,
    build_extra_targets,
    build_targets,
    infer_url_style,
    merge_targets,
)


# ---- infer_url_style --------------------------------------------------------

def test_infer_blog_prefix_with_trailing_slash():
    style = infer_url_style(
        "https://novalifepeptides.com/blog/can-bpc-157-be-absorbed-through-the-skin/"
    )
    assert style is not None
    assert style.prefix == "/blog/"
    assert style.trailing_slash is True
    assert (
        style.post_url("https://novalifepeptides.com", "retatrutide-dosage-guide")
        == "https://novalifepeptides.com/blog/retatrutide-dosage-guide/"
    )


def test_infer_root_level_posts_no_slash():
    style = infer_url_style("https://client.com/how-to-fix-a-roof")
    assert style is not None
    assert style.prefix == "/"
    assert style.trailing_slash is False
    assert style.post_url("https://client.com/", "new-post") == "https://client.com/new-post"


def test_infer_nested_prefix():
    style = infer_url_style("https://client.com/resources/guides/some-post/")
    assert style is not None
    assert style.prefix == "/resources/guides/"


def test_infer_rejects_date_based_permalinks():
    assert infer_url_style("https://client.com/2026/07/some-post/") is None


def test_infer_rejects_unusable_urls():
    assert infer_url_style("") is None
    assert infer_url_style("not a url") is None
    assert infer_url_style("ftp://client.com/blog/post/") is None
    assert infer_url_style("https://client.com/") is None  # bare root — no slug to strip


# ---- build_extra_targets ----------------------------------------------------

def test_extra_targets_derive_anchor_from_slug():
    [t] = build_extra_targets(["https://novalifepeptides.com/retatrutide-for-sale/"])
    assert t.url == "https://novalifepeptides.com/retatrutide-for-sale/"
    assert t.anchors == ["retatrutide for sale"]
    assert t.title == "Retatrutide For Sale"


def test_extra_targets_drop_invalid_dupes_and_cap_at_three():
    targets = build_extra_targets([
        "https://a.com/one/",
        "not a url",
        "https://a.com/one/",     # duplicate
        "",
        "https://a.com/two",
        "https://a.com/three",
        "https://a.com/four",     # over the cap
    ])
    assert [t.url for t in targets] == [
        "https://a.com/one/", "https://a.com/two", "https://a.com/three",
    ]


# ---- merge_targets ----------------------------------------------------------

def _t(url: str) -> LinkTarget:
    return LinkTarget(url=url, anchors=["x"], title=url)


def test_merge_priority_uplink_then_extras_then_laterals():
    arch = [_t("https://s.com/blog/pillar/"), _t("https://s.com/blog/lat1/"),
            _t("https://s.com/blog/lat2/"), _t("https://s.com/blog/lat3/"),
            _t("https://s.com/blog/lat4/")]
    extras = [_t("https://s.com/money-1/"), _t("https://s.com/money-2/")]
    merged = merge_targets(arch, extras)
    assert len(merged) == MAX_OUTBOUND_LINKS
    # up-link survives, extras outrank laterals, tail laterals trimmed
    assert [t.url for t in merged] == [
        "https://s.com/blog/pillar/", "https://s.com/money-1/", "https://s.com/money-2/",
        "https://s.com/blog/lat1/", "https://s.com/blog/lat2/",
    ]


def test_merge_dedupes_by_url():
    merged = merge_targets([_t("https://s.com/a/")], [_t("https://s.com/a/")])
    assert len(merged) == 1


# ---- build_targets with url_style --------------------------------------------

_ARCH = {
    "pillars": [{
        "topic_id": "t1", "silo_name": "Retatrutide",
        "target_keyword": "retatrutide", "title": "Retatrutide Guide",
    }],
    "supporting_articles": [
        {"article_id": "c1", "parent_pillar_topic_id": "t1",
         "lateral_article_links": ["c2"], "name": "Dosage Guide"},
        {"article_id": "c2", "parent_pillar_topic_id": "t1",
         "lateral_article_links": [], "name": "Side Effects"},
    ],
}
_CLUSTERS = {
    "c1": {"id": "c1", "topic_id": "t1", "slug": "retatrutide-dosage-guide",
           "primary_keyword_id": "k1"},
    "c2": {"id": "c2", "topic_id": "t1", "slug": "retatrutide-side-effects",
           "primary_keyword_id": "k2"},
}
_TOPICS = {"t1": {"id": "t1", "name": "Retatrutide"}}
_KEYWORDS = {"k1": "retatrutide dosage", "k2": "retatrutide side effects"}


def test_build_targets_default_scheme_unchanged():
    targets, _ = build_targets(
        "c1", architecture=_ARCH, clusters_by_id=_CLUSTERS, topics_by_id=_TOPICS,
        keywords_by_id=_KEYWORDS, base_url="https://site.com")
    assert [t.url for t in targets] == [
        "https://site.com/retatrutide/",
        "https://site.com/retatrutide/retatrutide-side-effects",
    ]


def test_build_targets_client_inferred_flat_scheme():
    style = infer_url_style("https://novalifepeptides.com/blog/example-post/")
    targets, _ = build_targets(
        "c1", architecture=_ARCH, clusters_by_id=_CLUSTERS, topics_by_id=_TOPICS,
        keywords_by_id=_KEYWORDS, base_url="https://novalifepeptides.com",
        url_style=style)
    assert [t.url for t in targets] == [
        "https://novalifepeptides.com/blog/retatrutide/",
        "https://novalifepeptides.com/blog/retatrutide-side-effects/",
    ]
