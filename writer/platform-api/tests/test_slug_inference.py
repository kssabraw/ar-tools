"""Unit tests for services/slug_inference — existing-site convention detection."""

from services.slug_inference import (
    build_reconcile_index,
    collection_relative_key,
    infer_content_paths_from_repo_tree,
    infer_extension,
    infer_nesting_from_tree,
    infer_separator,
    infer_slug_patterns,
    infer_trailing_slash,
    infer_url_role_prefixes,
    parse_frontmatter_slug,
)


# ── URL role prefixes (the SOP follow-the-site examples) ─────────────────────
def test_role_prefixes_follow_the_site():
    urls = [
        "https://acme.com/news/how-to-fix-a-leak/",
        "https://acme.com/news/winter-tips/",
        "https://acme.com/service-areas/inner-west/",
        "https://acme.com/service-areas/north-shore/",
        "https://acme.com/plumbing/",
        "https://acme.com/about-us/",
    ]
    prefixes = infer_url_role_prefixes(urls)
    assert prefixes["blog_post"] == "news"  # not the house default "blog"
    assert prefixes["location_page"] == "service-areas"


def test_role_prefixes_omits_unseen_roles():
    urls = ["https://acme.com/blog/x/", "https://acme.com/about-us/"]
    prefixes = infer_url_role_prefixes(urls)
    assert prefixes == {"blog_post": "blog"}


def test_role_prefixes_most_frequent_wins():
    # both "news" and "blog" appear; the more frequent one is chosen
    urls = [
        "https://a.com/blog/a/",
        "https://a.com/news/b/",
        "https://a.com/news/c/",
        "https://a.com/news/d/",
    ]
    assert infer_url_role_prefixes(urls)["blog_post"] == "news"


# ── separator / trailing slash / extension ───────────────────────────────────
def test_infer_separator():
    hyphen = [["blog"], ["how-to-fix-a-leak"]]
    assert infer_separator(hyphen) == "-"
    underscore = [["blog"], ["how_to_fix_a_leak"], ["winter_tips"]]
    assert infer_separator(underscore) == "_"
    assert infer_separator([["blog"], ["single"]]) is None


def test_infer_trailing_slash():
    assert infer_trailing_slash(["https://a.com/blog/x/", "https://a.com/y/"]) is True
    assert infer_trailing_slash(["https://a.com/blog/x", "https://a.com/y"]) is False
    # .html files are excluded from the vote (never carry a slash)
    assert infer_trailing_slash(["https://a.com/x.html", "https://a.com/y.html"]) is None


def test_infer_extension():
    assert infer_extension(["https://a.com/x.html", "https://a.com/y.html", "https://a.com/z/"]) == ".html"
    assert infer_extension(["https://a.com/x/", "https://a.com/y/"]) == ""


def test_infer_slug_patterns_descriptor():
    urls = [
        "https://acme.com/insights/seo-guide/",
        "https://acme.com/insights/local-seo/",
        "https://acme.com/locations/austin/",
    ]
    d = infer_slug_patterns(urls)
    assert d["separator"] == "-"
    assert d["trailing_slash"] is True
    assert d["extension"] == ""
    assert d["prefixes"]["blog_post"] == "insights"
    assert d["prefixes"]["location_page"] == "locations"


# ── repo content tree → content paths (populates github_content_paths) ────────
def test_content_paths_from_repo_tree():
    paths = [
        "src/content/blog/how-to.md",
        "src/content/blog/2024/nested-post.md",  # nested date dir still maps to blog root
        "src/content/services/plumbing.md",
        "src/content/services/drain-cleaning.md",
        "src/content/locations/los-angeles.md",
        "src/content/shop/bpc-157.mdx",
        "astro.config.mjs",  # ignored (not a content file)
        "src/pages/index.astro",  # ignored
        "README.md",  # ignored (no role segment)
    ]
    result = infer_content_paths_from_repo_tree(paths)
    assert result == {
        "blog_post": "src/content/blog",
        "service_page": "src/content/services",
        "location_page": "src/content/locations",
        "product": "src/content/shop",
    }


def test_content_paths_alt_collection_names():
    paths = [
        "src/content/news/post-one.md",
        "src/content/news/post-two.md",
        "src/content/service-areas/inner-west.md",
    ]
    result = infer_content_paths_from_repo_tree(paths)
    assert result["blog_post"] == "src/content/news"
    assert result["location_page"] == "src/content/service-areas"


def test_content_paths_empty_when_no_collections():
    assert infer_content_paths_from_repo_tree(["README.md", "package.json"]) == {}


def test_content_paths_ignore_docs_when_content_root_present():
    # a doc-heavy repo: /docs/blog/ must NOT out-vote the real src/content/blog
    paths = [
        "src/content/blog/real-post.md",
        "docs/blog/notes-a.md",
        "docs/blog/notes-b.md",
        "docs/blog/notes-c.md",  # more frequent, but under docs/ (no content root)
    ]
    assert infer_content_paths_from_repo_tree(paths) == {"blog_post": "src/content/blog"}


def test_content_paths_no_root_lifts_restriction():
    # no content/pages/data anywhere → best-effort, the docs collection counts
    paths = ["docs/blog/a.md", "docs/blog/b.md"]
    assert infer_content_paths_from_repo_tree(paths) == {"blog_post": "docs/blog"}


# ── collection_relative_key (2b path normalization) ──────────────────────────
def test_collection_relative_key():
    assert collection_relative_key("src/content/blog/2024/x.md", "src/content/blog") == "x"
    assert collection_relative_key("src/content/blog/06/x.md", "src/content/blog") == "x"  # month
    assert collection_relative_key("src/content/locations/la/plumbing.md", "src/content/locations") == "la/plumbing"
    # non-date-stripped keeps the date dir (used to preserve the live URL)
    assert (
        collection_relative_key("src/content/blog/2024/x.md", "src/content/blog", strip_dates=False)
        == "2024/x"
    )
    assert collection_relative_key("elsewhere/x.md", "src/content/blog") is None


# ── infer_nesting_from_tree (2a) ─────────────────────────────────────────────
def test_infer_nesting_from_tree():
    tree = [
        "src/content/blog/a.md",
        "src/content/blog/2024/b.md",  # date-nested, still depth 1
        "src/content/locations/la.md",
        "src/content/locations/sd.md",  # flat locations → depth 1 dominant
        "src/content/locations/la/plumbing.md",  # one nested, minority
    ]
    cps = {"blog_post": "src/content/blog", "location_page": "src/content/locations"}
    nesting = infer_nesting_from_tree(tree, cps)
    assert nesting["blog_post"] == 1
    assert nesting["location_page"] == 1  # modal (2 flat vs 1 nested)


# ── build_reconcile_index (2b) ───────────────────────────────────────────────
def test_reconcile_index_date_nested_and_flat():
    tree = ["src/content/blog/2024/06/how-to.md", "src/content/locations/la/plumbing.md"]
    cps = {"blog_post": "src/content/blog", "location_page": "src/content/locations"}
    idx = build_reconcile_index(tree, cps)
    # date-nested blog: match key "how-to" → its real path, slug preserves the date path
    assert idx["src/content/blog"]["how-to"] == {"path": "src/content/blog/2024/06/how-to.md", "slug": "2024/06/how-to"}
    # nested location matches on the full relative key
    assert idx["src/content/locations"]["la/plumbing"]["path"] == "src/content/locations/la/plumbing.md"


def test_reconcile_index_frontmatter_slug_override():
    # a page whose path doesn't reflect its slug (the pathological case)
    tree = ["src/content/blog/p123.md"]
    cps = {"blog_post": "src/content/blog"}
    idx = build_reconcile_index(tree, cps, frontmatter_slugs={"src/content/blog/p123.md": "how-to"})
    bucket = idx["src/content/blog"]
    # matchable by BOTH the path key and the frontmatter slug; slug preserved
    assert bucket["p123"]["path"] == "src/content/blog/p123.md"
    assert bucket["how-to"] == {"path": "src/content/blog/p123.md", "slug": "how-to"}


def test_reconcile_index_shortest_path_wins():
    tree = ["src/content/blog/dup/how-to.md", "src/content/blog/how-to.md"]
    cps = {"blog_post": "src/content/blog"}
    idx = build_reconcile_index(tree, cps)
    assert idx["src/content/blog"]["how-to"]["path"] == "src/content/blog/how-to.md"


# ── parse_frontmatter_slug ───────────────────────────────────────────────────
def test_parse_frontmatter_slug():
    assert parse_frontmatter_slug('---\ntitle: "X"\nslug: "los-angeles/plumbing"\n---\nbody') == "los-angeles/plumbing"
    assert parse_frontmatter_slug("---\nslug: how-to\n---\n") == "how-to"
    assert parse_frontmatter_slug("---\ntitle: X\n---\nbody") is None  # no slug
    assert parse_frontmatter_slug("no frontmatter here") is None
    assert parse_frontmatter_slug("") is None
