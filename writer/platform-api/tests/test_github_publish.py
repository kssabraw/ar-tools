"""Unit tests for resolve_github_path — the per-content-type repo path resolver
(enhancement #1). Mirrors test_google_docs.py's resolve_drive_folder coverage."""

from config import settings
from services.github_publish import build_markdown_file, resolve_github_path


def test_type_specific_path_wins():
    client = {
        "github_content_paths": {
            "blog_post": "src/content/blog",
            "service_page": "src/content/services",
        },
        "github_content_path": "src/content/default",
    }
    assert resolve_github_path(client, "blog_post") == "src/content/blog"
    assert resolve_github_path(client, "service_page") == "src/content/services"


def test_falls_back_to_single_default_when_type_unset():
    client = {
        "github_content_paths": {"blog_post": "src/content/blog"},
        "github_content_path": "src/content/default",
    }
    assert resolve_github_path(client, "location_page") == "src/content/default"


def test_falls_back_to_single_default_when_no_map():
    client = {"github_content_path": "src/content/default"}
    assert resolve_github_path(client, "blog_post") == "src/content/default"


def test_bad_entries_fall_through_to_single_default():
    default = {"github_content_path": "src/content/default"}
    assert resolve_github_path({**default, "github_content_paths": {"blog_post": "   "}}, "blog_post") == "src/content/default"
    assert resolve_github_path({**default, "github_content_paths": {"blog_post": 123}}, "blog_post") == "src/content/default"
    # non-dict map ignored, falls to the single default
    assert resolve_github_path({"github_content_paths": "oops", "github_content_path": "d"}, "blog_post") == "d"


def test_values_are_stripped_of_whitespace_and_surrounding_slashes():
    client = {"github_content_paths": {"blog_post": " /src/content/blog/ "}}
    assert resolve_github_path(client, "blog_post") == "src/content/blog"
    assert resolve_github_path({"github_content_path": "/foo/bar/"}, "blog_post") == "foo/bar"


def test_none_content_type_uses_single_default():
    client = {
        "github_content_paths": {"blog_post": "src/content/blog"},
        "github_content_path": "src/content/default",
    }
    assert resolve_github_path(client, None) == "src/content/default"


def test_server_default_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(settings, "github_default_content_path", "src/content/blog")
    assert resolve_github_path({}, "blog_post") == "src/content/blog"
    assert resolve_github_path({"github_content_paths": {}}, "blog_post") == "src/content/blog"
    # whitespace-only single default → falls through to the server default
    assert resolve_github_path({"github_content_path": "   "}, "blog_post") == "src/content/blog"


def test_server_default_is_slash_stripped(monkeypatch):
    monkeypatch.setattr(settings, "github_default_content_path", "/src/content/blog/")
    assert resolve_github_path({}, "blog_post") == "src/content/blog"


def test_empty_server_default_returns_repo_root(monkeypatch):
    monkeypatch.setattr(settings, "github_default_content_path", "")
    assert resolve_github_path({}, "blog_post") == ""


# ── 'site always wins': inferred content path beats override + default ────────
def test_inferred_content_path_beats_override():
    client = {
        "github_inferred_patterns": {"content_paths": {"blog_post": "src/content/news"}},
        "github_content_paths": {"blog_post": "src/content/manual"},
        "github_content_path": "src/content/default",
    }
    assert resolve_github_path(client, "blog_post") == "src/content/news"


def test_inferred_falls_through_when_type_absent():
    client = {
        "github_inferred_patterns": {"content_paths": {"blog_post": "src/content/news"}},
        "github_content_paths": {"service_page": "src/content/manual"},
    }
    # inferred has no service_page -> falls to the override map
    assert resolve_github_path(client, "service_page") == "src/content/manual"


def test_inferred_bad_shape_ignored():
    # non-dict inferred / content_paths must not break resolution
    assert resolve_github_path({"github_inferred_patterns": "oops", "github_content_path": "d"}, "blog_post") == "d"
    assert (
        resolve_github_path({"github_inferred_patterns": {"content_paths": "x"}, "github_content_path": "d"}, "blog_post")
        == "d"
    )


# ── build_markdown_file slug frontmatter ─────────────────────────────────────
def test_build_markdown_file_emits_slug():
    md = build_markdown_file("My Title", "body text", slug="los-angeles/plumbing")
    assert 'slug: "los-angeles/plumbing"' in md
    assert 'title: "My Title"' in md


def test_build_markdown_file_omits_slug_when_absent():
    md = build_markdown_file("My Title", "body text")
    assert "slug:" not in md
