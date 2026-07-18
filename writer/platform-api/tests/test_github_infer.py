"""Unit tests for the pure pieces of services/github_infer (I/O stays mocked)."""

from services.github_infer import assemble_inferred, parse_tree_response


# ── Git Trees response parsing ───────────────────────────────────────────────
def test_parse_tree_response_keeps_blobs_only():
    body = {
        "tree": [
            {"path": "src/content/blog/x.md", "type": "blob"},
            {"path": "src/content/blog", "type": "tree"},  # dir, dropped
            {"path": "src/content/services/y.md", "type": "blob"},
            {"type": "blob"},  # no path, dropped
        ]
    }
    assert parse_tree_response(body) == ["src/content/blog/x.md", "src/content/services/y.md"]


def test_parse_tree_response_bad_shapes():
    assert parse_tree_response({}) == []
    assert parse_tree_response({"tree": "oops"}) == []
    assert parse_tree_response("nope") == []


# ── descriptor assembly ──────────────────────────────────────────────────────
def test_assemble_repo_tree_plus_sitemap():
    tree = ["src/content/news/post.md", "src/content/services/plumbing.md"]
    urls = ["https://a.com/news/post/", "https://a.com/plumbing/"]
    d = assemble_inferred(tree_paths=tree, urls=urls, now_iso="2026-07-18T00:00:00Z")
    assert d["content_paths"] == {"blog_post": "src/content/news", "service_page": "src/content/services"}
    assert d["url"]["prefixes"]["blog_post"] == "news"
    assert d["source"] == "repo_tree+sitemap"
    assert d["inferred_at"] == "2026-07-18T00:00:00Z"


def test_assemble_repo_tree_only():
    d = assemble_inferred(tree_paths=["src/content/blog/x.md"], urls=[], now_iso="t")
    assert d["content_paths"] == {"blog_post": "src/content/blog"}
    assert d["url"] == {}
    assert d["source"] == "repo_tree"


def test_assemble_sitemap_only():
    d = assemble_inferred(tree_paths=[], urls=["https://a.com/insights/x/"], now_iso="t")
    assert d["content_paths"] == {}
    assert d["url"]["prefixes"]["blog_post"] == "insights"
    assert d["source"] == "sitemap"


def test_assemble_none():
    d = assemble_inferred(tree_paths=[], urls=[], now_iso="t")
    assert d == {"content_paths": {}, "url": {}, "inferred_at": "t", "source": "none"}
