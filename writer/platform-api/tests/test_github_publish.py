"""Unit tests for resolve_github_path — the per-content-type repo path resolver
(enhancement #1). Mirrors test_google_docs.py's resolve_drive_folder coverage."""

from datetime import date

from config import settings
from services.github_publish import build_markdown_file, derive_description, resolve_github_path


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
    # isolate the single server default by clearing the per-type map
    monkeypatch.setattr(settings, "github_default_content_paths", {})
    monkeypatch.setattr(settings, "github_default_content_path", "src/content/blog")
    assert resolve_github_path({}, "blog_post") == "src/content/blog"
    assert resolve_github_path({"github_content_paths": {}}, "blog_post") == "src/content/blog"
    # whitespace-only single default → falls through to the server default
    assert resolve_github_path({"github_content_path": "   "}, "blog_post") == "src/content/blog"


def test_server_default_is_slash_stripped(monkeypatch):
    monkeypatch.setattr(settings, "github_default_content_paths", {})
    monkeypatch.setattr(settings, "github_default_content_path", "/src/content/blog/")
    assert resolve_github_path({}, "blog_post") == "src/content/blog"


def test_empty_server_default_returns_repo_root(monkeypatch):
    monkeypatch.setattr(settings, "github_default_content_paths", {})
    monkeypatch.setattr(settings, "github_default_content_path", "")
    assert resolve_github_path({}, "blog_post") == ""


def test_per_type_server_default_beats_single_default():
    # a service page uses the per-type server default, not the blog single default
    assert resolve_github_path({}, "service_page") == "src/content/services"
    assert resolve_github_path({}, "location_page") == "src/content/locations"
    assert resolve_github_path({}, "product") == "src/content/shop"
    # an unmapped type falls through to the single server default
    assert resolve_github_path({}, "use_case") == "src/content/blog"


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


# ── build_markdown_file pubDate frontmatter ──────────────────────────────────
def test_pub_date_always_emitted_defaults_to_today():
    md = build_markdown_file("T", "body")
    assert f"pubDate: {date.today().isoformat()}" in md


def test_pub_date_date_renders_unquoted_iso():
    md = build_markdown_file("T", "body", pub_date=date(2026, 3, 18))
    assert "pubDate: 2026-03-18" in md
    assert 'pubDate: "' not in md


def test_pub_date_string_kept_verbatim():
    # the re-publish path preserves the existing file's scalar, quoted or not
    md = build_markdown_file("T", "body", pub_date='"2025-11-02"')
    assert 'pubDate: "2025-11-02"' in md


def test_hero_image_emitted_when_present():
    md = build_markdown_file("T", "body", hero_image="https://cdn.example.com/hero.png")
    assert 'heroImage: "https://cdn.example.com/hero.png"' in md


def test_hero_image_omitted_when_absent():
    assert "heroImage" not in build_markdown_file("T", "body")
    assert "heroImage" not in build_markdown_file("T", "body", hero_image="")


def test_description_emitted_before_pub_date_when_present():
    md = build_markdown_file("T", "body", description="A summary.")
    assert 'description: "A summary."' in md
    frontmatter = md.split("---")[1]
    assert frontmatter.index("description:") < frontmatter.index("pubDate:")


# ── derive_description ───────────────────────────────────────────────────────
def test_derive_description_skips_headings_and_lists():
    body = "# Title\n\n- a list item\n\n1. numbered\n\nFirst real paragraph here.\n\nSecond."
    assert derive_description(body) == "First real paragraph here."


def test_derive_description_strips_inline_markdown():
    body = "This has **bold**, *italic*, `code` and a [link](https://x.com) inline."
    assert derive_description(body) == "This has bold, italic, code and a link inline."


def test_derive_description_handles_html_body():
    # Local SEO pages publish HTML: heading text must not become the description.
    body = "<h1>Plumber Sydney</h1>\n<h2>Why us</h2>\n<p>We fix burst pipes fast, day or night.</p>"
    assert derive_description(body) == "We fix burst pipes fast, day or night."


def test_derive_description_clips_long_paragraphs_on_word_boundary():
    body = "word " * 80
    out = derive_description(body)
    assert out is not None and out.endswith("…") and len(out) <= 161


def test_derive_description_empty_or_structural_only_returns_none():
    assert derive_description("") is None
    assert derive_description("## Heading\n\n- only\n- lists") is None


def test_build_markdown_file_omits_slug_when_absent():
    md = build_markdown_file("My Title", "body text")
    assert "slug:" not in md


# ── JSON-LD schema frontmatter (#1) ──────────────────────────────────────────
def test_build_markdown_file_emits_schema_json_roundtrips():
    import json

    jsonld = '{"@context":"https://schema.org","@type":"Service","name":"Plumbing: 24/7"}'
    md = build_markdown_file("T", "body", schema=jsonld)
    # the frontmatter line is a JSON-encoded string the layout can JSON.parse
    line = next(ln for ln in md.splitlines() if ln.startswith("schema:"))
    value = line[len("schema:"):].strip()
    assert json.loads(value) == jsonld  # outer decode → the JSON-LD string
    assert json.loads(json.loads(value))["@type"] == "Service"  # inner is valid JSON-LD


def test_build_markdown_file_omits_schema_when_absent():
    assert "schema:" not in build_markdown_file("T", "body")
    assert "schema:" not in build_markdown_file("T", "body", schema="")
    assert "schema:" not in build_markdown_file("T", "body", schema="   ")
