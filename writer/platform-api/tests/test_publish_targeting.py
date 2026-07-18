"""Unit tests for services/publish_targeting — commit-target resolution with
full deep nesting + 'site always wins' precedence."""

from services.publish_targeting import (
    client_known_places,
    extract_place,
    resolve_publish_target,
)


# ── known places + geo split ─────────────────────────────────────────────────
def test_client_known_places_merges_and_dedupes():
    client = {
        "business_location": "Los Angeles",
        "target_cities": ["Pasadena", "los angeles"],  # dup, case-insensitive
        "gbp": {"service_area_places": ["Glendale", ""]},
    }
    assert client_known_places(client) == ["Los Angeles", "Pasadena", "Glendale"]


def test_extract_place_splits_service_and_location():
    places = ["Los Angeles", "Inner West"]
    assert extract_place("plumbing los angeles", places) == ("Los Angeles", "plumbing")
    assert extract_place("Los Angeles", places) == ("Los Angeles", "")
    assert extract_place("emergency plumber", places) == (None, "emergency plumber")
    # longest place wins (avoids matching a shorter substring first)
    assert extract_place("roofing west", ["West", "Inner West"]) == ("West", "roofing")


# ── deep nesting per content type ────────────────────────────────────────────
def _client(**kw):
    base = {"business_location": "Los Angeles", "target_cities": [], "gbp": {}}
    base.update(kw)
    return base


def test_blog_target_default():
    t = resolve_publish_target("blog_post", "How To Do SEO", client=_client())
    assert t["page_type"] == "blog_post"
    assert t["nested_slug"] == "how-to-do-seo"
    assert t["content_path"] == "src/content/blog"  # server default
    assert t["file_path"] == "src/content/blog/how-to-do-seo.md"
    assert t["public_url"] == "/blog/how-to-do-seo/"


def test_service_target():
    t = resolve_publish_target("service_page", "Landscaping", client=_client())
    assert t["page_type"] == "top_level_service"
    assert t["nested_slug"] == "landscaping"
    assert t["public_url"] == "/landscaping/"  # root-level, no prefix


def test_location_page_splits_into_local_landing():
    t = resolve_publish_target("location_page", "plumbing los angeles", client=_client())
    assert t["page_type"] == "local_landing"
    assert t["nested_slug"] == "los-angeles/plumbing"  # deep nested
    assert t["public_url"] == "/los-angeles/plumbing/"
    assert t["file_path"] == "src/content/blog/los-angeles/plumbing.md"


def test_location_page_without_service_is_top_level():
    t = resolve_publish_target("location_page", "Los Angeles", client=_client())
    assert t["page_type"] == "top_level_location"
    assert t["nested_slug"] == "los-angeles"
    assert t["public_url"] == "/los-angeles/"


# ── 'site always wins': inferred content path + url conventions ───────────────
def test_inferred_content_path_and_prefix_win():
    client = _client(
        github_content_paths={"blog_post": "src/content/manual"},  # human override
        github_inferred_patterns={
            "content_paths": {"blog_post": "src/content/news"},  # inferred site
            "url": {"separator": "-", "trailing_slash": True, "prefixes": {"blog_post": "news"}},
        },
    )
    t = resolve_publish_target("blog_post", "Winter Tips", client=client)
    # inferred content path beats the human override (SOP: site always wins)
    assert t["content_path"] == "src/content/news"
    assert t["file_path"] == "src/content/news/winter-tips.md"
    assert t["public_url"] == "/news/winter-tips/"  # inferred blog prefix


def test_inferred_separator_underscore():
    client = _client(github_inferred_patterns={"url": {"separator": "_"}})
    t = resolve_publish_target("blog_post", "How To Do SEO", client=client)
    assert t["nested_slug"] == "how_to_do_seo"


# ── deterministic collision on the leaf ──────────────────────────────────────
def test_collision_suffix_on_reserved_leaf():
    # a service literally named "Services" collides with the reserved hub
    t = resolve_publish_target("service_page", "Services", client=_client())
    assert t["nested_slug"].startswith("services-")
    assert len(t["nested_slug"]) == len("services-") + 5
    # deterministic — same target every run
    t2 = resolve_publish_target("service_page", "Services", client=_client())
    assert t2["nested_slug"] == t["nested_slug"]
